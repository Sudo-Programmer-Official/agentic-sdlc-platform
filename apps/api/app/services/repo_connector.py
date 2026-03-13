from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Project, ProjectRepository
from app.services.vcs import get_default_installation_id


def _normalize_provider(provider: str) -> str:
    value = (provider or "github").strip().lower()
    if value != "github":
        raise ValueError("Only github repositories are supported")
    return value


def _normalize_repo_full_name(repo_url: str, repo_full_name: str | None = None) -> str | None:
    if repo_full_name:
        return repo_full_name.strip().removesuffix(".git")

    ssh_match = re.match(r"^git@github\.com:(?P<name>[^/]+/[^/]+?)(?:\.git)?$", repo_url.strip())
    if ssh_match:
        return ssh_match.group("name")

    parsed = urlparse(repo_url)
    if parsed.netloc.lower() != "github.com":
        return None
    path = parsed.path.strip("/").removesuffix(".git")
    if path.count("/") != 1:
        return None
    return path


def _git_env() -> dict[str, str]:
    settings = get_settings()
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", settings.git_author_name)
    env.setdefault("GIT_AUTHOR_EMAIL", settings.git_author_email)
    env.setdefault("GIT_COMMITTER_NAME", settings.git_author_name)
    env.setdefault("GIT_COMMITTER_EMAIL", settings.git_author_email)
    return env


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        env=_git_env(),
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout).strip()
        raise RuntimeError(stderr or f"git {' '.join(args)} failed")
    return (result.stdout or "").strip()


async def get_project_repository(
    session: AsyncSession, *, project_id, tenant_id
) -> ProjectRepository | None:
    return await session.scalar(
        select(ProjectRepository).where(
            ProjectRepository.project_id == project_id,
            ProjectRepository.tenant_id == tenant_id,
        )
    )


async def connect_repo(
    session: AsyncSession,
    *,
    project: Project,
    provider: str,
    repo_url: str,
    default_branch: str,
    repo_full_name: str | None = None,
    installation_id: int | None = None,
    created_by: str | None = None,
) -> ProjectRepository:
    normalized_provider = _normalize_provider(provider)
    cleaned_repo_url = repo_url.strip()
    if not cleaned_repo_url:
        raise ValueError("repo_url is required")

    full_name = _normalize_repo_full_name(cleaned_repo_url, repo_full_name)
    install_id = installation_id or get_default_installation_id(normalized_provider)

    existing = await get_project_repository(session, project_id=project.id, tenant_id=project.tenant_id)
    if existing is None:
        existing = ProjectRepository(project_id=project.id, tenant_id=project.tenant_id)

    existing.provider = normalized_provider
    existing.repo_url = cleaned_repo_url
    existing.repo_full_name = full_name
    existing.default_branch = (default_branch or "main").strip()
    existing.installation_id = install_id
    existing.created_by = created_by or existing.created_by
    session.add(existing)
    await session.flush()
    return existing


def prepare_workspace_repo(
    *,
    repo_dir: Path,
    repo_url: str,
    default_branch: str,
    work_branch: str | None = None,
) -> None:
    repo_dir = repo_dir.resolve()
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if (repo_dir / ".git").exists():
        try:
            _run_git(["remote", "set-url", "origin", repo_url], cwd=repo_dir)
        except RuntimeError:
            _run_git(["remote", "add", "origin", repo_url], cwd=repo_dir)
        _run_git(["fetch", "origin", "--prune"], cwd=repo_dir)
    else:
        _run_git(["clone", repo_url, str(repo_dir)])

    base_branch = (default_branch or "main").strip() or "main"
    target_branch = (work_branch or base_branch).strip() or base_branch

    try:
        _run_git(["checkout", base_branch], cwd=repo_dir)
    except RuntimeError:
        _run_git(["checkout", "-B", base_branch], cwd=repo_dir)

    try:
        _run_git(["reset", "--hard", f"origin/{base_branch}"], cwd=repo_dir)
    except RuntimeError:
        pass

    if target_branch == base_branch:
        return

    try:
        _run_git(["checkout", "-B", target_branch, f"origin/{base_branch}"], cwd=repo_dir)
    except RuntimeError:
        _run_git(["checkout", "-B", target_branch, base_branch], cwd=repo_dir)


def repo_has_changes(repo_dir: Path) -> bool:
    return bool(_run_git(["status", "--porcelain"], cwd=repo_dir))


def commit_all(repo_dir: Path, message: str) -> str:
    _run_git(["add", "-A"], cwd=repo_dir)
    _run_git(["commit", "-m", message], cwd=repo_dir)
    return _run_git(["rev-parse", "HEAD"], cwd=repo_dir)


def push_branch(repo_dir: Path, branch_name: str) -> None:
    _run_git(["push", "-u", "origin", branch_name], cwd=repo_dir)
