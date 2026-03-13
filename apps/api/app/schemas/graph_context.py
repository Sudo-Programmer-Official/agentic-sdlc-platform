from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field

from app.schemas.graph import GraphEdge, GraphNode


class GraphContextBudget(BaseModel):
    max_depth: int = 0
    max_ancestor_nodes: int = 0
    max_descendant_nodes: int = 0
    max_edges: int = 0
    max_documents: int = 0
    max_tasks: int = 0
    max_artifacts: int = 0
    max_runs: int = 0
    max_work_items: int = 0
    truncated: bool = False
    returned_counts: Dict[str, int] = Field(default_factory=dict)


class GraphContextResponse(BaseModel):
    root: GraphNode
    ancestors: List[GraphNode] = Field(default_factory=list)
    descendants: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    project_brief: Dict[str, List[GraphNode]] = Field(default_factory=dict)
    budget: GraphContextBudget = Field(default_factory=GraphContextBudget)
