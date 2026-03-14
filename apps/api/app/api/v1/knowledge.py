from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_context
from app.db.session import get_session
from app.schemas.knowledge import (
    KnowledgeArtifactDetailOut,
    KnowledgeArtifactListResponse,
    KnowledgeDecisionRequest,
    KnowledgeEditApproveRequest,
    KnowledgeEventDetailOut,
    KnowledgeInboxResponse,
    KnowledgeManualSyncRequest,
    KnowledgeProposalDetailOut,
    KnowledgeProposalListResponse,
    KnowledgeSearchHookListResponse,
    KnowledgeTriggerResponse,
)
from app.services import knowledge_service


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, knowledge_service.KnowledgeNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, knowledge_service.KnowledgeConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    message = str(exc)
    if "not found" in message.lower():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


@router.post("/events/manual-sync", response_model=KnowledgeTriggerResponse, status_code=status.HTTP_202_ACCEPTED)
async def manual_sync_knowledge(
    payload: KnowledgeManualSyncRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeTriggerResponse:
    try:
        return await knowledge_service.trigger_manual_sync(
            session,
            tenant_id=ctx.tenant_id,
            project_id=payload.project_id,
            triggered_by=ctx.user_id,
            title=payload.title,
            branch_name=payload.branch_name,
            commit_sha=payload.commit_sha,
        )
    except Exception as exc:
        _raise_http(exc)


@router.get("/inbox", response_model=KnowledgeInboxResponse)
async def knowledge_inbox(
    project_id: uuid.UUID = Query(...),
    repository_id: uuid.UUID | None = Query(default=None),
    review_status: str | None = Query(default=None),
    change_type: str | None = Query(default=None),
    artifact_type: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeInboxResponse:
    return await knowledge_service.list_inbox(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        repository_id=repository_id,
        review_status=review_status,
        change_type=change_type,
        artifact_type=artifact_type,
        risk_level=risk_level,
    )


@router.get("/proposals", response_model=KnowledgeProposalListResponse)
async def knowledge_proposals(
    project_id: uuid.UUID = Query(...),
    repository_id: uuid.UUID | None = Query(default=None),
    review_status: str | None = Query(default=None),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeProposalListResponse:
    return await knowledge_service.list_proposals(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        repository_id=repository_id,
        review_status=review_status,
    )


@router.get("/proposals/{proposal_id}", response_model=KnowledgeProposalDetailOut)
async def knowledge_proposal_detail(
    proposal_id: uuid.UUID,
    project_id: uuid.UUID = Query(...),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeProposalDetailOut:
    try:
        return await knowledge_service.get_proposal_detail(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            proposal_id=proposal_id,
        )
    except Exception as exc:
        _raise_http(exc)


@router.post("/proposals/{proposal_id}/approve", response_model=KnowledgeProposalDetailOut)
async def approve_knowledge_proposal(
    proposal_id: uuid.UUID,
    payload: KnowledgeDecisionRequest,
    project_id: uuid.UUID = Query(...),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeProposalDetailOut:
    try:
        return await knowledge_service.approve_proposal(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            proposal_id=proposal_id,
            reviewer_user_id=ctx.user_id,
            review_notes=payload.review_notes,
        )
    except Exception as exc:
        _raise_http(exc)


@router.post("/proposals/{proposal_id}/edit-and-approve", response_model=KnowledgeProposalDetailOut)
async def edit_and_approve_knowledge_proposal(
    proposal_id: uuid.UUID,
    payload: KnowledgeEditApproveRequest,
    project_id: uuid.UUID = Query(...),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeProposalDetailOut:
    try:
        return await knowledge_service.approve_proposal(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            proposal_id=proposal_id,
            reviewer_user_id=ctx.user_id,
            review_notes=payload.review_notes,
            edited_content=payload.edited_content,
        )
    except Exception as exc:
        _raise_http(exc)


@router.post("/proposals/{proposal_id}/reject", response_model=KnowledgeProposalDetailOut)
async def reject_knowledge_proposal(
    proposal_id: uuid.UUID,
    payload: KnowledgeDecisionRequest,
    project_id: uuid.UUID = Query(...),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeProposalDetailOut:
    try:
        return await knowledge_service.reject_proposal(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            proposal_id=proposal_id,
            reviewer_user_id=ctx.user_id,
            review_notes=payload.review_notes,
        )
    except Exception as exc:
        _raise_http(exc)


@router.post("/proposals/{proposal_id}/defer", response_model=KnowledgeProposalDetailOut)
async def defer_knowledge_proposal(
    proposal_id: uuid.UUID,
    payload: KnowledgeDecisionRequest,
    project_id: uuid.UUID = Query(...),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeProposalDetailOut:
    try:
        return await knowledge_service.defer_proposal(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            proposal_id=proposal_id,
            reviewer_user_id=ctx.user_id,
            review_notes=payload.review_notes,
        )
    except Exception as exc:
        _raise_http(exc)


@router.get("/artifacts", response_model=KnowledgeArtifactListResponse)
async def knowledge_artifacts(
    project_id: uuid.UUID = Query(...),
    repository_id: uuid.UUID | None = Query(default=None),
    query: str | None = Query(default=None),
    include_drafts: bool = Query(default=False),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeArtifactListResponse:
    return await knowledge_service.list_artifacts(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        repository_id=repository_id,
        query=query,
        include_drafts=include_drafts,
    )


@router.get("/artifacts/{artifact_id}", response_model=KnowledgeArtifactDetailOut)
async def knowledge_artifact_detail(
    artifact_id: uuid.UUID,
    project_id: uuid.UUID = Query(...),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeArtifactDetailOut:
    try:
        return await knowledge_service.get_artifact_detail(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            artifact_id=artifact_id,
        )
    except Exception as exc:
        _raise_http(exc)


@router.get("/events/{event_id}", response_model=KnowledgeEventDetailOut)
async def knowledge_event_detail(
    event_id: uuid.UUID,
    project_id: uuid.UUID = Query(...),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeEventDetailOut:
    try:
        return await knowledge_service.get_event_detail(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            event_id=event_id,
        )
    except Exception as exc:
        _raise_http(exc)


@router.get("/search-hooks", response_model=KnowledgeSearchHookListResponse)
async def knowledge_search_hooks(
    project_id: uuid.UUID = Query(...),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeSearchHookListResponse:
    return await knowledge_service.list_search_hooks(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
    )
