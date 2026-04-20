from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_context
from app.db.session import get_session
from app.schemas.architecture_profile import (
    ArchitectureProfileBootstrapRequest,
    ArchitectureProfileDeriveRequest,
    ArchitectureProfileOut,
    ArchitectureProfileSectionPatch,
    ArchitectureProfileSummaryOut,
    ArchitectureProfileUpsert,
)
from app.services.architecture_profile_service import (
    bootstrap_architecture_profile,
    derive_architecture_profile,
    get_architecture_profile,
    patch_architecture_profile,
    summarize_architecture_profile,
    upsert_architecture_profile,
)

router = APIRouter(tags=["architecture-profile"])
public_router = APIRouter(tags=["architecture-profile"])


@router.get("/projects/{project_id}/architecture-profile", response_model=ArchitectureProfileOut)
@public_router.get("/projects/{project_id}/architecture-profile", response_model=ArchitectureProfileOut)
async def fetch_architecture_profile(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ArchitectureProfileOut:
    try:
        profile = await get_architecture_profile(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if detail in {"Project not found", "Architecture profile not found"} else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return ArchitectureProfileOut.model_validate(profile)


@router.get("/projects/{project_id}/architecture-profile/summary", response_model=ArchitectureProfileSummaryOut)
@public_router.get("/projects/{project_id}/architecture-profile/summary", response_model=ArchitectureProfileSummaryOut)
async def fetch_architecture_profile_summary(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ArchitectureProfileSummaryOut:
    try:
        return await summarize_architecture_profile(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/projects/{project_id}/architecture-profile", response_model=ArchitectureProfileOut)
@public_router.post("/projects/{project_id}/architecture-profile", response_model=ArchitectureProfileOut)
async def save_architecture_profile(
    project_id: uuid.UUID,
    payload: ArchitectureProfileUpsert,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ArchitectureProfileOut:
    try:
        profile = await upsert_architecture_profile(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            status=payload.status,
            source=payload.source,
            summary=payload.summary,
            profile_json=payload.profile_json,
            created_by=payload.created_by or ctx.user_id,
            updated_by=payload.updated_by or ctx.user_id,
        )
        await session.commit()
        await session.refresh(profile)
    except ValueError as exc:
        await session.rollback()
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if detail == "Project not found" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return ArchitectureProfileOut.model_validate(profile)


@router.patch("/projects/{project_id}/architecture-profile", response_model=ArchitectureProfileOut)
@public_router.patch("/projects/{project_id}/architecture-profile", response_model=ArchitectureProfileOut)
async def patch_profile_sections(
    project_id: uuid.UUID,
    payload: ArchitectureProfileSectionPatch,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ArchitectureProfileOut:
    try:
        profile = await patch_architecture_profile(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            summary=payload.summary,
            sections=payload.sections,
            updated_by=payload.updated_by or ctx.user_id,
        )
        await session.commit()
        await session.refresh(profile)
    except ValueError as exc:
        await session.rollback()
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if detail in {"Project not found", "Architecture profile not found"} else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return ArchitectureProfileOut.model_validate(profile)


@router.post("/projects/{project_id}/architecture-profile/bootstrap", response_model=ArchitectureProfileOut)
@public_router.post("/projects/{project_id}/architecture-profile/bootstrap", response_model=ArchitectureProfileOut)
async def bootstrap_profile(
    project_id: uuid.UUID,
    payload: ArchitectureProfileBootstrapRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ArchitectureProfileOut:
    try:
        profile = await bootstrap_architecture_profile(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            refresh_repo_map_requested=payload.refresh_repo_map,
            created_by=payload.created_by or ctx.user_id,
        )
        await session.commit()
        await session.refresh(profile)
    except ValueError as exc:
        await session.rollback()
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if detail == "Project not found" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return ArchitectureProfileOut.model_validate(profile)


@router.post("/projects/{project_id}/architecture-profile/derive", response_model=ArchitectureProfileOut)
@public_router.post("/projects/{project_id}/architecture-profile/derive", response_model=ArchitectureProfileOut)
async def derive_profile(
    project_id: uuid.UUID,
    payload: ArchitectureProfileDeriveRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ArchitectureProfileOut:
    try:
        profile = await derive_architecture_profile(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            refresh_repo_map_requested=payload.refresh_repo_map,
            bootstrap_if_missing=payload.bootstrap_if_missing,
            updated_by=payload.updated_by or ctx.user_id,
        )
        await session.commit()
        await session.refresh(profile)
    except ValueError as exc:
        await session.rollback()
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if detail in {"Project not found", "Architecture profile not found"} else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return ArchitectureProfileOut.model_validate(profile)
