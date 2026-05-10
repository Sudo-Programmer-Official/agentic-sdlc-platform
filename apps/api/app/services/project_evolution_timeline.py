from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Artifact,
    Document,
    ImprovementRequest,
    MemorySummaryArtifact,
    Project,
    ProjectEvolutionEvent,
    RecoveryAttempt,
    Run,
    RunEvent,
    RunSummary,
    Task,
    WorkItem,
)
from app.schemas.mission_control import (
    MissionControlMemoryExplainResponse,
    MissionControlMemorySummaryArtifact,
    MissionControlMemorySummaryListResponse,
    MissionControlTimelineEvent,
    MissionControlTimelineResponse,
)


@dataclass
class _TimelineItem:
    id: str
    event_at: datetime
    domain: str
    event_type: str
    title: str
    summary: str | None
    severity: str
    status: str
    retention_class: str = "keep"
    requirement_id: str | None = None
    run_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    work_item_id: uuid.UUID | None = None
    contract_id: str | None = None
    related_artifact_ids: list[str] | None = None
    deployment_ref: str | None = None
    metadata: dict | None = None


def _event_title(event_type: str) -> str:
    return event_type.replace("_", " ").strip().title()


def _severity_from_event_type(event_type: str) -> str:
    upper = event_type.upper()
    if "FAILED" in upper or "BLOCKED" in upper:
        return "critical"
    if "RECOVERY" in upper or "RETRIED" in upper or "WARNING" in upper:
        return "warning"
    return "info"


def _status_from_event_type(event_type: str) -> str:
    upper = event_type.upper()
    if "FAILED" in upper or "BLOCKED" in upper:
        return "open"
    if "COMPLETED" in upper or "DONE" in upper or "SUCCEEDED" in upper:
        return "resolved"
    return "observed"


def _retention_class(event_type: str, domain: str, severity: str) -> str:
    upper = event_type.upper()
    if domain in {"requirement", "deployment", "architecture"}:
        return "keep"
    if severity == "critical" or "FAILED" in upper:
        return "keep"
    if "RECOVERY" in upper or "RETRIED" in upper or domain in {"recovery", "improvement"}:
        return "compress"
    if "NUDGE" in upper or "HEARTBEAT" in upper:
        return "discard"
    return "keep"


def _extract_requirement_id_from_payload(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("requirement_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    values = payload.get("requirement_ids")
    if isinstance(values, list):
        for item in values:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None


async def build_project_evolution_timeline(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int = 60,
    domain: str | None = None,
    severity: str | None = None,
    requirement_id: str | None = None,
    run_id: uuid.UUID | None = None,
) -> MissionControlTimelineResponse:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
    if project is None:
        raise ValueError("Project not found")

    timeline: list[_TimelineItem] = []
    scan_limit = min(max(limit * 4, 80), 300)

    runs = (
        await session.execute(select(Run).where(Run.project_id == project_id, Run.tenant_id == tenant_id))
    ).scalars().all()
    run_by_id = {row.id: row for row in runs}
    work_items = (
        await session.execute(select(WorkItem).where(WorkItem.project_id == project_id, WorkItem.tenant_id == tenant_id))
    ).scalars().all()
    work_item_by_id = {row.id: row for row in work_items}
    tasks = (
        await session.execute(
            select(Task).where(Task.project_id == project_id, Task.tenant_id == tenant_id, Task.deleted_at.is_(None))
        )
    ).scalars().all()
    task_by_id = {row.id: row for row in tasks}
    requirement_by_run: dict[uuid.UUID, str] = {}
    for task in tasks:
        if task.run_id and task.requirement_id and task.requirement_id.strip():
            requirement_by_run.setdefault(task.run_id, task.requirement_id.strip())
    artifact_rows = (
        await session.execute(
            select(Artifact).where(
                Artifact.project_id == project_id,
                Artifact.tenant_id == tenant_id,
                Artifact.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    artifact_ids_by_run: dict[uuid.UUID, list[str]] = {}
    artifact_ids_by_work_item: dict[uuid.UUID, list[str]] = {}
    for artifact in artifact_rows:
        sid = str(artifact.id)
        if artifact.run_id:
            artifact_ids_by_run.setdefault(artifact.run_id, []).append(sid)
        if artifact.work_item_id:
            artifact_ids_by_work_item.setdefault(artifact.work_item_id, []).append(sid)

    if domain in {None, "run", "recovery", "contract"}:
        run_events = (
            await session.execute(
                select(RunEvent)
                .where(
                    RunEvent.project_id == project_id,
                    RunEvent.tenant_id == tenant_id,
                    RunEvent.run_id == run_id if run_id is not None else True,
                )
                .order_by(RunEvent.ts.desc(), RunEvent.id.desc())
                .limit(scan_limit)
            )
        ).scalars().all()
        for event in run_events:
            event_domain = "recovery" if "RECOVERY" in event.event_type.upper() else "run"
            run_obj = run_by_id.get(event.run_id)
            work_item = work_item_by_id.get(event.work_item_id) if event.work_item_id else None
            requirement = (
                _extract_requirement_id_from_payload(event.payload)
                or (run_obj.requirement_id if run_obj and run_obj.requirement_id else None)
                or requirement_by_run.get(event.run_id)
            )
            contract_id = None
            if run_obj and isinstance(run_obj.summary, dict):
                contract_meta = run_obj.summary.get("execution_contract")
                if isinstance(contract_meta, dict):
                    raw_id = contract_meta.get("contract_id")
                    if isinstance(raw_id, str) and raw_id.strip():
                        contract_id = raw_id.strip()
            timeline.append(
                _TimelineItem(
                    id=f"run_event:{event.id}",
                    event_at=event.ts,
                    domain=event_domain,
                    event_type=event.event_type,
                    title=_event_title(event.event_type),
                    summary=event.message,
                    severity=_severity_from_event_type(event.event_type),
                    status=_status_from_event_type(event.event_type),
                    retention_class=_retention_class(event.event_type, event_domain, _severity_from_event_type(event.event_type)),
                    requirement_id=requirement,
                    run_id=event.run_id,
                    task_id=event.task_id,
                    work_item_id=event.work_item_id,
                    contract_id=contract_id,
                    related_artifact_ids=(
                        (artifact_ids_by_work_item.get(work_item.id, []) if work_item else [])
                        or artifact_ids_by_run.get(event.run_id, [])
                    )[:12],
                    metadata=event.payload if isinstance(event.payload, dict) else None,
                )
            )

    if domain in {None, "recovery"}:
        recovery_attempts = (
            await session.execute(
                select(RecoveryAttempt)
                .where(
                    RecoveryAttempt.project_id == project_id,
                    RecoveryAttempt.tenant_id == tenant_id,
                    RecoveryAttempt.run_id == run_id if run_id is not None else True,
                )
                .order_by(RecoveryAttempt.created_at.desc(), RecoveryAttempt.id.desc())
                .limit(scan_limit // 2)
            )
        ).scalars().all()
        for attempt in recovery_attempts:
            sev = "critical" if str(attempt.result).lower() == "failed" else "warning"
            timeline.append(
                _TimelineItem(
                    id=f"recovery_attempt:{attempt.id}",
                    event_at=attempt.created_at,
                    domain="recovery",
                    event_type="RECOVERY_ATTEMPT",
                    title=f"Recovery attempt {attempt.recovery_action}",
                    summary=attempt.rationale,
                    severity=sev,
                    status="resolved" if str(attempt.result).lower() == "succeeded" else "open",
                    retention_class=_retention_class("RECOVERY_ATTEMPT", "recovery", sev),
                    requirement_id=requirement_by_run.get(attempt.run_id),
                    run_id=attempt.run_id,
                    task_id=None,
                    work_item_id=attempt.work_item_id,
                    contract_id=None,
                    related_artifact_ids=artifact_ids_by_run.get(attempt.run_id, [])[:12],
                    metadata={
                        "failure_type": attempt.failure_type,
                        "attempt_number": attempt.attempt_number,
                        "result": attempt.result,
                    },
                )
            )

    if domain in {None, "requirement"}:
        requirement_docs = (
            await session.execute(
                select(Document)
                .where(
                    Document.project_id == project_id,
                    Document.tenant_id == tenant_id,
                    Document.deleted_at.is_(None),
                    Document.type.in_(["prd", "requirements", "requirements_graph", "spec"]),
                )
                .order_by(Document.created_at.desc(), Document.id.desc())
                .limit(scan_limit // 2)
            )
        ).scalars().all()
        for doc in requirement_docs:
            timeline.append(
                _TimelineItem(
                    id=f"document:{doc.id}",
                    event_at=doc.created_at,
                    domain="requirement",
                    event_type="REQUIREMENT_DOCUMENT_UPDATED",
                    title=f"Requirement source updated: {doc.title}",
                    summary=f"type={doc.type} version={doc.version}",
                    severity="info",
                    status="observed",
                    retention_class="keep",
                    metadata={"document_type": doc.type, "source": doc.source},
                )
            )

    if domain in {None, "improvement"}:
        improvements = (
            await session.execute(
                select(ImprovementRequest)
                .where(
                    ImprovementRequest.project_id == project_id,
                    ImprovementRequest.tenant_id == tenant_id,
                    ImprovementRequest.source_run_id == run_id if run_id is not None else True,
                    ImprovementRequest.source_requirement_id == requirement_id if requirement_id is not None else True,
                )
                .order_by(ImprovementRequest.created_at.desc(), ImprovementRequest.id.desc())
                .limit(scan_limit // 2)
            )
        ).scalars().all()
        for improvement in improvements:
            timeline.append(
                _TimelineItem(
                    id=f"improvement:{improvement.id}",
                    event_at=improvement.created_at,
                    domain="improvement",
                    event_type="IMPROVEMENT_REQUEST_CREATED",
                    title="Improvement request created",
                    summary=improvement.issue_text or improvement.goal_text,
                    severity="warning",
                    status="open" if str(improvement.status).upper() not in {"COMPLETED", "DONE"} else "resolved",
                    retention_class=_retention_class("IMPROVEMENT_REQUEST_CREATED", "improvement", "warning"),
                    requirement_id=improvement.source_requirement_id,
                    run_id=improvement.source_run_id,
                    metadata={"status": improvement.status, "executor": improvement.executor},
                )
            )

    if domain in {None, "deployment"}:
        run_summaries = (
            await session.execute(
                select(RunSummary)
                .where(
                    RunSummary.project_id == project_id,
                    RunSummary.tenant_id == tenant_id,
                    RunSummary.run_id == run_id if run_id is not None else True,
                    RunSummary.pr_created.is_(True),
                )
                .order_by(RunSummary.created_at.desc(), RunSummary.run_id.desc())
                .limit(scan_limit // 3)
            )
        ).scalars().all()
        for summary_row in run_summaries:
            timeline.append(
                _TimelineItem(
                    id=f"deployment:pr:{summary_row.run_id}",
                    event_at=summary_row.finished_at or summary_row.created_at,
                    domain="deployment",
                    event_type="PULL_REQUEST_CREATED",
                    title="Pull request created",
                    summary=summary_row.pr_url,
                    severity="info",
                    status="observed",
                    retention_class="keep",
                    requirement_id=run_by_id.get(summary_row.run_id).requirement_id if run_by_id.get(summary_row.run_id) else None,
                    run_id=summary_row.run_id,
                    deployment_ref=summary_row.pr_url,
                    related_artifact_ids=artifact_ids_by_run.get(summary_row.run_id, [])[:12],
                    metadata={"pull_request_number": summary_row.pull_request_number},
                )
            )

    if requirement_id:
        timeline = [item for item in timeline if item.requirement_id == requirement_id]
    if severity:
        timeline = [item for item in timeline if item.severity == severity]

    timeline.sort(key=lambda item: (item.event_at, item.id), reverse=True)
    items = timeline[:limit]
    await _persist_timeline_items(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        items=items,
    )
    await session.commit()
    return MissionControlTimelineResponse(
        items=[
            MissionControlTimelineEvent(
                id=item.id,
                event_at=item.event_at,
                domain=item.domain,
                event_type=item.event_type,
                title=item.title,
                summary=item.summary,
                severity=item.severity,
                status=item.status,
                retention_class=item.retention_class,
                requirement_id=item.requirement_id,
                run_id=item.run_id,
                task_id=item.task_id,
                work_item_id=item.work_item_id,
                contract_id=item.contract_id,
                related_artifact_ids=list(item.related_artifact_ids or []),
                deployment_ref=item.deployment_ref,
                metadata=item.metadata,
            )
            for item in items
        ]
    )


async def _persist_timeline_items(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    items: list[_TimelineItem],
) -> None:
    # Idempotent ingest key for synthesized events.
    for item in items:
        existing = await session.scalar(
            select(ProjectEvolutionEvent).where(
                and_(
                    ProjectEvolutionEvent.tenant_id == tenant_id,
                    ProjectEvolutionEvent.project_id == project_id,
                    ProjectEvolutionEvent.event_type == item.event_type,
                    ProjectEvolutionEvent.domain == item.domain,
                    ProjectEvolutionEvent.event_at == item.event_at,
                    ProjectEvolutionEvent.run_id == item.run_id,
                    ProjectEvolutionEvent.task_id == item.task_id,
                    ProjectEvolutionEvent.work_item_id == item.work_item_id,
                    ProjectEvolutionEvent.title == item.title,
                )
            )
        )
        if existing is not None:
            continue
        session.add(
            ProjectEvolutionEvent(
                tenant_id=tenant_id,
                project_id=project_id,
                event_at=item.event_at,
                event_type=item.event_type,
                domain=item.domain,
                title=item.title,
                summary=item.summary,
                severity=item.severity,
                status=item.status,
                retention_class=item.retention_class,
                requirement_id=item.requirement_id,
                run_id=item.run_id,
                task_id=item.task_id,
                work_item_id=item.work_item_id,
                contract_id=item.contract_id,
                deployment_ref=item.deployment_ref,
                related_artifact_ids=list(item.related_artifact_ids or []),
                related_file_paths=[],
                event_metadata=item.metadata if isinstance(item.metadata, dict) else None,
            )
        )


async def count_persisted_timeline_events(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> int:
    count = (
        await session.execute(
            select(func.count()).where(
                ProjectEvolutionEvent.tenant_id == tenant_id,
                ProjectEvolutionEvent.project_id == project_id,
            )
        )
    ).scalar()
    return int(count or 0)


async def materialize_timeline_summaries(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> list[MemorySummaryArtifact]:
    events = (
        await session.execute(
            select(ProjectEvolutionEvent)
            .where(
                ProjectEvolutionEvent.tenant_id == tenant_id,
                ProjectEvolutionEvent.project_id == project_id,
            )
            .order_by(ProjectEvolutionEvent.event_at.desc(), ProjectEvolutionEvent.id.desc())
            .limit(1000)
        )
    ).scalars().all()
    if not events:
        return []

    newest = events[0].event_at
    oldest = events[-1].event_at
    domain_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    retention_counts: dict[str, int] = {}
    for event in events:
        domain_counts[event.domain] = domain_counts.get(event.domain, 0) + 1
        severity_counts[event.severity] = severity_counts.get(event.severity, 0) + 1
        retention_counts[event.retention_class] = retention_counts.get(event.retention_class, 0) + 1

    summary_payloads = {
        "project_evolution_daily": {
            "synthesis_version": "v1",
            "source_event_window": {"start_at": oldest.isoformat(), "end_at": newest.isoformat(), "event_count": len(events)},
            "compression_strategy": "daily_operational_summary",
            "window": "daily",
            "totals": {"events": len(events)},
            "domains": domain_counts,
            "severity": severity_counts,
            "retention": retention_counts,
        },
        "project_evolution_weekly": {
            "synthesis_version": "v1",
            "source_event_window": {"start_at": oldest.isoformat(), "end_at": newest.isoformat(), "event_count": len(events)},
            "compression_strategy": "weekly_operational_summary",
            "window": "weekly",
            "totals": {"events": len(events)},
            "critical_events": severity_counts.get("critical", 0),
            "recovery_events": domain_counts.get("recovery", 0),
            "deployment_events": domain_counts.get("deployment", 0),
        },
        "project_evolution_milestone": {
            "synthesis_version": "v1",
            "source_event_window": {"start_at": oldest.isoformat(), "end_at": newest.isoformat(), "event_count": len(events)},
            "compression_strategy": "milestone_operational_summary",
            "window": "milestone",
            "highlights": [
                f"Critical events: {severity_counts.get('critical', 0)}",
                f"Recovery events: {domain_counts.get('recovery', 0)}",
                f"Requirement events: {domain_counts.get('requirement', 0)}",
            ],
        },
    }

    saved: list[MemorySummaryArtifact] = []
    for summary_type, payload in summary_payloads.items():
        existing = await session.scalar(
            select(MemorySummaryArtifact)
            .where(
                MemorySummaryArtifact.tenant_id == tenant_id,
                MemorySummaryArtifact.project_id == project_id,
                MemorySummaryArtifact.summary_type == summary_type,
                MemorySummaryArtifact.source_entity_type == "project",
                MemorySummaryArtifact.source_entity_id == str(project_id),
            )
            .order_by(MemorySummaryArtifact.version.desc())
        )
        next_version = int(existing.version + 1) if existing is not None else 1
        row = MemorySummaryArtifact(
            tenant_id=tenant_id,
            project_id=project_id,
            summary_type=summary_type,
            source_entity_type="project",
            source_entity_id=str(project_id),
            version=next_version,
            window_start_at=oldest,
            window_end_at=newest,
            payload=payload,
            quality_score=1.0 if len(events) >= 10 else 0.6,
        )
        session.add(row)
        saved.append(row)
    await session.commit()
    return saved


async def list_memory_summaries(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    summary_type: str | None = None,
    limit: int = 30,
) -> MissionControlMemorySummaryListResponse:
    query = select(MemorySummaryArtifact).where(
        MemorySummaryArtifact.tenant_id == tenant_id,
        MemorySummaryArtifact.project_id == project_id,
    )
    if summary_type:
        query = query.where(MemorySummaryArtifact.summary_type == summary_type)
    rows = (
        await session.execute(query.order_by(MemorySummaryArtifact.created_at.desc(), MemorySummaryArtifact.id.desc()).limit(limit))
    ).scalars().all()
    return MissionControlMemorySummaryListResponse(
        items=[
            MissionControlMemorySummaryArtifact(
                id=row.id,
                summary_type=row.summary_type,
                source_entity_type=row.source_entity_type,
                source_entity_id=row.source_entity_id,
                version=row.version,
                window_start_at=row.window_start_at,
                window_end_at=row.window_end_at,
                payload=row.payload if isinstance(row.payload, dict) else {},
                quality_score=row.quality_score,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]
    )


async def explain_memory_event_chain(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    requirement_id: str | None = None,
    run_id: uuid.UUID | None = None,
    limit: int = 20,
) -> MissionControlMemoryExplainResponse:
    query = select(ProjectEvolutionEvent).where(
        ProjectEvolutionEvent.tenant_id == tenant_id,
        ProjectEvolutionEvent.project_id == project_id,
    )
    if requirement_id:
        query = query.where(ProjectEvolutionEvent.requirement_id == requirement_id)
    if run_id:
        query = query.where(ProjectEvolutionEvent.run_id == run_id)
    rows = (
        await session.execute(query.order_by(ProjectEvolutionEvent.event_at.desc(), ProjectEvolutionEvent.id.desc()).limit(limit))
    ).scalars().all()

    causes: list[str] = []
    if any(row.severity == "critical" for row in rows):
        causes.append("Critical runtime failures were observed in the linked timeline.")
    if any(row.domain == "recovery" for row in rows):
        causes.append("Recovery actions were repeatedly needed, indicating instability.")
    if any(row.domain == "deployment" for row in rows):
        causes.append("Deployment/PR activity overlaps with incident window.")
    if not causes:
        causes.append("No dominant failure pattern detected in the selected window.")

    linked_events = [
        MissionControlTimelineEvent(
            id=str(row.id),
            event_at=row.event_at,
            domain=row.domain,
            event_type=row.event_type,
            title=row.title,
            summary=row.summary,
            severity=row.severity,
            status=row.status,
            retention_class=row.retention_class,
            requirement_id=row.requirement_id,
            run_id=row.run_id,
            task_id=row.task_id,
            work_item_id=row.work_item_id,
            contract_id=row.contract_id,
            related_artifact_ids=[str(v) for v in (row.related_artifact_ids or [])],
            deployment_ref=row.deployment_ref,
            metadata=row.event_metadata if isinstance(row.event_metadata, dict) else None,
        )
        for row in rows
    ]
    linked_runs = sorted({str(row.run_id) for row in rows if row.run_id})
    linked_requirements = sorted({row.requirement_id for row in rows if row.requirement_id})
    recommendations: list[str] = []
    if any(row.severity == "critical" for row in rows):
        recommendations.append("Prioritize failing validation and recovery root cause before expanding scope.")
    if any(row.domain == "recovery" for row in rows):
        recommendations.append("Review repeated recovery actions and add deterministic fix strategy.")
    if any(row.retention_class == "compress" for row in rows):
        recommendations.append("Compress repetitive retry/noise events into periodic summary artifacts.")
    if not recommendations:
        recommendations.append("Continue monitoring with weekly summary artifacts.")

    return MissionControlMemoryExplainResponse(
        target={"project_id": str(project_id), "requirement_id": requirement_id, "run_id": str(run_id) if run_id else None},
        top_causes=causes[:5],
        linked_events=linked_events,
        linked_runs=linked_runs,
        linked_requirements=linked_requirements,
        recommended_actions=recommendations[:5],
    )
