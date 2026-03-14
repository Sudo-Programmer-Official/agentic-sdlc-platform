from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.db.models import ProjectRepository
from app.services.repo_connector import prepare_workspace_repo, resolve_repo_runtime_access


@dataclass(frozen=True)
class RepoDiffSnapshot:
    base_ref: str | None
    head_ref: str
    changed_files: list[str]
    diff_text: str
    commit_messages: list[str]


def _knowledge_repo_dir(project_id: uuid.UUID, repository_id: uuid.UUID) -> Path:
    base_dir = Path(get_settings().workspace_base_dir).expanduser().resolve()
    return base_dir / "knowledge" / str(project_id) / str(repository_id) / "repo"


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    git_config: tuple[tuple[str, str], ...] = (),
    allow_failure: bool = False,
) -> str:
    command = ["git"]
    for key, value in git_config:
        command.extend(["-c", f"{key}={value}"])
    command.extend(args)
    result = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0 and not allow_failure:
        raise RuntimeError((result.stderr or result.stdout or "").strip() or f"git {' '.join(args)} failed")
    return (result.stdout or "").strip()


def ensure_analysis_repo(project_repo: ProjectRepository, *, branch_name: str | None = None) -> Path:
    repo_dir = _knowledge_repo_dir(project_repo.project_id, project_repo.id)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    prepare_workspace_repo(
        repo_dir=repo_dir,
        provider=project_repo.provider,
        repo_url=project_repo.repo_url,
        default_branch=project_repo.default_branch,
        repo_full_name=project_repo.repo_full_name,
        installation_id=project_repo.installation_id,
        work_branch=branch_name or project_repo.default_branch,
    )
    return repo_dir


def fetch_origin(project_repo: ProjectRepository, repo_dir: Path) -> None:
    access = resolve_repo_runtime_access(
        provider=project_repo.provider,
        repo_url=project_repo.repo_url,
        repo_full_name=project_repo.repo_full_name,
        installation_id=project_repo.installation_id,
    )
    _run_git(["fetch", "origin", "--prune"], cwd=repo_dir, git_config=access.git_config)


def rev_parse(repo_dir: Path, ref: str, *, allow_failure: bool = False) -> str | None:
    value = _run_git(["rev-parse", ref], cwd=repo_dir, allow_failure=allow_failure)
    return value or None


def current_head(repo_dir: Path, ref: str = "HEAD") -> str | None:
    return rev_parse(repo_dir, ref, allow_failure=True)


def previous_commit(repo_dir: Path, ref: str = "HEAD") -> str | None:
    return rev_parse(repo_dir, f"{ref}^", allow_failure=True)


def diff_snapshot(repo_dir: Path, *, base_ref: str | None, head_ref: str) -> RepoDiffSnapshot:
    if base_ref:
        changed_files = _run_git(["diff", "--name-only", base_ref, head_ref], cwd=repo_dir, allow_failure=True)
        diff_text = _run_git(["diff", base_ref, head_ref], cwd=repo_dir, allow_failure=True)
        commits_text = _run_git(["log", "--format=%s", f"{base_ref}..{head_ref}"], cwd=repo_dir, allow_failure=True)
    else:
        changed_files = _run_git(["show", "--format=", "--name-only", head_ref], cwd=repo_dir, allow_failure=True)
        diff_text = _run_git(["show", "--format=", head_ref], cwd=repo_dir, allow_failure=True)
        commits_text = _run_git(["log", "--format=%s", "-n", "1", head_ref], cwd=repo_dir, allow_failure=True)
    return RepoDiffSnapshot(
        base_ref=base_ref,
        head_ref=head_ref,
        changed_files=[line.strip() for line in changed_files.splitlines() if line.strip()],
        diff_text=diff_text or "",
        commit_messages=[line.strip() for line in commits_text.splitlines() if line.strip()],
    )
