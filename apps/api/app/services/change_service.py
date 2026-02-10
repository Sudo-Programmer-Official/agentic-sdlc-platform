from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Set
from uuid import uuid4

from core.ledger import ActionLedger
from core.models import (
    ChangeArea,
    ChangeRequest,
    ChangeSeverity,
    ChangeSource,
    ChangeStage,
    ChangeStatus,
    Project,
    Stage,
)

from .artifact_service import ArtifactSnapshotService
from .errors import ChangeRequestNotFoundError, InvalidChangeStatusError


CHANGE_STAGE_TO_SUGGESTED: dict[ChangeStage, Stage] = {
    ChangeStage.REQUIREMENTS: Stage.REQUIREMENTS_DRAFTED,
    ChangeStage.DESIGN: Stage.DESIGN_DRAFTED,
    ChangeStage.IMPLEMENTATION: Stage.IMPLEMENTING,
}

CHANGE_STAGE_STALE: dict[ChangeStage, Set[Stage]] = {
    ChangeStage.REQUIREMENTS: {
        Stage.REQUIREMENTS_APPROVED,
        Stage.DESIGN_DRAFTED,
        Stage.DESIGN_APPROVED,
        Stage.PLAN_READY,
        Stage.IMPLEMENTING,
        Stage.TESTING,
        Stage.READY_FOR_REVIEW,
        Stage.MERGED,
        Stage.DEPLOYED,
    },
    ChangeStage.DESIGN: {
        Stage.DESIGN_APPROVED,
        Stage.PLAN_READY,
        Stage.IMPLEMENTING,
        Stage.TESTING,
        Stage.READY_FOR_REVIEW,
        Stage.MERGED,
        Stage.DEPLOYED,
    },
    ChangeStage.IMPLEMENTATION: {
        Stage.TESTING,
        Stage.READY_FOR_REVIEW,
        Stage.MERGED,
        Stage.DEPLOYED,
    },
}


class InMemoryChangeStore:
    def __init__(self) -> None:
        self._changes_by_id: Dict[str, ChangeRequest] = {}
        self._changes_by_project: Dict[str, List[str]] = {}

    def add(self, change: ChangeRequest) -> None:
        self._changes_by_id[change.id] = change
        self._changes_by_project.setdefault(change.project_id, []).append(change.id)

    def get(self, change_id: str) -> ChangeRequest:
        if change_id not in self._changes_by_id:
            raise ChangeRequestNotFoundError(f"ChangeRequest {change_id} not found")
        return self._changes_by_id[change_id]

    def update(self, change: ChangeRequest) -> None:
        self._changes_by_id[change.id] = change

    def list_by_project(self, project_id: str) -> List[ChangeRequest]:
        ids = self._changes_by_project.get(project_id, [])
        return [self._changes_by_id[change_id] for change_id in ids]


class ChangeRequestService:
    def __init__(
        self,
        store: InMemoryChangeStore,
        ledger: ActionLedger,
        artifact_service: ArtifactSnapshotService,
        project_getter,
        project_stage_setter,
    ) -> None:
        self._store = store
        self._ledger = ledger
        self._artifact_service = artifact_service
        self._project_getter = project_getter
        self._project_stage_setter = project_stage_setter

    def create(
        self,
        project_id: str,
        source: str,
        summary: str,
        affected_area: str,
        severity: str,
        suggested_stage: str,
    ) -> ChangeRequest:
        if self._project_getter is not None:
            self._project_getter(project_id)
        change = ChangeRequest(
            id=str(uuid4()),
            project_id=project_id,
            source=self._parse_source(source),
            summary=summary,
            affected_area=self._parse_area(affected_area),
            severity=self._parse_severity(severity),
            suggested_stage=self._parse_stage(suggested_stage),
        )
        self._store.add(change)
        self._ledger.log(
            run_id="system",
            project_id=project_id,
            stage=Stage.REQUIREMENTS_DRAFTED,
            agent_name="system",
            tool_name="change_request",
            message="Change request created",
            details={"change_id": change.id, "summary": change.summary},
        )
        return change

    def list_for_project(self, project_id: str) -> List[ChangeRequest]:
        return self._store.list_by_project(project_id)

    def accept(self, change_id: str, decided_by: Optional[str] = None) -> ChangeRequest:
        change = self._store.get(change_id)
        if change.status != ChangeStatus.OPEN:
            raise InvalidChangeStatusError("ChangeRequest is not OPEN")

        change.status = ChangeStatus.ACCEPTED
        change.decided_by = decided_by
        change.decided_at = datetime.utcnow()
        self._store.update(change)

        target_stage = CHANGE_STAGE_TO_SUGGESTED[change.suggested_stage]
        stale_stages = CHANGE_STAGE_STALE[change.suggested_stage]
        self._project_stage_setter(change.project_id, target_stage)
        self._artifact_service.mark_stale(
            project_id=change.project_id,
            stages=stale_stages,
            reason=f"ChangeRequest {change.id} accepted",
        )

        self._ledger.log(
            run_id="system",
            project_id=change.project_id,
            stage=target_stage,
            agent_name="system",
            tool_name="change_request",
            message="Change request accepted",
            details={
                "change_id": change.id,
                "suggested_stage": change.suggested_stage.value,
                "stale_stages": [stage.value for stage in stale_stages],
            },
        )
        return change

    def reject(self, change_id: str, decided_by: Optional[str] = None) -> ChangeRequest:
        change = self._store.get(change_id)
        if change.status != ChangeStatus.OPEN:
            raise InvalidChangeStatusError("ChangeRequest is not OPEN")
        change.status = ChangeStatus.REJECTED
        change.decided_by = decided_by
        change.decided_at = datetime.utcnow()
        self._store.update(change)
        self._ledger.log(
            run_id="system",
            project_id=change.project_id,
            stage=Stage.REQUIREMENTS_DRAFTED,
            agent_name="system",
            tool_name="change_request",
            message="Change request rejected",
            details={"change_id": change.id},
        )
        return change

    @staticmethod
    def _parse_source(raw: str) -> ChangeSource:
        cleaned = raw.strip()
        try:
            return ChangeSource(cleaned)
        except ValueError:
            return ChangeSource[cleaned.upper()]

    @staticmethod
    def _parse_area(raw: str) -> ChangeArea:
        cleaned = raw.strip()
        try:
            return ChangeArea(cleaned)
        except ValueError:
            return ChangeArea[cleaned.upper()]

    @staticmethod
    def _parse_severity(raw: str) -> ChangeSeverity:
        cleaned = raw.strip()
        try:
            return ChangeSeverity(cleaned)
        except ValueError:
            return ChangeSeverity[cleaned.upper()]

    @staticmethod
    def _parse_stage(raw: str) -> ChangeStage:
        cleaned = raw.strip()
        try:
            return ChangeStage(cleaned)
        except ValueError:
            return ChangeStage[cleaned.upper()]
