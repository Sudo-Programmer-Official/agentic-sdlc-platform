from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artifact, Document, Project, ProjectPreviewProfile, ProjectRepository, Run, RunEvent, RunSummary, Task, WorkItem, Workspace
from app.schemas.mission_control import (
    MissionControlArtifactRef,
    MissionControlChangeImpact,
    MissionControlImportedReference,
    MissionControlNamedCount,
    MissionControlOverviewResponse,
    MissionControlPreviewAndPrs,
    MissionControlRunCard,
    MissionControlStalledRun,
    MissionControlStrategyInsight,
    MissionControlEtaProfile,
    MissionControlSystemInsights,
    MissionControlViolationInsights,
    MissionControlViolationSample,
    MissionControlWorkIntakeItem,
)
from app.services.artifact_diff import parse_unified_diff, resolve_artifact_content
from app.services.preview_service import preview_profile_available, resolve_preview_profile
from app.services.preview_domain import build_workspace_project_preview_host
from app.services.run_memory import find_similar_runs
from app.services.run_summary_builder import ensure_project_run_summaries
from app.services.architecture_profile_service import summarize_architecture_profile
from app.services.execution_contract_telemetry import build_execution_contract_telemetry
from app.services.project_contract_service import summarize_project_contract

_HTTP_ROUTE_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_./:-]+)")


def _excerpt(text: str | None, limit: int = 180) -> str | None:
    if not text:
        return None
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit - 1]}…"


def _is_test_file(path: str) -> bool:
    lowered = path.lower()
    parts = PurePosixPath(lowered).parts
    return (
        any(part in {"tests", "test", "__tests__"} for part in parts)
        or lowered.endswith("_test.py")
        or lowered.endswith(".test.js")
        or lowered.endswith(".test.ts")
        or lowered.endswith(".spec.js")
        or lowered.endswith(".spec.ts")
        or "pytest" in lowered
    )


def _module_name(path: str) -> str:
    pure = PurePosixPath(path)
    if pure.stem:
        return pure.stem
    if pure.name:
        return pure.name
    return path


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _extract_api_impact(*texts: str | None) -> list[str]:
    found: list[str] = []
    for text in texts:
        if not text:
            continue
        for method, route in _HTTP_ROUTE_RE.findall(text):
            found.append(f"{method} {route}")
    return _unique(found)


def _risk_score(files: list[str], recovery_count: int, primary_error: str | None = None) -> tuple[float, str]:
    score = 0.12
    score += min(len(files), 8) * 0.06
    score += min(recovery_count, 5) * 0.09
    text = " ".join(files) + " " + (primary_error or "")
    lowered = text.lower()
    if any(token in lowered for token in ("auth", "security", "payment", "secret", "token", "schema", "migration")):
        score += 0.18
    if any(token in lowered for token in ("db", "database", "sql", "worker", "runtime")):
        score += 0.12
    score = max(0.0, min(score, 1.0))
    if score >= 0.75:
        tier = "HIGH"
    elif score >= 0.4:
        tier = "MEDIUM"
    else:
        tier = "LOW"
    return round(score, 3), tier


def _confidence_from_summary(summary: RunSummary) -> float:
    score = 0.35
    if summary.status == "COMPLETED":
        score += 0.28
    elif summary.status in {"RUNNING", "QUEUED"}:
        score += 0.1
    if summary.approval_status == "APPROVED":
        score += 0.12
    if summary.pr_created:
        score += 0.08
    score -= min(summary.recovery_count, 5) * 0.05
    score -= max(0, len(summary.changed_files) - 1) * 0.015
    if summary.primary_error:
        score -= 0.1
    return round(max(0.0, min(score, 0.99)), 3)


def _artifact_ref(artifact: Artifact | None) -> MissionControlArtifactRef | None:
    if artifact is None:
        return None
    return MissionControlArtifactRef(
        id=artifact.id,
        type=artifact.type,
        uri=artifact.uri,
        created_at=artifact.created_at,
    )


async def _load_recent_documents(session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID) -> list[Document]:
    return (
        await session.execute(
            select(Document)
            .where(
                Document.project_id == project_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
            .order_by(Document.created_at.desc(), Document.id.desc())
            .limit(3)
        )
    ).scalars().all()


async def _load_tasks_for_documents(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    document_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[Task]]:
    if not document_ids:
        return {}
    tasks = (
        await session.execute(
            select(Task)
            .where(
                Task.project_id == project_id,
                Task.tenant_id == tenant_id,
                Task.document_id.in_(document_ids),
                Task.deleted_at.is_(None),
            )
            .order_by(Task.created_at.asc(), Task.id.asc())
        )
    ).scalars().all()
    grouped: dict[uuid.UUID, list[Task]] = defaultdict(list)
    for task in tasks:
        if task.document_id:
            grouped[task.document_id].append(task)
    return grouped


async def _build_work_intake(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> list[MissionControlWorkIntakeItem]:
    documents = await _load_recent_documents(session, tenant_id=tenant_id, project_id=project_id)
    tasks_by_doc = await _load_tasks_for_documents(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        document_ids=[doc.id for doc in documents],
    )
    items: list[MissionControlWorkIntakeItem] = []
    for doc in documents:
        doc_tasks = tasks_by_doc.get(doc.id, [])
        matches = await find_similar_runs(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            goal_text=f"{doc.title}\n{_excerpt(doc.body, limit=320)}",
            limit=3,
        )
        predicted_files: list[str] = []
        for match in matches.matches:
            predicted_files.extend(match.files_changed)
        predicted_files = _unique(predicted_files)[:5]
        predicted_modules = _unique([_module_name(path) for path in predicted_files if not _is_test_file(path)])[:4]
        risk_score, risk_tier = _risk_score(predicted_files, 0, doc.title)
        confidence = 0.3 + min(len(matches.matches), 3) * 0.12 + min(len(doc_tasks), 4) * 0.06
        suggested_plan = [task.title for task in doc_tasks[:3]]
        if not suggested_plan:
            if predicted_modules:
                suggested_plan = [f"Inspect {module}" for module in predicted_modules[:2]]
                suggested_plan.append("Generate patch and run targeted tests")
            else:
                suggested_plan = ["Review incoming work", "Generate patch", "Validate with tests"]
        items.append(
            MissionControlWorkIntakeItem(
                id=doc.id,
                kind="document",
                title=doc.title,
                source=doc.source,
                summary=_excerpt(doc.body),
                created_at=doc.created_at,
                predicted_modules=predicted_modules,
                predicted_files=predicted_files,
                risk_tier=risk_tier,
                confidence_score=round(min(confidence + risk_score * 0.15, 0.95), 3),
                suggested_plan=suggested_plan,
                related_task_count=len(doc_tasks),
            )
        )
    return items


async def _load_recent_runs_and_artifacts(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int = 8,
) -> tuple[list[RunSummary], dict[uuid.UUID, Run], dict[uuid.UUID, Artifact | None], dict[uuid.UUID, Artifact | None]]:
    summaries = await ensure_project_run_summaries(session, tenant_id=tenant_id, project_id=project_id, limit=limit)
    run_ids = [summary.run_id for summary in summaries]
    if not run_ids:
        return [], {}, {}, {}
    runs = (
        await session.execute(select(Run).where(Run.id.in_(run_ids), Run.tenant_id == tenant_id))
    ).scalars().all()
    run_by_id = {run.id: run for run in runs}
    summaries.sort(
        key=lambda summary: (
            2
            if str(summary.status or "").upper() == "RUNNING"
            else 1
            if str(summary.status or "").upper() == "QUEUED"
            else 0,
            (
                (
                    (run_by_id.get(summary.run_id).started_at if run_by_id.get(summary.run_id) else None)
                    or summary.run_created_at
                    or summary.created_at
                ).timestamp()
                if (
                    (run_by_id.get(summary.run_id).started_at if run_by_id.get(summary.run_id) else None)
                    or summary.run_created_at
                    or summary.created_at
                )
                else float("-inf")
            ),
        ),
        reverse=True,
    )
    artifacts = (
        await session.execute(
            select(Artifact)
            .where(
                Artifact.run_id.in_(run_ids),
                Artifact.tenant_id == tenant_id,
                Artifact.deleted_at.is_(None),
            )
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    ).scalars().all()
    latest_patch_by_run: dict[uuid.UUID, Artifact | None] = {run_id: None for run_id in run_ids}
    latest_pr_by_run: dict[uuid.UUID, Artifact | None] = {run_id: None for run_id in run_ids}
    for artifact in artifacts:
        if artifact.run_id is None:
            continue
        if artifact.type == "git_diff" and latest_patch_by_run.get(artifact.run_id) is None:
            latest_patch_by_run[artifact.run_id] = artifact
        if artifact.type == "pull_request" and latest_pr_by_run.get(artifact.run_id) is None:
            latest_pr_by_run[artifact.run_id] = artifact
    return summaries, run_by_id, latest_patch_by_run, latest_pr_by_run


def _build_recent_runs(
    summaries: list[RunSummary],
    runs: dict[uuid.UUID, Run],
    patch_artifacts: dict[uuid.UUID, Artifact | None],
) -> list[MissionControlRunCard]:
    cards: list[MissionControlRunCard] = []
    for summary in summaries:
        run = runs.get(summary.run_id)
        cards.append(
            MissionControlRunCard(
                run_id=summary.run_id,
                goal_text=summary.goal_text,
                status=summary.status,
                executor=summary.executor,
                branch_name=summary.branch_name,
                elapsed_seconds=summary.elapsed_seconds,
                recovery_count=summary.recovery_count,
                artifact_count=summary.artifact_count,
                files_changed=[value for value in summary.changed_files if isinstance(value, str)],
                confidence_score=_confidence_from_summary(summary),
                pull_request_url=summary.pr_url,
                approval_status=summary.approval_status,
                created_at=summary.run_created_at or summary.created_at,
                patch_artifact=_artifact_ref(patch_artifacts.get(summary.run_id)),
                execution_contract=build_execution_contract_telemetry(
                    run.summary if run is not None and isinstance(run.summary, dict) else None
                ),
            )
        )
    return cards


async def _load_imported_references(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int = 6,
) -> list[MissionControlImportedReference]:
    artifacts = (
        await session.execute(
            select(Artifact)
            .where(
                Artifact.project_id == project_id,
                Artifact.tenant_id == tenant_id,
                Artifact.type == "external_reference",
                Artifact.deleted_at.is_(None),
            )
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    refs: list[MissionControlImportedReference] = []
    for artifact in artifacts:
        metadata = artifact.extra_metadata if isinstance(artifact.extra_metadata, dict) else {}
        imported_at_raw = metadata.get("fetched_at")
        imported_at: datetime | None = None
        if isinstance(imported_at_raw, str) and imported_at_raw.strip():
            try:
                imported_at = datetime.fromisoformat(imported_at_raw.replace("Z", "+00:00"))
            except ValueError:
                imported_at = None
        freshness_score: float | None = None
        if imported_at is not None:
            age_days = max(0.0, (datetime.now(imported_at.tzinfo) - imported_at).total_seconds() / 86400.0)
            freshness_score = round(max(0.0, min(1.0, 1.0 - min(age_days / 30.0, 1.0))), 3)
        refs.append(
            MissionControlImportedReference(
                id=artifact.id,
                type=artifact.type,
                uri=artifact.uri,
                created_at=artifact.created_at,
                domain=str(metadata.get("domain") or "") or None,
                label=str(metadata.get("label") or "") or None,
                imported_at=imported_at,
                linked_requirement_id=artifact.requirement_id,
                linked_run_id=artifact.run_id,
                linked_work_item_id=artifact.work_item_id,
                linked_task_id=artifact.task_id,
                trust_score=float(metadata.get("trust_score")) if metadata.get("trust_score") is not None else 0.8,
                freshness_score=freshness_score,
                used_in_execution_count=int(metadata.get("used_in_execution_count") or 0),
            )
        )
    return refs


def _build_change_impact(
    summary: RunSummary | None,
    run: Run | None,
    patch_artifact: Artifact | None,
    related_docs: list[Document],
) -> MissionControlChangeImpact | None:
    if summary is None:
        return None
    files_changed = [value for value in summary.changed_files if isinstance(value, str)]
    modules_impacted = _unique([_module_name(path) for path in files_changed if not _is_test_file(path)])[:6]
    tests_impacted = [path for path in files_changed if _is_test_file(path)]
    additions = 0
    deletions = 0
    if run is not None and patch_artifact is not None:
        diff = resolve_artifact_content(run, patch_artifact)
        if diff:
            _, additions, deletions = parse_unified_diff(diff)
    risk_score, risk_tier = _risk_score(files_changed, summary.recovery_count, summary.primary_error)
    api_impact = _extract_api_impact(summary.goal_text, *[doc.body for doc in related_docs])
    return MissionControlChangeImpact(
        run_id=summary.run_id,
        files_changed=files_changed,
        modules_impacted=modules_impacted,
        tests_impacted=tests_impacted,
        api_impact=api_impact,
        risk_score=risk_score,
        risk_tier=risk_tier,
        confidence_score=_confidence_from_summary(summary),
        additions=additions,
        deletions=deletions,
        approval_status=summary.approval_status,
        patch_artifact=_artifact_ref(patch_artifact),
        pull_request_url=summary.pr_url,
    )


def _build_preview_panel(
    project: Project,
    workspace_name: str | None,
    project_repo: ProjectRepository | None,
    preview_profile: ProjectPreviewProfile | None,
    summary: RunSummary | None,
    patch_artifact: Artifact | None,
    change_impact: MissionControlChangeImpact | None,
    run: Run | None,
) -> MissionControlPreviewAndPrs:
    effective_profile = resolve_preview_profile(preview_profile, repository_connected=project_repo is not None)
    preview_summary = run.summary.get("preview") if run is not None and isinstance(run.summary, dict) else None
    if not isinstance(preview_summary, dict):
        preview_summary = {}
    preview_url = preview_summary.get("preview_url") if isinstance(preview_summary.get("preview_url"), str) else None
    frontend = preview_summary.get("frontend") if isinstance(preview_summary.get("frontend"), dict) else None
    backend = preview_summary.get("backend") if isinstance(preview_summary.get("backend"), dict) else None
    active_preview_url = (
        frontend.get("url")
        if frontend and isinstance(frontend.get("url"), str)
        else (backend.get("url") if backend and isinstance(backend.get("url"), str) else preview_url)
    )
    stale_preview_url = preview_url if preview_url and active_preview_url and preview_url != active_preview_url else None
    preview_host = build_workspace_project_preview_host(
        workspace_name=workspace_name or str(project.workspace_id),
        project_name=project.name or str(project.id),
        workspace_id=str(project.workspace_id or ""),
        project_id=str(project.id),
    )
    preview_status = str(preview_summary.get("status") or "NOT_CONFIGURED")
    if preview_status == "NOT_CONFIGURED" and summary and summary.status in {"QUEUED", "RUNNING"}:
        preview_status = "PENDING"
    file_count = len(change_impact.files_changed) if change_impact and change_impact.patch_artifact else 0
    return MissionControlPreviewAndPrs(
        run_id=summary.run_id if summary else None,
        repository_connected=project_repo is not None,
        profile_configured=preview_profile_available(preview_profile, repository_connected=project_repo is not None),
        provider=project_repo.provider if project_repo else None,
        repo_full_name=project_repo.repo_full_name if project_repo else None,
        branch_name=(summary.branch_name if summary else None) or (project_repo.default_branch if project_repo else None),
        preview_mode=str(preview_summary.get("mode") or (effective_profile.mode if effective_profile else "local")),
        preview_status=preview_status,
        preview_url=preview_url,
        active_preview_url=active_preview_url,
        stale_preview_url=stale_preview_url,
        preview_domain_host=preview_host,
        preview_domain_url=f"https://{preview_host}",
        frontend_url=frontend.get("url") if frontend else None,
        backend_url=backend.get("url") if backend else None,
        frontend_port=int(frontend.get("port")) if frontend and frontend.get("port") is not None else None,
        backend_port=int(backend.get("port")) if backend and backend.get("port") is not None else None,
        frontend_log_path=frontend.get("log_path") if frontend else None,
        backend_log_path=backend.get("log_path") if backend else None,
        preview_checked_at=datetime.fromisoformat(preview_summary["last_checked_at"]) if isinstance(preview_summary.get("last_checked_at"), str) else None,
        last_health_check_at=datetime.fromisoformat(preview_summary["last_checked_at"]) if isinstance(preview_summary.get("last_checked_at"), str) else None,
        preview_expires_at=datetime.fromisoformat(preview_summary["expires_at"]) if isinstance(preview_summary.get("expires_at"), str) else None,
        requires_verification=bool(preview_summary.get("requires_verification")) or (run is not None and run.status != "COMPLETED"),
        verification_note=(
            str(preview_summary.get("verification_note"))
            if isinstance(preview_summary.get("verification_note"), str)
            else ("Run must be completed before preview launch." if run is not None and run.status != "COMPLETED" else None)
        ),
        patch_artifact=_artifact_ref(patch_artifact),
        pull_request_url=summary.pr_url if summary else None,
        approval_status=summary.approval_status if summary else None,
        file_count=file_count,
        additions=change_impact.additions if change_impact else 0,
        deletions=change_impact.deletions if change_impact else 0,
    )


def _is_delivery_candidate(
    summary: RunSummary | None,
    run: Run | None,
    patch_artifact: Artifact | None,
) -> bool:
    if summary is None or summary.status != "COMPLETED":
        return False
    summary_payload = run.summary if run is not None and isinstance(run.summary, dict) else {}
    preview_summary = summary_payload.get("preview") if isinstance(summary_payload.get("preview"), dict) else {}
    preview_status = str(preview_summary.get("status") or "NOT_CONFIGURED").upper()
    return any(
        (
            patch_artifact is not None,
            bool(summary.pr_url),
            bool(summary.changed_files),
            bool(summary_payload.get("remote_branch_pushed")),
            preview_status != "NOT_CONFIGURED",
        )
    )


def _build_strategy_learning(runs: list[Run]) -> list[MissionControlStrategyInsight]:
    buckets: dict[tuple[str, str], dict[str, object]] = {}
    for run in runs:
        summary = run.summary or {}
        strategy_type = summary.get("strategy_type")
        label = summary.get("strategy_label")
        if not isinstance(strategy_type, str) or not strategy_type.strip():
            continue
        if not isinstance(label, str) or not label.strip():
            label = strategy_type.replace("_", " ").title()
        key = (strategy_type.strip(), label.strip())
        bucket = buckets.setdefault(
            key,
            {
                "uses": 0,
                "successes": 0,
                "elapsed": [],
            },
        )
        bucket["uses"] = int(bucket["uses"]) + 1
        if run.status == "COMPLETED":
            bucket["successes"] = int(bucket["successes"]) + 1
        if run.started_at and run.finished_at:
            bucket["elapsed"].append((run.finished_at - run.started_at).total_seconds())

    insights: list[MissionControlStrategyInsight] = []
    for (strategy_type, label), bucket in buckets.items():
        uses = int(bucket["uses"])
        successes = int(bucket["successes"])
        elapsed = bucket["elapsed"]
        avg_elapsed = round(sum(elapsed) / len(elapsed), 3) if elapsed else None
        insights.append(
            MissionControlStrategyInsight(
                strategy_type=strategy_type,
                label=label,
                uses=uses,
                success_rate=round(successes / uses, 3) if uses else 0.0,
                average_elapsed_seconds=avg_elapsed,
            )
        )
    insights.sort(key=lambda item: (-item.success_rate, -item.uses, item.label))
    return insights[:5]


def _top_counts(counter: Counter[str], limit: int = 5) -> list[MissionControlNamedCount]:
    return [MissionControlNamedCount(name=name, count=count) for name, count in counter.most_common(limit)]


def _normalize_violation_mode(mode: str | None) -> str:
    normalized = str(mode or "off").strip().lower()
    if normalized in {"off", "warn", "strict"}:
        return normalized
    return "off"


def _parse_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        return None


def _project_contract_violation_records_for_run(run: Run | None) -> list[dict[str, object]]:
    if run is None or not isinstance(run.summary, dict):
        return []
    raw_records = run.summary.get("project_contract_violations")
    if not isinstance(raw_records, list):
        return []
    records: list[dict[str, object]] = []
    for raw in raw_records:
        if not isinstance(raw, dict):
            continue
        mode = _normalize_violation_mode(raw.get("mode"))
        blocking_value = raw.get("blocking")
        blocking = bool(blocking_value) if isinstance(blocking_value, bool) else mode == "strict"
        violation_type = str(raw.get("type") or "project_contract_violation").strip().lower()
        rule = str(raw.get("rule") or "unknown").strip().lower()
        file_path = raw.get("file")
        if not isinstance(file_path, str) or not file_path.strip():
            file_path = None
        value = raw.get("value")
        if not isinstance(value, str) or not value.strip():
            value = None
        message = raw.get("message")
        if not isinstance(message, str) or not message.strip():
            message = None
        work_item_type = raw.get("work_item_type")
        if not isinstance(work_item_type, str) or not work_item_type.strip():
            work_item_type = None
        records.append(
            {
                "work_item_id": _parse_uuid(raw.get("work_item_id")),
                "work_item_type": work_item_type,
                "mode": mode,
                "blocking": blocking,
                "type": violation_type,
                "rule": rule,
                "file": file_path,
                "value": value,
                "message": message,
            }
        )
    return records


def _build_violation_insights(
    summaries: list[RunSummary],
    runs: dict[uuid.UUID, Run],
    *,
    recent_window: int = 5,
    sample_limit: int = 8,
) -> MissionControlViolationInsights | None:
    if not summaries:
        return None

    windowed = summaries[: max(1, recent_window)]
    latest_summary = windowed[0]
    latest_records = _project_contract_violation_records_for_run(runs.get(latest_summary.run_id))
    latest_blocking = sum(1 for record in latest_records if bool(record.get("blocking")))

    rule_counter: Counter[str] = Counter()
    type_counter: Counter[str] = Counter()
    file_counter: Counter[str] = Counter()
    recent_total = 0
    samples: list[MissionControlViolationSample] = []

    for summary in windowed:
        run_records = _project_contract_violation_records_for_run(runs.get(summary.run_id))
        recent_total += len(run_records)
        for record in run_records:
            rule = record.get("rule")
            if isinstance(rule, str) and rule.strip():
                rule_counter[rule] += 1
            violation_type = record.get("type")
            if isinstance(violation_type, str) and violation_type.strip():
                type_counter[violation_type] += 1
            file_path = record.get("file")
            if isinstance(file_path, str) and file_path.strip():
                file_counter[file_path] += 1

            if len(samples) < sample_limit:
                samples.append(
                    MissionControlViolationSample(
                        run_id=summary.run_id,
                        work_item_id=record.get("work_item_id"),
                        work_item_type=record.get("work_item_type"),
                        mode=record.get("mode") if isinstance(record.get("mode"), str) else "off",
                        blocking=bool(record.get("blocking")),
                        type=record.get("type") if isinstance(record.get("type"), str) else "project_contract_violation",
                        rule=record.get("rule") if isinstance(record.get("rule"), str) else "unknown",
                        file=record.get("file") if isinstance(record.get("file"), str) else None,
                        value=record.get("value") if isinstance(record.get("value"), str) else None,
                        message=record.get("message") if isinstance(record.get("message"), str) else None,
                    )
                )

    return MissionControlViolationInsights(
        latest_run_id=latest_summary.run_id,
        latest_run_total=len(latest_records),
        latest_run_blocking=latest_blocking,
        latest_run_warning=max(0, len(latest_records) - latest_blocking),
        recent_run_window=min(len(summaries), max(1, recent_window)),
        recent_total=recent_total,
        top_rules=_top_counts(rule_counter),
        top_types=_top_counts(type_counter),
        top_files=_top_counts(file_counter),
        recent_samples=samples,
    )


def _build_system_insights(summaries: list[RunSummary]) -> MissionControlSystemInsights:
    total_runs = len(summaries)
    successful = sum(1 for summary in summaries if summary.status == "COMPLETED")
    completed_elapsed = [summary.elapsed_seconds for summary in summaries if summary.status == "COMPLETED" and summary.elapsed_seconds is not None]
    average_fix_time = round(sum(completed_elapsed) / len(completed_elapsed), 3) if completed_elapsed else None
    average_recovery = round(sum(summary.recovery_count for summary in summaries) / total_runs, 3) if total_runs else 0.0
    file_counter: Counter[str] = Counter()
    module_counter: Counter[str] = Counter()
    total_prs = sum(1 for summary in summaries if summary.pr_created)
    for summary in summaries:
        for path in summary.changed_files:
            if not isinstance(path, str):
                continue
            file_counter[path] += 1
            if not _is_test_file(path):
                module_counter[_module_name(path)] += 1
    return MissionControlSystemInsights(
        total_runs=total_runs,
        successful_runs=successful,
        success_rate=round(successful / total_runs, 3) if total_runs else 0.0,
        average_fix_time_seconds=average_fix_time,
        total_pull_requests=total_prs,
        average_recovery_count=average_recovery,
        most_impacted_modules=_top_counts(module_counter),
        most_impacted_files=_top_counts(file_counter),
    )


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2)


async def _build_eta_profiles(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    recent_run_ids: list[uuid.UUID],
) -> list[MissionControlEtaProfile]:
    if not recent_run_ids:
        return []
    rows = (
        await session.execute(
            select(WorkItem.type, WorkItem.started_at, WorkItem.finished_at)
            .where(
                WorkItem.tenant_id == tenant_id,
                WorkItem.project_id == project_id,
                WorkItem.run_id.in_(recent_run_ids),
                WorkItem.status == "DONE",
                WorkItem.started_at.is_not(None),
                WorkItem.finished_at.is_not(None),
            )
            .order_by(WorkItem.finished_at.desc())
            .limit(800)
        )
    ).all()
    durations_by_type: dict[str, list[float]] = {}
    for work_item_type, started_at, finished_at in rows:
        if not work_item_type or started_at is None or finished_at is None:
            continue
        elapsed = (finished_at - started_at).total_seconds()
        if elapsed <= 0:
            continue
        durations_by_type.setdefault(str(work_item_type), []).append(float(elapsed))
    profiles: list[MissionControlEtaProfile] = []
    for work_item_type, values in durations_by_type.items():
        if not values:
            continue
        profiles.append(
            MissionControlEtaProfile(
                work_item_type=work_item_type,
                median_seconds=round(_median(values), 3),
                sample_count=len(values),
            )
        )
    profiles.sort(key=lambda item: item.work_item_type)
    return profiles


async def _build_stalled_runs(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    runs: list[Run],
    stale_after_seconds: int = 300,
) -> list[MissionControlStalledRun]:
    running = [run for run in runs if str(run.status or "").upper() in {"RUNNING", "QUEUED"}]
    if not running:
        return []
    run_ids = [run.id for run in running]
    events = (
        await session.execute(
            select(RunEvent.run_id, RunEvent.ts)
            .where(
                RunEvent.tenant_id == tenant_id,
                RunEvent.project_id == project_id,
                RunEvent.run_id.in_(run_ids),
            )
            .order_by(RunEvent.ts.desc())
            .limit(400)
        )
    ).all()
    latest_event_by_run: dict[uuid.UUID, datetime] = {}
    for run_id, ts in events:
        if run_id not in latest_event_by_run:
            latest_event_by_run[run_id] = ts
    now = datetime.utcnow()
    stalled: list[MissionControlStalledRun] = []
    for run in running:
        baseline = run.started_at or run.created_at
        last_event = latest_event_by_run.get(run.id) or baseline
        if last_event is None:
            continue
        last_event_ts = last_event.replace(tzinfo=None) if getattr(last_event, "tzinfo", None) is not None else last_event
        stale_seconds = int(max(0.0, (now - last_event_ts).total_seconds()))
        if stale_seconds < stale_after_seconds:
            continue
        stalled.append(
            MissionControlStalledRun(
                run_id=run.id,
                status=run.status,
                last_event_at=last_event,
                stale_seconds=stale_seconds,
                suggested_action="Resume or unblock if paused; inspect run events if still active.",
            )
        )
    stalled.sort(key=lambda item: item.stale_seconds, reverse=True)
    return stalled[:6]


async def build_mission_control_overview(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    lightweight: bool = True,
) -> MissionControlOverviewResponse:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
    if project is None:
        raise ValueError("Project not found")

    work_intake = await _build_work_intake(session, tenant_id=tenant_id, project_id=project_id)
    summaries, run_by_id, patch_artifacts, _ = await _load_recent_runs_and_artifacts(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        limit=20,
    )
    recent_runs = _build_recent_runs(summaries[:6], run_by_id, patch_artifacts)
    latest_summary = summaries[0] if summaries else None
    latest_run = run_by_id.get(latest_summary.run_id) if latest_summary else None
    latest_patch = patch_artifacts.get(latest_summary.run_id) if latest_summary else None
    delivery_summary = next(
        (
            summary
            for summary in summaries
            if _is_delivery_candidate(
                summary,
                run_by_id.get(summary.run_id),
                patch_artifacts.get(summary.run_id),
            )
        ),
        latest_summary,
    )
    delivery_run = run_by_id.get(delivery_summary.run_id) if delivery_summary else None
    delivery_patch = patch_artifacts.get(delivery_summary.run_id) if delivery_summary else None
    related_docs = await _load_recent_documents(session, tenant_id=tenant_id, project_id=project_id)
    change_impact = _build_change_impact(latest_summary, latest_run, latest_patch, related_docs)
    delivery_change_impact = _build_change_impact(delivery_summary, delivery_run, delivery_patch, related_docs)
    project_repo = await session.scalar(
        select(ProjectRepository).where(
            ProjectRepository.project_id == project_id,
            ProjectRepository.tenant_id == tenant_id,
        )
    )
    preview_profile = await session.scalar(
        select(ProjectPreviewProfile).where(
            ProjectPreviewProfile.project_id == project_id,
            ProjectPreviewProfile.tenant_id == tenant_id,
        )
    )
    workspace_name = None
    if project.workspace_id:
        workspace = await session.scalar(
            select(Workspace).where(Workspace.id == project.workspace_id, Workspace.tenant_id == tenant_id)
        )
        workspace_name = workspace.name if workspace else None
    runs = list(run_by_id.values())
    # Preview and delivery controls should follow the latest deliverable run
    # (branch push / patch-bearing / PR-capable context), not the latest noop.
    preview_panel = _build_preview_panel(
        project,
        workspace_name,
        project_repo,
        preview_profile,
        delivery_summary,
        delivery_patch,
        delivery_change_impact,
        delivery_run,
    )
    architecture_summary = await summarize_architecture_profile(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        touched_files=change_impact.files_changed if change_impact else [],
    )
    project_contract_summary = await summarize_project_contract(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    imported_references = await _load_imported_references(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    eta_profiles = (
        []
        if lightweight
        else await _build_eta_profiles(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            recent_run_ids=[summary.run_id for summary in summaries[:20]],
        )
    )
    return MissionControlOverviewResponse(
        work_intake=work_intake,
        recent_runs=recent_runs,
        latest_change_impact=change_impact,
        previews_and_prs=preview_panel,
        architecture_profile=architecture_summary,
        project_contract=project_contract_summary,
        latest_execution_contract=build_execution_contract_telemetry(
            latest_run.summary if latest_run is not None and isinstance(latest_run.summary, dict) else None
        ),
        strategy_learning=[] if lightweight else _build_strategy_learning(runs),
        eta_profiles=eta_profiles,
        system_insights=_build_system_insights(summaries),
        violation_insights=_build_violation_insights(summaries, run_by_id),
        imported_references=imported_references,
        stalled_runs=await _build_stalled_runs(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            runs=runs,
        ),
    )
    MissionControlImportedReference,
