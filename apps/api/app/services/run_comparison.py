from __future__ import annotations

import uuid
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Approval, Artifact, Run, RunEvent, WorkItem
from app.schemas.run_comparison import (
    RunComparisonArtifact,
    RunComparisonResponse,
    RunComparisonSide,
    RunComparisonSummary,
)


def _elapsed_seconds(run: Run) -> float | None:
    if not run.started_at or not run.finished_at:
        return None
    return round((run.finished_at - run.started_at).total_seconds(), 3)


def _forked_from_run_id(run: Run) -> uuid.UUID | None:
    value = (run.summary or {}).get("forked_from_run_id")
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _pull_request_meta(run: Run) -> tuple[str | None, int | None]:
    summary = run.summary or {}
    url = summary.get("pull_request_url")
    number = summary.get("pull_request_number")
    if isinstance(number, str) and number.isdigit():
        number = int(number)
    if isinstance(number, int):
        return url, number
    return url, None


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


def _recovery_steps(events: list[RunEvent]) -> list[str]:
    steps: list[str] = []
    for event in events:
        payload = event.payload or {}
        failure_class = payload.get("failure_class")
        action = payload.get("recovery_action")
        recovery_type = payload.get("recovery_type")
        if event.message:
            steps.append(event.message)
            continue
        bits = []
        if failure_class:
            bits.append(str(failure_class))
        if action:
            bits.append(f"-> {action}")
        if recovery_type:
            bits.append(f"({recovery_type})")
        steps.append(" ".join(bits) or event.event_type)
    return steps


def _work_item_counts(items: list[WorkItem]) -> dict[str, int]:
    counts: dict[str, int] = {"queued": 0, "running": 0, "done": 0, "skipped": 0, "failed": 0, "canceled": 0}
    for item in items:
        if item.status == "QUEUED":
            counts["queued"] += 1
        elif item.status in {"CLAIMED", "RUNNING"}:
            counts["running"] += 1
        elif item.status == "DONE":
            counts["done"] += 1
        elif item.status == "SKIPPED":
            counts["skipped"] += 1
        elif item.status == "FAILED":
            counts["failed"] += 1
        elif item.status == "CANCELED":
            counts["canceled"] += 1
    return counts


def _build_side(
    run: Run,
    artifacts: list[Artifact],
    work_items: list[WorkItem],
    recovery_events: list[RunEvent],
    approval_status: str | None,
) -> RunComparisonSide:
    artifact_types = sorted({artifact.type for artifact in artifacts})
    files_changed: set[str] = set()
    for artifact in artifacts:
        if artifact.type != "git_diff":
            continue
        diff = _artifact_content(run, artifact)
        if diff:
            files_changed.update(_changed_files_from_diff(diff))

    pull_request_url, pull_request_number = _pull_request_meta(run)
    if not pull_request_url:
        pr_artifact = next((artifact for artifact in artifacts if artifact.type == "pull_request"), None)
        if pr_artifact is not None:
            pull_request_url = pr_artifact.uri
            metadata = pr_artifact.extra_metadata or {}
            number = metadata.get("number")
            pull_request_number = number if isinstance(number, int) else pull_request_number

    return RunComparisonSide(
        id=run.id,
        project_id=run.project_id,
        status=run.status,
        executor=run.executor,
        branch_name=run.branch_name,
        workspace_status=run.workspace_status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        elapsed_seconds=_elapsed_seconds(run),
        forked_from_run_id=_forked_from_run_id(run),
        recovery_count=len(recovery_events),
        recovery_steps=_recovery_steps(recovery_events),
        artifact_count=len(artifacts),
        artifact_types=artifact_types,
        files_changed=sorted(files_changed),
        work_item_counts=_work_item_counts(work_items),
        pull_request_url=pull_request_url,
        pull_request_number=pull_request_number,
        approval_status=approval_status,
        summary=run.summary,
        artifacts=[
            RunComparisonArtifact(
                id=artifact.id,
                type=artifact.type,
                uri=artifact.uri,
                created_at=artifact.created_at,
                work_item_id=artifact.work_item_id,
            )
            for artifact in artifacts[:8]
        ],
    )


def _summary(run_a: RunComparisonSide, run_b: RunComparisonSide) -> RunComparisonSummary:
    faster_run_id: uuid.UUID | None = None
    faster_by_seconds: float | None = None
    if run_a.elapsed_seconds is not None and run_b.elapsed_seconds is not None and run_a.elapsed_seconds != run_b.elapsed_seconds:
        if run_a.elapsed_seconds < run_b.elapsed_seconds:
            faster_run_id = run_a.id
            faster_by_seconds = round(run_b.elapsed_seconds - run_a.elapsed_seconds, 3)
        else:
            faster_run_id = run_b.id
            faster_by_seconds = round(run_a.elapsed_seconds - run_b.elapsed_seconds, 3)

    more_recoveries_run_id: uuid.UUID | None = None
    if run_a.recovery_count != run_b.recovery_count:
        more_recoveries_run_id = run_a.id if run_a.recovery_count > run_b.recovery_count else run_b.id

    pull_request_run_id: uuid.UUID | None = None
    if run_a.pull_request_url and not run_b.pull_request_url:
        pull_request_run_id = run_a.id
    elif run_b.pull_request_url and not run_a.pull_request_url:
        pull_request_run_id = run_b.id

    return RunComparisonSummary(
        faster_run_id=faster_run_id,
        faster_by_seconds=faster_by_seconds,
        more_recoveries_run_id=more_recoveries_run_id,
        pull_request_run_id=pull_request_run_id,
        artifact_types_only_in_a=sorted(set(run_a.artifact_types) - set(run_b.artifact_types)),
        artifact_types_only_in_b=sorted(set(run_b.artifact_types) - set(run_a.artifact_types)),
        files_only_in_a=sorted(set(run_a.files_changed) - set(run_b.files_changed)),
        files_only_in_b=sorted(set(run_b.files_changed) - set(run_a.files_changed)),
    )


async def compare_runs(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run_a_id: uuid.UUID,
    run_b_id: uuid.UUID,
) -> RunComparisonResponse:
    if run_a_id == run_b_id:
        raise ValueError("Choose two different runs to compare")

    runs = (
        await session.execute(
            select(Run).where(
                Run.id.in_([run_a_id, run_b_id]),
                Run.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    if len(runs) != 2:
        raise ValueError("Both runs must exist in the current tenant")

    runs_by_id = {run.id: run for run in runs}
    run_a = runs_by_id.get(run_a_id)
    run_b = runs_by_id.get(run_b_id)
    if run_a is None or run_b is None:
        raise ValueError("Both runs must exist in the current tenant")
    if run_a.project_id != run_b.project_id:
        raise ValueError("Run comparison requires runs from the same project")

    artifacts = (
        await session.execute(
            select(Artifact).where(
                Artifact.run_id.in_([run_a_id, run_b_id]),
                Artifact.tenant_id == tenant_id,
                Artifact.deleted_at.is_(None),
            ).order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    ).scalars().all()
    artifacts_by_run: dict[uuid.UUID, list[Artifact]] = defaultdict(list)
    artifact_ids: list[uuid.UUID] = []
    for artifact in artifacts:
        if artifact.run_id is None:
            continue
        artifacts_by_run[artifact.run_id].append(artifact)
        artifact_ids.append(artifact.id)

    work_items = (
        await session.execute(
            select(WorkItem).where(
                WorkItem.run_id.in_([run_a_id, run_b_id]),
                WorkItem.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    work_items_by_run: dict[uuid.UUID, list[WorkItem]] = defaultdict(list)
    for item in work_items:
        work_items_by_run[item.run_id].append(item)

    events = (
        await session.execute(
            select(RunEvent).where(
                RunEvent.run_id.in_([run_a_id, run_b_id]),
                RunEvent.tenant_id == tenant_id,
                RunEvent.event_type == "WORK_ITEM_RECOVERY",
            ).order_by(RunEvent.ts.asc(), RunEvent.id.asc())
        )
    ).scalars().all()
    recovery_by_run: dict[uuid.UUID, list[RunEvent]] = defaultdict(list)
    for event in events:
        recovery_by_run[event.run_id].append(event)

    latest_approval_by_artifact: dict[uuid.UUID, str] = {}
    if artifact_ids:
        approvals = (
            await session.execute(
                select(Approval).where(
                    Approval.tenant_id == tenant_id,
                    Approval.target_type == "artifact",
                    Approval.target_id.in_(artifact_ids),
                    Approval.deleted_at.is_(None),
                ).order_by(Approval.created_at.desc(), Approval.id.desc())
            )
        ).scalars().all()
        for approval in approvals:
            latest_approval_by_artifact.setdefault(approval.target_id, approval.status)

    def approval_status_for(run_id: uuid.UUID) -> str | None:
        statuses = [
            latest_approval_by_artifact[artifact.id]
            for artifact in artifacts_by_run.get(run_id, [])
            if artifact.id in latest_approval_by_artifact
        ]
        return statuses[0] if statuses else None

    side_a = _build_side(
        run_a,
        artifacts_by_run.get(run_a_id, []),
        work_items_by_run.get(run_a_id, []),
        recovery_by_run.get(run_a_id, []),
        approval_status_for(run_a_id),
    )
    side_b = _build_side(
        run_b,
        artifacts_by_run.get(run_b_id, []),
        work_items_by_run.get(run_b_id, []),
        recovery_by_run.get(run_b_id, []),
        approval_status_for(run_b_id),
    )
    return RunComparisonResponse(
        run_a=side_a,
        run_b=side_b,
        summary=_summary(side_a, side_b),
    )
