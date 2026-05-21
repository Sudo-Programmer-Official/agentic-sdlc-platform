from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, WorkItem
from app.runtime.execution_contract import build_execution_contract

PHASE_BY_TYPE = {
    "PLAN_DAG": "plan",
    "PLAN_BACKEND_TOPOLOGY": "plan",
    "GENERATE_ROUTE": "build",
    "GENERATE_SERVICE": "build",
    "GENERATE_REPOSITORY": "build",
    "GENERATE_CAPABILITY_BINDING": "build",
    "CODE_BACKEND": "build",
    "GENESIS_FOUNDATION": "build",
    "CODE_FRONTEND": "build",
    "FRAMEWORK_VALIDATE": "verify",
    "WRITE_TESTS": "verify",
    "RUN_TESTS": "verify",
    "PREVIEW_VALIDATE": "review",
    "REVIEW_DIFF": "review",
    "REVIEW_INTEGRATION": "review",
}

RATIONALE_BY_TYPE = {
    "PLAN_DAG": "Translate the run goal into a bounded execution graph before code changes start.",
    "PLAN_BACKEND_TOPOLOGY": "Generate a capability-aware backend topology contract (routes, services, repositories, schemas, capability modules).",
    "GENERATE_ROUTE": "Generate route module bounded by the backend topology contract.",
    "GENERATE_SERVICE": "Generate service module bounded by the backend topology contract.",
    "GENERATE_REPOSITORY": "Generate repository module bounded by the backend topology contract.",
    "GENERATE_CAPABILITY_BINDING": "Generate capability binding module bounded by the backend topology contract.",
    "CODE_BACKEND": "Apply the smallest backend patch needed to move the goal forward.",
    "GENESIS_FOUNDATION": "Establish a production-grade frontend foundation shell before feature mutations.",
    "CODE_FRONTEND": "Apply the smallest frontend patch needed to move the goal forward.",
    "FRAMEWORK_VALIDATE": "Run framework-native frontend compiler validation and repair syntax before tests or preview.",
    "WRITE_TESTS": "Prepare or adjust tests so the patch can be validated and reviewed safely.",
    "RUN_TESTS": "Run the relevant test suite before continuing to review or preview.",
    "PREVIEW_VALIDATE": "Validate preview/runtime readiness before final integration review.",
    "REVIEW_DIFF": "Evaluate the patch for scope, confidence, and review readiness.",
    "REVIEW_INTEGRATION": "Confirm the assembled change is ready for handoff.",
}

SUCCESS_CRITERIA_BY_TYPE = {
    "PLAN_DAG": ["Execution steps are staged with explicit dependencies."],
    "PLAN_BACKEND_TOPOLOGY": ["Backend module boundaries and capability usage are explicitly planned before code generation."],
    "GENERATE_ROUTE": ["Route module is generated without violating layer boundaries."],
    "GENERATE_SERVICE": ["Service module is generated with capability-aware orchestration."],
    "GENERATE_REPOSITORY": ["Repository module is generated with persistence-only responsibilities."],
    "GENERATE_CAPABILITY_BINDING": ["Capability integration module is generated using runtime capability resolution contract."],
    "CODE_BACKEND": ["Backend patch stays inside the intended subsystem."],
    "GENESIS_FOUNDATION": ["Frontend foundation shell is established and ready for feature-level mutations."],
    "CODE_FRONTEND": ["Frontend patch stays inside the intended subsystem."],
    "FRAMEWORK_VALIDATE": ["Framework syntax validation passes or deterministic syntax repair succeeds."],
    "WRITE_TESTS": ["Relevant tests are ready to validate the change."],
    "RUN_TESTS": ["Validation tests complete without failures."],
    "PREVIEW_VALIDATE": ["Preview/runtime readiness checks pass for the scoped change."],
    "REVIEW_DIFF": ["Patch review signals are recorded before approval."],
    "REVIEW_INTEGRATION": ["Run is ready for preview or pull request creation."],
}

EXPECTED_COMMANDS_BY_TYPE = {
    "PLAN_DAG": ["plan run DAG"],
    "PLAN_BACKEND_TOPOLOGY": ["plan backend topology"],
    "GENERATE_ROUTE": ["generate route module"],
    "GENERATE_SERVICE": ["generate service module"],
    "GENERATE_REPOSITORY": ["generate repository module"],
    "GENERATE_CAPABILITY_BINDING": ["generate capability binding module"],
    "CODE_BACKEND": ["apply backend patch"],
    "GENESIS_FOUNDATION": ["build frontend foundation shell"],
    "CODE_FRONTEND": ["apply frontend patch"],
    "FRAMEWORK_VALIDATE": ["validate frontend framework syntax"],
    "WRITE_TESTS": ["update tests"],
    "RUN_TESTS": ["run tests"],
    "PREVIEW_VALIDATE": ["validate preview"],
    "REVIEW_DIFF": ["review diff"],
    "REVIEW_INTEGRATION": ["review integration"],
}

_SINGULAR_PATH_KEYS = ("file", "filepath", "path", "target_file")
_LIST_PATH_KEYS = ("files", "expected_files")


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


def _expected_files_for_payload(payload: dict | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    files: list[str] = []
    for key in _SINGULAR_PATH_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            files.append(value.strip())
    for key in _LIST_PATH_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            files.extend(str(path).strip() for path in value if isinstance(path, str) and path.strip())
    return list(dict.fromkeys(files))


def build_plan_snapshot(run: Run, work_items: list[WorkItem]) -> dict:
    steps = []
    for item in work_items:
        expected_files = _expected_files_for_payload(item.payload)
        steps.append(
            {
                "id": str(item.id),
                "title": _work_item_title(item),
                "phase": PHASE_BY_TYPE.get(item.type, "execute"),
                "status": item.status,
                "rationale": RATIONALE_BY_TYPE.get(item.type, "Carry the run forward with the next bounded step."),
                "success_criteria": SUCCESS_CRITERIA_BY_TYPE.get(item.type, ["Step completes without runtime errors."]),
                "expected_files": expected_files,
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
    expected_files = list(
        dict.fromkeys(path for step in steps for path in step["expected_files"])
    )
    validation_steps = [step["title"] for step in steps if step["phase"] in {"verify", "review"}]

    return {
        "goal": _goal_for_run(run),
        "rationale": "Execute a bounded run plan, validate the patch, and only hand work off once review signals are readable.",
        "success_criteria": success_criteria,
        "expected_files": expected_files,
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
    summary["execution_contract"] = build_execution_contract(
        run_summary=summary,
        architecture_profile=(summary.get("architecture_profile") if isinstance(summary.get("architecture_profile"), dict) else None),
        plan_snapshot=snapshot,
        previous_contract=summary.get("execution_contract"),
    ).to_dict()
    run.summary = summary
    session.add(run)
    await session.flush()

    if run.workspace_root:
        context_dir = Path(run.workspace_root) / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        (context_dir / "plan.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        (context_dir / "execution_contract.json").write_text(
            json.dumps(summary["execution_contract"], indent=2) + "\n",
            encoding="utf-8",
        )

    return snapshot
