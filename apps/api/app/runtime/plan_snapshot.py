from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, WorkItem

PHASE_BY_TYPE = {
    "PLAN_DAG": "plan",
    "CODE_BACKEND": "build",
    "CODE_FRONTEND": "build",
    "WRITE_TESTS": "verify",
    "RUN_TESTS": "verify",
    "REVIEW_DIFF": "review",
    "REVIEW_INTEGRATION": "review",
}

RATIONALE_BY_TYPE = {
    "PLAN_DAG": "Translate the run goal into a bounded execution graph before code changes start.",
    "CODE_BACKEND": "Apply the smallest backend patch needed to move the goal forward.",
    "CODE_FRONTEND": "Apply the smallest frontend patch needed to move the goal forward.",
    "WRITE_TESTS": "Prepare or adjust tests so the patch can be validated and reviewed safely.",
    "RUN_TESTS": "Run the relevant test suite before continuing to review or preview.",
    "REVIEW_DIFF": "Evaluate the patch for scope, confidence, and review readiness.",
    "REVIEW_INTEGRATION": "Confirm the assembled change is ready for handoff.",
}

SUCCESS_CRITERIA_BY_TYPE = {
    "PLAN_DAG": ["Execution steps are staged with explicit dependencies."],
    "CODE_BACKEND": ["Backend patch stays inside the intended subsystem."],
    "CODE_FRONTEND": ["Frontend patch stays inside the intended subsystem."],
    "WRITE_TESTS": ["Relevant tests are ready to validate the change."],
    "RUN_TESTS": ["Validation tests complete without failures."],
    "REVIEW_DIFF": ["Patch review signals are recorded before approval."],
    "REVIEW_INTEGRATION": ["Run is ready for preview or pull request creation."],
}

EXPECTED_COMMANDS_BY_TYPE = {
    "PLAN_DAG": ["plan run DAG"],
    "CODE_BACKEND": ["apply backend patch"],
    "CODE_FRONTEND": ["apply frontend patch"],
    "WRITE_TESTS": ["update tests"],
    "RUN_TESTS": ["run tests"],
    "REVIEW_DIFF": ["review diff"],
    "REVIEW_INTEGRATION": ["review integration"],
}


def _humanize_token(token: str) -> str:
    return token.replace("_", " ").replace("-", " ").strip().title()


def _work_item_title(item: WorkItem) -> str:
    payload = item.payload or {}
    title = payload.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    if item.key:
        return item.key
    return _humanize_token(item.type)


def _goal_for_run(run: Run) -> str | None:
    if isinstance(run.summary, dict):
        goal = run.summary.get("goal") or run.summary.get("strategy_goal")
        if isinstance(goal, str) and goal.strip():
            return goal.strip()
    return None


def build_plan_snapshot(run: Run, work_items: list[WorkItem]) -> dict:
    steps = []
    for item in work_items:
        steps.append(
            {
                "id": str(item.id),
                "title": _work_item_title(item),
                "phase": PHASE_BY_TYPE.get(item.type, "execute"),
                "status": item.status,
                "rationale": RATIONALE_BY_TYPE.get(item.type, "Carry the run forward with the next bounded step."),
                "success_criteria": SUCCESS_CRITERIA_BY_TYPE.get(item.type, ["Step completes without runtime errors."]),
                "expected_files": [],
                "expected_commands": EXPECTED_COMMANDS_BY_TYPE.get(item.type, []),
                "work_item_id": str(item.id),
                "work_item_type": item.type,
                "executor": item.executor,
            }
        )

    success_criteria = list(
        dict.fromkeys(criterion for step in steps for criterion in step["success_criteria"])
    )
    expected_commands = list(
        dict.fromkeys(command for step in steps for command in step["expected_commands"])
    )
    validation_steps = [step["title"] for step in steps if step["phase"] in {"verify", "review"}]

    return {
        "goal": _goal_for_run(run),
        "rationale": "Execute a bounded run plan, validate the patch, and only hand work off once review signals are readable.",
        "success_criteria": success_criteria,
        "expected_files": [],
        "expected_commands": expected_commands,
        "validation_steps": validation_steps,
        "risk_level": "LOW",
        "confidence_score": None,
        "steps": steps,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "runtime_dag",
    }


async def persist_run_plan_snapshot(session: AsyncSession, run: Run) -> dict:
    work_items = (
        await session.execute(
            select(WorkItem)
            .where(WorkItem.run_id == run.id)
            .order_by(WorkItem.priority.desc(), WorkItem.created_at.asc())
        )
    ).scalars().all()
    snapshot = build_plan_snapshot(run, work_items)
    summary = dict(run.summary or {})
    summary["plan_snapshot"] = snapshot
    run.summary = summary
    session.add(run)
    await session.flush()

    if run.workspace_root:
        context_dir = Path(run.workspace_root) / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        (context_dir / "plan.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")

    return snapshot
