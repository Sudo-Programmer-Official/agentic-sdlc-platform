from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ArtifactDiffFile(BaseModel):
    path: str
    old_path: str | None = None
    new_path: str | None = None
    additions: int = 0
    deletions: int = 0
    patch: str = ""


class ArtifactDiffResponse(BaseModel):
    artifact_id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID | None = None
    work_item_id: uuid.UUID | None = None
    artifact_type: str
    uri: str
    created_at: datetime
    file_count: int = 0
    additions: int = 0
    deletions: int = 0
    files: list[ArtifactDiffFile] = Field(default_factory=list)
