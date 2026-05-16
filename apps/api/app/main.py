from __future__ import annotations

import logging
import os
import re
import uuid
import asyncio

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import router as v1_router
from app.api.v1.persistence import router as store_router, public_router as public_store_router
from app.api.v1.trace_artifact import router as trace_router, public_router as public_trace_router
from app.api.v1.generation import router as gen_router, public_router as public_gen_router
from app.api.v1.impact import router as impact_router, public_router as public_impact_router
from app.api.v1.activity import router as activity_router, public_router as public_activity_router
from app.api.v1.mission_control import public_router as public_mission_control_router
from app.api.v1.operator import public_router as public_operator_router
from app.api.v1.repo_map import public_router as public_repo_map_router
from app.api.v1.architecture_profile import router as architecture_profile_router, public_router as public_architecture_profile_router
from app.api.v1.project_contract import router as project_contract_router, public_router as public_project_contract_router
from app.api.v1.snapshot import router as snapshot_router
from app.api.v1.health import router as health_router, public_router as public_health_router
from app.api.v1.lifecycle_score import router as lifecycle_router, public_router as public_lifecycle_router
from app.api.v1.lifecycle_history import router as lifecycle_history_router, public_router as public_lifecycle_history_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.ai_ops import router as ai_ops_router
from app.core.config import DEFAULT_DATABASE_URL, get_settings
from app.services.build_info import get_build_history, get_current_build_info
from app.services.runtime_env_diagnostics import collect_runtime_startup_diagnostics
from app.services.requirement_refresh_daemon import run_requirement_memory_daemon, shutdown_daemon
from app.services.memory_synthesizer import run_memory_synthesizer_daemon, shutdown_memory_synthesizer
from app.services.deployment_runtime import run_deployment_runtime_daemon, shutdown_deployment_runtime
from app.services.workspace_ops_daemon import run_workspace_ops_daemon, shutdown_workspace_ops
from app.startup import run_startup_migrations


def create_app() -> FastAPI:
    settings = get_settings()

    # Safety guard: external mode required outside local environments
    if settings.env.lower() != "local" and settings.runtime_mode.lower() != "external":
        raise RuntimeError("runtime_mode must be 'external' when env is not local.")
    if settings.env.lower() != "local" and not os.getenv("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL must be set when env is not local.")
    if settings.env.lower() != "local" and settings.database_url == DEFAULT_DATABASE_URL:
        raise RuntimeError("DATABASE_URL must be set when env is not local.")

    app = FastAPI(title=settings.app_name)
    log = logging.getLogger("app")

    # CORS (frontend at prompt2pr.com calls api.prompt2pr.com; localhost during dev)
    prompt2pr_origin_regex = r"https://(www\.)?prompt2pr\.com"
    local_origin_regex = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
    allowed_origin_pattern = re.compile(f"{prompt2pr_origin_regex}|{local_origin_regex}")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_origin_regex=allowed_origin_pattern.pattern,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", include_in_schema=False)
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/version", include_in_schema=False)
    def version() -> dict:
        return get_current_build_info()

    @app.get("/version/history", include_in_schema=False)
    def version_history() -> dict:
        current = get_current_build_info()
        return {"current": current, "history": get_build_history()}

    def _error_cors_headers(origin: str | None) -> dict[str, str]:
        if not origin:
            return {}
        if origin in settings.allowed_origins or allowed_origin_pattern.fullmatch(origin):
            return {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
                "Vary": "Origin",
            }
        return {}

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request, exc):
        """Log and surface a short error id for faster prod debugging."""
        error_id = uuid.uuid4().hex[:8]
        log.exception(
            "Unhandled error id=%s path=%s type=%s error=%s",
            error_id,
            request.url.path,
            type(exc).__name__,
            exc,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            headers=_error_cors_headers(request.headers.get("origin")),
            content={"error": "internal_server_error", "error_id": error_id},
        )

    @app.on_event("startup")
    async def on_startup() -> None:
        build = get_current_build_info()
        diagnostics = collect_runtime_startup_diagnostics(settings.runtime_mode, settings.runtime_git_auth_mode)
        log.info(
            "Starting API build=%s sha=%s env=%s prefix=%s runtime_mode=%s runtime_git_auth_mode=%s",
            build.get("version"),
            build.get("short_sha"),
            settings.env,
            settings.api_prefix,
            diagnostics.runtime_mode,
            diagnostics.runtime_git_auth_mode,
        )
        if diagnostics.git_binary:
            log.info("Runtime tool availability git=%s", diagnostics.git_binary)
        else:
            log.warning("Runtime tool availability git=missing repo-backed runs will fail until git is installed")
        if diagnostics.runtime_git_auth_mode == "ssh":
            if diagnostics.ssh_binary:
                log.info("Runtime tool availability ssh=%s", diagnostics.ssh_binary)
            else:
                log.warning("Runtime tool availability ssh=missing SSH-authenticated repo runs will fail until ssh is installed")
        log.info(
            "GitHub integration env app_id_present=%s private_key_present=%s webhook_secret_present=%s",
            diagnostics.github_app_id_present,
            diagnostics.github_private_key_present,
            diagnostics.github_webhook_secret_present,
        )
        log.info("Startup phase=migrations begin")
        try:
            await run_startup_migrations()
        except Exception:
            log.exception("Application startup failed during phase=migrations")
            raise
        log.info("Startup phase=migrations complete")
        app.state.requirement_refresh_stop_event = None
        app.state.requirement_refresh_task = None
        app.state.memory_synthesizer_stop_event = None
        app.state.memory_synthesizer_task = None
        app.state.deployment_runtime_stop_event = None
        app.state.deployment_runtime_task = None
        app.state.workspace_ops_stop_event = None
        app.state.workspace_ops_task = None
        if settings.requirement_memory_refresh_enabled:
            stop_event = asyncio.Event()
            task = asyncio.create_task(run_requirement_memory_daemon(stop_event))
            app.state.requirement_refresh_stop_event = stop_event
            app.state.requirement_refresh_task = task
            log.info(
                "Requirement memory daemon enabled interval_seconds=%s",
                settings.requirement_memory_refresh_interval_seconds,
            )
        if settings.memory_synthesizer_enabled:
            stop_event = asyncio.Event()
            task = asyncio.create_task(run_memory_synthesizer_daemon(stop_event))
            app.state.memory_synthesizer_stop_event = stop_event
            app.state.memory_synthesizer_task = task
            log.info(
                "Memory synthesizer daemon enabled interval_seconds=%s",
                settings.memory_synthesizer_interval_seconds,
            )
        if settings.deployment_runtime_enabled:
            stop_event = asyncio.Event()
            task = asyncio.create_task(run_deployment_runtime_daemon(stop_event))
            app.state.deployment_runtime_stop_event = stop_event
            app.state.deployment_runtime_task = task
            log.info(
                "Deployment runtime daemon enabled interval_seconds=%s",
                settings.deployment_runtime_interval_seconds,
            )
        if settings.workspace_ops_daemon_enabled:
            stop_event = asyncio.Event()
            task = asyncio.create_task(run_workspace_ops_daemon(stop_event))
            app.state.workspace_ops_stop_event = stop_event
            app.state.workspace_ops_task = task
            log.info(
                "Workspace ops daemon enabled interval_seconds=%s window_days=%s",
                settings.workspace_ops_daemon_interval_seconds,
                settings.workspace_ops_window_days,
            )

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        await shutdown_daemon(
            getattr(app.state, "requirement_refresh_task", None),
            getattr(app.state, "requirement_refresh_stop_event", None),
        )
        await shutdown_memory_synthesizer(
            getattr(app.state, "memory_synthesizer_task", None),
            getattr(app.state, "memory_synthesizer_stop_event", None),
        )
        await shutdown_deployment_runtime(
            getattr(app.state, "deployment_runtime_task", None),
            getattr(app.state, "deployment_runtime_stop_event", None),
        )
        await shutdown_workspace_ops(
            getattr(app.state, "workspace_ops_task", None),
            getattr(app.state, "workspace_ops_stop_event", None),
        )

    # Register the DB-backed public surface before the legacy v1 router so
    # overlapping /projects/... and /runs/... paths resolve to the current system.
    app.include_router(public_store_router, prefix=settings.api_prefix)
    app.include_router(public_trace_router, prefix=settings.api_prefix)
    app.include_router(public_gen_router, prefix=settings.api_prefix)
    app.include_router(public_impact_router, prefix=settings.api_prefix)
    app.include_router(public_activity_router, prefix=settings.api_prefix)
    app.include_router(public_mission_control_router, prefix=settings.api_prefix)
    app.include_router(public_operator_router, prefix=settings.api_prefix)
    app.include_router(public_repo_map_router, prefix=settings.api_prefix)
    app.include_router(public_architecture_profile_router, prefix=settings.api_prefix)
    app.include_router(public_project_contract_router, prefix=settings.api_prefix)
    app.include_router(public_health_router, prefix=settings.api_prefix)
    app.include_router(public_lifecycle_router, prefix=settings.api_prefix)
    app.include_router(public_lifecycle_history_router, prefix=settings.api_prefix)
    app.include_router(v1_router, prefix=settings.api_prefix)
    app.include_router(store_router, prefix=settings.api_prefix)
    app.include_router(trace_router, prefix=settings.api_prefix)
    app.include_router(gen_router, prefix=settings.api_prefix)
    app.include_router(impact_router, prefix=settings.api_prefix)
    app.include_router(activity_router, prefix=settings.api_prefix)
    app.include_router(architecture_profile_router, prefix=settings.api_prefix)
    app.include_router(project_contract_router, prefix=settings.api_prefix)
    app.include_router(snapshot_router, prefix=settings.api_prefix)
    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(lifecycle_router, prefix=settings.api_prefix)
    app.include_router(lifecycle_history_router, prefix=settings.api_prefix)
    app.include_router(knowledge_router, prefix=settings.api_prefix)
    app.include_router(ai_ops_router, prefix=settings.api_prefix)
    return app


app = create_app()
