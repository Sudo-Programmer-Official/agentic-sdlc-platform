from __future__ import annotations

from typing import List

from core.ledger import ActionLedger
from core.models import ActionLog


class AuditService:
    def __init__(self, ledger: ActionLedger) -> None:
        self._ledger = ledger

    def get_project_audit_logs(self, project_id: str) -> List[ActionLog]:
        logs = self._ledger.get_by_project(project_id)
        return sorted(logs, key=lambda log: log.timestamp)
