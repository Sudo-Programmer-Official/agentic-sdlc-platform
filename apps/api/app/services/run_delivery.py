from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run
from app.services.event_log import record_event
from app.services.repo_connector import (
    commit_all,
    current_head_sha,
    github_app_runtime_configured,
    normalize_auth_strategy,
    get_project_repository,
    push_branch,
    repo_has_changes,
)


def _commit_message_for_run(run: Run) -> str:
    summary = run.summary or {}
    for key in ("goal", "title", "strategy_goal"):
        value = summary.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip().splitlines()[0]
            return f"Agentic SDLC: {text[:72]}".strip()
    return f"Agentic SDLC run {run.id}"


async def publish_run_branch_if_ready(
    session: AsyncSession,
    *,
    run: Run,
    actor_type: str = "SYSTEM",
    actor_id: str | None = None,
    auth_strategy_override: str | None = None,
) -> dict | None:
    if run.workspace_status != "SEEDED" or not run.repo_path:
        return None

    repo_path = Path(run.repo_path)
    if not repo_path.exists() or not (repo_path / ".git").exists():
        return None

    project_repo = await get_project_repository(session, project_id=run.project_id, tenant_id=run.tenant_id)
    if project_repo is None:
        return None

    branch_name = (run.branch_name or f"run/{str(run.id)[:8]}").strip()
    created_commit = repo_has_changes(repo_path)
    commit_sha = commit_all(repo_path, _commit_message_for_run(run)) if created_commit else current_head_sha(repo_path)
    selected_strategy = normalize_auth_strategy(auth_strategy_override or project_repo.auth_strategy)
    fallback_order = ["github_app", "ssh", "public_https", "runtime_default"]
    strategy_attempts: list[str] = []
    skip_github_app_runtime = not github_app_runtime_configured()
    for candidate in [selected_strategy, *fallback_order]:
        normalized = normalize_auth_strategy(candidate)
        if skip_github_app_runtime and normalized in {"github_app", "runtime_default"}:
            continue
        if normalized not in strategy_attempts:
            strategy_attempts.append(normalized)
    if not strategy_attempts:
        # Always keep at least one explicit non-app fallback.
        strategy_attempts = ["ssh", "public_https"]

    push_errors: list[str] = []
    successful_strategy: str | None = None
    for strategy in strategy_attempts:
        try:
            push_branch(
                repo_path,
                branch_name,
                provider=project_repo.provider,
                repo_url=project_repo.repo_url,
                repo_full_name=project_repo.repo_full_name,
                installation_id=project_repo.installation_id,
                auth_strategy=strategy,
            )
            successful_strategy = strategy
            break
        except Exception as exc:
            push_errors.append(f"{strategy}: {exc}")
    if successful_strategy is None:
        raise RuntimeError("Push failed across strategies: " + " | ".join(push_errors))
    if project_repo.auth_strategy != successful_strategy:
        project_repo.auth_strategy = successful_strategy
        session.add(project_repo)

    pushed_at = datetime.now(timezone.utc).isoformat()
    summary = dict(run.summary or {})
    summary.update(
        {
            "remote_branch_pushed": True,
            "remote_branch_name": branch_name,
            "remote_branch_commit_sha": commit_sha,
            "remote_branch_pushed_at": pushed_at,
            "remote_branch_created_commit": created_commit,
            "remote_branch_auth_strategy": successful_strategy,
            "remote_branch_push_attempts": strategy_attempts,
        }
    )
    summary.pop("remote_branch_push_error", None)
    run.summary = summary
    session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_BRANCH_PUSHED",
        actor_type=actor_type,
        actor_id=actor_id,
        tenant_id=run.tenant_id,
        message=f"Branch {branch_name} pushed to origin at {commit_sha[:7]}.",
        payload={
            "branch_name": branch_name,
            "commit_sha": commit_sha,
            "created_commit": created_commit,
            "repo_url": project_repo.repo_url,
        },
    )
    await session.flush()
    return {
        "branch_name": branch_name,
        "commit_sha": commit_sha,
        "created_commit": created_commit,
    }
