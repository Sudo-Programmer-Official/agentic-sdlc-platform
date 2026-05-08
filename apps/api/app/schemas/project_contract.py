from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProjectContractUpsert(BaseModel):
    status: str = "DRAFT"
    source: str = "MANUAL"
    summary: str | None = None
    contract_json: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    updated_by: str | None = None


class ProjectContractSectionPatch(BaseModel):
    summary: str | None = None
    sections: dict[str, Any] = Field(default_factory=dict)
    updated_by: str | None = None


class ProjectContractBootstrapRequest(BaseModel):
    created_by: str | None = None


class ProjectContractDeriveRequest(BaseModel):
    bootstrap_if_missing: bool = False
    updated_by: str | None = None


class ProjectContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    status: str
    source: str
    version: int
    summary: str | None = None
    contract_json: dict[str, Any] = Field(default_factory=dict)
    derived_json: dict[str, Any] = Field(default_factory=dict)
    last_derived_at: datetime | None = None
    created_by: str | None = None
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectContractSummaryOut(BaseModel):
    profile_exists: bool = False
    profile_id: uuid.UUID | None = None
    status: str = "MISSING"
    source: str | None = None
    version: int | None = None
    summary: str | None = None
    enforcement_enabled: bool = False
    enforcement_mode: str = "off"
    brand_token_count: int = 0
    brand_tokens: list[str] = Field(default_factory=list)
    component_count: int = 0
    components: list[str] = Field(default_factory=list)
    rule_count: int = 0
    active_rules: list[str] = Field(default_factory=list)
    blocked_patterns: list[str] = Field(default_factory=list)
    allowed_css_var_prefixes: list[str] = Field(default_factory=list)
    allowed_hex_values: list[str] = Field(default_factory=list)
    assumptions_used: list[str] = Field(default_factory=list)
    derived_ready: bool = False
    last_derived_at: datetime | None = None
