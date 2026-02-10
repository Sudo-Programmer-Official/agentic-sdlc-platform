from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

from core.execution import AgentResult, AgentType, ExecutionContext
from core.ledger import ActionLedger
from core.models import Stage

from .adapter import AgentRole, BedrockAgentAdapter


@dataclass
class PlannerInputs:
    project_id: str
    project_name: str
    project_description: str
    current_stage: Stage
    artifacts: Dict[str, str]
    max_parallel_tasks: int


class PlannerAgent:
    name = "planner_agent"
    agent_type = AgentType.PLANNER
    supported_stages = {Stage.DESIGN_DRAFTED}

    def __init__(self, adapter: BedrockAgentAdapter, ledger: ActionLedger) -> None:
        self._adapter = adapter
        self._ledger = ledger

    def run(self, context: ExecutionContext) -> AgentResult:
        stage = context.stage or (context.run.stage if context.run else None)
        if stage != Stage.DESIGN_DRAFTED:
            raise ValueError("Planner agent can only run at DESIGN_DRAFTED")

        docs_root = Path(context.registry.get("docs_root", "docs"))
        should_continue = context.registry.get("should_continue", lambda: True)
        run_id = context.run.run_id if context.run else "unknown"
        project_id = context.project.id if context.project else "unknown"
        project_name = context.project.name if context.project else "Untitled Project"
        project_description = (
            context.project.description if context.project and context.project.description else "No description provided."
        )
        max_parallel_tasks = int(context.constraints.get("max_parallel_tasks", 2))
        ledger = context.logger or self._ledger

        docs_root.mkdir(parents=True, exist_ok=True)
        if ledger:
            ledger.log(
                run_id=run_id,
                project_id=project_id,
                stage=stage,
                agent_name="planner_agent",
                tool_name="planner_agent",
                message="Planner agent invoked",
                details={"docs_root": str(docs_root)},
            )

        if not should_continue():
            if ledger:
                ledger.log(
                    run_id=run_id,
                    project_id=project_id,
                    stage=stage,
                    agent_name="planner_agent",
                    tool_name="planner_agent",
                    message="Planner agent halted before start",
                )
            return AgentResult(output=docs_root / "PLAN.json")

        artifacts = self._load_artifacts(docs_root)
        inputs = PlannerInputs(
            project_id=project_id,
            project_name=project_name or "Untitled Project",
            project_description=project_description or "No description provided.",
            current_stage=stage,
            artifacts=artifacts,
            max_parallel_tasks=max_parallel_tasks,
        )

        prompt = self._load_prompt_template()
        self._adapter.invoke_agent(
            agent_name="planner_agent",
            role=AgentRole.PLANNER,
            input_payload={
                "prompt": prompt,
                "inputs": {
                    "project_meta": {
                        "name": inputs.project_name,
                        "description": inputs.project_description,
                    },
                    "artifacts": inputs.artifacts,
                    "constraints": {
                        "max_parallel_tasks": inputs.max_parallel_tasks,
                        "repo_style": "monorepo",
                        "stack": "Vue 3 + FastAPI",
                        "document_first": True,
                    },
                },
            },
        )

        if not should_continue():
            if ledger:
                ledger.log(
                    run_id=run_id,
                    project_id=project_id,
                    stage=stage,
                    agent_name="planner_agent",
                    tool_name="planner_agent",
                    message="Planner agent halted before write",
                )
            return AgentResult(output=docs_root / "PLAN.json")

        plan = self._render_plan(inputs)
        plan_path = docs_root / "PLAN.json"
        plan_path.write_text(json.dumps(plan, indent=2))

        if ledger:
            ledger.log(
                run_id=run_id,
                project_id=project_id,
                stage=stage,
                agent_name="planner_agent",
                tool_name="file_write",
                message="Wrote PLAN.json",
                details={"path": str(plan_path)},
            )

            ledger.log(
                run_id=run_id,
                project_id=project_id,
                stage=stage,
                agent_name="planner_agent",
                tool_name="planner_agent",
                message="Planner agent completed",
            )
        return AgentResult(output=plan_path)

    @staticmethod
    def _load_artifacts(docs_root: Path) -> Dict[str, str]:
        artifacts: Dict[str, str] = {}
        for name in ("PRD.md", "USER_STORIES.md", "ACCEPTANCE.md"):
            path = docs_root / name
            artifacts[name] = path.read_text() if path.exists() else ""
        return artifacts

    @staticmethod
    def _load_prompt_template() -> str:
        prompt_path = PlannerAgent._resolve_prompt_path()
        if prompt_path.exists():
            return prompt_path.read_text()
        return "Planner agent prompt template not found."

    @staticmethod
    def _resolve_prompt_path() -> Path:
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "prompts").exists() and parent.name == "agent":
                return parent / "prompts" / "planner_agent.md"
        return Path("agent/prompts/planner_agent.md")

    @staticmethod
    def _render_plan(inputs: PlannerInputs) -> Dict[str, object]:
        return {
            "plan_id": f"PLAN-{uuid4().hex[:8].upper()}",
            "project_id": inputs.project_id,
            "stage": inputs.current_stage.value,
            "max_parallel_tasks": inputs.max_parallel_tasks,
            "tasks": [
                {
                    "task_id": "T-UI-001",
                    "title": "Draft UI wireframe for intake and approvals",
                    "agent": "UI_AGENT",
                    "inputs": ["PRD.md", "USER_STORIES.md", "ACCEPTANCE.md"],
                    "outputs": ["docs/design/UI_WIREFRAME.md"],
                    "depends_on": [],
                    "parallel_group": "A",
                    "est_effort": "S",
                },
                {
                    "task_id": "T-API-001",
                    "title": "Define API contract for planning endpoints",
                    "agent": "BACKEND_AGENT",
                    "inputs": ["PRD.md", "USER_STORIES.md", "ACCEPTANCE.md"],
                    "outputs": ["docs/design/API_CONTRACT.md"],
                    "depends_on": [],
                    "parallel_group": "A",
                    "est_effort": "S",
                },
                {
                    "task_id": "T-ARCH-001",
                    "title": "Update architecture notes for planner integration",
                    "agent": "ARCH_AGENT",
                    "inputs": ["docs/design/UI_WIREFRAME.md", "docs/design/API_CONTRACT.md"],
                    "outputs": ["docs/design/ARCH_NOTES.md"],
                    "depends_on": ["T-UI-001", "T-API-001"],
                    "parallel_group": "B",
                    "est_effort": "S",
                },
            ],
        }
