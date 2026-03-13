from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_context
from app.db.session import get_session
from app.schemas.repo_map import RepoMapImpactOut, RepoMapOut, RepoMapSearchOut, RepoMapSymbolSearchOut
from app.services.repo_map import (
    build_project_repo_impact,
    build_project_repo_map,
    refresh_project_repo_map,
    search_project_repo_map,
    search_project_repo_symbols,
)

public_router = APIRouter(tags=["repo-map"])


@public_router.get("/projects/{project_id}/repo-map", response_model=RepoMapOut)
async def get_repo_map(
    project_id: uuid.UUID,
    limit: int = Query(default=180, ge=10, le=500),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RepoMapOut:
    try:
        return await build_project_repo_map(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@public_router.get("/projects/{project_id}/repo-map/search", response_model=RepoMapSearchOut)
async def search_repo_map(
    project_id: uuid.UUID,
    q: str = Query(min_length=2, alias="q"),
    limit: int = Query(default=8, ge=1, le=25),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RepoMapSearchOut:
    try:
        return await search_project_repo_map(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            query=q,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@public_router.post("/projects/{project_id}/repo-map/refresh", response_model=RepoMapOut)
async def refresh_repo_map(
    project_id: uuid.UUID,
    limit: int = Query(default=180, ge=10, le=500),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RepoMapOut:
    try:
        return await refresh_project_repo_map(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@public_router.get("/projects/{project_id}/repo-map/symbols", response_model=RepoMapSymbolSearchOut)
async def search_repo_symbols(
    project_id: uuid.UUID,
    q: str = Query(min_length=1, alias="q"),
    limit: int = Query(default=10, ge=1, le=25),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RepoMapSymbolSearchOut:
    try:
        return await search_project_repo_symbols(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            query=q,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@public_router.get("/projects/{project_id}/repo-map/impact", response_model=RepoMapImpactOut)
async def get_repo_map_impact(
    project_id: uuid.UUID,
    file: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    depth: int = Query(default=1, ge=1, le=2),
    max_files: int = Query(default=15, ge=1, le=25),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RepoMapImpactOut:
    try:
        return await build_project_repo_impact(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            file_path=file,
            symbol_name=symbol,
            depth=depth,
            max_files=max_files,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
