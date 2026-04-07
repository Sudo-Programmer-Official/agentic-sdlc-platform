from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run
from app.services.event_log import record_event
from app.services.repo_connector import (
    commit_all,
    current_head_sha,
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
    push_branch(
        repo_path,
        branch_name,
        provider=project_repo.provider,
        repo_url=project_repo.repo_url,
        repo_full_name=project_repo.repo_full_name,
        installation_id=project_repo.installation_id,
    )

    pushed_at = datetime.now(timezone.utc).isoformat()
    summary = dict(run.summary or {})
    summary.update(
        {
            "remote_branch_pushed": True,
            "remote_branch_name": branch_name,
            "remote_branch_commit_sha": commit_sha,
            "remote_branch_pushed_at": pushed_at,
            "remote_branch_created_commit": created_commit,
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
