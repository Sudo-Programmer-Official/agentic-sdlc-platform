from __future__ import annotations

import logging
import uuid

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
from app.api.v1.snapshot import router as snapshot_router
from app.api.v1.health import router as health_router, public_router as public_health_router
from app.api.v1.lifecycle_score import router as lifecycle_router, public_router as public_lifecycle_router
from app.api.v1.lifecycle_history import router as lifecycle_history_router, public_router as public_lifecycle_history_router
from app.core.config import DEFAULT_DATABASE_URL, get_settings
from app.services.build_info import get_build_history, get_current_build_info
from app.startup import run_startup_migrations


def create_app() -> FastAPI:
    settings = get_settings()

    # Safety guard: external mode required outside local environments
    if settings.env.lower() != "local" and settings.runtime_mode.lower() != "external":
        raise RuntimeError("runtime_mode must be 'external' when env is not local.")
    if settings.env.lower() != "local" and settings.database_url == DEFAULT_DATABASE_URL:
        raise RuntimeError("DATABASE_URL must be set when env is not local.")

    app = FastAPI(title=settings.app_name)
    log = logging.getLogger("app")

    # CORS (frontend at prompt2pr.com calls api.prompt2pr.com; localhost during dev)
    prompt2pr_origin_regex = r"https://(www\.)?prompt2pr\.com"
    local_origin_regex = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_origin_regex=f"{prompt2pr_origin_regex}|{local_origin_regex}",
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

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request, exc):
        """Log and surface a short error id for faster prod debugging."""
        error_id = uuid.uuid4().hex[:8]
        log.exception("Unhandled error id=%s path=%s", error_id, request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_server_error", "error_id": error_id},
        )

    @app.on_event("startup")
    async def on_startup() -> None:
        build = get_current_build_info()
        log.info(
            "Starting API build=%s sha=%s env=%s prefix=%s runtime_mode=%s",
            build.get("version"),
            build.get("short_sha"),
            settings.env,
            settings.api_prefix,
            settings.runtime_mode,
        )
        await run_startup_migrations()

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
    app.include_router(public_health_router, prefix=settings.api_prefix)
    app.include_router(public_lifecycle_router, prefix=settings.api_prefix)
    app.include_router(public_lifecycle_history_router, prefix=settings.api_prefix)
    app.include_router(v1_router, prefix=settings.api_prefix)
    app.include_router(store_router, prefix=settings.api_prefix)
    app.include_router(trace_router, prefix=settings.api_prefix)
    app.include_router(gen_router, prefix=settings.api_prefix)
    app.include_router(impact_router, prefix=settings.api_prefix)
    app.include_router(activity_router, prefix=settings.api_prefix)
    app.include_router(snapshot_router, prefix=settings.api_prefix)
    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(lifecycle_router, prefix=settings.api_prefix)
    app.include_router(lifecycle_history_router, prefix=settings.api_prefix)
    return app


app = create_app()
