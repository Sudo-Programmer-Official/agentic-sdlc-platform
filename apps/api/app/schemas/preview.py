from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProjectPreviewProfileUpsert(BaseModel):
    enabled: bool = True
    mode: str = "local"
    frontend_root: str | None = None
    backend_root: str | None = None
    compose_file: str | None = None
    frontend_build_command: str | None = None
    backend_build_command: str | None = None
    frontend_start_command: str | None = None
    backend_start_command: str | None = None
    frontend_healthcheck_path: str | None = "/"
    backend_healthcheck_path: str | None = "/"
    frontend_port: int | None = None
    backend_port: int | None = None
    env_overrides: dict[str, str] = Field(default_factory=dict)
    ttl_hours: int = 24
    max_previews_per_project: int | None = None
    created_by: str | None = None


class ProjectPreviewProfileOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    enabled: bool
    mode: str
    frontend_root: str | None = None
    backend_root: str | None = None
    compose_file: str | None = None
    frontend_build_command: str | None = None
    backend_build_command: str | None = None
    frontend_start_command: str | None = None
    backend_start_command: str | None = None
    frontend_healthcheck_path: str | None = None
    backend_healthcheck_path: str | None = None
    frontend_port: int | None = None
    backend_port: int | None = None
    env_overrides: dict[str, str] = Field(default_factory=dict)
    ttl_hours: int
    max_previews_per_project: int | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RunPreviewLaunchRequest(BaseModel):
    reuse_if_healthy: bool = True


class RunPreviewServiceRef(BaseModel):
    kind: str
    status: str
    url: str | None = None
    pid: int | None = None
    port: int | None = None
    root: str | None = None
    start_command: str | None = None
    build_command: str | None = None
    healthcheck_path: str | None = None
    log_path: str | None = None
    last_error: str | None = None


class RunPreviewOut(BaseModel):
    run_id: uuid.UUID
    project_id: uuid.UUID
    status: str
    mode: str = "local"
    branch_name: str | None = None
    reusable: bool = False
    launched_at: datetime | None = None
    expires_at: datetime | None = None
    ttl_hours: int = 24
    preview_url: str | None = None
    frontend: RunPreviewServiceRef | None = None
    backend: RunPreviewServiceRef | None = None
    compose_file: str | None = None
    reuse_reason: str | None = None
    requires_verification: bool = False
    verification_note: str | None = None
    profile_configured: bool = False
    repository_connected: bool = False
