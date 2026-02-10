from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, Set

from core.execution.context import ExecutionContext
from core.models import Stage


class AgentType(str, Enum):
    REQUIREMENTS = "REQUIREMENTS"
    PLANNER = "PLANNER"
    BACKEND = "BACKEND"
    FRONTEND = "FRONTEND"
    TEST = "TEST"


@dataclass
class AgentResult:
    output: Any = None
    metadata: dict = field(default_factory=dict)


class AgentInterface(Protocol):
    name: str
    agent_type: AgentType
    supported_stages: Set[Stage]

    def run(self, context: ExecutionContext) -> AgentResult:
        ...
