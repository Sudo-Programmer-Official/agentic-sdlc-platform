from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Set

from core.execution import ExecutionContext
from core.ledger import ActionLedger
from core.models import Project, Stage

from agent.runtime import PlannerAgent


class PlannerService:
    def __init__(
        self,
        planner_agent: PlannerAgent,
        ledger: ActionLedger,
        project_getter,
        requirements_service,
        docs_root: Optional[Path] = None,
    ) -> None:
        self._planner_agent = planner_agent
        self._ledger = ledger
        self._project_getter = project_getter
        self._requirements_service = requirements_service
        self._docs_root = docs_root or self._resolve_docs_root()
        self._history: dict[str, list[dict]] = {}

    def regenerate_plan(self, project_id: str, triggered_by: str = "system", mode: str = "AUTO") -> dict:
        project: Project = self._project_getter(project_id)
        # must have approved & fresh requirements
        self._requirements_service.assert_approved(project_id)
        self._requirements_service.assert_fresh(project_id)

        context = ExecutionContext(
            project=project,
            run=None,
            task=None,
            stage=Stage.DESIGN_DRAFTED,
            artifacts={},
            approvals={},
            constraints={"max_parallel_tasks": 2},
            registry={"docs_root": self._docs_root, "should_continue": lambda: True},
            logger=self._ledger,
        )
        current_graph = self._requirements_service.get_graph(project_id)
        current_nodes = self._snapshot_nodes(current_graph)
        current_sha = current_graph.compute_hash()

        previous_plan = self._load_plan()
        prev_nodes = previous_plan.get("requirements_nodes") if previous_plan else None
        prev_tasks = previous_plan.get("tasks") if previous_plan else []
        prev_plan_id = previous_plan.get("plan_id") if previous_plan else None

        changed_ids = set()
        regeneration_mode = "FULL"
        if previous_plan and prev_nodes is not None and mode.upper() != "FULL":
            changed_ids = self._diff_requirements(prev_nodes, current_nodes)
            if not changed_ids:
                regeneration_mode = "NONE"
            else:
                regeneration_mode = "PARTIAL"

        result = self._planner_agent.run(context)
        plan_path = result.output or (self._docs_root / "PLAN.json")
        data = plan_path.read_text()
        plan_dict = self._safe_json(data)

        new_tasks = plan_dict.get("tasks", [])
        reused_task_ids: Set[str] = set()
        regenerated_task_ids: Set[str] = set()

        if regeneration_mode == "PARTIAL":
            preserved = [t for t in prev_tasks if not set(t.get("linked_requirements", [])) & changed_ids]
            regenerated = [t for t in new_tasks if set(t.get("linked_requirements", [])) & changed_ids]
            if not regenerated:
                regenerated = new_tasks  # fallback
            combined = preserved + regenerated
            reused_task_ids = {t["task_id"] for t in preserved}
            regenerated_task_ids = {t["task_id"] for t in regenerated}
            plan_dict["tasks"] = combined
        elif regeneration_mode == "NONE":
            plan_dict["tasks"] = prev_tasks
            reused_task_ids = {t["task_id"] for t in prev_tasks}
        else:
            regenerated_task_ids = {t["task_id"] for t in new_tasks}

        created_at = datetime.utcnow().isoformat()
        plan_id = plan_dict.get("plan_id", plan_path.name)

        # augment metadata
        plan_dict.update(
            {
                "requirements_sha": current_sha,
                "requirements_nodes": current_nodes,
                "parent_plan_id": prev_plan_id,
                "regeneration_mode": regeneration_mode,
                "changed_requirements": sorted(list(changed_ids)),
                "reused_task_ids": sorted(list(reused_task_ids)),
                "regenerated_task_ids": sorted(list(regenerated_task_ids)),
                "created_at": created_at,
            }
        )
        plan_path.write_text(self._to_json(plan_dict))

        entry = {
            "version": len(self._history.get(project_id, [])) + 1,
            "plan_id": plan_id,
            "requirements_sha": current_sha,
            "created_at": created_at,
            "triggered_by": triggered_by,
            "plan_path": str(plan_path),
            "regeneration_mode": regeneration_mode,
            "changed_requirements_count": len(changed_ids),
            "reused_count": len(reused_task_ids),
            "regenerated_count": len(regenerated_task_ids),
        }
        self._history.setdefault(project_id, []).append(entry)

        return {
            "plan_path": str(plan_path),
            "created_at": created_at,
            "plan_id": plan_id,
            "requirements_sha": current_sha,
            "raw": self._to_json(plan_dict),
            "regeneration_mode": regeneration_mode,
            "reused_task_ids": sorted(list(reused_task_ids)),
            "regenerated_task_ids": sorted(list(regenerated_task_ids)),
            "changed_requirements": sorted(list(changed_ids)),
        }

    def list_history(self, project_id: str) -> list[dict]:
        return list(self._history.get(project_id, []))

    @staticmethod
    def _snapshot_nodes(graph) -> list[dict]:
        nodes = []
        for node in graph.nodes:
            nodes.append(
                {
                    "id": node.id,
                    "type": node.type.value,
                    "text": node.text,
                    "quality_type": node.quality_type.value if node.quality_type else None,
                }
            )
        return nodes

    @staticmethod
    def _diff_requirements(previous: list[dict], current: list[dict]) -> Set[str]:
        prev_map: Dict[str, dict] = {n["id"]: n for n in previous}
        curr_map: Dict[str, dict] = {n["id"]: n for n in current}
        changed: Set[str] = set()
        for rid, node in curr_map.items():
            if rid not in prev_map:
                changed.add(rid)
                continue
            prev_node = prev_map[rid]
            if (
                node.get("type") != prev_node.get("type")
                or node.get("text") != prev_node.get("text")
                or node.get("quality_type") != prev_node.get("quality_type")
            ):
                changed.add(rid)
        for rid in prev_map.keys():
            if rid not in curr_map:
                changed.add(rid)
        return changed

    @staticmethod
    def _safe_json(raw: str) -> dict:
        try:
            import json

            return json.loads(raw)
        except Exception:
            return {}

    @staticmethod
    def _to_json(obj: dict) -> str:
        import json

        return json.dumps(obj, indent=2)

    @staticmethod
    def _resolve_docs_root() -> Path:
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "docs").exists() and (parent / "apps").exists():
                return parent / "docs"
        return Path.cwd() / "docs"
