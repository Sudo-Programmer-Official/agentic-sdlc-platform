from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Project, ProjectRepository
from app.services.vcs import get_default_installation_id, get_vcs_adapter
from app.services.vcs.github_app import GitHubAppAdapter

log = logging.getLogger("app.repo_connector")


@dataclass(frozen=True)
class RepoRuntimeAccess:
    auth_mode: str
    clean_repo_url: str
    transport_url: str
    git_config: tuple[tuple[str, str], ...] = ()


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


def git_binary_path() -> str | None:
    return shutil.which("git")


def ensure_git_available() -> str:
    git_binary = git_binary_path()
    if git_binary:
        return git_binary
    raise RuntimeError(
        "git binary is unavailable in the API runtime. Install git in the runtime image before running repo-backed tasks."
    )


def _run_git(
    args: list[str],
    cwd: Path | None = None,
    *,
    git_config: tuple[tuple[str, str], ...] | None = None,
) -> str:
    git_binary = ensure_git_available()
    command = [git_binary]
    for key, value in git_config or ():
        command.extend(["-c", f"{key}={value}"])
    command.extend(args)
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            env=_git_env(),
            check=False,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "git binary is unavailable in the API runtime. Install git in the runtime image before running repo-backed tasks."
        ) from exc
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout).strip()
        raise RuntimeError(stderr or f"git {' '.join(args)} failed")
    return (result.stdout or "").strip()


def _looks_like_github_remote(repo_url: str) -> bool:
    value = repo_url.strip()
    if value.startswith("git@github.com:"):
        return True
    parsed = urlparse(value)
    return parsed.netloc.lower() == "github.com"


def _normalize_repo_url_for_mode(
    *,
    repo_url: str,
    repo_full_name: str | None,
    auth_mode: str,
) -> str:
    cleaned_repo_url = repo_url.strip()
    if not cleaned_repo_url:
        return cleaned_repo_url

    full_name = _normalize_repo_full_name(cleaned_repo_url, repo_full_name)
    if not full_name or not _looks_like_github_remote(cleaned_repo_url):
        return cleaned_repo_url

    mode = (auth_mode or "auto").strip().lower()
    if mode == "ssh":
        return f"git@github.com:{full_name}.git"
    if mode in {"auto", "github_app_https"}:
        return f"https://github.com/{full_name}.git"
    return cleaned_repo_url


def resolve_repo_runtime_access(
    *,
    provider: str,
    repo_url: str,
    repo_full_name: str | None = None,
    installation_id: int | None = None,
) -> RepoRuntimeAccess:
    normalized_provider = _normalize_provider(provider)
    cleaned_repo_url = repo_url.strip()
    full_name = _normalize_repo_full_name(cleaned_repo_url, repo_full_name)
    auth_mode = (get_settings().runtime_git_auth_mode or "auto").strip().lower()

    if normalized_provider == "github" and full_name and _looks_like_github_remote(cleaned_repo_url):
        if auth_mode == "ssh":
            return RepoRuntimeAccess(
                auth_mode="ssh",
                clean_repo_url=cleaned_repo_url,
                transport_url=f"git@github.com:{full_name}.git",
            )

        adapter = get_vcs_adapter(normalized_provider)
        if auth_mode in {"auto", "github_app_https"} and installation_id and isinstance(adapter, GitHubAppAdapter):
            return RepoRuntimeAccess(
                auth_mode="github_app_https",
                clean_repo_url=cleaned_repo_url,
                transport_url=adapter.build_clone_url(full_name),
                git_config=tuple(adapter.build_git_http_config(installation_id)),
            )
        if auth_mode == "github_app_https":
            raise ValueError("GitHub App HTTPS runtime auth requires a valid installation_id and configured GitHub App")

    return RepoRuntimeAccess(
        auth_mode="plain",
        clean_repo_url=cleaned_repo_url,
        transport_url=cleaned_repo_url,
    )


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

    normalized_repo_url = _normalize_repo_url_for_mode(
        repo_url=cleaned_repo_url,
        repo_full_name=repo_full_name,
        auth_mode=get_settings().runtime_git_auth_mode,
    )
    full_name = _normalize_repo_full_name(normalized_repo_url, repo_full_name)
    install_id = installation_id or get_default_installation_id(normalized_provider)

    existing = await get_project_repository(session, project_id=project.id, tenant_id=project.tenant_id)
    if existing is None:
        existing = ProjectRepository(project_id=project.id, tenant_id=project.tenant_id)

    existing.provider = normalized_provider
    existing.repo_url = normalized_repo_url
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
    provider: str,
    repo_url: str,
    default_branch: str,
    repo_full_name: str | None = None,
    installation_id: int | None = None,
    work_branch: str | None = None,
) -> None:
    access = resolve_repo_runtime_access(
        provider=provider,
        repo_url=repo_url,
        repo_full_name=repo_full_name,
        installation_id=installation_id,
    )
    repo_dir = repo_dir.resolve()
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    base_branch = (default_branch or "main").strip() or "main"
    target_branch = (work_branch or base_branch).strip() or base_branch
    log.info(
        "Preparing workspace repository repo_dir=%s provider=%s auth_mode=%s repo_url=%s base_branch=%s target_branch=%s git_binary=%s",
        repo_dir,
        provider,
        access.auth_mode,
        access.clean_repo_url,
        base_branch,
        target_branch,
        git_binary_path() or "missing",
    )

    if (repo_dir / ".git").exists():
        try:
            _run_git(["remote", "set-url", "origin", access.transport_url], cwd=repo_dir)
        except RuntimeError:
            _run_git(["remote", "add", "origin", access.transport_url], cwd=repo_dir)
        _run_git(["fetch", "origin", "--prune"], cwd=repo_dir, git_config=access.git_config)
    else:
        _run_git(["clone", access.transport_url, str(repo_dir)], git_config=access.git_config)

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


def push_branch(
    repo_dir: Path,
    branch_name: str,
    *,
    provider: str,
    repo_url: str,
    repo_full_name: str | None = None,
    installation_id: int | None = None,
) -> None:
    access = resolve_repo_runtime_access(
        provider=provider,
        repo_url=repo_url,
        repo_full_name=repo_full_name,
        installation_id=installation_id,
    )
    _run_git(["push", "-u", "origin", branch_name], cwd=repo_dir, git_config=access.git_config)
