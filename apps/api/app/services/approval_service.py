from __future__ import annotations

from typing import Optional
from uuid import uuid4

from core.sdlc import ApprovalGate, ApprovalStatus
from core.models import Stage

from .artifact_service import ArtifactSnapshotService
from .errors import ApprovalNotFoundError, InvalidStageError


class ApprovalService:
    def __init__(self, gate: ApprovalGate, artifact_service: ArtifactSnapshotService) -> None:
        self._gate = gate
        self._artifact_service = artifact_service

    def request_approval(
        self, project_id: str, stage: str, requested_by: str, comment: Optional[str] = None
    ):
        stage_enum = self._parse_stage(stage)
        self._artifact_service.assert_not_stale(project_id, stage_enum)
        approval_id = str(uuid4())
        return self._gate.request_approval(
            approval_id=approval_id,
            project_id=project_id,
            stage=stage_enum,
            requested_by=requested_by,
            comment=comment,
        )

    def decide(self, approval_id: str, decision: str, decided_by: str, comment: Optional[str] = None):
        try:
            status = self._parse_decision(decision)
            record = self._gate.decide(
                approval_id=approval_id,
                decision=status,
                decided_by=decided_by,
                comment=comment,
            )
            if status == ApprovalStatus.APPROVED and record.decided_at is not None:
                self._artifact_service.capture_snapshot(
                    project_id=record.approval.project_id,
                    stage=record.approval.stage,
                    approved_at=record.decided_at,
                )
            return record
        except KeyError as exc:
            raise ApprovalNotFoundError(f"Approval {approval_id} not found") from exc

    @staticmethod
    def _parse_stage(raw: str) -> Stage:
        cleaned = raw.strip()
        try:
            return Stage(cleaned)
        except ValueError:
            try:
                return Stage[cleaned.upper()]
            except KeyError as exc:
                raise InvalidStageError(f"Unknown stage '{raw}'") from exc

    @staticmethod
    def _parse_decision(raw: str) -> ApprovalStatus:
        cleaned = raw.strip()
        try:
            return ApprovalStatus(cleaned)
        except ValueError:
            try:
                return ApprovalStatus[cleaned.upper()]
            except KeyError as exc:
                raise ValueError(f"Unknown decision '{raw}'") from exc
