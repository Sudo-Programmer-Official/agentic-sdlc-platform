from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artifact, Document, Project, ProjectPreviewProfile, ProjectRepository, Run, RunSummary, Task
from app.schemas.mission_control import (
    MissionControlArtifactRef,
    MissionControlChangeImpact,
    MissionControlNamedCount,
    MissionControlOverviewResponse,
    MissionControlPreviewAndPrs,
    MissionControlRunCard,
    MissionControlStrategyInsight,
    MissionControlSystemInsights,
    MissionControlWorkIntakeItem,
)
from app.services.artifact_diff import parse_unified_diff, resolve_artifact_content
from app.services.preview_service import preview_profile_available, resolve_preview_profile
from app.services.run_memory import find_similar_runs
from app.services.run_summary_builder import ensure_project_run_summaries

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
            run_by_id.get(summary.run_id).started_at if run_by_id.get(summary.run_id) else None
        )
        or summary.run_created_at
        or summary.created_at,
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
    patch_artifacts: dict[uuid.UUID, Artifact | None],
) -> list[MissionControlRunCard]:
    cards: list[MissionControlRunCard] = []
    for summary in summaries:
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
            )
        )
    return cards


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
    preview_status = str(preview_summary.get("status") or "NOT_CONFIGURED")
    if preview_status == "NOT_CONFIGURED" and summary and summary.status in {"QUEUED", "RUNNING"}:
        preview_status = "PENDING"
    file_count = len(change_impact.files_changed) if change_impact and change_impact.patch_artifact else 0
    return MissionControlPreviewAndPrs(
        repository_connected=project_repo is not None,
        profile_configured=preview_profile_available(preview_profile, repository_connected=project_repo is not None),
        provider=project_repo.provider if project_repo else None,
        repo_full_name=project_repo.repo_full_name if project_repo else None,
        branch_name=(summary.branch_name if summary else None) or (project_repo.default_branch if project_repo else None),
        preview_mode=str(preview_summary.get("mode") or (effective_profile.mode if effective_profile else "local")),
        preview_status=preview_status,
        preview_url=preview_url,
        frontend_url=frontend.get("url") if frontend else None,
        backend_url=backend.get("url") if backend else None,
        frontend_log_path=frontend.get("log_path") if frontend else None,
        backend_log_path=backend.get("log_path") if backend else None,
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


async def build_mission_control_overview(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
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
    recent_runs = _build_recent_runs(summaries[:6], patch_artifacts)
    latest_summary = summaries[0] if summaries else None
    latest_run = run_by_id.get(latest_summary.run_id) if latest_summary else None
    latest_patch = patch_artifacts.get(latest_summary.run_id) if latest_summary else None
    related_docs = await _load_recent_documents(session, tenant_id=tenant_id, project_id=project_id)
    change_impact = _build_change_impact(latest_summary, latest_run, latest_patch, related_docs)
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
    runs = list(run_by_id.values())
    preview_panel = _build_preview_panel(project_repo, preview_profile, latest_summary, latest_patch, change_impact, latest_run)
    return MissionControlOverviewResponse(
        work_intake=work_intake,
        recent_runs=recent_runs,
        latest_change_impact=change_impact,
        previews_and_prs=preview_panel,
        strategy_learning=_build_strategy_learning(runs),
        system_insights=_build_system_insights(summaries),
    )
