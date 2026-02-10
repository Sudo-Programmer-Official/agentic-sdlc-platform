from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class Stage(str, Enum):
    INTAKE = "INTAKE"
    REQUIREMENTS_DRAFTED = "REQUIREMENTS_DRAFTED"
    REQUIREMENTS_APPROVED = "REQUIREMENTS_APPROVED"
    DESIGN_DRAFTED = "DESIGN_DRAFTED"
    DESIGN_APPROVED = "DESIGN_APPROVED"
    PLAN_READY = "PLAN_READY"
    IMPLEMENTING = "IMPLEMENTING"
    TESTING = "TESTING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    MERGED = "MERGED"
    DEPLOYED = "DEPLOYED"


class ApprovalDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class ChangeSource(str, Enum):
    USER = "USER"
    PROD_FEEDBACK = "PROD_FEEDBACK"
    BUG = "BUG"
    OPS = "OPS"


class ChangeArea(str, Enum):
    UI = "UI"
    BACKEND = "BACKEND"
    BOTH = "BOTH"


class ChangeSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ChangeStage(str, Enum):
    REQUIREMENTS = "REQUIREMENTS"
    DESIGN = "DESIGN"
    IMPLEMENTATION = "IMPLEMENTATION"


class ChangeStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


@dataclass
class Project:
    id: str
    name: str
    description: Optional[str] = None
    current_stage: Stage = Stage.INTAKE
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class StageRecord:
    project_id: str
    stage: Stage
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


@dataclass
class Artifact:
    id: str
    project_id: str
    stage: Stage
    kind: str
    uri: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ArtifactSnapshot:
    project_id: str
    artifact: str
    hash: str
    approved_stage: Stage
    approved_at: datetime


@dataclass
class AgentRun:
    id: str
    project_id: str
    stage: Stage
    agent_name: str
    status: str
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    input_payload: Dict[str, Any] = field(default_factory=dict)
    output_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Run:
    run_id: str
    project_id: str
    stage: Stage
    status: RunStatus = RunStatus.PENDING
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


@dataclass
class AgentTask:
    task_id: str
    run_id: str
    agent: str
    title: str
    status: TaskStatus = TaskStatus.PENDING
    depends_on: List[str] = field(default_factory=list)
    parallel_group: str = "A"
    outputs: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None


@dataclass
class ChangeRequest:
    id: str
    project_id: str
    source: ChangeSource
    summary: str
    affected_area: ChangeArea
    severity: ChangeSeverity
    suggested_stage: ChangeStage
    status: ChangeStatus = ChangeStatus.OPEN
    created_at: datetime = field(default_factory=datetime.utcnow)
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None


@dataclass
class Approval:
    id: str
    project_id: str
    stage: Stage
    requested_by: str
    status: ApprovalDecision = ApprovalDecision.PENDING
    requested_at: datetime = field(default_factory=datetime.utcnow)
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    comment: Optional[str] = None


@dataclass
class ActionLog:
    id: str
    run_id: str
    project_id: str
    stage: Stage
    agent_name: str
    tool_name: str
    message: Optional[str] = None
    files_touched: List[str] = field(default_factory=list)
    command: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = field(default_factory=dict)
