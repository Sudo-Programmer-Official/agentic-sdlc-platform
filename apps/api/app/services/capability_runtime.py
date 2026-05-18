from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CapabilityBinding, CapabilityDefinition, CapabilityIntegration
from app.services.secret_vault import resolve_vault_secret


ENVIRONMENTS = {"LOCAL_DEV", "PREVIEW", "STAGING", "PRODUCTION"}


class CapabilityResolutionError(RuntimeError):
    pass


@dataclass
class CapabilityResolution:
    capability_key: str
    provider: str
    environment: str
    integration_id: uuid.UUID
    target: str | None
    credentials: str | None
    adapter: str
    health_status: str
    diagnostics: dict


class BaseCapabilityAdapter:
    name = "base"

    @classmethod
    async def health(cls, integration: CapabilityIntegration) -> tuple[str, str | None]:
        status = str(integration.health_status or "UNKNOWN").upper()
        if status in {"HEALTHY", "CONNECTED", "READY"}:
            return "HEALTHY", None
        return "DEGRADED", str(integration.failure_reason or "Provider health unavailable")


class SupabaseAdapter(BaseCapabilityAdapter):
    name = "supabase"


class FirebaseAdapter(BaseCapabilityAdapter):
    name = "firebase"


class PostgresAdapter(BaseCapabilityAdapter):
    name = "postgres"


class HubspotAdapter(BaseCapabilityAdapter):
    name = "hubspot"


class WebhookAdapter(BaseCapabilityAdapter):
    name = "webhook"


ADAPTERS = {
    "supabase": SupabaseAdapter,
    "firebase": FirebaseAdapter,
    "postgres": PostgresAdapter,
    "hubspot": HubspotAdapter,
    "webhook": WebhookAdapter,
}


def normalize_environment(environment: str | None) -> str:
    env = str(environment or "PREVIEW").strip().upper()
    return env if env in ENVIRONMENTS else "PREVIEW"


async def resolve_capability(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    environment: str,
    capability_key: str,
) -> CapabilityResolution:
    env = normalize_environment(environment)
    key = (capability_key or "").strip().lower()
    if not key:
        raise CapabilityResolutionError("capability_key is required")

    binding = await session.scalar(
        select(CapabilityBinding).where(
            CapabilityBinding.tenant_id == tenant_id,
            CapabilityBinding.project_id == project_id,
            CapabilityBinding.environment == env,
            CapabilityBinding.capability_key == key,
            CapabilityBinding.status == "ACTIVE",
        )
    )
    if binding is None:
        raise CapabilityResolutionError(f"Capability '{key}' is not bound for {env}")

    integration = await session.scalar(
        select(CapabilityIntegration).where(
            CapabilityIntegration.id == binding.integration_id,
            CapabilityIntegration.tenant_id == tenant_id,
            CapabilityIntegration.project_id == project_id,
            CapabilityIntegration.environment == env,
            CapabilityIntegration.status.in_(["CONNECTED", "ACTIVE"]),
        )
    )
    if integration is None:
        raise CapabilityResolutionError(f"Bound integration for '{key}' is unavailable")

    provider = str(integration.provider or "").strip().lower()
    adapter_cls = ADAPTERS.get(provider, BaseCapabilityAdapter)
    health_status, health_error = await adapter_cls.health(integration)

    credentials = resolve_vault_secret(integration.credentials_vault_ref) if integration.credentials_vault_ref else None
    if integration.credentials_vault_ref and not credentials:
        raise CapabilityResolutionError(f"Credentials unavailable for capability '{key}' ({provider})")

    integration.last_successful_call_at = datetime.now(timezone.utc) if health_status == "HEALTHY" else integration.last_successful_call_at

    return CapabilityResolution(
        capability_key=key,
        provider=provider,
        environment=env,
        integration_id=integration.id,
        target=binding.target,
        credentials=credentials,
        adapter=adapter_cls.name,
        health_status=health_status,
        diagnostics={
            "integration_status": integration.status,
            "failure_reason": integration.failure_reason,
            "health_error": health_error,
            "retry_state": integration.retry_state,
            "environment_sync_state": integration.environment_sync_state,
        },
    )


async def unresolved_required_capabilities(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    environment: str,
) -> list[str]:
    env = normalize_environment(environment)
    required_defs = (
        await session.execute(
            select(CapabilityDefinition).where(CapabilityDefinition.required.is_(True))
        )
    ).scalars().all()
    required = {str(row.capability_key or "").strip().lower() for row in required_defs if row.capability_key}
    if not required:
        return []

    bound = (
        await session.execute(
            select(CapabilityBinding.capability_key).where(
                CapabilityBinding.tenant_id == tenant_id,
                CapabilityBinding.project_id == project_id,
                CapabilityBinding.environment == env,
                CapabilityBinding.status == "ACTIVE",
            )
        )
    ).scalars().all()
    bound_set = {str(item or "").strip().lower() for item in bound if str(item or "").strip()}
    return sorted(required.difference(bound_set))
