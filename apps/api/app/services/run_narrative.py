from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artifact, Run, RunEvent, WorkItem
from app.schemas.persistence import RunOut
from app.schemas.run_narrative import (
    RunNarrativeResponse,
    RunPatchVerificationFinding,
    RunTaskDecomposition,
    RunPlanSnapshot,
    RunPlanStep,
    RunReflectionItem,
    RunWorkingContextSummary,
)
from app.schemas.run_timeline import RunTimelineSummary
from app.core.config import get_settings
from app.services.artifact_diff import parse_unified_diff, resolve_artifact_content
from app.services.patch_verification import build_run_patch_plan_and_verification
from app.services.runtime_env_diagnostics import collect_runtime_startup_diagnostics
from app.services.run_summary_builder import upsert_run_summary
from app.services.task_decomposition import build_task_decomposition
from app.services.work_item_state import is_blocking_failure, is_non_blocking_failure, is_optional_work_item, is_superseded_failure

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
    "PLAN_DAG": "Translate the run goal into bounded execution steps before any code changes begin.",
    "CODE_BACKEND": "Apply the smallest backend patch needed to satisfy the run goal.",
    "CODE_FRONTEND": "Apply the smallest frontend patch needed to satisfy the run goal.",
    "WRITE_TESTS": "Update or add tests so the change is reviewable and reproducible.",
    "RUN_TESTS": "Validate the patch against the relevant test suite before review or delivery.",
    "REVIEW_DIFF": "Score the generated patch for scope, confidence, and review readiness.",
    "REVIEW_INTEGRATION": "Confirm the composed change is safe to hand off for preview or pull request creation.",
}

SUCCESS_CRITERIA_BY_TYPE = {
    "PLAN_DAG": ["Execution steps are queued with a clear dependency order."],
    "CODE_BACKEND": ["Backend changes are applied without expanding beyond the scoped subsystem."],
    "CODE_FRONTEND": ["Frontend changes are applied without expanding beyond the scoped subsystem."],
    "WRITE_TESTS": ["Relevant test coverage is updated for the generated patch."],
    "RUN_TESTS": ["Validation tests complete without failures."],
    "REVIEW_DIFF": ["Patch risk and confidence are recorded before review."],
    "REVIEW_INTEGRATION": ["The run is ready for preview or pull request review."],
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


def _work_item_label(work_item: WorkItem) -> str:
    payload = work_item.payload or {}
    title = payload.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    if work_item.key:
        return work_item.key
    return _humanize_token(work_item.type)


def _summary_str(summary: dict | None, key: str) -> str | None:
    if not isinstance(summary, dict):
        return None
    value = summary.get(key)
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _review_metrics(work_items: list[WorkItem]) -> tuple[float | None, float | None]:
    risk_scores: list[float] = []
    confidence_scores: list[float] = []
    for item in work_items:
        review = (item.result or {}).get("review") if isinstance(item.result, dict) else None
        if not isinstance(review, dict):
            continue
        risk = review.get("risk_score")
        confidence = review.get("confidence")
        if isinstance(risk, (int, float)):
            risk_scores.append(float(risk))
        if isinstance(confidence, (int, float)):
            confidence_scores.append(float(confidence))
    max_risk = max(risk_scores) if risk_scores else None
    avg_confidence = round(sum(confidence_scores) / len(confidence_scores), 3) if confidence_scores else None
    return max_risk, avg_confidence


def _risk_level(*, risk_score: float | None, changed_files: int, recovery_count: int, primary_error: str | None) -> str:
    if (risk_score is not None and risk_score >= 0.7) or changed_files >= 8 or recovery_count >= 2 or primary_error:
        return "HIGH"
    if (risk_score is not None and risk_score >= 0.35) or changed_files >= 4 or recovery_count >= 1:
        return "MEDIUM"
    return "LOW"


def _event_message(event: RunEvent) -> str | None:
    if isinstance(event.message, str) and event.message.strip():
        return event.message.strip()
    payload = event.payload or {}
    message = payload.get("message")
    return message.strip() if isinstance(message, str) and message.strip() else None


def _next_best_step(run: Run, work_items: list[WorkItem], summary: RunTimelineSummary) -> str | None:
    if run.workspace_status == "ERROR":
        return "Resolve the workspace failure and rerun once repository access and persistence are healthy."

    active = next((item for item in work_items if item.status in {"RUNNING", "CLAIMED"}), None)
    if active:
        return f"Wait for {_work_item_label(active)} to finish."

    queued = next((item for item in work_items if item.status == "QUEUED"), None)
    if queued:
        return f"Queue {_work_item_label(queued)} next."

    blocking_failed = next((item for item in work_items if is_blocking_failure(item)), None)
    if blocking_failed:
        return "Inspect the failure and decide whether to retry or fork a safer strategy."

    optional_failed = next((item for item in work_items if is_non_blocking_failure(item)), None)
    if optional_failed and summary.pull_request_url:
        return "Review the warning and decide whether to merge."
    if optional_failed and run.status == "COMPLETED":
        return "Review the warning and decide whether to continue with pull request creation."

    if summary.pull_request_url:
        return "Review the pull request and decide whether to merge."

    if run.status == "COMPLETED":
        return "Open the review surface and create a pull request."

    if run.status == "FAILED":
        return "Review the failure narrative and compare against a previous successful run."

    return None


def _validation_state(run: Run, work_items: list[WorkItem]) -> str:
    if run.workspace_status == "ERROR":
        return "BLOCKED"
    validation_items = [
        item for item in work_items if item.type in {"WRITE_TESTS", "RUN_TESTS", "REVIEW_DIFF", "REVIEW_INTEGRATION"}
    ]
    effective_validation_items = [item for item in validation_items if not is_superseded_failure(item)]
    if not effective_validation_items:
        return "NOT_STARTED"
    if any(is_blocking_failure(item) for item in effective_validation_items):
        return "FAILED"
    if any(item.status in {"RUNNING", "CLAIMED", "QUEUED"} for item in effective_validation_items):
        return "PENDING"
    if any(is_non_blocking_failure(item) for item in effective_validation_items):
        return "PASSED_WITH_WARNINGS"
    if all(item.status in {"DONE", "SKIPPED"} for item in effective_validation_items):
        return "PASSED"
    return "IN_PROGRESS"


def _review_state(run: Run, summary: RunTimelineSummary, work_items: list[WorkItem]) -> str:
    if run.workspace_status == "ERROR":
        return "BLOCKED"
    if summary.pull_request_url:
        return "PULL_REQUEST_READY"
    if isinstance(run.summary, dict):
        approval_status = run.summary.get("approval_status")
        if isinstance(approval_status, str) and approval_status:
            return approval_status
    review_items = [item for item in work_items if item.type in {"REVIEW_DIFF", "REVIEW_INTEGRATION"}]
    effective_review_items = [item for item in review_items if not is_superseded_failure(item)]
    if any(is_blocking_failure(item) for item in effective_review_items):
        return "CHANGES_REQUESTED"
    if any(is_non_blocking_failure(item) for item in effective_review_items):
        return "REVIEWED_WITH_WARNINGS"
    if effective_review_items and all(item.status in {"DONE", "SKIPPED"} for item in effective_review_items):
        return "REVIEWED"
    if effective_review_items:
        return "PENDING_REVIEW"
    return "NOT_STARTED"


async def build_run_narrative(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
) -> RunNarrativeResponse:
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id))
    if run is None:
        raise ValueError("Run not found")

    work_items = (
        await session.execute(
            select(WorkItem)
            .where(WorkItem.run_id == run.id, WorkItem.tenant_id == tenant_id)
            .order_by(WorkItem.priority.desc(), WorkItem.created_at.asc())
        )
    ).scalars().all()
    events = (
        await session.execute(
            select(RunEvent)
            .where(RunEvent.run_id == run.id, RunEvent.tenant_id == tenant_id)
            .order_by(RunEvent.ts.asc(), RunEvent.id.asc())
        )
    ).scalars().all()
    artifacts = (
        await session.execute(
            select(Artifact)
            .where(Artifact.run_id == run.id, Artifact.tenant_id == tenant_id, Artifact.deleted_at.is_(None))
            .order_by(Artifact.created_at.asc(), Artifact.id.asc())
        )
    ).scalars().all()

    summary = await upsert_run_summary(session, run.id)
    await session.commit()

    artifact_files_by_work_item: dict[uuid.UUID, list[str]] = defaultdict(list)
    changed_files = set(summary.changed_files if summary else [])
    for artifact in artifacts:
        if artifact.type != "git_diff":
            continue
        diff = resolve_artifact_content(run, artifact)
        if not diff:
            continue
        files, _, _ = parse_unified_diff(diff)
        paths = [file.path for file in files if file.path]
        if artifact.work_item_id:
            artifact_files_by_work_item[artifact.work_item_id].extend(paths)
        changed_files.update(paths)

    latest_messages_by_work_item: dict[uuid.UUID, tuple[object, str]] = {}
    latest_non_recovery_messages_by_work_item: dict[uuid.UUID, tuple[object, str]] = {}
    recovery_message_by_work_item: dict[uuid.UUID, str] = {}
    latest_failure = summary.primary_error if summary else None
    latest_warning: str | None = None
    summary_has_primary_error = bool(summary and summary.primary_error)
    active_blocking_failed_work_item_ids = {item.id for item in work_items if is_blocking_failure(item)}
    active_warning_work_item_ids = {item.id for item in work_items if is_non_blocking_failure(item)}
    for event in events:
        if event.work_item_id:
            message = _event_message(event)
            if message:
                latest_messages_by_work_item[event.work_item_id] = (event.ts, message)
                if event.event_type != "WORK_ITEM_RECOVERY":
                    latest_non_recovery_messages_by_work_item[event.work_item_id] = (event.ts, message)
                if event.event_type == "WORK_ITEM_RECOVERY":
                    recovery_message_by_work_item[event.work_item_id] = message
        if not summary_has_primary_error and event.event_type == "WORK_ITEM_FAILED" and event.work_item_id in active_blocking_failed_work_item_ids:
            latest_failure = _event_message(event)
        elif not summary_has_primary_error and event.event_type == "RUN_FAILED" and run.status == "FAILED":
            latest_failure = _event_message(event)
        if event.event_type == "WORK_ITEM_FAILED" and event.work_item_id in active_warning_work_item_ids:
            latest_warning = _event_message(event) or latest_warning

    risk_score, confidence_score = _review_metrics(work_items)
    risk_level = _risk_level(
        risk_score=risk_score,
        changed_files=len(changed_files),
        recovery_count=summary.recovery_count if summary else 0,
        primary_error=summary.primary_error if summary else None,
    )

    plan_steps: list[RunPlanStep] = []
    reflections: list[RunReflectionItem] = []
    for index, item in enumerate(work_items):
        label = _work_item_label(item)
        files_for_item = sorted(set(artifact_files_by_work_item.get(item.id, [])))
        plan_steps.append(
            RunPlanStep(
                id=str(item.id),
                title=label,
                phase=PHASE_BY_TYPE.get(item.type, "execute"),
                status=item.status,
                blocking=not is_optional_work_item(item),
                rationale=RATIONALE_BY_TYPE.get(item.type, "Carry the run forward with the next scoped execution step."),
                success_criteria=SUCCESS_CRITERIA_BY_TYPE.get(item.type, ["Step completes without runtime errors."]),
                expected_files=files_for_item,
                expected_commands=EXPECTED_COMMANDS_BY_TYPE.get(item.type, []),
                work_item_id=item.id,
                work_item_type=item.type,
                executor=item.executor,
            )
        )

        message = None
        if item.id in latest_non_recovery_messages_by_work_item:
            message = latest_non_recovery_messages_by_work_item[item.id][1]
        elif item.id in latest_messages_by_work_item:
            message = latest_messages_by_work_item[item.id][1]
        if not message and item.last_error:
            message = item.last_error
        if not message:
            if item.status == "DONE":
                message = f"{label} completed successfully."
            elif item.status == "SKIPPED":
                message = f"{label} was skipped because validation was not required."
            elif is_non_blocking_failure(item):
                message = f"{label} failed without blocking run completion."
            elif item.status in {"RUNNING", "CLAIMED"}:
                message = f"{label} is currently in progress."
            elif item.status == "QUEUED":
                message = f"{label} is queued and waiting on dependencies."
            else:
                message = f"{label} ended with status {item.status}."

        next_label = _work_item_label(work_items[index + 1]) if index + 1 < len(work_items) else None
        changed_next = (
            recovery_message_by_work_item.get(item.id)
            or ("Optional warning recorded; remaining delivery steps can still continue." if is_non_blocking_failure(item) else None)
            or (f"Next planned step: {next_label}." if next_label else None)
        )
        reflections.append(
            RunReflectionItem(
                id=f"reflection:{item.id}",
                ts=item.finished_at or item.started_at or item.created_at,
                title=label,
                status=item.status,
                blocking=not is_optional_work_item(item),
                happened=message,
                matched_plan=True if item.status in {"DONE", "SKIPPED"} else False if item.status in {"FAILED", "CANCELED"} else None,
                changed_next=changed_next,
                files_touched=files_for_item,
                work_item_id=item.id,
                event_type=(
                    "WORK_ITEM_DONE"
                    if item.status == "DONE"
                    else "WORK_ITEM_SKIPPED"
                    if item.status == "SKIPPED"
                    else "WORK_ITEM_FAILED"
                    if item.status == "FAILED"
                    else "WORK_ITEM_STARTED"
                ),
            )
        )

    current_step = None
    active_item = next((item for item in work_items if item.status in {"RUNNING", "CLAIMED"}), None)
    if active_item:
        current_step = _work_item_label(active_item)
    else:
        last_finished = next((item for item in reversed(work_items) if item.status in {"DONE", "SKIPPED", "FAILED", "CANCELED"}), None)
        if last_finished:
            current_step = _work_item_label(last_finished)

    goal = None
    if summary and summary.goal_text:
        goal = summary.goal_text
    elif isinstance(run.summary, dict):
        raw_goal = run.summary.get("goal") or run.summary.get("strategy_goal")
        if isinstance(raw_goal, str) and raw_goal.strip():
            goal = raw_goal.strip()

    stored_plan = (run.summary or {}).get("plan_snapshot") if isinstance(run.summary, dict) else None
    stored_decomposition = (run.summary or {}).get("task_decomposition") if isinstance(run.summary, dict) else None
    validation_steps = [
        step.title
        for step in plan_steps
        if step.phase in {"verify", "review"}
    ]
    deduped_commands = list(dict.fromkeys(command for step in plan_steps for command in step.expected_commands))

    timeline_summary = RunTimelineSummary(
        goal_text=(summary.goal_text if summary else None) or goal,
        status=run.status,
        executor=run.executor,
        branch_name=run.branch_name,
        workspace_status=run.workspace_status,
        elapsed_seconds=summary.elapsed_seconds if summary else None,
        recovery_count=summary.recovery_count if summary else 0,
        artifact_count=summary.artifact_count if summary else len(artifacts),
        changed_files=sorted(changed_files) if changed_files else list(summary.changed_files) if summary else [],
        primary_error=(summary.primary_error if summary else None) or latest_failure,
        pull_request_url=summary.pr_url if summary else None,
    )

    if isinstance(stored_plan, dict):
        stored_steps = stored_plan.get("steps", [])
        step_overrides = {
            str(step.work_item_id): step for step in plan_steps if step.work_item_id is not None
        }
        normalized_steps: list[RunPlanStep] = []
        for raw in stored_steps:
            if not isinstance(raw, dict):
                continue
            work_item_id = raw.get("work_item_id")
            override = step_overrides.get(str(work_item_id)) if work_item_id else None
            normalized_steps.append(
                RunPlanStep(
                    id=str(raw.get("id") or work_item_id or raw.get("title") or uuid.uuid4()),
                    title=(raw.get("title") or (override.title if override else None) or "Plan step"),
                    phase=(raw.get("phase") or (override.phase if override else None) or "execute"),
                    status=override.status if override else str(raw.get("status") or "QUEUED"),
                    rationale=raw.get("rationale") or (override.rationale if override else None),
                    success_criteria=list(raw.get("success_criteria") or (override.success_criteria if override else [])),
                    expected_files=list(raw.get("expected_files") or (override.expected_files if override else [])),
                    expected_commands=list(raw.get("expected_commands") or (override.expected_commands if override else [])),
                    work_item_id=override.work_item_id if override else raw.get("work_item_id"),
                    work_item_type=override.work_item_type if override else raw.get("work_item_type"),
                    executor=override.executor if override else raw.get("executor"),
                )
            )
        if not normalized_steps:
            normalized_steps = plan_steps
        plan = RunPlanSnapshot(
            goal=stored_plan.get("goal") or goal,
            rationale=stored_plan.get("rationale") or "Execute a bounded run plan, validate the patch, and only hand off work once review signals are readable.",
            success_criteria=list(stored_plan.get("success_criteria") or list(dict.fromkeys(
                criterion for step in normalized_steps for criterion in step.success_criteria
            ))),
            expected_files=sorted(changed_files) if changed_files else list(stored_plan.get("expected_files") or []),
            expected_commands=list(stored_plan.get("expected_commands") or deduped_commands),
            validation_steps=list(stored_plan.get("validation_steps") or validation_steps),
            risk_level=risk_level if risk_level != "LOW" else str(stored_plan.get("risk_level") or "LOW"),
            confidence_score=confidence_score if confidence_score is not None else stored_plan.get("confidence_score"),
            steps=normalized_steps,
        )
    else:
        plan = RunPlanSnapshot(
            goal=goal,
            rationale="Execute a bounded run plan, validate the patch, and only hand off work once review signals are readable.",
            success_criteria=list(
                dict.fromkeys(
                    criterion for step in plan_steps for criterion in step.success_criteria
                )
            ),
            expected_files=sorted(changed_files),
            expected_commands=deduped_commands,
            validation_steps=validation_steps,
            risk_level=risk_level,
            confidence_score=confidence_score,
            steps=plan_steps,
        )

    patch_plan, verification = await build_run_patch_plan_and_verification(
        session,
        tenant_id=tenant_id,
        run=run,
        goal=plan.goal,
        planned_steps=[step.title for step in plan.steps],
        planned_files=list(plan.expected_files or []),
        confidence_score=plan.confidence_score,
    )
    planned_scope = {
        *patch_plan.primary_files,
        *patch_plan.dependent_files,
        *patch_plan.related_tests,
    }
    actual_files = sorted(changed_files)
    extra_files = sorted(set(actual_files) - planned_scope) if planned_scope else []
    missing_files = sorted(set(patch_plan.primary_files) - set(actual_files))
    verification.actual_files = actual_files
    verification.extra_files = extra_files
    verification.missing_files = missing_files
    verification.scope_match = None if not actual_files else not extra_files
    if extra_files:
        verification.findings.append(
            RunPatchVerificationFinding(
                code="scope_drift",
                severity="high",
                title="Patch drifted beyond the planned scope",
                detail="The final changed files exceeded the planned patch envelope and should be reviewed before approval.",
                files=extra_files[:8],
            )
        )

    task_decomposition = RunTaskDecomposition.model_validate(
        stored_decomposition if isinstance(stored_decomposition, dict) else build_task_decomposition(run, work_items)
    )
    settings = get_settings()
    runtime_diagnostics = collect_runtime_startup_diagnostics(settings.runtime_mode, settings.runtime_git_auth_mode)
    summary_payload = run.summary if isinstance(run.summary, dict) else {}
    delivery_commit_sha = _summary_str(summary_payload, "pull_request_commit_sha") or _summary_str(
        summary_payload, "remote_branch_commit_sha"
    )
    pull_request_number = summary_payload.get("pull_request_number") if isinstance(summary_payload, dict) else None
    if isinstance(pull_request_number, str) and pull_request_number.isdigit():
        pull_request_number = int(pull_request_number)

    working_context = RunWorkingContextSummary(
        goal=goal,
        current_step=current_step,
        next_best_step=_next_best_step(run, work_items, timeline_summary),
        files_touched=sorted(changed_files),
        latest_failure=latest_failure,
        latest_warning=latest_warning,
        validation_state=_validation_state(run, work_items),
        review_state=_review_state(run, timeline_summary, work_items),
        recovery_count=timeline_summary.recovery_count,
        blocking_failure_count=len(active_blocking_failed_work_item_ids),
        warning_failure_count=len(active_warning_work_item_ids),
        workspace_status=run.workspace_status,
        branch_name=run.branch_name,
        confidence_score=confidence_score,
        risk_level=risk_level,
        pull_request_url=timeline_summary.pull_request_url,
        pull_request_number=pull_request_number if isinstance(pull_request_number, int) else None,
        delivery_pushed=bool(summary_payload.get("remote_branch_pushed")),
        delivery_branch_name=_summary_str(summary_payload, "remote_branch_name") or run.branch_name,
        delivery_commit_sha=delivery_commit_sha,
        delivery_pushed_at=_summary_str(summary_payload, "remote_branch_pushed_at"),
        runtime_mode=runtime_diagnostics.runtime_mode,
        runtime_git_auth_mode=runtime_diagnostics.runtime_git_auth_mode,
        runtime_git_auth_status=runtime_diagnostics.runtime_git_auth_status,
        runtime_git_auth_ready=runtime_diagnostics.runtime_git_auth_ready,
        runtime_git_auth_missing=list(runtime_diagnostics.runtime_git_auth_missing),
        git_binary=runtime_diagnostics.git_binary,
        ssh_binary=runtime_diagnostics.ssh_binary,
        github_clone_auth_status=runtime_diagnostics.github_clone_auth_status,
        github_clone_auth_ready=runtime_diagnostics.github_clone_auth_ready,
        github_clone_auth_missing=list(runtime_diagnostics.github_clone_auth_missing),
        github_app_id_present=runtime_diagnostics.github_app_id_present,
        github_private_key_present=runtime_diagnostics.github_private_key_present,
        github_webhook_secret_present=runtime_diagnostics.github_webhook_secret_present,
    )

    return RunNarrativeResponse(
        run=RunOut.model_validate(run),
        summary=timeline_summary,
        plan=plan,
        task_decomposition=task_decomposition,
        patch_plan=patch_plan,
        verification=verification,
        reflections=reflections,
        working_context=working_context,
    )
