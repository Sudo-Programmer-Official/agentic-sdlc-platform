from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_context
from app.db.session import get_session
from app.schemas.project_contract import (
    ProjectContractBootstrapRequest,
    ProjectContractDeriveRequest,
    ProjectContractOut,
    ProjectContractSectionPatch,
    ProjectContractSummaryOut,
    ProjectContractUpsert,
)
from app.services.project_contract_service import (
    bootstrap_project_contract,
    derive_project_contract,
    get_project_contract,
    patch_project_contract,
    summarize_project_contract,
    upsert_project_contract,
)

router = APIRouter(tags=["project-contract"])
public_router = APIRouter(tags=["project-contract"])


@router.get("/projects/{project_id}/project-contract", response_model=ProjectContractOut)
@public_router.get("/projects/{project_id}/project-contract", response_model=ProjectContractOut)
async def fetch_project_contract(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectContractOut:
    try:
        profile = await get_project_contract(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if detail in {"Project not found", "Project contract not found"}
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return ProjectContractOut.model_validate(profile)


@router.get("/projects/{project_id}/project-contract/summary", response_model=ProjectContractSummaryOut)
@public_router.get("/projects/{project_id}/project-contract/summary", response_model=ProjectContractSummaryOut)
async def fetch_project_contract_summary(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectContractSummaryOut:
    try:
        return await summarize_project_contract(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/projects/{project_id}/project-contract", response_model=ProjectContractOut)
@public_router.post("/projects/{project_id}/project-contract", response_model=ProjectContractOut)
async def save_project_contract(
    project_id: uuid.UUID,
    payload: ProjectContractUpsert,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectContractOut:
    try:
        profile = await upsert_project_contract(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            status=payload.status,
            source=payload.source,
            summary=payload.summary,
            contract_json=payload.contract_json,
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
    return ProjectContractOut.model_validate(profile)


@router.patch("/projects/{project_id}/project-contract", response_model=ProjectContractOut)
@public_router.patch("/projects/{project_id}/project-contract", response_model=ProjectContractOut)
async def patch_project_contract_sections(
    project_id: uuid.UUID,
    payload: ProjectContractSectionPatch,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectContractOut:
    try:
        profile = await patch_project_contract(
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
        status_code = (
            status.HTTP_404_NOT_FOUND
            if detail in {"Project not found", "Project contract not found"}
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return ProjectContractOut.model_validate(profile)


@router.post("/projects/{project_id}/project-contract/bootstrap", response_model=ProjectContractOut)
@public_router.post("/projects/{project_id}/project-contract/bootstrap", response_model=ProjectContractOut)
async def bootstrap_contract(
    project_id: uuid.UUID,
    payload: ProjectContractBootstrapRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectContractOut:
    try:
        profile = await bootstrap_project_contract(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            created_by=payload.created_by or ctx.user_id,
        )
        await session.commit()
        await session.refresh(profile)
    except ValueError as exc:
        await session.rollback()
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if detail == "Project not found" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return ProjectContractOut.model_validate(profile)


@router.post("/projects/{project_id}/project-contract/derive", response_model=ProjectContractOut)
@public_router.post("/projects/{project_id}/project-contract/derive", response_model=ProjectContractOut)
async def derive_contract(
    project_id: uuid.UUID,
    payload: ProjectContractDeriveRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectContractOut:
    try:
        profile = await derive_project_contract(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            bootstrap_if_missing=payload.bootstrap_if_missing,
            updated_by=payload.updated_by or ctx.user_id,
        )
        await session.commit()
        await session.refresh(profile)
    except ValueError as exc:
        await session.rollback()
        detail = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if detail in {"Project not found", "Project contract not found"}
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return ProjectContractOut.model_validate(profile)
