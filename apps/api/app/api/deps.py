from __future__ import annotations

import uuid
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_session
from app.db.models.tenant_member import TenantMember
from app.db.models.workspace import Workspace
from app.db.models.workspace_member import WorkspaceMember
from app.services.firebase_auth import FirebaseAuthError, verify_firebase_bearer_token

ZERO_TENANT = uuid.UUID(int=0)


class TenantContext:
    def __init__(
        self,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
        user_id: str = "system",
        role: str | None = None,
        enforcement: bool = False,
    ):
        self.tenant_id = tenant_id
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.role = role
        self.enforcement = enforcement


def _tenant_auth_error(
    status_code: int,
    code: str,
    message: str,
    *,
    correlation_id: str | None = None,
) -> HTTPException:
    detail = {
        "code": code,
        "message": message,
        "user_message": message,
    }
    if correlation_id:
        detail["correlation_id"] = correlation_id
    return HTTPException(
        status_code=status_code,
        detail=detail,
    )


async def get_tenant_context(
    x_tenant_id: str | None = Header(None),
    x_workspace_id: str | None = Header(None),
    x_user_id: str | None = Header(None),
    x_correlation_id: str | None = Header(None),
    authorization: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
) -> TenantContext:
    settings = get_settings()
    enforcement = settings.tenancy_enforcement
    user_id = x_user_id or "system"

    if not enforcement:
        # Legacy / transitional mode
        tenant_id = ZERO_TENANT if not x_tenant_id else _parse_uuid(x_tenant_id)
        workspace_id = None if not x_workspace_id else _parse_uuid(x_workspace_id)
        return TenantContext(tenant_id=tenant_id, workspace_id=workspace_id, user_id=user_id, role=None, enforcement=False)

    if settings.firebase_auth_enforcement or settings.firebase_project_id:
        token = _extract_bearer_token(authorization, correlation_id=x_correlation_id)
        try:
            claims = verify_firebase_bearer_token(token, project_id=str(settings.firebase_project_id or ""))
        except FirebaseAuthError as exc:
            raise _tenant_auth_error(
                status.HTTP_401_UNAUTHORIZED,
                "AUTH_TOKEN_INVALID",
                str(exc) or "Authentication token is invalid.",
                correlation_id=x_correlation_id,
            ) from exc
        user_id = _user_id_from_claims(claims)

    if not x_tenant_id:
        raise _tenant_auth_error(
            status.HTTP_401_UNAUTHORIZED,
            "TENANT_HEADER_MISSING",
            "Tenant context is required. Provide X-Tenant-Id.",
            correlation_id=x_correlation_id,
        )
    tenant_id = _parse_uuid(x_tenant_id, correlation_id=x_correlation_id)
    if tenant_id == ZERO_TENANT:
        raise _tenant_auth_error(
            status.HTTP_403_FORBIDDEN,
            "TENANT_SYSTEM_FORBIDDEN",
            "System tenant is not available for user actions.",
            correlation_id=x_correlation_id,
        )

    # Membership check
    member = (
        await session.execute(
            select(TenantMember).where(TenantMember.tenant_id == tenant_id, TenantMember.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not member:
        raise _tenant_auth_error(
            status.HTTP_403_FORBIDDEN,
            "TENANT_MEMBERSHIP_REQUIRED",
            "You are not a member of the requested tenant.",
            correlation_id=x_correlation_id,
        )

    workspace_id: uuid.UUID | None = None
    if x_workspace_id:
        requested_workspace_id = _parse_uuid(x_workspace_id, correlation_id=x_correlation_id)
        workspace = await session.scalar(
            select(Workspace).where(
                Workspace.id == requested_workspace_id,
                Workspace.tenant_id == tenant_id,
            )
        )
        if workspace is None:
            raise _tenant_auth_error(
                status.HTTP_403_FORBIDDEN,
                "WORKSPACE_NOT_FOUND",
                "Requested workspace is not available under the tenant context.",
                correlation_id=x_correlation_id,
            )
        workspace_member = await session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == requested_workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        if workspace_member is None:
            raise _tenant_auth_error(
                status.HTTP_403_FORBIDDEN,
                "WORKSPACE_MEMBERSHIP_REQUIRED",
                "You are not a member of the requested workspace.",
                correlation_id=x_correlation_id,
            )
        workspace_id = requested_workspace_id
    else:
        workspace = await session.scalar(select(Workspace).where(Workspace.tenant_id == tenant_id))
        workspace_id = workspace.id if workspace else None

    return TenantContext(tenant_id=tenant_id, workspace_id=workspace_id, user_id=user_id, role=member.role, enforcement=True)


async def get_tenant_id(ctx: TenantContext = Depends(get_tenant_context)) -> uuid.UUID:
    return ctx.tenant_id


def _parse_uuid(value: str, *, correlation_id: str | None = None) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise _tenant_auth_error(
            status.HTTP_401_UNAUTHORIZED,
            "TENANT_HEADER_INVALID",
            "Tenant context is invalid. X-Tenant-Id must be a UUID.",
            correlation_id=correlation_id,
        )


def _extract_bearer_token(authorization: str | None, *, correlation_id: str | None = None) -> str:
    if not authorization:
        raise _tenant_auth_error(
            status.HTTP_401_UNAUTHORIZED,
            "AUTH_TOKEN_MISSING",
            "Authorization bearer token is required.",
            correlation_id=correlation_id,
        )
    prefix = "bearer "
    if not authorization.lower().startswith(prefix):
        raise _tenant_auth_error(
            status.HTTP_401_UNAUTHORIZED,
            "AUTH_TOKEN_INVALID",
            "Authorization header must use Bearer token.",
            correlation_id=correlation_id,
        )
    token = authorization[len(prefix) :].strip()
    if not token:
        raise _tenant_auth_error(
            status.HTTP_401_UNAUTHORIZED,
            "AUTH_TOKEN_INVALID",
            "Authorization bearer token is required.",
            correlation_id=correlation_id,
        )
    return token


def _user_id_from_claims(claims: dict) -> str:
    for key in ("user_id", "uid", "sub", "email"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "system"
