from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.routes import router as v1_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    @app.get("/health", include_in_schema=False)
    def health() -> dict:
        return {"status": "ok"}

    @app.on_event("startup")
    async def on_startup() -> None:
        # Placeholder for startup hooks (DB connections, caches, etc.)
        return None

    app.include_router(v1_router, prefix=settings.api_prefix)
    return app


app = create_app()
