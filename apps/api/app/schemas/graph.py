from __future__ import annotations

import uuid
from typing import List, Optional
from pydantic import BaseModel


class GraphNode(BaseModel):
    id: uuid.UUID
    type: str
    label: Optional[str] = None
    meta: Optional[dict] = None


class GraphEdge(BaseModel):
    from_id: uuid.UUID
    to_id: uuid.UUID
    relation_type: str
    relation_strength: float | None = None
    depth: int
    direction: str  # forward|backward


class GraphResult(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    depth_reached: int
