from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol
from uuid import uuid4

from core.models import ActionLog, Stage


class ActionLogStore(Protocol):
    def append(self, record: ActionLog) -> None:
        ...

    def list_by_project(self, project_id: str) -> List[ActionLog]:
        ...


class InMemoryActionLogStore:
    def __init__(self) -> None:
        self._records: Dict[str, List[ActionLog]] = {}

    def append(self, record: ActionLog) -> None:
        self._records.setdefault(record.project_id, []).append(record)

    def list_by_project(self, project_id: str) -> List[ActionLog]:
        return list(self._records.get(project_id, []))


@dataclass
class ActionLogInput:
    run_id: str
    project_id: str
    stage: Stage
    agent_name: str
    tool_name: str
    message: Optional[str] = None
    files_touched: List[str]
    command: Optional[str] = None
    details: Optional[dict] = None


class ActionLedger:
    def __init__(self, store: ActionLogStore) -> None:
        self._store = store

    def record_action(self, action_id: str, payload: ActionLogInput) -> ActionLog:
        record = ActionLog(
            id=action_id,
            run_id=payload.run_id,
            project_id=payload.project_id,
            stage=payload.stage,
            agent_name=payload.agent_name,
            tool_name=payload.tool_name,
            message=payload.message,
            files_touched=payload.files_touched,
            command=payload.command,
            details=payload.details or {},
        )
        self._store.append(record)
        return record

    def log(
        self,
        *,
        run_id: str,
        project_id: str,
        stage: Stage,
        agent_name: str,
        tool_name: str,
        message: str,
        files_touched: Optional[List[str]] = None,
        command: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> ActionLog:
        payload = ActionLogInput(
            run_id=run_id,
            project_id=project_id,
            stage=stage,
            agent_name=agent_name,
            tool_name=tool_name,
            message=message,
            files_touched=files_touched or [],
            command=command,
            details=details,
        )
        return self.record_action(action_id=str(uuid4()), payload=payload)

    def list_actions(self, project_id: str) -> List[ActionLog]:
        return self._store.list_by_project(project_id)

    def get_by_project(self, project_id: str) -> List[ActionLog]:
        return self.list_actions(project_id)
