from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ArchitectureProfileUpsert(BaseModel):
    status: str = "DRAFT"
    source: str = "MANUAL"
    summary: str | None = None
    profile_json: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    updated_by: str | None = None


class ArchitectureProfileSectionPatch(BaseModel):
    summary: str | None = None
    sections: dict[str, Any] = Field(default_factory=dict)
    updated_by: str | None = None


class ArchitectureProfileDeriveRequest(BaseModel):
    refresh_repo_map: bool = False
    bootstrap_if_missing: bool = False
    updated_by: str | None = None


class ArchitectureProfileBootstrapRequest(BaseModel):
    refresh_repo_map: bool = False
    created_by: str | None = None


class ArchitectureProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    status: str
    source: str
    version: int
    latest_source_run_id: uuid.UUID | None = None
    repo_full_name: str | None = None
    repo_default_branch: str | None = None
    summary: str | None = None
    profile_json: dict[str, Any] = Field(default_factory=dict)
    derived_json: dict[str, Any] = Field(default_factory=dict)
    last_derived_at: datetime | None = None
    created_by: str | None = None
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime


class ArchitectureProfileSummaryOut(BaseModel):
    profile_exists: bool = False
    profile_id: uuid.UUID | None = None
    status: str = "MISSING"
    source: str | None = None
    version: int | None = None
    summary: str | None = None
    repo_full_name: str | None = None
    repo_default_branch: str | None = None
    repo_layout_label: str = "Repository"
    monorepo: bool = False
    package_count: int = 0
    packages: list[str] = Field(default_factory=list)
    boundary_count: int = 0
    protected_zone_count: int = 0
    protected_zones: list[str] = Field(default_factory=list)
    safe_zone_count: int = 0
    safe_zones: list[str] = Field(default_factory=list)
    command_coverage_count: int = 0
    commands: list[str] = Field(default_factory=list)
    validation_recipe_count: int = 0
    derived_ready: bool = False
    last_derived_at: datetime | None = None
    execution_slice: list[str] = Field(default_factory=list)
    validation_recipes: list[str] = Field(default_factory=list)
    protected_zones_touched: list[str] = Field(default_factory=list)
    safe_zones_touched: list[str] = Field(default_factory=list)
    assumptions_used: list[str] = Field(default_factory=list)
    derivation_confidence: str = "LOW"
    derived_from: list[str] = Field(default_factory=list)
