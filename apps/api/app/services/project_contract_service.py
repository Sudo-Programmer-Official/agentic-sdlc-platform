from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ProjectContract, ProjectRepository
from app.schemas.project_contract import (
    DesignContractOut,
    DesignContractUpsert,
    ProjectContractSummaryOut,
)

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _normalize_token_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    if not cleaned:
        return ""
    return cleaned


def _normalize_css_var(value: str) -> str:
    cleaned = _normalize_token_name(value)
    if not cleaned:
        return ""
    return cleaned if cleaned.startswith("--") else f"--{cleaned}"


def _unique(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen


def _deep_merge(existing: Any, incoming: Any, *, preserve_existing_scalars: bool = True) -> Any:
    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged = {key: value for key, value in existing.items()}
        for key, value in incoming.items():
            if key in merged:
                merged[key] = _deep_merge(
                    merged[key],
                    value,
                    preserve_existing_scalars=preserve_existing_scalars,
                )
            else:
                merged[key] = value
        return merged
    if isinstance(existing, list) and isinstance(incoming, list):
        if all(isinstance(item, str) for item in existing + incoming):
            return _unique([*existing, *incoming] if preserve_existing_scalars else [*incoming, *existing])
        merged = list(existing)
        for item in incoming:
            if item not in merged:
                merged.append(item)
        return merged
    if preserve_existing_scalars:
        if existing in (None, "", [], {}):
            return incoming
        return existing
    if incoming is None:
        return existing
    return incoming


def _coerce_brand_tokens(contract_json: dict[str, Any]) -> dict[str, str]:
    brand_kit = contract_json.get("brand_kit")
    if not isinstance(brand_kit, dict):
        return {}
    tokens = brand_kit.get("tokens")
    normalized: dict[str, str] = {}
    if isinstance(tokens, dict):
        for name, value in tokens.items():
            if not isinstance(name, str) or not isinstance(value, str):
                continue
            key = _normalize_token_name(name)
            val = value.strip()
            if key and val:
                normalized[key] = val
        return normalized
    if isinstance(tokens, list):
        for item in tokens:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            if isinstance(name, str) and isinstance(value, str):
                key = _normalize_token_name(name)
                val = value.strip()
                if key and val:
                    normalized[key] = val
    return normalized


def _coerce_components(contract_json: dict[str, Any]) -> list[str]:
    design_system = contract_json.get("design_system")
    if not isinstance(design_system, dict):
        return []
    components = design_system.get("components")
    values: list[str] = []
    if isinstance(components, list):
        for item in components:
            if isinstance(item, str) and item.strip():
                values.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    values.append(name.strip())
    return _unique(values)


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _normalize_enforcement_mode(value: Any, *, enabled: bool) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"off", "warn", "strict"}:
            return normalized
    return "warn" if enabled else "off"


def _build_derived_contract(contract_json: dict[str, Any]) -> dict[str, Any]:
    tokens = _coerce_brand_tokens(contract_json)
    components = _coerce_components(contract_json)
    design_system = contract_json.get("design_system") if isinstance(contract_json.get("design_system"), dict) else {}
    enforcement = contract_json.get("enforcement") if isinstance(contract_json.get("enforcement"), dict) else {}
    rules = design_system.get("rules") if isinstance(design_system.get("rules"), dict) else {}

    enabled = bool(enforcement.get("enabled", rules.get("enabled", False)))
    configured_mode = enforcement.get("mode", rules.get("mode"))
    enforcement_mode = _normalize_enforcement_mode(configured_mode, enabled=enabled)
    enabled = enforcement_mode != "off"
    disallow_inline_styles = bool(enforcement.get("disallow_inline_styles", rules.get("disallow_inline_styles", False)))
    enforce_color_tokens = bool(enforcement.get("enforce_color_tokens", rules.get("enforce_color_tokens", False)))
    require_known_css_variables = bool(
        enforcement.get("require_known_css_variables", rules.get("require_known_css_variables", False))
    )

    explicit_prefixes = _coerce_string_list(enforcement.get("allowed_css_var_prefixes")) or _coerce_string_list(
        design_system.get("token_prefixes")
    )
    token_vars = [_normalize_css_var(token_name) for token_name in tokens.keys()]
    token_vars = [item for item in token_vars if item]

    derived_prefixes: list[str] = []
    for token_var in token_vars:
        body = token_var[2:]
        first = body.split("-", maxsplit=1)[0]
        if first:
            derived_prefixes.append(f"--{first}-")

    allowed_css_var_prefixes = _unique(
        [_normalize_css_var(item) for item in explicit_prefixes if _normalize_css_var(item)]
        + derived_prefixes
    )
    blocked_patterns = _unique(
        _coerce_string_list(enforcement.get("blocked_patterns"))
        or _coerce_string_list(design_system.get("blocked_patterns"))
    )
    explicit_allowed_hex_values = sorted(
        {
            value.strip().lower()
            for value in _coerce_string_list(enforcement.get("allowed_hex_values"))
            if isinstance(value, str) and _HEX_RE.match(value.strip())
        }
    )
    allowed_hex_values = explicit_allowed_hex_values or sorted(
        {value.lower() for value in tokens.values() if isinstance(value, str) and _HEX_RE.match(value.strip())}
    )
    active_rules: list[str] = []
    if enabled and disallow_inline_styles:
        active_rules.append("disallow_inline_styles")
    if enabled and enforce_color_tokens:
        active_rules.append("enforce_color_tokens")
    if enabled and require_known_css_variables and allowed_css_var_prefixes:
        active_rules.append("require_known_css_variables")
    if enabled and blocked_patterns:
        active_rules.append("blocked_patterns")
    if enabled and components:
        active_rules.append("preferred_components")

    return {
        "summary_cards": {
            "brand_token_count": len(tokens),
            "component_count": len(components),
            "rule_count": len(active_rules),
        },
        "brand_tokens": tokens,
        "components": components,
        "enforcement": {
            "enabled": enabled,
            "mode": enforcement_mode,
            "active_rules": active_rules,
            "disallow_inline_styles": disallow_inline_styles,
            "enforce_color_tokens": enforce_color_tokens,
            "require_known_css_variables": require_known_css_variables,
            "blocked_patterns": blocked_patterns,
            "allowed_css_var_prefixes": allowed_css_var_prefixes,
            "allowed_hex_values": allowed_hex_values,
            "preferred_components": components,
        },
    }


def _build_bootstrap_contract(project: Project, repo: ProjectRepository | None) -> tuple[dict[str, Any], str]:
    contract_json = {
        "brand_kit": {
            "tokens": {
                "brand-primary": "#2563eb",
                "brand-accent": "#ec4899",
                "surface-background": "#f8fafc",
                "text-primary": "#0f172a",
            },
            "typography": {
                "heading_family": "system-ui",
                "body_family": "system-ui",
            },
        },
        "design_system": {
            "components": ["SiteHeader", "HeroSection", "FooterSection", "PrimaryButton"],
            "token_prefixes": ["--brand-", "--surface-", "--text-"],
            "blocked_patterns": ["style=\""],
            "rules": {
                "enabled": True,
                "disallow_inline_styles": True,
                "enforce_color_tokens": True,
                "require_known_css_variables": False,
            },
        },
        "system_architecture": {
            "delivery": {
                "branch_strategy": "run_branch_then_pr",
                "default_branch": repo.default_branch if repo else "main",
            },
            "notes": f"{project.name} should keep UI changes aligned with brand tokens and approved components.",
        },
        "enforcement": {
            "enabled": True,
            "mode": "warn",
        },
        "design_contract": {
            "experience_blueprint": "premium_saas",
            "identity": {
                "name": project.name,
                "tone": "technical_minimal_premium",
                "personality": "confident_operational_clean",
            },
            "tokens": {
                "primary": "#2563eb",
                "surface": "#f8fafc",
                "accent": "#ec4899",
                "success": "#22c55e",
                "text_primary": "#0f172a",
            },
            "typography": {
                "heading_font": "Inter",
                "body_font": "Inter",
                "radius_scale": "soft",
                "density": "comfortable",
            },
            "token_registry": {
                "colors": {
                    "primary": "#2563eb",
                    "surface": "#f8fafc",
                    "accent": "#ec4899",
                    "success": "#22c55e",
                    "text_primary": "#0f172a",
                },
                "spacing": {
                    "xs": "0.25rem",
                    "sm": "0.5rem",
                    "md": "1rem",
                    "lg": "1.5rem",
                    "xl": "2rem",
                },
                "radius": {"sm": "0.375rem", "md": "0.5rem", "lg": "0.75rem", "xl": "1rem"},
                "motion": {"fast": "120ms", "base": "200ms", "slow": "320ms"},
                "elevation": {"sm": "shadow-sm", "md": "shadow", "lg": "shadow-lg"},
            },
            "allowed_components": ["HeroSection", "DashboardShell", "MetricCard", "Timeline", "PrimaryButton"],
            "components": {
                "buttons": {"style": "glass", "radius": "xl", "shadow": "soft"},
                "registry": ["HeroSection", "DashboardShell", "MetricCard", "Timeline", "PrimaryButton"],
            },
            "layout": {
                "spacing": "airy",
                "container_width": "wide",
                "visual_weight": "balanced",
                "hero_style": "immersive",
            },
        },
    }
    summary = (
        f"{project.name} project contract enforces brand tokens and design-system conventions for bounded UI delivery."
    )
    return contract_json, summary


def _assumptions_from_contract(contract_json: dict[str, Any]) -> list[str]:
    assumptions: list[str] = []
    system_architecture = contract_json.get("system_architecture")
    if isinstance(system_architecture, dict):
        delivery = system_architecture.get("delivery")
        if isinstance(delivery, dict):
            branch_strategy = delivery.get("branch_strategy")
            if isinstance(branch_strategy, str) and branch_strategy.strip():
                assumptions.append(f"Branch strategy: {branch_strategy.strip()}")
            default_branch = delivery.get("default_branch")
            if isinstance(default_branch, str) and default_branch.strip():
                assumptions.append(f"Default branch: {default_branch.strip()}")
        notes = system_architecture.get("notes")
        if isinstance(notes, str) and notes.strip():
            assumptions.append(notes.strip())
    return assumptions[:6]


def _build_summary(
    *,
    profile_exists: bool,
    profile_id: uuid.UUID | None,
    status: str,
    source: str | None,
    version: int | None,
    summary: str | None,
    contract_json: dict[str, Any],
    derived_json: dict[str, Any],
    last_derived_at: datetime | None,
) -> ProjectContractSummaryOut:
    enforcement = derived_json.get("enforcement") if isinstance(derived_json.get("enforcement"), dict) else {}
    tokens = derived_json.get("brand_tokens") if isinstance(derived_json.get("brand_tokens"), dict) else {}
    components = derived_json.get("components") if isinstance(derived_json.get("components"), list) else []
    active_rules = _coerce_string_list(enforcement.get("active_rules"))
    blocked_patterns = _coerce_string_list(enforcement.get("blocked_patterns"))
    prefixes = _coerce_string_list(enforcement.get("allowed_css_var_prefixes"))
    allowed_hex_values = _coerce_string_list(enforcement.get("allowed_hex_values"))
    enforcement_mode = _normalize_enforcement_mode(
        enforcement.get("mode"),
        enabled=bool(enforcement.get("enabled")),
    )
    return ProjectContractSummaryOut(
        profile_exists=profile_exists,
        profile_id=profile_id,
        status=status,
        source=source,
        version=version,
        summary=summary,
        enforcement_enabled=bool(enforcement.get("enabled")),
        enforcement_mode=enforcement_mode,
        brand_token_count=len(tokens),
        brand_tokens=list(tokens.keys())[:12],
        component_count=len(components),
        components=[item for item in components if isinstance(item, str)][:12],
        rule_count=len(active_rules),
        active_rules=active_rules[:12],
        blocked_patterns=blocked_patterns[:8],
        allowed_css_var_prefixes=prefixes[:8],
        allowed_hex_values=allowed_hex_values[:8],
        assumptions_used=_assumptions_from_contract(contract_json),
        derived_ready=bool(derived_json),
        last_derived_at=last_derived_at,
    )


async def _get_project(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> Project:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
    if project is None:
        raise ValueError("Project not found")
    return project


async def _get_profile(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ProjectContract | None:
    return await session.scalar(
        select(ProjectContract).where(
            ProjectContract.project_id == project_id,
            ProjectContract.tenant_id == tenant_id,
        )
    )


def _runtime_meta_from_profile(profile: ProjectContract) -> dict[str, Any]:
    contract_json = profile.contract_json if isinstance(profile.contract_json, dict) else {}
    derived_json = profile.derived_json if isinstance(profile.derived_json, dict) else {}
    summary = _build_summary(
        profile_exists=True,
        profile_id=profile.id,
        status=profile.status,
        source=profile.source,
        version=profile.version,
        summary=profile.summary,
        contract_json=contract_json,
        derived_json=derived_json,
        last_derived_at=profile.last_derived_at,
    )
    return {
        "profile_id": str(profile.id),
        "status": profile.status,
        "source": profile.source,
        "version": profile.version,
        "summary": summary.model_dump(mode="json"),
        "brand_kit": contract_json.get("brand_kit") if isinstance(contract_json.get("brand_kit"), dict) else {},
        "design_system": contract_json.get("design_system") if isinstance(contract_json.get("design_system"), dict) else {},
        "design_contract": contract_json.get("design_contract") if isinstance(contract_json.get("design_contract"), dict) else {},
        "enforcement": derived_json.get("enforcement") if isinstance(derived_json.get("enforcement"), dict) else {},
    }


def _coerce_design_contract(contract_json: dict[str, Any], *, fallback_name: str) -> DesignContractOut:
    raw = contract_json.get("design_contract") if isinstance(contract_json.get("design_contract"), dict) else {}
    identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
    typography = raw.get("typography") if isinstance(raw.get("typography"), dict) else {}
    layout = raw.get("layout") if isinstance(raw.get("layout"), dict) else {}
    tokens_raw = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else {}
    token_registry_raw = raw.get("token_registry") if isinstance(raw.get("token_registry"), dict) else {}
    allowed_components_raw = raw.get("allowed_components")
    components = raw.get("components") if isinstance(raw.get("components"), dict) else {}

    tokens: dict[str, str] = {}
    for key, value in tokens_raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        normalized_key = _normalize_token_name(key)
        normalized_value = value.strip()
        if normalized_key and normalized_value:
            tokens[normalized_key] = normalized_value
    if not tokens:
        tokens = {
            "primary": "#2563eb",
            "surface": "#f8fafc",
            "accent": "#ec4899",
            "success": "#22c55e",
            "text_primary": "#0f172a",
        }
    token_registry = {
        "colors": token_registry_raw.get("colors") if isinstance(token_registry_raw.get("colors"), dict) else dict(tokens),
        "spacing": token_registry_raw.get("spacing") if isinstance(token_registry_raw.get("spacing"), dict) else {},
        "radius": token_registry_raw.get("radius") if isinstance(token_registry_raw.get("radius"), dict) else {},
        "motion": token_registry_raw.get("motion") if isinstance(token_registry_raw.get("motion"), dict) else {},
        "elevation": token_registry_raw.get("elevation") if isinstance(token_registry_raw.get("elevation"), dict) else {},
    }
    registry_components = components.get("registry") if isinstance(components.get("registry"), list) else []
    allowed_components = [
        str(item).strip()
        for item in (allowed_components_raw if isinstance(allowed_components_raw, list) else registry_components)
        if isinstance(item, str) and str(item).strip()
    ]
    experience_blueprint = str(raw.get("experience_blueprint") or "premium_saas").strip() or "premium_saas"

    return DesignContractOut.model_validate(
        {
            "experience_blueprint": experience_blueprint,
            "identity": {
                "name": str(identity.get("name") or fallback_name).strip() or fallback_name,
                "tone": str(identity.get("tone") or "technical_minimal_premium").strip() or "technical_minimal_premium",
                "personality": str(identity.get("personality") or "confident_operational_clean").strip() or "confident_operational_clean",
            },
            "tokens": tokens,
            "token_registry": token_registry,
            "allowed_components": allowed_components,
            "typography": typography,
            "components": components,
            "layout": layout,
        }
    )


async def get_project_contract(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ProjectContract:
    await _get_project(session, tenant_id=tenant_id, project_id=project_id)
    profile = await _get_profile(session, tenant_id=tenant_id, project_id=project_id)
    if profile is None:
        raise ValueError("Project contract not found")
    return profile


async def get_project_contract_runtime_meta(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> dict[str, Any] | None:
    profile = await _get_profile(session, tenant_id=tenant_id, project_id=project_id)
    if profile is None:
        return None
    return _runtime_meta_from_profile(profile)


async def upsert_project_contract(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    status: str,
    source: str,
    summary: str | None,
    contract_json: dict[str, Any],
    created_by: str | None,
    updated_by: str | None,
) -> ProjectContract:
    await _get_project(session, tenant_id=tenant_id, project_id=project_id)
    profile = await _get_profile(session, tenant_id=tenant_id, project_id=project_id)
    now = datetime.now(timezone.utc)
    derived_json = _build_derived_contract(contract_json)
    if profile is None:
        profile = ProjectContract(
            tenant_id=tenant_id,
            project_id=project_id,
            status=status,
            source=source,
            version=1,
            summary=summary,
            contract_json=contract_json,
            derived_json=derived_json,
            last_derived_at=now,
            created_by=created_by or updated_by,
            updated_by=updated_by or created_by,
        )
        session.add(profile)
    else:
        profile.status = status
        profile.source = source
        profile.summary = summary
        profile.contract_json = contract_json
        profile.derived_json = derived_json
        profile.last_derived_at = now
        profile.updated_by = updated_by or created_by or profile.updated_by
        profile.version += 1
        session.add(profile)
    await session.flush()
    return profile


async def patch_project_contract(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    summary: str | None,
    sections: dict[str, Any],
    updated_by: str | None,
) -> ProjectContract:
    profile = await get_project_contract(session, tenant_id=tenant_id, project_id=project_id)
    merged = _deep_merge(
        profile.contract_json if isinstance(profile.contract_json, dict) else {},
        sections,
        preserve_existing_scalars=False,
    )
    profile.contract_json = merged
    if summary is not None:
        profile.summary = summary
    profile.derived_json = _build_derived_contract(merged)
    profile.last_derived_at = datetime.now(timezone.utc)
    profile.updated_by = updated_by or profile.updated_by
    profile.version += 1
    session.add(profile)
    await session.flush()
    return profile


async def bootstrap_project_contract(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    created_by: str | None = None,
) -> ProjectContract:
    project = await _get_project(session, tenant_id=tenant_id, project_id=project_id)
    repo = await session.scalar(
        select(ProjectRepository).where(
            ProjectRepository.project_id == project_id,
            ProjectRepository.tenant_id == tenant_id,
        )
    )
    bootstrap_json, bootstrap_summary = _build_bootstrap_contract(project, repo)
    profile = await _get_profile(session, tenant_id=tenant_id, project_id=project_id)
    now = datetime.now(timezone.utc)
    if profile is None:
        profile = ProjectContract(
            tenant_id=tenant_id,
            project_id=project_id,
            status="DRAFT",
            source="BOOTSTRAP",
            version=1,
            summary=bootstrap_summary,
            contract_json=bootstrap_json,
            derived_json=_build_derived_contract(bootstrap_json),
            last_derived_at=now,
            created_by=created_by,
            updated_by=created_by,
        )
        session.add(profile)
    else:
        merged = _deep_merge(profile.contract_json if isinstance(profile.contract_json, dict) else {}, bootstrap_json)
        changed = merged != (profile.contract_json if isinstance(profile.contract_json, dict) else {})
        profile.contract_json = merged
        profile.derived_json = _build_derived_contract(merged)
        profile.last_derived_at = now
        if not profile.summary:
            profile.summary = bootstrap_summary
        if changed:
            profile.version += 1
        profile.updated_by = created_by or profile.updated_by
        session.add(profile)
    await session.flush()
    return profile


async def derive_project_contract(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    bootstrap_if_missing: bool = False,
    updated_by: str | None = None,
) -> ProjectContract:
    profile = await _get_profile(session, tenant_id=tenant_id, project_id=project_id)
    if profile is None:
        if not bootstrap_if_missing:
            raise ValueError("Project contract not found")
        return await bootstrap_project_contract(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            created_by=updated_by,
        )
    profile.derived_json = _build_derived_contract(profile.contract_json if isinstance(profile.contract_json, dict) else {})
    profile.last_derived_at = datetime.now(timezone.utc)
    profile.updated_by = updated_by or profile.updated_by
    session.add(profile)
    await session.flush()
    return profile


async def summarize_project_contract(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ProjectContractSummaryOut:
    project = await _get_project(session, tenant_id=tenant_id, project_id=project_id)
    profile = await _get_profile(session, tenant_id=tenant_id, project_id=project_id)
    if profile is not None:
        return _build_summary(
            profile_exists=True,
            profile_id=profile.id,
            status=profile.status,
            source=profile.source,
            version=profile.version,
            summary=profile.summary,
            contract_json=profile.contract_json if isinstance(profile.contract_json, dict) else {},
            derived_json=profile.derived_json if isinstance(profile.derived_json, dict) else {},
            last_derived_at=profile.last_derived_at,
        )
    inferred_json = {
        "brand_kit": {"tokens": {}},
        "design_system": {"components": [], "rules": {"enabled": False}},
        "system_architecture": {"notes": f"{project.name} does not have a persisted project contract yet."},
        "enforcement": {"enabled": False},
    }
    return _build_summary(
        profile_exists=False,
        profile_id=None,
        status="MISSING",
        source="INFERRED",
        version=None,
        summary=f"{project.name} has no persisted project contract. Runtime enforcement is currently disabled.",
        contract_json=inferred_json,
        derived_json=_build_derived_contract(inferred_json),
        last_derived_at=None,
    )


async def get_design_contract(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> DesignContractOut:
    project = await _get_project(session, tenant_id=tenant_id, project_id=project_id)
    profile = await _get_profile(session, tenant_id=tenant_id, project_id=project_id)
    if profile is None:
        return _coerce_design_contract({}, fallback_name=project.name)
    contract_json = profile.contract_json if isinstance(profile.contract_json, dict) else {}
    return _coerce_design_contract(contract_json, fallback_name=project.name)


async def upsert_design_contract(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: DesignContractUpsert,
    updated_by: str | None,
) -> ProjectContract:
    project = await _get_project(session, tenant_id=tenant_id, project_id=project_id)
    profile = await _get_profile(session, tenant_id=tenant_id, project_id=project_id)
    existing_contract_json = profile.contract_json if profile is not None and isinstance(profile.contract_json, dict) else {}
    current = _coerce_design_contract(existing_contract_json, fallback_name=project.name)

    incoming = {
        "experience_blueprint": payload.experience_blueprint or current.experience_blueprint,
        "identity": payload.identity.model_dump() if payload.identity else current.identity.model_dump(),
        "tokens": payload.tokens if payload.tokens else dict(current.tokens),
        "token_registry": payload.token_registry.model_dump() if payload.token_registry else current.token_registry.model_dump(),
        "allowed_components": payload.allowed_components if payload.allowed_components else list(current.allowed_components),
        "typography": payload.typography.model_dump() if payload.typography else current.typography.model_dump(),
        "components": payload.components if payload.components else dict(current.components),
        "layout": payload.layout.model_dump() if payload.layout else current.layout.model_dump(),
    }
    normalized = DesignContractOut.model_validate(incoming)

    merged = dict(existing_contract_json)
    merged["design_contract"] = normalized.model_dump(mode="json")
    if profile is None:
        # Bootstrap baseline sections so runtime checks stay available.
        base_json, base_summary = _build_bootstrap_contract(project, repo=None)
        base_json["design_contract"] = normalized.model_dump(mode="json")
        return await upsert_project_contract(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            status="DRAFT",
            source="MANUAL",
            summary=base_summary,
            contract_json=base_json,
            created_by=updated_by,
            updated_by=updated_by,
        )
    profile.contract_json = merged
    profile.derived_json = _build_derived_contract(merged)
    profile.last_derived_at = datetime.now(timezone.utc)
    profile.updated_by = updated_by or profile.updated_by
    profile.version += 1
    session.add(profile)
    await session.flush()
    return profile
