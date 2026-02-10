from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from core.ledger import ActionLedger
from core.models import AgentTask, Project, Run, Stage


@dataclass
class ExecutionContext:
    project: Optional[Project]
    run: Optional[Run]
    task: Optional[AgentTask]
    stage: Optional[Stage]
    artifacts: Dict[str, str] = field(default_factory=dict)
    approvals: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)
    registry: Dict[str, Any] = field(default_factory=dict)
    logger: Optional[ActionLedger] = None
