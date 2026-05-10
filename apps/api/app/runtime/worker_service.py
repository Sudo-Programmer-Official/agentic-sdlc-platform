from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select, and_, exists, update

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.models import Agent, Run, WorkItem, WorkItemEdge
from app.runtime.leases import keep_work_item_lease_alive, lease_seconds_for_executor
from app.runtime.registry import build_executor
from app.runtime.recovery_policy import maybe_apply_recovery
from app.runtime.execution_contract import sync_run_execution_contract_state
from app.services.event_log import record_event
from app.services.run_resume import capture_run_checkpoint, sync_run_resume_state
from app.services.runtime_lineage import persist_work_item_artifacts
from app.services.runtime_env_diagnostics import collect_runtime_startup_diagnostics
from app.services.workspace_supervisor import build_run_context
from app.services.work_item_state import is_dependency_satisfied
from app.api.v1.lifecycle_score import lifecycle_score
settings = get_settings()
log = logging.getLogger("app.runtime.worker")


def _work_item_terminal_event_type(status: str) -> str:
    if status == "DONE":
        return "WORK_ITEM_DONE"
    if status == "SKIPPED":
        return "WORK_ITEM_SKIPPED"
    return "WORK_ITEM_FAILED"


async def execute_item(session, wi: WorkItem, agent: Agent):
    work_item_id = wi.id
    run_id = wi.run_id
    project_id = wi.project_id
    tenant_id = wi.tenant_id
    agent_id = agent.id
    run = await session.get(Run, run_id)
    if run is None:
        return
    failure_stage = "workspace_context"
    try:
        context = await build_run_context(session, run, require_repo=wi.executor in {"codex", "test"})
        executor = build_executor(wi.executor, repo_root=None if not context.repo_path else Path(context.repo_path))
        failure_stage = "executor_execute"
        result = await executor.execute(wi, context)
        wi.status = result.get("status", "DONE")
        wi.result = result.get("payload", {})
        wi.finished_at = datetime.now(timezone.utc)
        wi.last_error = None
        session.add(wi)
        failure_stage = "artifact_persistence"
        await persist_work_item_artifacts(session, wi, (wi.result or {}).get("artifacts"))
        if wi.status in {"DONE", "SKIPPED"}:
            await capture_run_checkpoint(session, run, work_item=wi, checkpoint_kind="safe")
        failure_stage = "event_recording"
        await record_event(
            session,
            project_id=project_id,
            run_id=run_id,
            work_item_id=work_item_id,
            event_type=_work_item_terminal_event_type(wi.status),
            actor_type="AGENT",
            actor_id=str(agent_id),
            payload={"work_item_id": str(work_item_id), "status": wi.status},
        )
        await session.flush()
        failure_stage = "recovery_policy"
        await maybe_apply_recovery(session, wi)
        if run is not None:
            await sync_run_execution_contract_state(session, run)
            await sync_run_resume_state(session, run)
    except Exception as exc:
        await session.rollback()
        failed_item = await session.get(WorkItem, work_item_id)
        if failed_item is None:
            return
        failed_item.status = "FAILED"
        failed_item.finished_at = datetime.now(timezone.utc)
        failed_item.last_error = str(exc)
        session.add(failed_item)
        await record_event(
            session,
            project_id=project_id,
            run_id=run_id,
            work_item_id=work_item_id,
            event_type="WORK_ITEM_FAILED",
            actor_type="AGENT",
            actor_id=str(agent_id),
            tenant_id=tenant_id,
            payload={
                "work_item_id": str(work_item_id),
                "error": str(exc),
                "exception_class": exc.__class__.__name__,
                "failure_stage": failure_stage,
            },
        )
        await session.flush()
        await maybe_apply_recovery(session, failed_item)
        failed_run = await session.get(Run, run_id)
        if failed_run is not None:
            await sync_run_execution_contract_state(session, failed_run)
            await sync_run_resume_state(session, failed_run, failed_work_item=failed_item)


async def tick_worker(agent_id: uuid.UUID):
    settings = get_settings()
    if settings.runtime_mode != "external":
        return
    async with SessionLocal() as session:
        agent = await session.get(Agent, agent_id)
        if not agent or agent.status != "ACTIVE":
            return
        # claim one item
        now = datetime.now(timezone.utc)
        agent.last_heartbeat_at = now
        session.add(agent)
        agent_caps = set(agent.capabilities or [])
        agent_executors = set(agent.executors or [])
        # Prevent multiple RUN_TESTS per run at once
        from sqlalchemy.orm import aliased
        other = aliased(WorkItem)
        parent = aliased(WorkItem)
        result = await session.execute(
            select(WorkItem)
            .join(Run, Run.id == WorkItem.run_id)
            .where(
                WorkItem.status == "QUEUED",
                Run.status.in_(["RUNNING", "QUEUED"]),
                ~exists().where(
                    and_(
                        other.run_id == WorkItem.run_id,
                        other.type == "RUN_TESTS",
                        other.status == "RUNNING",
                    )
                ),
            )
            .order_by(WorkItem.priority.desc(), WorkItem.created_at)
            .limit(20)
            .with_for_update(skip_locked=True)
        )
        wi = None
        candidate_items = result.scalars().all()
        dependency_rows = []
        if candidate_items:
            candidate_ids = [item.id for item in candidate_items]
            candidate_run_ids = list({item.run_id for item in candidate_items})
            dependency_rows = (
                await session.execute(
                    select(
                        WorkItemEdge.to_work_item_id,
                        parent.status,
                        parent.payload,
                        parent.result,
                    ).join(parent, parent.id == WorkItemEdge.from_work_item_id)
                    .where(
                        WorkItemEdge.run_id.in_(candidate_run_ids),
                        WorkItemEdge.to_work_item_id.in_(candidate_ids),
                    )
                )
            ).all()
        deps_by_child: dict[uuid.UUID, list[SimpleNamespace]] = {}
        for to_work_item_id, status, payload, result_payload in dependency_rows:
            deps_by_child.setdefault(to_work_item_id, []).append(
                SimpleNamespace(status=status, payload=payload, result=result_payload)
            )
        for candidate in candidate_items:
            active_run = await session.scalar(
                select(Run)
                .where(Run.id == candidate.run_id, Run.status.in_(["RUNNING", "QUEUED"]))
                .with_for_update(skip_locked=True)
            )
            if active_run is None:
                continue
            if any(not is_dependency_satisfied(dep) for dep in deps_by_child.get(candidate.id, [])):
                continue
            req_caps = set(candidate.required_capabilities or [])
            if req_caps and not req_caps.issubset(agent_caps):
                continue
            if agent_executors and candidate.executor not in agent_executors:
                continue
            wi = candidate
            break
        if not wi:
            await session.commit()
            return
        lease_seconds = lease_seconds_for_executor(settings, wi.executor)
        lease_expires = now + timedelta(seconds=lease_seconds)
        wi.status = "RUNNING"
        wi.assigned_agent_id = agent_id
        wi.lease_expires_at = lease_expires
        wi.started_at = now
        session.add(wi)
        await record_event(
            session,
            project_id=wi.project_id,
            run_id=wi.run_id,
            work_item_id=wi.id,
            event_type="WORK_ITEM_CLAIMED",
            actor_type="AGENT",
            actor_id=str(agent_id),
            payload={"work_item_id": str(wi.id), "agent_id": str(agent_id)},
        )
        await session.commit()

    # execute outside the claim transaction
    async with SessionLocal() as session:
        wi = await session.get(WorkItem, wi.id)
        agent = await session.get(Agent, agent_id)
        if not wi or not agent:
            return
        lease_keepalive = asyncio.create_task(
            keep_work_item_lease_alive(
                SessionLocal,
                agent_id=agent_id,
                work_item_id=wi.id,
                lease_seconds=lease_seconds,
            )
        )
        try:
            await execute_item(session, wi, agent)
            await session.commit()
        finally:
            lease_keepalive.cancel()
            await lease_keepalive


async def main():
    settings = get_settings()
    agent_id = uuid.uuid4()
    diagnostics = collect_runtime_startup_diagnostics(settings.runtime_mode, settings.runtime_git_auth_mode)
    log.info(
        "Starting worker build=%s sha=%s runtime_mode=%s runtime_git_auth_mode=%s",
        diagnostics.build_version,
        diagnostics.build_sha,
        diagnostics.runtime_mode,
        diagnostics.runtime_git_auth_mode,
    )
    if diagnostics.git_binary:
        log.info("Worker runtime tool availability git=%s", diagnostics.git_binary)
    else:
        log.warning("Worker runtime tool availability git=missing repo-backed runs will fail until git is installed")
    if diagnostics.runtime_git_auth_mode == "ssh":
        if diagnostics.ssh_binary:
            log.info("Worker runtime tool availability ssh=%s", diagnostics.ssh_binary)
        else:
            log.warning(
                "Worker runtime tool availability ssh=missing SSH-authenticated repo runs will fail until ssh is installed"
            )
    log.info(
        "Worker GitHub integration env app_id_present=%s private_key_present=%s webhook_secret_present=%s",
        diagnostics.github_app_id_present,
        diagnostics.github_private_key_present,
        diagnostics.github_webhook_secret_present,
    )
    # Register ephemeral worker agent record
    async with SessionLocal() as session:
        if settings.env == "local":
            await session.execute(
                update(Agent)
                .where(Agent.kind == "worker", Agent.status == "ACTIVE")
                .values(status="INACTIVE", executors=[], capabilities=[])
            )
            log.info("Marked existing local worker agents inactive before registering worker_id=%s", agent_id)
        agent = Agent(
            id=agent_id,
            name=f"worker-{agent_id.hex[:8]}",
            kind="worker",
            executors=["dummy", "codex", "test"],
            capabilities=["code", "test", "review", "plan"],
            max_concurrency=1,
            status="ACTIVE",
            last_heartbeat_at=datetime.now(timezone.utc),
        )
        session.add(agent)
        await session.commit()
        log.info("Registered worker agent_id=%s name=%s", agent.id, agent.name)

    while True:
        try:
            await tick_worker(agent_id)
        except Exception:
            log.exception("Worker tick failed agent_id=%s", agent_id)
        await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
