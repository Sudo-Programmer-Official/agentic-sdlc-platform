from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Tuple

from core.models import Approval, ApprovalDecision, Stage


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


@dataclass
class ApprovalRecord:
    approval: Approval
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None


class ApprovalGate:
    def __init__(self) -> None:
        self._by_id: Dict[str, ApprovalRecord] = {}
        self._by_stage: Dict[Tuple[str, Stage], str] = {}

    def request_approval(
        self,
        approval_id: str,
        project_id: str,
        stage: Stage,
        requested_by: str,
        comment: str | None = None,
    ) -> ApprovalRecord:
        approval = Approval(
            id=approval_id,
            project_id=project_id,
            stage=stage,
            requested_by=requested_by,
            comment=comment,
        )
        record = ApprovalRecord(approval=approval, status=ApprovalStatus.PENDING)
        self._by_id[approval_id] = record
        self._by_stage[(project_id, stage)] = approval_id
        return record

    def decide(
        self,
        approval_id: str,
        decision: ApprovalStatus,
        decided_by: str,
        comment: str | None = None,
    ) -> ApprovalRecord:
        record = self._require_record(approval_id)
        record.status = decision
        record.decided_by = decided_by
        record.decided_at = datetime.utcnow()
        record.approval.status = ApprovalDecision(decision.value)
        record.approval.decided_by = decided_by
        record.approval.decided_at = record.decided_at
        record.approval.comment = comment
        return record

    def get_stage_record(self, project_id: str, stage: Stage) -> Optional[ApprovalRecord]:
        approval_id = self._by_stage.get((project_id, stage))
        if approval_id is None:
            return None
        return self._by_id.get(approval_id)

    def assert_stage_approved(self, project_id: str, stage: Stage) -> None:
        record = self.get_stage_record(project_id, stage)
        if record is None:
            raise ValueError(f"No approval found for project={project_id} stage={stage}")
        if record.status != ApprovalStatus.APPROVED:
            raise ValueError(
                f"Stage {stage} for project={project_id} not approved (status={record.status})"
            )


    def get_record(self, approval_id: str) -> ApprovalRecord:
        return self._require_record(approval_id)

    def _require_record(self, approval_id: str) -> ApprovalRecord:
        if approval_id not in self._by_id:
            raise KeyError(f"Approval {approval_id} not found")
        return self._by_id[approval_id]
