from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ComponentCapabilityContract
from app.runtime.component_capability_protocol import resolve_component_capability


def _normalize_environment(environment: str | None) -> str:
    env = (environment or "PREVIEW").strip().upper()
    if env not in {"PREVIEW", "STAGING", "PRODUCTION"}:
        raise ValueError("environment must be PREVIEW, STAGING, or PRODUCTION")
    return env


def _normalize_capability(capability: str) -> str:
    key = (capability or "").strip()
    if not key:
        raise ValueError("capability is required")
    return key


async def upsert_component_capability_contract(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    project_id: uuid.UUID,
    environment: str,
    capability: str,
    contract_json: dict[str, Any],
    created_by: str | None,
    updated_by: str | None,
) -> ComponentCapabilityContract:
    env = _normalize_environment(environment)
    cap = _normalize_capability(capability)
    row = await session.scalar(
        select(ComponentCapabilityContract).where(
            ComponentCapabilityContract.tenant_id == tenant_id,
            ComponentCapabilityContract.project_id == project_id,
            ComponentCapabilityContract.environment == env,
            ComponentCapabilityContract.capability == cap,
        )
    )
    if row is None:
        row = ComponentCapabilityContract(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
            environment=env,
            capability=cap,
            created_by=created_by,
        )
        session.add(row)

    row.contract_json = contract_json or {}
    row.status = "DRAFT"
    row.approved_by = None
    row.approved_at = None
    row.updated_by = updated_by
    await session.flush()
    return row


async def approve_component_capability_contract(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    environment: str,
    capability: str,
    approved_by: str | None,
) -> ComponentCapabilityContract:
    env = _normalize_environment(environment)
    cap = _normalize_capability(capability)
    row = await session.scalar(
        select(ComponentCapabilityContract).where(
            ComponentCapabilityContract.tenant_id == tenant_id,
            ComponentCapabilityContract.project_id == project_id,
            ComponentCapabilityContract.environment == env,
            ComponentCapabilityContract.capability == cap,
        )
    )
    if row is None:
        raise ValueError("component capability contract not found")
    row.status = "APPROVED"
    row.approved_by = approved_by
    row.approved_at = datetime.now(timezone.utc)
    row.updated_by = approved_by
    await session.flush()
    return row


async def list_component_capability_contracts(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    environment: str,
) -> list[ComponentCapabilityContract]:
    env = _normalize_environment(environment)
    rows = await session.execute(
        select(ComponentCapabilityContract)
        .where(
            ComponentCapabilityContract.tenant_id == tenant_id,
            ComponentCapabilityContract.project_id == project_id,
            ComponentCapabilityContract.environment == env,
        )
        .order_by(ComponentCapabilityContract.capability.asc())
    )
    return list(rows.scalars().all())


async def resolve_component_capability_contract(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    environment: str,
    capability: str,
    variant: str,
) -> dict[str, Any]:
    env = _normalize_environment(environment)
    cap = _normalize_capability(capability)

    row = await session.scalar(
        select(ComponentCapabilityContract).where(
            ComponentCapabilityContract.tenant_id == tenant_id,
            ComponentCapabilityContract.project_id == project_id,
            ComponentCapabilityContract.environment == env,
            ComponentCapabilityContract.capability == cap,
            ComponentCapabilityContract.status == "APPROVED",
        )
    )

    if row is not None and isinstance(row.contract_json, dict) and row.contract_json:
        payload = dict(row.contract_json)
        payload.setdefault("capability", cap)
        payload.setdefault("variant", variant)
        payload.setdefault("allowed_props", [])
        payload.setdefault("slots", [])
        payload.setdefault("tokens", [])
        payload.setdefault("variants", [variant])
        return payload

    # fallback to static runtime catalog
    return resolve_component_capability(cap, variant=variant)
