from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_context
from app.db.session import get_session
from app.operator.schemas import OperatorRequest, OperatorResponse
from app.operator.service import handle_operator_request

public_router = APIRouter(tags=["ai-operator"])


@public_router.post("/ai/operator", response_model=OperatorResponse)
async def post_operator_message(
    payload: OperatorRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> OperatorResponse:
    try:
        return await handle_operator_request(
            session,
            tenant_id=ctx.tenant_id,
            request=payload,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail in {"Project not found", "Run not found", "Artifact not found"} else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
