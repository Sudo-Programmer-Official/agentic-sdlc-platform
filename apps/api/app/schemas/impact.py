from __future__ import annotations

from typing import List
from pydantic import BaseModel
import uuid


class ImpactPreviewRequest(BaseModel):
    proposed_body: str
    similarity_threshold: float = 0.9


class ImpactPreviewResponse(BaseModel):
    current_hash: str | None
    proposed_hash: str
    similarity: float
    risk_score: float
    risk_tier: str
    regeneration_required: bool
    impacted_tasks: List[uuid.UUID]
    approvals_to_revalidate: List[uuid.UUID]
    regenerate_count: int
    warnings: Optional[list[str]] = None
