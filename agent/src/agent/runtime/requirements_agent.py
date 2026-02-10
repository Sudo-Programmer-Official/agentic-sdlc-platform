from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from core.execution import AgentResult, AgentType, ExecutionContext
from core.ledger import ActionLedger
from core.models import Stage

from .adapter import AgentRole, BedrockAgentAdapter


@dataclass
class RequirementsInputs:
    project_name: str
    project_description: str
    current_stage: Stage
    existing_docs: Dict[str, str]


class RequirementsAgent:
    name = "requirements_agent"
    agent_type = AgentType.REQUIREMENTS
    supported_stages = {Stage.REQUIREMENTS_DRAFTED}

    def __init__(self, adapter: BedrockAgentAdapter, ledger: ActionLedger) -> None:
        self._adapter = adapter
        self._ledger = ledger

    def run(self, context: ExecutionContext) -> AgentResult:
        stage = context.stage or (context.run.stage if context.run else None)
        if stage != Stage.REQUIREMENTS_DRAFTED:
            raise ValueError("Requirements agent can only run at REQUIREMENTS_DRAFTED")

        docs_root = Path(context.registry.get("docs_root", "docs"))
        should_continue = context.registry.get("should_continue", lambda: True)
        run_id = context.run.run_id if context.run else "unknown"
        project_id = context.project.id if context.project else "unknown"
        project_name = context.project.name if context.project else "Untitled Project"
        project_description = (
            context.project.description if context.project and context.project.description else "No description provided."
        )
        ledger = context.logger or self._ledger

        docs_root.mkdir(parents=True, exist_ok=True)
        if ledger:
            ledger.log(
                run_id=run_id,
                project_id=project_id,
                stage=stage,
                agent_name="requirements_agent",
                tool_name="requirements_agent",
                message="Requirements agent invoked",
                details={"docs_root": str(docs_root)},
            )

        if not should_continue():
            if ledger:
                ledger.log(
                    run_id=run_id,
                    project_id=project_id,
                    stage=stage,
                    agent_name="requirements_agent",
                    tool_name="requirements_agent",
                    message="Requirements agent halted before start",
                )
            return AgentResult(output={})

        existing_docs = self._load_existing_docs(docs_root)
        inputs = RequirementsInputs(
            project_name=project_name or "Untitled Project",
            project_description=project_description or "No description provided.",
            current_stage=stage,
            existing_docs=existing_docs,
        )

        prompt = self._load_prompt_template()
        self._adapter.invoke_agent(
            agent_name="requirements_agent",
            role=AgentRole.REQUIREMENTS,
            input_payload={
                "prompt": prompt,
                "inputs": {
                    "project_name": inputs.project_name,
                    "project_description": inputs.project_description,
                    "current_stage": inputs.current_stage.value,
                    "existing_docs": inputs.existing_docs,
                },
            },
        )

        if not should_continue():
            if ledger:
                ledger.log(
                    run_id=run_id,
                    project_id=project_id,
                    stage=stage,
                    agent_name="requirements_agent",
                    tool_name="requirements_agent",
                    message="Requirements agent halted before write",
                )
            return AgentResult(output={})

        outputs = {
            "PRD.md": self._render_prd(inputs),
            "USER_STORIES.md": self._render_user_stories(inputs),
            "ACCEPTANCE.md": self._render_acceptance(inputs),
        }

        written: Dict[str, Path] = {}
        for filename, content in outputs.items():
            if not should_continue():
                if ledger:
                    ledger.log(
                        run_id=run_id,
                        project_id=project_id,
                        stage=stage,
                        agent_name="requirements_agent",
                        tool_name="requirements_agent",
                        message="Requirements agent halted during write",
                        details={"next_file": filename},
                    )
                break
            path = docs_root / filename
            path.write_text(content)
            written[filename] = path
            if ledger:
                ledger.log(
                    run_id=run_id,
                    project_id=project_id,
                    stage=stage,
                    agent_name="requirements_agent",
                    tool_name="file_write",
                    message=f"Wrote {filename}",
                    details={"path": str(path)},
                )

        if ledger:
            ledger.log(
                run_id=run_id,
                project_id=project_id,
                stage=stage,
                agent_name="requirements_agent",
                tool_name="requirements_agent",
                message="Requirements agent completed",
                details={"files_written": list(written.keys())},
            )
        return AgentResult(output=written)

    @staticmethod
    def _load_existing_docs(docs_root: Path) -> Dict[str, str]:
        docs: Dict[str, str] = {}
        for name in ("PRD.md", "USER_STORIES.md", "ACCEPTANCE.md"):
            path = docs_root / name
            if path.exists():
                docs[name] = path.read_text()
        return docs

    @staticmethod
    def _load_prompt_template() -> str:
        prompt_path = RequirementsAgent._resolve_prompt_path()
        if prompt_path.exists():
            return prompt_path.read_text()
        return "Requirements agent prompt template not found."

    @staticmethod
    def _resolve_prompt_path() -> Path:
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "prompts").exists() and parent.name == "agent":
                return parent / "prompts" / "requirements_agent.md"
        return Path("agent/prompts/requirements_agent.md")

    @staticmethod
    def _render_prd(inputs: RequirementsInputs) -> str:
        return f"""# Product Requirements Document\n\n""" \
            f"""## Project\n{inputs.project_name}\n\n""" \
            f"""## Summary\n{inputs.project_description}\n\n""" \
            """## Goals\n- Capture stakeholder needs\n- Define scope for MVP\n- Establish success criteria\n\n""" \
            """## Non-Goals\n- Production deployment\n- Fine-tuned models\n- Automated code changes\n\n""" \
            """## Requirements\n- Human approval required before stage progression\n- All actions logged to the audit ledger\n- Runs are pauseable and resumable\n\n""" \
            """## Assumptions\n- Documentation is the source of truth\n- Agents are invoked only by the orchestrator\n"""

    @staticmethod
    def _render_user_stories(inputs: RequirementsInputs) -> str:
        return f"""# User Stories\n\n""" \
            """## Primary Persona: Project Owner\n""" \
            """- As a project owner, I want to submit a project description so the system can draft requirements.\n""" \
            """- As a project owner, I want to approve requirements before any implementation begins.\n\n""" \
            """## Primary Persona: Orchestrator\n""" \
            """- As the orchestrator, I want to track runs so execution is auditable.\n""" \
            """- As the orchestrator, I want to pause or cancel runs to maintain control.\n"""

    @staticmethod
    def _render_acceptance(inputs: RequirementsInputs) -> str:
        return """# Acceptance Criteria\n\n""" \
            """- Requirements documents are generated in /docs.\n""" \
            """- Runs cannot advance stages without approvals.\n""" \
            """- Every run lifecycle transition is logged to the audit ledger.\n""" \
            """- Operators can pause/resume/cancel runs without losing audit history.\n"""
