from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass
class RunContext:
    project_id: uuid.UUID
    run_id: uuid.UUID
    workspace_root: str | None = None
    repo_path: str | None = None
    artifacts_path: str | None = None
    logs_path: str | None = None
    patches_path: str | None = None
    context_path: str | None = None
    branch_name: str | None = None
    workspace_status: str | None = None
