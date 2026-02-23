from __future__ import annotations

import uuid
from difflib import SequenceMatcher
from hashlib import sha256
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Document, Task, Approval
from app.db.session import get_session
from app.schemas.impact import ImpactPreviewRequest, ImpactPreviewResponse
from app.services.activity_log import log_activity
from app.core.config import get_settings
from app.api.v1.lifecycle_score import lifecycle_score

router = APIRouter(prefix="/store", tags=["impact"])


async def _get_doc(session: AsyncSession, project_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    doc = await session.get(Document, document_id)
    if not doc or doc.project_id != project_id or doc.deleted_at:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _tier_and_flag(similarity: float, threshold: float) -> tuple[str, bool]:
    delta = 1 - similarity
    if similarity >= threshold:
        tier = "LOW"
    elif delta < 0.15:
        tier = "MEDIUM"
    elif delta < 0.3:
        tier = "HIGH"
    else:
        tier = "CRITICAL"
    regen = similarity < threshold
    return tier, regen


@router.post(
    "/projects/{project_id}/documents/{document_id}/impact-preview",
    response_model=ImpactPreviewResponse,
)
async def impact_preview(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: ImpactPreviewRequest,
    session: AsyncSession = Depends(get_session),
) -> ImpactPreviewResponse:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    doc = await _get_doc(session, project_id, document_id)

    current_hash = doc.content_hash
    proposed_hash = sha256(payload.proposed_body.encode("utf-8")).hexdigest()

    if current_hash and proposed_hash == current_hash:
        return ImpactPreviewResponse(
            current_hash=current_hash,
            proposed_hash=proposed_hash,
            similarity=1.0,
            risk_score=0.0,
            risk_tier="LOW",
            regeneration_required=False,
            impacted_tasks=[],
            approvals_to_revalidate=[],
            regenerate_count=0,
        )

    similarity = _similarity(doc.body, payload.proposed_body)
    risk_score = 1 - similarity
    risk_tier, regen_flag = _tier_and_flag(similarity, payload.similarity_threshold)

    # Advisory gating: if regen required and health score is low, inform caller via warnings (no hard block here)
    health_index = None
    try:
        score_resp = await lifecycle_score(project_id, session)  # reuse score computation
        health_index = score_resp.get("health_index")
    except Exception:
        health_index = None

    tasks_result = await session.execute(
        select(Task.id).where(
            Task.document_id == document_id,
            Task.status != "DEPRECATED",
            Task.deleted_at.is_(None),
        )
    )
    impacted_tasks = [row[0] for row in tasks_result.fetchall()]

    approvals_result = await session.execute(
        select(Approval.id).where(
            Approval.project_id == project_id,
            Approval.target_id.in_(impacted_tasks + [document_id]),
            Approval.deleted_at.is_(None),
        )
    )
    approvals_to_revalidate = [row[0] for row in approvals_result.fetchall()]

    warnings = []
    settings = get_settings()
    if health_index is not None and health_index < settings.health_regen_threshold and regen_flag:
        warnings.append(
            f"Health index {health_index:.1f} below threshold {settings.health_regen_threshold}; regeneration may require force."
        )

    response = ImpactPreviewResponse(
        current_hash=current_hash,
        proposed_hash=proposed_hash,
        similarity=similarity,
        risk_score=risk_score,
        risk_tier=risk_tier,
        regeneration_required=regen_flag,
        impacted_tasks=impacted_tasks,
        approvals_to_revalidate=approvals_to_revalidate,
        regenerate_count=len(impacted_tasks),
        warnings=warnings if warnings else None,
    )
    async with session.begin():
        await log_activity(
            session,
            project_id=project_id,
            entity_type="document",
            entity_id=document_id,
            action_type="impact.preview",
            event_type="impact",
            metadata={
                "similarity": similarity,
                "risk_tier": risk_tier,
                "regeneration_required": regen_flag,
                "impacted_tasks": impacted_tasks,
                "health_index": health_index,
            },
            previous_state={"content_hash": current_hash},
            new_state={"proposed_hash": proposed_hash},
        )

    return response
