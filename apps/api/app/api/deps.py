from __future__ import annotations

import uuid
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_session
from app.db.models.tenant_member import TenantMember

ZERO_TENANT = uuid.UUID(int=0)


class TenantContext:
    def __init__(self, tenant_id: uuid.UUID, user_id: str, role: str | None, enforcement: bool):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.role = role
        self.enforcement = enforcement


async def get_tenant_context(
    x_tenant_id: str | None = Header(None),
    x_user_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
) -> TenantContext:
    settings = get_settings()
    enforcement = settings.tenancy_enforcement

    user_id = x_user_id or "system"

    if not enforcement:
        # Legacy / transitional mode
        tenant_id = ZERO_TENANT if not x_tenant_id else _parse_uuid(x_tenant_id)
        return TenantContext(tenant_id=tenant_id, user_id=user_id, role=None, enforcement=False)

    if not x_tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-Tenant-Id required")
    tenant_id = _parse_uuid(x_tenant_id)
    if tenant_id == ZERO_TENANT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="system tenant not available")

    # Membership check
    member = (
        await session.execute(
            select(TenantMember).where(TenantMember.tenant_id == tenant_id, TenantMember.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of tenant")

    return TenantContext(tenant_id=tenant_id, user_id=user_id, role=member.role, enforcement=True)


async def get_tenant_id(ctx: TenantContext = Depends(get_tenant_context)) -> uuid.UUID:
    return ctx.tenant_id


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tenant id")
