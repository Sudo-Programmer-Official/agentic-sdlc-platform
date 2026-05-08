from __future__ import annotations

from collections import Counter
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select, case, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Approval, Artifact, Run, RunEvent, RunSummary, WorkItem
from app.services.work_item_state import is_blocking_failure


def _run_activity_ordering():
    return (
        case(
            (Run.status == "RUNNING", 0),
            (Run.status == "QUEUED", 1),
            else_=2,
        ),
        func.coalesce(Run.started_at, Run.created_at, Run.updated_at).desc(),
        Run.id.desc(),
    )


def _elapsed_seconds(run: Run) -> float | None:
    if not run.started_at or not run.finished_at:
        return None
    return round((run.finished_at - run.started_at).total_seconds(), 3)


def _goal_text(run: Run) -> str | None:
    summary = run.summary or {}
    for key in ("goal", "title", "fork_notes"):
        value = summary.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _pull_request_meta(run: Run, artifacts: list[Artifact]) -> tuple[str | None, int | None]:
    summary = run.summary or {}
    url = summary.get("pull_request_url")
    number = summary.get("pull_request_number")
    if isinstance(number, str) and number.isdigit():
        number = int(number)
    if not url:
        pr_artifact = next((artifact for artifact in artifacts if artifact.type == "pull_request"), None)
        if pr_artifact is not None:
            url = pr_artifact.uri
            meta = pr_artifact.extra_metadata or {}
            artifact_number = meta.get("number")
            if isinstance(artifact_number, int):
                number = artifact_number
    return url, number if isinstance(number, int) else None


def _artifact_content(run: Run, artifact: Artifact) -> str | None:
    metadata = artifact.extra_metadata or {}
    content = metadata.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if artifact.uri.startswith("workspace://patches/") and run.workspace_root:
        patch_name = artifact.uri.removeprefix("workspace://patches/")
        patch_path = Path(run.workspace_root) / "patches" / patch_name
        if patch_path.exists():
            try:
                return patch_path.read_text(encoding="utf-8")
            except OSError:
                return None
    return None


def _changed_files_from_diff(diff: str) -> set[str]:
    changed: set[str] = set()
    for line in diff.splitlines():
        if not line.startswith("+++ "):
            continue
        path = line.split(maxsplit=1)[1].strip()
        if path == "/dev/null":
            continue
        if path.startswith("b/"):
            path = path[2:]
        elif path.startswith("a/"):
            path = path[2:]
        changed.add(path)
    return changed


def _diff_summary(changed_files: list[str]) -> str | None:
    normalized = [path for path in changed_files if isinstance(path, str) and path.strip()]
    if not normalized:
        return None
    if len(normalized) == 1:
        return f"Updated {normalized[0]}"
    if len(normalized) == 2:
        return f"Updated {normalized[0]} and {normalized[1]}"
    return f"Updated {normalized[0]}, {normalized[1]}, and {len(normalized) - 2} more files"


def _primary_error(run: Run, work_items: list[WorkItem]) -> str | None:
    ordered = sorted(
        [item for item in work_items if is_blocking_failure(item)],
        key=lambda wi: (wi.finished_at or wi.updated_at or wi.created_at),
        reverse=True,
    )
    for item in ordered:
        if item.last_error:
            return item.last_error
        result = item.result or {}
        for key in ("stderr", "message", "stdout"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if run.workspace_status == "ERROR" and run.workspace_error:
        return run.workspace_error
    return None


def _coerce_project_contract_violation_records(work_item: WorkItem) -> list[dict[str, Any]]:
    result = work_item.result if isinstance(work_item.result, dict) else {}
    patch_guard = result.get("patch_guard") if isinstance(result.get("patch_guard"), dict) else {}
    mode = str(patch_guard.get("project_enforcement_mode") or "off").strip().lower()
    if mode not in {"off", "warn", "strict"}:
        mode = "off"
    blocking_default = mode == "strict"

    records: list[dict[str, Any]] = []
    raw_records = patch_guard.get("project_violation_records")
    if isinstance(raw_records, list):
        for raw in raw_records:
            if not isinstance(raw, dict):
                continue
            message = raw.get("message")
            if not isinstance(message, str) or not message.strip():
                continue
            record_type = str(raw.get("type") or "project_contract_violation").strip().lower()
            rule = str(raw.get("rule") or "unknown").strip().lower()
            file_path = raw.get("file")
            if not isinstance(file_path, str) or not file_path.strip():
                file_path = None
            value = raw.get("value")
            if not isinstance(value, str) or not value.strip():
                value = None
            blocking = raw.get("blocking")
            if not isinstance(blocking, bool):
                blocking = blocking_default
            records.append(
                {
                    "work_item_id": str(work_item.id),
                    "work_item_type": work_item.type,
                    "mode": mode,
                    "blocking": blocking,
                    "type": record_type,
                    "rule": rule,
                    "file": file_path,
                    "value": value,
                    "message": message.strip(),
                }
            )

    if records:
        return records

    fallback_warnings = patch_guard.get("project_warnings")
    if isinstance(fallback_warnings, list):
        for warning in fallback_warnings:
            if not isinstance(warning, str) or not warning.strip():
                continue
            records.append(
                {
                    "work_item_id": str(work_item.id),
                    "work_item_type": work_item.type,
                    "mode": "warn" if mode == "off" else mode,
                    "blocking": False,
                    "type": "project_contract_warning",
                    "rule": "unknown",
                    "file": None,
                    "value": None,
                    "message": warning.strip(),
                }
            )
    return records


def _project_contract_violation_counts(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_rule: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    by_file: Counter[str] = Counter()
    blocking_count = 0
    for record in records:
        rule = record.get("rule")
        if isinstance(rule, str) and rule.strip():
            by_rule[rule.strip().lower()] += 1
        record_type = record.get("type")
        if isinstance(record_type, str) and record_type.strip():
            by_type[record_type.strip().lower()] += 1
        file_path = record.get("file")
        if isinstance(file_path, str) and file_path.strip():
            by_file[file_path.strip()] += 1
        if bool(record.get("blocking")):
            blocking_count += 1
    return {
        "total": len(records),
        "blocking": blocking_count,
        "warning": max(0, len(records) - blocking_count),
        "by_rule": dict(by_rule),
        "by_type": dict(by_type),
        "by_file": dict(by_file),
    }


async def upsert_run_summary(session: AsyncSession, run_id: uuid.UUID) -> RunSummary | None:
    run = await session.get(Run, run_id)
    if run is None:
        return None

    artifacts = (
        await session.execute(
            select(Artifact).where(
                Artifact.run_id == run_id,
                Artifact.tenant_id == run.tenant_id,
                Artifact.deleted_at.is_(None),
            ).order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    ).scalars().all()
    work_items = (
        await session.execute(
            select(WorkItem).where(
                WorkItem.run_id == run_id,
                WorkItem.tenant_id == run.tenant_id,
            )
        )
    ).scalars().all()
    recovery_count = (
        await session.execute(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.tenant_id == run.tenant_id,
                RunEvent.event_type == "WORK_ITEM_RECOVERY",
            )
        )
    ).scalars().all()
    artifact_ids = [artifact.id for artifact in artifacts]
    latest_approval_status: str | None = None
    if artifact_ids:
        approvals = (
            await session.execute(
                select(Approval).where(
                    Approval.tenant_id == run.tenant_id,
                    Approval.target_type == "artifact",
                    Approval.target_id.in_(artifact_ids),
                    Approval.deleted_at.is_(None),
                ).order_by(Approval.created_at.desc(), Approval.id.desc())
            )
        ).scalars().all()
        if approvals:
            latest_approval_status = approvals[0].status

    changed_files: set[str] = set()
    for artifact in artifacts:
        if artifact.type != "git_diff":
            continue
        diff = _artifact_content(run, artifact)
        if diff:
            changed_files.update(_changed_files_from_diff(diff))
    diff_summary = _diff_summary(sorted(changed_files))

    pr_url, pr_number = _pull_request_meta(run, artifacts)

    summary = await session.get(RunSummary, run.id)
    if summary is None:
        summary = RunSummary(run_id=run.id, tenant_id=run.tenant_id, project_id=run.project_id)
        session.add(summary)

    summary.goal_text = _goal_text(run)
    summary.status = run.status
    summary.executor = run.executor
    summary.branch_name = run.branch_name
    summary.workspace_status = run.workspace_status
    summary.elapsed_seconds = _elapsed_seconds(run)
    summary.recovery_count = len(recovery_count)
    summary.artifact_count = len(artifacts)
    summary.changed_files = sorted(changed_files)
    summary.artifact_types = sorted({artifact.type for artifact in artifacts})
    summary.primary_error = _primary_error(run, work_items)
    summary.approval_status = latest_approval_status
    summary.pr_created = bool(pr_url)
    summary.pr_url = pr_url
    summary.pull_request_number = pr_number
    summary.run_created_at = run.created_at
    summary.finished_at = run.finished_at
    summary_meta = dict(run.summary or {})
    project_contract_violations: list[dict[str, Any]] = []
    for item in work_items:
        project_contract_violations.extend(_coerce_project_contract_violation_records(item))
    if project_contract_violations:
        summary_meta["project_contract_violations"] = project_contract_violations[:100]
        summary_meta["project_contract_violation_counts"] = _project_contract_violation_counts(project_contract_violations)
    else:
        summary_meta.pop("project_contract_violations", None)
        summary_meta.pop("project_contract_violation_counts", None)
    if diff_summary:
        summary_meta["diff_summary"] = diff_summary
    else:
        summary_meta.pop("diff_summary", None)
    if summary_meta != (run.summary or {}):
        run.summary = summary_meta
        session.add(run)
        await session.flush()
        await session.refresh(run, attribute_names=["updated_at"])
    summary.source_updated_at = run.updated_at
    await session.flush()
    return summary


async def ensure_project_run_summaries(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int,
) -> list[RunSummary]:
    runs = (
        await session.execute(
            select(Run)
            .where(Run.project_id == project_id, Run.tenant_id == tenant_id)
            .order_by(*_run_activity_ordering())
            .limit(limit)
        )
    ).scalars().all()
    if not runs:
        return []

    run_ids = [run.id for run in runs]
    existing_rows = (
        await session.execute(
            select(RunSummary).where(
                RunSummary.run_id.in_(run_ids),
                RunSummary.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    by_run_id = {row.run_id: row for row in existing_rows}

    def summary_is_stale(run: Run, current: RunSummary | None) -> bool:
        if current is None:
            return True
        if current.source_updated_at is None:
            return True
        if run.updated_at and current.source_updated_at < run.updated_at:
            return True
        if current.status != run.status:
            return True
        if current.executor != run.executor:
            return True
        if current.branch_name != run.branch_name:
            return True
        if current.workspace_status != run.workspace_status:
            return True
        if current.finished_at != run.finished_at:
            return True
        if current.goal_text != _goal_text(run):
            return True
        summary = run.summary or {}
        summary_pr_url = summary.get("pull_request_url")
        if isinstance(summary_pr_url, str) and summary_pr_url != current.pr_url:
            return True
        return False

    refreshed: dict[uuid.UUID, RunSummary] = {}
    for run in runs:
        current = by_run_id.get(run.id)
        if summary_is_stale(run, current):
            refreshed_row = await upsert_run_summary(session, run.id)
            if refreshed_row is not None:
                refreshed[run.id] = refreshed_row
        elif current is not None:
            refreshed[run.id] = current

    await session.commit()
    return [refreshed[run.id] for run in runs if run.id in refreshed]
