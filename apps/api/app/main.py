from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import router as v1_router
from app.api.v1.persistence import router as store_router
from app.api.v1.trace_artifact import router as trace_router
from app.api.v1.generation import router as gen_router
from app.api.v1.impact import router as impact_router
from app.api.v1.activity import router as activity_router
from app.api.v1.snapshot import router as snapshot_router
from app.api.v1.health import router as health_router
from app.api.v1.lifecycle_score import router as lifecycle_router
from app.api.v1.lifecycle_history import router as lifecycle_history_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    # CORS (frontend at prompt2pr.com calls api.prompt2pr.com)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://www.prompt2pr.com",
            "https://prompt2pr.com",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", include_in_schema=False)
    def health() -> dict:
        return {"status": "ok"}

    @app.on_event("startup")
    async def on_startup() -> None:
        # Placeholder for startup hooks (DB connections, caches, etc.)
        return None

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
