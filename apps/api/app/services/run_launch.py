from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Run, Task
from app.db.session import SessionLocal
from app.schemas.architecture_profile import ArchitectureProfileSummaryOut
from app.runtime.execution_contract import build_execution_contract
from app.runtime.orchestrator import RunOrchestrator
from app.services.activity_log import log_activity
from app.services.architecture_profile_service import summarize_architecture_profile
from app.services.event_log import record_event
from app.services.repo_connector import get_project_repository
from app.services.run_resume import capture_run_checkpoint, sync_run_resume_state
from app.services.task_branching import clean_branch_value, resolve_task_branch_plan
from app.services.workspace_supervisor import ensure_run_workspace

log = logging.getLogger("app.run_launch")
_TASK_SCOPE_HINT_RE = re.compile(r"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.[A-Za-z0-9]{1,12})(?![\w./-])")
_FRONTEND_SCOPE_HINTS = {
    "homepage",
    "landing page",
    "hero section",
    "footer",
    "navbar",
    "navigation",
    "section",
    "layout",
    "responsive",
    "portfolio",
    "ui",
    "frontend",
    "css",
    "style",
}


def _list_strings(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _has_task_file_scope(summary: dict[str, object] | None) -> bool:
    if not isinstance(summary, dict):
        return False
    for key in ("target_files", "expected_files", "files", "related_files"):
        if _list_strings(summary.get(key)):
            return True
    return False


def _has_text_scope_hints(summary: dict[str, object] | None) -> bool:
    if not isinstance(summary, dict):
        return False
    text = " ".join(
        str(summary.get(key) or "").strip()
        for key in ("goal", "task_title", "task_description")
        if str(summary.get(key) or "").strip()
    )
    lowered = text.lower()
    return bool(_TASK_SCOPE_HINT_RE.search(text)) or any(keyword in lowered for keyword in _FRONTEND_SCOPE_HINTS)


def _build_task_run_summary(task: Task) -> dict[str, object]:
    title = task.title.strip()
    description = (task.description or "").strip() or None
    goal = title if not description else f"{title}: {description}"
    summary: dict[str, str | list[str] | dict | None] = {
        "goal": goal,
        "task_id": str(task.id),
        "task_title": title,
        "task_description": description,
        "task_source": task.source,
        "task_branch_strategy": task.branch_strategy,
        "task_base_branch": clean_branch_value(task.base_branch),
        "task_requested_branch_name": clean_branch_value(task.branch_name),
    }
    if isinstance(task.result_payload, dict):
        for key in ("target_files", "expected_files", "files", "related_files"):
            values = _list_strings(task.result_payload.get(key))
            if values:
                summary[key] = values
        edit_budget = task.result_payload.get("edit_budget")
        if isinstance(edit_budget, dict):
            summary["edit_budget"] = dict(edit_budget)
    return summary


async def _resolve_architecture_payload(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    touched_files: list[str],
) -> dict[str, object]:
    try:
        summary = await summarize_architecture_profile(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            touched_files=touched_files,
        )
    except Exception:
        log.warning(
            "Architecture profile summary unavailable during run launch project_id=%s tenant_id=%s",
            project_id,
            tenant_id,
            exc_info=True,
        )
        summary = ArchitectureProfileSummaryOut(
            summary="Architecture profile unavailable during run launch.",
            assumptions_used=["Execution contract derived from runtime defaults because architecture summary lookup failed."],
        )
    return summary.model_dump(mode="json")


def _schedule_orchestrator_start(
    orchestrator: RunOrchestrator,
    *,
    run_id: uuid.UUID,
    actor_type: str,
    actor_id: str | None,
    executor_name: str,
) -> None:
    task = asyncio.create_task(
        orchestrator.start(run_id, actor_type=actor_type, actor_id=actor_id, executor_name=executor_name)
    )

    def _log_result(completed: asyncio.Task[None]) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            exc = completed.exception()
            if exc is not None:
                log.exception("Run orchestration failed run_id=%s", run_id, exc_info=exc)

    task.add_done_callback(_log_result)


async def _fail_run_for_workspace_error(
    session: AsyncSession,
    *,
    run: Run,
    actor_type: str,
    actor_id: str | None,
) -> None:
    previous = run.status
    run.status = "FAILED"
    run.finished_at = run.finished_at or datetime.now(timezone.utc)
    session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_FAILED",
        actor_type=actor_type,
        actor_id=actor_id,
        tenant_id=run.tenant_id,
        payload={
            "previous": previous,
            "new": "FAILED",
            "workspace_status": run.workspace_status,
            "workspace_error": run.workspace_error,
        },
    )
    log.warning(
        "Run failed during launch due to workspace preparation error run_id=%s project_id=%s executor=%s workspace_status=%s workspace_error=%s",
        run.id,
        run.project_id,
        run.executor,
        run.workspace_status,
        run.workspace_error,
    )


async def launch_run_for_project(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    executor_name: str = "dummy",
    task_id: uuid.UUID | None = None,
    actor_type: str = "USER",
    actor_id: str | None = None,
    schedule: bool = True,
) -> Run:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
    if project is None:
        raise ValueError("Project not found")
    selected_task: Task | None = None
    run_summary: dict[str, object] | None = None
    branch_plan = None
    if task_id is not None:
        selected_task = await session.scalar(
            select(Task).where(
                Task.id == task_id,
                Task.project_id == project_id,
                Task.tenant_id == tenant_id,
                Task.deleted_at.is_(None),
            )
        )
        if selected_task is None:
            raise ValueError("Task not found")
        run_summary = _build_task_run_summary(selected_task)

    existing_running = await session.scalar(
        select(func.count()).select_from(
            select(Run.id)
            .where(Run.project_id == project_id, Run.tenant_id == tenant_id, Run.status == "RUNNING")
            .subquery()
        )
    ) or 0
    if existing_running > 0:
        raise ValueError(
            "A run is already in progress for this project; finish or cancel it before starting another."
        )

    if run_summary is None:
        run_summary = {}
    if (
        selected_task is not None
        and executor_name.lower() == "dummy"
        and not _has_task_file_scope(run_summary)
        and not _has_text_scope_hints(run_summary)
    ):
        # Keep dummy task-bound runs operable in local/dev environments even when
        # a manual task has not been scoped to explicit files yet.
        run_summary["expected_files"] = ["app.py", "index.html"]
    touched_files = _list_strings((run_summary or {}).get("target_files")) or _list_strings(
        (run_summary or {}).get("expected_files")
    )
    architecture_payload = await _resolve_architecture_payload(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        touched_files=touched_files,
    )
    run_summary["architecture_profile"] = architecture_payload
    run_summary["execution_contract"] = build_execution_contract(
        run_summary=run_summary,
        architecture_profile=architecture_payload,
        plan_snapshot=None,
    ).to_dict()

    project_repo = await get_project_repository(session, project_id=project_id, tenant_id=tenant_id)
    default_repo_branch = project_repo.default_branch if project_repo else None
    if selected_task is not None:
        branch_plan = resolve_task_branch_plan(selected_task, default_repo_branch)
    run = Run(
        project_id=project_id,
        tenant_id=tenant_id,
        status="QUEUED",
        executor=executor_name.lower(),
        summary=run_summary,
        branch_name=branch_plan.actual_branch_name if branch_plan else None,
    )
    session.add(run)
    await session.flush()
    if selected_task is not None:
        selected_task.run_id = run.id
        session.add(selected_task)
    await ensure_run_workspace(
        session,
        run,
        require_repo=run.executor in {"codex", "test"},
        repo_url=project_repo.repo_url if project_repo else None,
        repo_branch=branch_plan.base_branch if branch_plan else default_repo_branch,
        repo_provider=project_repo.provider if project_repo else None,
        repo_full_name=project_repo.repo_full_name if project_repo else None,
        repo_installation_id=project_repo.installation_id if project_repo else None,
    )
    if isinstance(run.summary, dict):
        run.summary = {
            **run.summary,
            "task_branch_strategy": branch_plan.strategy if branch_plan else "auto",
            "task_base_branch": branch_plan.base_branch if branch_plan else default_repo_branch,
            "task_requested_branch_name": branch_plan.requested_branch_name if branch_plan else None,
            "resolved_branch_name": run.branch_name,
        }
        session.add(run)
        await session.flush()
    await log_activity(
        session,
        project_id=project_id,
        entity_type="run",
        entity_id=run.id,
        action_type="run.created",
        metadata={
            "status": run.status,
            "executor": run.executor,
            "task_id": str(selected_task.id) if selected_task else None,
            "task_title": selected_task.title if selected_task else None,
            "branch_strategy": branch_plan.strategy if branch_plan else "auto",
            "base_branch": branch_plan.base_branch if branch_plan else default_repo_branch,
            "branch_name": run.branch_name,
        },
        actor=actor_id,
    )
    if selected_task is not None:
        await log_activity(
            session,
            project_id=project_id,
            entity_type="task",
            entity_id=selected_task.id,
            action_type="task.run.created",
            metadata={
                "run_id": str(run.id),
                "executor": run.executor,
                "status": run.status,
                "branch_strategy": branch_plan.strategy if branch_plan else "auto",
                "base_branch": branch_plan.base_branch if branch_plan else default_repo_branch,
                "branch_name": run.branch_name,
            },
            actor=actor_id,
        )
    await record_event(
        session,
        project_id=project_id,
        run_id=run.id,
        event_type="RUN_CREATED",
        actor_type=actor_type,
        actor_id=actor_id,
        tenant_id=tenant_id,
        task_id=selected_task.id if selected_task else None,
        payload={
            "status": run.status,
            "executor": run.executor,
            "task_id": str(selected_task.id) if selected_task else None,
            "task_title": selected_task.title if selected_task else None,
            "branch_strategy": branch_plan.strategy if branch_plan else "auto",
            "base_branch": branch_plan.base_branch if branch_plan else default_repo_branch,
            "branch_name": run.branch_name,
        },
    )
    log.info(
        "Run created project_id=%s run_id=%s executor=%s task_id=%s",
        project_id,
        run.id,
        run.executor,
        selected_task.id if selected_task else None,
    )

    if run.workspace_status == "ERROR":
        await _fail_run_for_workspace_error(
            session,
            run=run,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        await session.commit()
        await session.refresh(run)
        return run

    await capture_run_checkpoint(session, run, checkpoint_kind="baseline")
    await sync_run_resume_state(session, run)
    await session.commit()
    await session.refresh(run)

    bind = session.get_bind()
    is_sqlite = bind is not None and bind.dialect.name == "sqlite"
    run_id = run.id
    project_id = run.project_id

    if schedule:
        orchestrator = RunOrchestrator(SessionLocal, executor_name=run.executor)
        try:
            await orchestrator.bootstrap_in_session(
                session,
                run_id,
                actor_type=actor_type,
                actor_id=actor_id,
                executor_name=run.executor,
            )
        except Exception:
            await session.rollback()
            log.exception("Run bootstrap failed run_id=%s project_id=%s", run_id, project_id)
            raise
        await session.refresh(run)
        if not is_sqlite:
            _schedule_orchestrator_start(
                orchestrator,
                run_id=run_id,
                actor_type=actor_type,
                actor_id=actor_id,
                executor_name=run.executor,
            )
        else:
            log.info(
                "Run execution handoff deferred run_id=%s project_id=%s reason=sqlite_test_session",
                run_id,
                project_id,
            )

    return run
