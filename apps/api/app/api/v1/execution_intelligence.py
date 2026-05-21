from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_context
from app.db.session import get_session
from app.schemas.execution_intelligence import TrainingExampleResponse
from app.services.execution_intelligence import build_training_examples

public_router = APIRouter(tags=["execution-intelligence"])


@public_router.get(
    "/projects/{project_id}/execution-intelligence/training-examples",
    response_model=TrainingExampleResponse,
)
async def get_training_examples(
    project_id: uuid.UUID,
    limit: int = 100,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> TrainingExampleResponse:
    try:
        bounded_limit = max(10, min(limit, 1000))
        return await build_training_examples(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            limit=bounded_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
