from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artifact, Run, RunEvent, WorkItem
from app.schemas.persistence import RunOut
from app.schemas.run_timeline import RunTimelineResponse, RunTimelineStep, RunTimelineSummary
from app.services.artifact_diff import parse_unified_diff, resolve_artifact_content
from app.services.run_summary_builder import upsert_run_summary


def _humanize_token(token: str) -> str:
    return token.replace("_", " ").strip().title()


def _work_item_label(work_item: WorkItem | None) -> str:
    if work_item is None:
        return "Work Item"
    payload = work_item.payload or {}
    title = payload.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    if work_item.key:
        return work_item.key
    return _humanize_token(work_item.type)


def _event_status(event_type: str) -> str:
    upper = event_type.upper()
    if upper.endswith("FAILED") or upper == "RUN_FAILED":
        return "failed"
    if upper.endswith("DONE") or upper.endswith("COMPLETED") or upper == "RUN_PULL_REQUEST_CREATED":
        return "success"
    if "RECOVERY" in upper or "RETRIED" in upper:
        return "recovery"
    if upper.endswith("RUNNING") or upper.endswith("STARTED") or upper.endswith("CLAIMED"):
        return "running"
    if "CANCELED" in upper or "FALLBACK" in upper:
        return "warning"
    return "info"


def _event_title(event: RunEvent, work_item: WorkItem | None) -> str:
    event_type = event.event_type.upper()
    label = _work_item_label(work_item)
    mapping = {
        "RUN_CREATED": "Run created",
        "RUN_PLAN_CAPTURED": "Run plan captured",
        "RUN_RUNNING": "Run started",
        "RUN_COMPLETED": "Run completed",
        "RUN_FAILED": "Run failed",
        "RUN_CANCELED": "Run canceled",
        "RUN_APPROVAL_RECORDED": "Approval recorded",
        "RUN_PULL_REQUEST_CREATED": "Pull request created",
        "RUN_FORKED": "Run forked",
        "RUN_RUNTIME_FALLBACK": "Runtime fallback engaged",
        "WORK_DAG_CREATED": "Execution DAG created",
        "WORK_ITEM_CLAIMED": f"{label} claimed",
        "WORK_ITEM_STARTED": f"{label} started",
        "WORK_ITEM_DONE": f"{label} completed",
        "WORK_ITEM_FAILED": f"{label} failed",
        "WORK_ITEM_RECOVERY": f"Recovery created for {label}",
        "WORK_ITEM_CREATED": f"{label} created",
        "WORK_ITEM_RETRIED": f"{label} retried",
        "WORK_ITEM_LEASE_EXPIRED": f"{label} lease expired",
        "LIFECYCLE_SCORED": "Lifecycle score updated",
    }
    return mapping.get(event_type, _humanize_token(event.event_type))


def _artifact_step(artifact: Artifact, changed_files: list[str]) -> RunTimelineStep:
    title = "Artifact produced"
    if artifact.type == "git_diff":
        title = "Patch artifact created"
    elif artifact.type == "pull_request":
        title = "Pull request artifact recorded"
    return RunTimelineStep(
        id=f"artifact:{artifact.id}",
        kind="artifact",
        ts=artifact.created_at,
        title=title,
        status="success",
        artifact_id=artifact.id,
        artifact_type=artifact.type,
        changed_files=changed_files,
        details={
            "uri": artifact.uri,
            "metadata": artifact.extra_metadata or {},
        },
    )


async def build_run_timeline(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
) -> RunTimelineResponse:
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id))
    if run is None:
        raise ValueError("Run not found")

    work_items = (
        await session.execute(
            select(WorkItem).where(
                WorkItem.run_id == run.id,
                WorkItem.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    work_items_by_id = {item.id: item for item in work_items}

    events = (
        await session.execute(
            select(RunEvent)
            .where(RunEvent.run_id == run.id, RunEvent.tenant_id == tenant_id)
            .order_by(RunEvent.ts.asc(), RunEvent.id.asc())
        )
    ).scalars().all()
    artifacts = (
        await session.execute(
            select(Artifact)
            .where(
                Artifact.run_id == run.id,
                Artifact.tenant_id == tenant_id,
                Artifact.deleted_at.is_(None),
            )
            .order_by(Artifact.created_at.asc(), Artifact.id.asc())
        )
    ).scalars().all()

    summary = await upsert_run_summary(session, run.id)
    await session.commit()

    artifact_files_by_id: dict[uuid.UUID, list[str]] = {}
    for artifact in artifacts:
        if artifact.type != "git_diff":
            artifact_files_by_id[artifact.id] = []
            continue
        diff = resolve_artifact_content(run, artifact)
        if not diff:
            artifact_files_by_id[artifact.id] = []
            continue
        files, _, _ = parse_unified_diff(diff)
        artifact_files_by_id[artifact.id] = [file.path for file in files if file.path]

    event_steps: list[tuple[object, RunTimelineStep]] = []
    for event in events:
        work_item = work_items_by_id.get(event.work_item_id) if event.work_item_id else None
        event_steps.append(
            (
                event.ts,
                RunTimelineStep(
                    id=f"event:{event.id}",
                    kind="event",
                    ts=event.ts,
                    title=_event_title(event, work_item),
                    status=_event_status(event.event_type),
                    event_type=event.event_type,
                    message=event.message,
                    work_item_id=work_item.id if work_item else None,
                    work_item_type=work_item.type if work_item else None,
                    work_item_key=work_item.key if work_item else None,
                    details=event.payload or None,
                ),
            )
        )

    artifact_steps = [
        (artifact.created_at, _artifact_step(artifact, artifact_files_by_id.get(artifact.id, [])))
        for artifact in artifacts
    ]

    steps = [step for _, step in sorted(event_steps + artifact_steps, key=lambda item: (item[0], item[1].id))]
    timeline_summary = RunTimelineSummary(
        goal_text=summary.goal_text if summary else None,
        status=run.status,
        executor=run.executor,
        branch_name=run.branch_name,
        workspace_status=run.workspace_status,
        elapsed_seconds=summary.elapsed_seconds if summary else None,
        recovery_count=summary.recovery_count if summary else 0,
        artifact_count=summary.artifact_count if summary else len(artifacts),
        changed_files=list(summary.changed_files) if summary else sorted({path for paths in artifact_files_by_id.values() for path in paths}),
        primary_error=summary.primary_error if summary else None,
        pull_request_url=summary.pr_url if summary else None,
    )
    return RunTimelineResponse(
        run=RunOut.model_validate(run),
        summary=timeline_summary,
        steps=steps,
    )
