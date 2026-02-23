from __future__ import annotations

import uuid
from typing import List, Optional
from pydantic import BaseModel

from app.schemas.graph import GraphResult
from app.schemas.persistence import DocumentOut, TaskOut
from app.schemas.artifact import ArtifactOut
from app.schemas.approval import ApprovalOut
from app.schemas.provenance import Provenance


class ExplainTaskResponse(BaseModel):
    task: TaskOut
    origin_documents: List[DocumentOut]
    artifacts: List[ArtifactOut]
    approvals: List[ApprovalOut]
    graph: GraphResult
    provenance: Optional[Provenance] = None
    confidence_score: Optional[float] = None
    supersede_depth: int
    origin_document_chain: List[DocumentOut]
    confidence_aggregate: Optional[float] = None
    provenance_summary: Optional[dict] = None
    regeneration_history: Optional[dict] = None
