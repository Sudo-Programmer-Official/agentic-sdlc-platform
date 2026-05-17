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


class DesignContractIdentity(BaseModel):
    name: str = "Product"
    tone: str = "technical_minimal_premium"
    personality: str = "confident_operational_clean"


class DesignContractTypography(BaseModel):
    heading_font: str = "Inter"
    body_font: str = "Inter"
    radius_scale: str = "soft"
    density: str = "comfortable"


class DesignContractLayout(BaseModel):
    spacing: str = "airy"
    container_width: str = "wide"
    visual_weight: str = "balanced"
    hero_style: str = "immersive"


class DesignContractTokenRegistry(BaseModel):
    colors: dict[str, str] = Field(default_factory=dict)
    spacing: dict[str, str] = Field(default_factory=dict)
    radius: dict[str, str] = Field(default_factory=dict)
    motion: dict[str, str] = Field(default_factory=dict)
    elevation: dict[str, str] = Field(default_factory=dict)


class DesignContractOut(BaseModel):
    experience_blueprint: str = "premium_saas"
    identity: DesignContractIdentity = Field(default_factory=DesignContractIdentity)
    tokens: dict[str, str] = Field(default_factory=dict)
    token_registry: DesignContractTokenRegistry = Field(default_factory=DesignContractTokenRegistry)
    allowed_components: list[str] = Field(default_factory=list)
    typography: DesignContractTypography = Field(default_factory=DesignContractTypography)
    components: dict[str, Any] = Field(default_factory=dict)
    layout: DesignContractLayout = Field(default_factory=DesignContractLayout)


class DesignContractUpsert(BaseModel):
    experience_blueprint: str | None = None
    identity: DesignContractIdentity | None = None
    tokens: dict[str, str] = Field(default_factory=dict)
    token_registry: DesignContractTokenRegistry | None = None
    allowed_components: list[str] = Field(default_factory=list)
    typography: DesignContractTypography | None = None
    components: dict[str, Any] = Field(default_factory=dict)
    layout: DesignContractLayout | None = None
    updated_by: str | None = None
