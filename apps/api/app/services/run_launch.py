from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Project, ProjectBlueprint, ProjectGenesisRun, Run, Task, WorkItem
from app.db.session import SessionLocal
from app.schemas.architecture_profile import ArchitectureProfileSummaryOut
from app.schemas.project_contract import ProjectContractSummaryOut
from app.runtime.execution_contract import build_execution_contract
from app.runtime.orchestrator import RunOrchestrator
from app.services.activity_log import log_activity
from app.services.architecture_profile_service import summarize_architecture_profile
from app.services.event_log import record_event
from app.services.project_contract_service import summarize_project_contract
from app.services.repo_connector import get_project_repository
from app.services.foundation_readiness import build_foundation_readiness
from app.services.impact_analysis_loop import predict_pre_execution_impact
from app.services.requirement_memory import build_requirement_context_pack, compress_requirement_memory
from app.services.execution_intelligence import capture_pre_run_estimation_features
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
        "requirement_id": task.requirement_id or (task.derived_from_requirement_ids[0] if isinstance(task.derived_from_requirement_ids, list) and task.derived_from_requirement_ids else None),
        "requirement_ids": task.derived_from_requirement_ids if isinstance(task.derived_from_requirement_ids, list) else None,
        "task_source": task.source,
        "task_source_type": task.source_type,
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


def _resolve_repository_state(*, is_genesis_setup: bool, prior_runs: int) -> str:
    if is_genesis_setup:
        return "GENESIS"
    if prior_runs <= 1:
        return "EARLY_BUILD"
    return "ACTIVE_PRODUCT"


def _normalize_repository_state(value: object) -> str:
    raw = str(value or "").strip().upper()
    if raw in {"GENESIS", "EARLY_BUILD", "ACTIVE_PRODUCT", "PRODUCTION_CRITICAL", "LEGACY_COMPLEX"}:
        return raw
    return "ACTIVE_PRODUCT"


def _default_runtime_governance_mode(repository_state: str) -> str:
    state = _normalize_repository_state(repository_state)
    if state in {"GENESIS", "EARLY_BUILD", "ACTIVE_PRODUCT"}:
        return "stability"
    return "governed"


def _resolve_runtime_governance_mode(
    *,
    repository_state: str,
    has_preview_success: bool,
    active_product_default_mode: str = "stability",
    emergency_ship_mode_enabled: bool = False,
) -> str:
    if emergency_ship_mode_enabled or str(active_product_default_mode or "").strip().lower() == "emergency":
        return "emergency"
    state = _normalize_repository_state(repository_state)
    if state in {"GENESIS", "EARLY_BUILD"}:
        return "stability"
    if state == "ACTIVE_PRODUCT":
        preferred = str(active_product_default_mode or "").strip().lower()
        if preferred == "governed":
            return "governed" if has_preview_success else "stability"
        return "stability"
    return "governed"


async def _project_has_preview_success(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> bool:
    count = (
        await session.scalar(
            select(func.count())
            .select_from(WorkItem)
            .where(
                WorkItem.tenant_id == tenant_id,
                WorkItem.project_id == project_id,
                WorkItem.type == "PREVIEW_VALIDATE",
                WorkItem.status == "DONE",
            )
        )
    ) or 0
    return int(count) > 0


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


async def _resolve_project_contract_payload(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> dict[str, object]:
    try:
        summary = await summarize_project_contract(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
        )
    except Exception:
        log.warning(
            "Project contract summary unavailable during run launch project_id=%s tenant_id=%s",
            project_id,
            tenant_id,
            exc_info=True,
        )
        summary = ProjectContractSummaryOut(
            summary="Project contract unavailable during run launch.",
            assumptions_used=["Runtime enforcement fallback applied because project contract lookup failed."],
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
    settings = get_settings()
    previous = run.status
    target_status = "COMPLETED" if settings.runtime_never_fail_runs else "FAILED"
    run.status = target_status
    run.finished_at = run.finished_at or datetime.now(timezone.utc)
    if settings.runtime_never_fail_runs:
        summary = dict(run.summary or {})
        summary["degraded_completion"] = True
        summary["degraded_reason"] = "workspace_prepare_failed"
        summary["workspace_error"] = run.workspace_error
        run.summary = summary
    session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_DEGRADED" if settings.runtime_never_fail_runs else "RUN_FAILED",
        actor_type=actor_type,
        actor_id=actor_id,
        tenant_id=run.tenant_id,
        payload={
            "previous": previous,
            "new": target_status,
            "workspace_status": run.workspace_status,
            "workspace_error": run.workspace_error,
        },
    )
    if settings.runtime_never_fail_runs:
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="RUN_COMPLETED",
            actor_type=actor_type,
            actor_id=actor_id,
            tenant_id=run.tenant_id,
            payload={"final_status": "COMPLETED", "degraded": True, "reason": "workspace_prepare_failed"},
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
    executor_name: str = "codex",
    task_id: uuid.UUID | None = None,
    actor_type: str = "USER",
    actor_id: str | None = None,
    run_kind: str | None = None,
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

    blueprint = await session.scalar(
        select(ProjectBlueprint)
        .where(ProjectBlueprint.project_id == project_id, ProjectBlueprint.tenant_id == tenant_id)
        .order_by(ProjectBlueprint.created_at.desc())
    )
    active_statuses = ("QUEUED", "RUNNING")
    existing_active = await session.scalar(
        select(func.count()).select_from(
            select(Run.id)
            .where(Run.project_id == project_id, Run.tenant_id == tenant_id, Run.status.in_(active_statuses))
            .subquery()
        )
    ) or 0
    if existing_active > 0:
        raise ValueError(
            "A run is already in progress for this project; finish or cancel it before starting another."
        )
    is_genesis_setup = (run_kind or "").strip().lower() in {
        "genesis",
        "genesis_setup",
        "setup",
        "base_task",
        "base_setup",
        "foundation_setup",
    }
    if selected_task is not None:
        selected_source = str(selected_task.source or "").strip().lower()
        selected_source_type = str(selected_task.source_type or "").strip().lower()
        selected_category = str(selected_task.category or "").strip().lower()
        is_genesis_setup = is_genesis_setup or (
            selected_source == "genesis"
            or selected_source in {"base", "foundation"}
            or selected_source_type in {"genesis_setup", "base_task", "foundation_setup", "setup"}
            or selected_category == "setup"
        )
    existing_run_count = (
        await session.scalar(
            select(func.count())
            .select_from(Run)
            .where(
                Run.project_id == project_id,
                Run.tenant_id == tenant_id,
            )
        )
    ) or 0
    if not is_genesis_setup and not isinstance(project.project_intent_json, dict):
        # Backward-compatible bridge: legacy projects without guided onboarding metadata
        # still need deterministic intent defaults to launch scoped feature runs safely.
        project.project_intent_json = {
            "setup_experience": "legacy_auto",
            "architecture_mode": "guided",
            "repo_layout": "monorepo",
            "frontend_stack": "vue_vite",
            "backend_stack": "fastapi",
            "capabilities": [],
            "runtime_defaults": {
                "component_driven_frontend": True,
                "module_driven_backend": True,
            },
        }
        session.add(project)
    settings = get_settings()
    readiness_gate_enabled = bool(getattr(settings, "foundation_readiness_gate_enabled", False))
    if readiness_gate_enabled and blueprint is not None and blueprint.readiness_enforced and not is_genesis_setup:
        latest_genesis = await session.scalar(
            select(ProjectGenesisRun)
            .where(ProjectGenesisRun.project_id == project_id, ProjectGenesisRun.tenant_id == tenant_id)
            .order_by(ProjectGenesisRun.created_at.desc())
        )
        readiness_status = ""
        if latest_genesis is not None:
            validation = latest_genesis.validation if isinstance(latest_genesis.validation, dict) else {}
            readiness_status = str(validation.get("status") or "").upper()
        live_readiness = await build_foundation_readiness(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        live_readiness_status = str(live_readiness.get("status") or "").upper()
        effective_readiness_status = live_readiness_status or readiness_status
        if effective_readiness_status != "READY":
            missing = live_readiness.get("missing_prerequisites")
            missing_list = (
                ", ".join(str(item) for item in missing if isinstance(item, str) and item.strip())
                if isinstance(missing, list)
                else ""
            )
            next_step = str(live_readiness.get("recommended_next_step") or "").strip()
            detail_parts: list[str] = []
            if missing_list:
                detail_parts.append(f"missing: {missing_list}")
            if next_step:
                detail_parts.append(f"next: {next_step}")
            detail = " ".join(detail_parts).strip()
            base = "Foundation readiness is not READY; complete setup tasks before launching feature runs."
            raise ValueError(f"{base} {detail}".strip())

    if run_summary is None:
        run_summary = {}
    latest_prior_run = await session.scalar(
        select(Run)
        .where(
            Run.project_id == project_id,
            Run.tenant_id == tenant_id,
        )
        .order_by(Run.created_at.desc())
        .limit(1)
    )
    previous_repository_state = "GENESIS"
    if latest_prior_run is not None and isinstance(latest_prior_run.summary, dict):
        previous_repository_state = _normalize_repository_state(latest_prior_run.summary.get("repository_state"))
    prior_runs = existing_run_count
    current_repository_state = _resolve_repository_state(
        is_genesis_setup=is_genesis_setup,
        prior_runs=int(prior_runs),
    )
    preview_success = await _project_has_preview_success(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    run_summary["repository_state"] = current_repository_state
    run_summary["repository_state_previous"] = previous_repository_state
    run_summary["runtime_governance_mode"] = _resolve_runtime_governance_mode(
        repository_state=current_repository_state,
        has_preview_success=preview_success,
        active_product_default_mode=settings.runtime_governance_active_product_default_mode,
        emergency_ship_mode_enabled=bool(getattr(settings, "runtime_emergency_ship_mode_enabled", False)),
    )
    if isinstance(project.project_intent_json, dict):
        run_summary["project_intent"] = dict(project.project_intent_json)
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
    project_contract_payload = await _resolve_project_contract_payload(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    run_summary["project_contract"] = project_contract_payload
    run_summary["execution_contract"] = build_execution_contract(
        run_summary=run_summary,
        architecture_profile=architecture_payload,
        project_contract=project_contract_payload,
        plan_snapshot=None,
    ).to_dict()
    run_summary["impact_prediction"] = predict_pre_execution_impact(
        run_summary=run_summary,
        architecture_profile=architecture_payload,
    )

    project_repo = await get_project_repository(session, project_id=project_id, tenant_id=tenant_id)
    default_repo_branch = project_repo.default_branch if project_repo else None
    if selected_task is not None:
        branch_plan = resolve_task_branch_plan(selected_task, default_repo_branch)
    requirement_id = None
    if isinstance(run_summary, dict) and isinstance(run_summary.get("requirement_id"), str):
        candidate = str(run_summary.get("requirement_id")).strip()
        requirement_id = candidate or None
    run = Run(
        project_id=project_id,
        tenant_id=tenant_id,
        status="QUEUED",
        executor=executor_name.lower(),
        summary=run_summary,
        branch_name=branch_plan.actual_branch_name if branch_plan else None,
        requirement_id=requirement_id,
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
        repo_auth_strategy=project_repo.auth_strategy if project_repo else None,
    )
    if isinstance(run.summary, dict):
        if selected_task is not None:
            req_id = selected_task.requirement_id or (
                selected_task.derived_from_requirement_ids[0]
                if isinstance(selected_task.derived_from_requirement_ids, list) and selected_task.derived_from_requirement_ids
                else None
            )
            if req_id:
                try:
                    memory = await compress_requirement_memory(
                        session,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        requirement_id=req_id,
                    )
                    run.summary["requirement_context_pack"] = build_requirement_context_pack(memory)
                except Exception:
                    run.summary["requirement_context_pack"] = {
                        "requirement_id": req_id,
                    }
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
    await capture_pre_run_estimation_features(session, run=run)
    transitioned_to_stricter_mode = (
        previous_repository_state in {"GENESIS", "EARLY_BUILD"}
        and current_repository_state in {"ACTIVE_PRODUCT", "PRODUCTION_CRITICAL"}
        and previous_repository_state != current_repository_state
    )
    if transitioned_to_stricter_mode:
        await record_event(
            session,
            project_id=project_id,
            run_id=run.id,
            event_type="RUN_GOVERNANCE_TRANSITION",
            actor_type="SYSTEM",
            tenant_id=tenant_id,
            message=(
                f"Governance profile elevated from {previous_repository_state} to {current_repository_state}."
            ),
            payload={
                "from_repository_state": previous_repository_state,
                "to_repository_state": current_repository_state,
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
