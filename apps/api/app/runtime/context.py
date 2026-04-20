from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.runtime.execution_contract import ExecutionContract


@dataclass
class RunContext:
    project_id: uuid.UUID
    run_id: uuid.UUID
    plan_snapshot: dict | None = None
    architecture_profile: dict | None = None
    execution_contract: ExecutionContract | None = None
    workspace_root: str | None = None
    repo_path: str | None = None
    artifacts_path: str | None = None
    logs_path: str | None = None
    patches_path: str | None = None
    context_path: str | None = None
    branch_name: str | None = None
    workspace_status: str | None = None
    simulation_mode: str | None = None
    command_audit_path: str | None = None
    cleanup_policy: str | None = None
