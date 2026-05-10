from __future__ import annotations

import os
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Approval, Artifact, Run, Trace
from app.runtime.tools.repo_tools import RepoTools
from app.services.activity_log import log_activity
from app.services.event_log import record_event
from app.services.repo_connector import (
    branch_has_commits_ahead,
    commit_all,
    current_head_sha,
    get_project_repository,
    prepare_workspace_repo,
    push_branch,
    remote_branch_exists,
    repo_has_changes,
)
from app.services.vcs import get_vcs_adapter
from app.services.workspace_supervisor import ensure_run_workspace

_FORBIDDEN_PATCH_PATH_PARTS = {"__pycache__", ".pytest_cache"}
_FORBIDDEN_PATCH_SUFFIXES = {".pyc", ".pyo"}


def _is_forbidden_patch_path(path: str) -> bool:
    normalized = path.replace("\\", "/").strip()
    if not normalized:
        return False
    if normalized.startswith(("a/", "b/")):
        normalized = normalized[2:]
    pure = Path(normalized)
    if any(part.lower() in _FORBIDDEN_PATCH_PATH_PARTS for part in pure.parts):
        return True
    return pure.suffix.lower() in _FORBIDDEN_PATCH_SUFFIXES


def _sanitize_patch_for_pr(diff: str) -> tuple[str, list[str]]:
    lines = diff.splitlines()
    kept_lines: list[str] = []
    removed_files: list[str] = []
    current_chunk: list[str] = []
    current_path: str | None = None
    current_forbidden = False
    seen_header = False

    def _flush_chunk() -> None:
        nonlocal current_chunk, current_path, current_forbidden, seen_header
        if not current_chunk:
            return
        if current_forbidden:
            if current_path and current_path not in removed_files:
                removed_files.append(current_path)
        else:
            kept_lines.extend(current_chunk)
        current_chunk = []
        current_path = None
        current_forbidden = False
        seen_header = False

    for line in lines:
        if line.startswith("diff --git "):
            _flush_chunk()
            seen_header = True
            current_chunk = [line]
            current_path = None
            current_forbidden = False
            parts = line.split()
            if len(parts) >= 4:
                a_path = parts[2]
                b_path = parts[3]
                candidate_paths = [a_path, b_path]
                for candidate in candidate_paths:
                    cleaned = candidate[2:] if candidate.startswith(("a/", "b/")) else candidate
                    if _is_forbidden_patch_path(cleaned):
                        current_path = cleaned
                        current_forbidden = True
                        break
            continue
        if seen_header:
            current_chunk.append(line)
            if line.startswith("+++ "):
                candidate = line.split(maxsplit=1)[1].strip()
                if candidate != "/dev/null":
                    current_path = candidate[2:] if candidate.startswith(("a/", "b/")) else candidate
                    current_forbidden = _is_forbidden_patch_path(current_path)
            continue
        kept_lines.append(line)

    _flush_chunk()
    sanitized = "\n".join(kept_lines)
    if diff.endswith("\n"):
        sanitized += "\n"
    return sanitized, removed_files


def _resolve_patch_content(run: Run, artifact: Artifact) -> str | None:
    if artifact.uri.startswith("workspace://patches/") and run.workspace_root:
        patch_name = artifact.uri.removeprefix("workspace://patches/")
        patch_path = Path(run.workspace_root) / "patches" / patch_name
        if patch_path.exists():
            return patch_path.read_text(encoding="utf-8")
    metadata = artifact.extra_metadata or {}
    content = metadata.get("content")
    if isinstance(content, str) and content.strip():
        return content
    return None


async def create_pr_from_artifact(
    session: AsyncSession,
    *,
    run: Run,
    artifact: Artifact | None = None,
    title: str | None = None,
    body: str | None = None,
    branch_name: str | None = None,
) -> dict:
    project_repo = await get_project_repository(session, project_id=run.project_id, tenant_id=run.tenant_id)
    if project_repo is None:
        raise ValueError("Project repository is not connected")
    adapter = get_vcs_adapter(project_repo.provider)
    if adapter is None:
        provider = str(project_repo.provider or "").strip().lower()
        if provider == "github":
            settings = get_settings()
            missing: list[str] = []
            if not (os.getenv("GITHUB_APP_ID") or settings.github_app_id):
                missing.append("GITHUB_APP_ID")
            if not (os.getenv("GITHUB_PRIVATE_KEY") or settings.github_private_key):
                missing.append("GITHUB_PRIVATE_KEY")
            suffix = f" Missing: {', '.join(missing)}." if missing else ""
            raise RuntimeError(f"GitHub App integration is not configured.{suffix}")
        raise RuntimeError(f"{project_repo.provider} integration is not configured")
    if not project_repo.repo_full_name:
        raise ValueError("Connected repository is missing repo_full_name")

    working_branch = (branch_name or run.branch_name or f"run/{str(run.id)[:8]}").strip()
    if run.branch_name != working_branch:
        run.branch_name = working_branch
        session.add(run)
        await session.flush()

    await ensure_run_workspace(
        session,
        run,
        require_repo=True,
        repo_url=project_repo.repo_url,
        repo_branch=project_repo.default_branch,
        repo_provider=project_repo.provider,
        repo_full_name=project_repo.repo_full_name,
        repo_installation_id=project_repo.installation_id,
        repo_auth_strategy=project_repo.auth_strategy,
    )
    repo_path = Path(run.repo_path or "")
    if not repo_path.exists():
        raise RuntimeError("Run workspace repository is unavailable")

    prepare_workspace_repo(
        repo_dir=repo_path,
        provider=project_repo.provider,
        repo_url=project_repo.repo_url,
        default_branch=project_repo.default_branch,
        repo_full_name=project_repo.repo_full_name,
        installation_id=project_repo.installation_id,
        auth_strategy=project_repo.auth_strategy,
        work_branch=working_branch,
    )

    if artifact is None:
        artifact = await session.scalar(
            select(Artifact)
            .where(
                Artifact.run_id == run.id,
                Artifact.tenant_id == run.tenant_id,
                Artifact.type == "git_diff",
            )
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    if artifact is None:
        raise ValueError("No patch artifact found for this run")
    if artifact.type != "git_diff":
        raise ValueError("Selected artifact is not a patch artifact")

    latest_approval = await session.scalar(
        select(Approval)
        .where(
            Approval.project_id == run.project_id,
            Approval.tenant_id == run.tenant_id,
            Approval.target_type == "artifact",
            Approval.target_id == artifact.id,
            Approval.deleted_at.is_(None),
        )
        .order_by(Approval.created_at.desc(), Approval.id.desc())
    )
    if latest_approval is None or latest_approval.status != "APPROVED":
        raise ValueError("Patch artifact must be approved before creating a PR")

    summary = run.summary or {}
    remote_branch_present = remote_branch_exists(repo_path, working_branch)
    branch_was_published = (
        bool(summary.get("remote_branch_pushed")) and summary.get("remote_branch_name") == working_branch
    )
    branch_ready_for_pr = remote_branch_present and (
        branch_was_published or branch_has_commits_ahead(repo_path, project_repo.default_branch)
    )
    has_repo_changes = repo_has_changes(repo_path)

    if not has_repo_changes and not branch_ready_for_pr:
        diff = _resolve_patch_content(run, artifact)
        if not diff:
            raise ValueError("Selected artifact does not contain patch content")
        diff, removed_files = _sanitize_patch_for_pr(diff)
        if removed_files:
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                event_type="RUN_PATCH_SANITIZED",
                actor_type="SYSTEM",
                tenant_id=run.tenant_id,
                message="Removed forbidden cache/compiled artifacts from patch before PR apply.",
                payload={"removed_files": removed_files},
            )
        if not diff.strip():
            raise ValueError("Patch artifact only contains forbidden cache/compiled artifacts; regenerate patch.")
        log_dir = Path(run.workspace_root) / "logs" if run.workspace_root else None
        RepoTools(repo_path, logs_path=log_dir).apply_patch(diff)
        has_repo_changes = repo_has_changes(repo_path)

    if not has_repo_changes and not branch_ready_for_pr:
        raise ValueError("No repository changes available to create a PR")

    commit_message = title or f"Agentic SDLC run {run.id}"
    if has_repo_changes:
        commit_sha = commit_all(repo_path, commit_message)
        push_branch(
            repo_path,
            working_branch,
            provider=project_repo.provider,
            repo_url=project_repo.repo_url,
            repo_full_name=project_repo.repo_full_name,
            installation_id=project_repo.installation_id,
            auth_strategy=project_repo.auth_strategy,
        )
    else:
        commit_sha = str(summary.get("remote_branch_commit_sha") or "").strip() or current_head_sha(repo_path)

    pr_payload = adapter.create_pull_request(
        project_repo.repo_full_name,
        title=title or f"Agentic SDLC run {run.id}",
        body=body
        or (
            f"Automated pull request for run `{run.id}`.\n\n"
            f"- Executor: `{run.executor}`\n"
            f"- Branch: `{working_branch}`\n"
        ),
        head=working_branch,
        base=project_repo.default_branch,
        installation_id=project_repo.installation_id,
    )

    pr_url = pr_payload.get("html_url") or pr_payload.get("url")
    pr_number = pr_payload.get("number")
    run.summary = {
        **(run.summary or {}),
        "pull_request_url": pr_url,
        "pull_request_number": pr_number,
        "pull_request_branch": working_branch,
        "pull_request_commit_sha": commit_sha,
    }
    session.add(run)
    pr_artifact = Artifact(
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        run_id=run.id,
        work_item_id=None,
        task_id=None,
        type="pull_request",
        uri=pr_url or f"github://{project_repo.repo_full_name}/pull/{pr_number}",
        version=1,
        extra_metadata={
            "number": pr_number,
            "head": working_branch,
            "base": project_repo.default_branch,
            "commit_sha": commit_sha,
            "repo_full_name": project_repo.repo_full_name,
        },
    )
    session.add(pr_artifact)
    await session.flush()
    session.add(
        Trace(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            from_type="run",
            from_id=run.id,
            to_type="artifact",
            to_id=pr_artifact.id,
            relation_type="produces",
            relation_strength=1.0,
        )
    )
    await log_activity(
        session,
        project_id=run.project_id,
        entity_type="run",
        entity_id=run.id,
        action_type="run.pull_request_created",
        metadata={
            "pull_request_url": pr_url,
            "pull_request_number": pr_number,
            "branch_name": working_branch,
        },
    )
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_PULL_REQUEST_CREATED",
        actor_type="USER",
        payload={
            "pull_request_url": pr_url,
            "pull_request_number": pr_number,
            "branch_name": working_branch,
            "artifact_id": str(pr_artifact.id),
        },
        tenant_id=run.tenant_id,
    )
    await session.commit()
    await session.refresh(run)
    await session.refresh(pr_artifact)

    return {
        "run_id": run.id,
        "artifact_id": pr_artifact.id,
        "pull_request_url": pr_url,
        "pull_request_number": pr_number,
        "branch_name": working_branch,
        "base_branch": project_repo.default_branch,
        "commit_sha": commit_sha,
    }
