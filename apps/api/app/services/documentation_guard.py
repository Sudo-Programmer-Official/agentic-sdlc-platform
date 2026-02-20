from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from core.ledger import ActionLedger
from core.models import Stage


class DocumentationGuardService:
    def __init__(self, ledger: ActionLedger, docs_root: Path | None = None) -> None:
        self._ledger = ledger
        self._docs_root = docs_root or self._resolve_docs_root()

    def evaluate_guard(self, repo: str, pr_number: int, file_summary: Dict[str, List[str]]) -> dict:
        graph = self._load_json(self._docs_root / "REQUIREMENTS_GRAPH.json")
        plan = self._load_json(self._docs_root / "PLAN.json")

        graph_sha = graph.get("sha256") or graph.get("sha")
        plan_sha = plan.get("requirements_sha")
        plan_stale = bool(graph_sha and plan_sha and graph_sha != plan_sha)

        changed_reqs = plan.get("changed_requirements", []) if plan else []
        impacted = list(dict.fromkeys(changed_reqs)) if plan_stale else []

        status = "WARNING" if plan_stale else "OK"
        message = (
            "Plan is stale relative to requirements. Regenerate plan."
            if plan_stale
            else "Documentation guard passed."
        )

        guard_result = {
            "status": status,
            "impacted_requirements": impacted,
            "plan_stale": plan_stale,
            "message": message,
        }

        # ledger entry (use project_id if derivable later; repo as message for now)
        self._ledger.log(
            run_id="github-webhook",
            project_id="unknown",
            stage=Stage.INTAKE,
            agent_name="documentation-guard",
            tool_name="github-webhook",
            message=f"PR #{pr_number} guard status: {status}",
            details={"repo": repo, "files": file_summary, "guard_result": guard_result},
        )
        return guard_result

    @staticmethod
    def _load_json(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}

    @staticmethod
    def _resolve_docs_root() -> Path:
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "docs").exists() and (parent / "apps").exists():
                return parent / "docs"
        return Path.cwd() / "docs"
