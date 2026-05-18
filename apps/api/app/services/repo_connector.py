from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Project, ProjectRepository
from app.services.vcs import InMemoryGitHubIntegrationStore, build_github_adapter, get_default_installation_id, get_vcs_adapter
from app.services.vcs.github_app import GitHubAppAdapter

log = logging.getLogger("app.repo_connector")


@dataclass(frozen=True)
class RepoRuntimeAccess:
    auth_mode: str
    clean_repo_url: str
    transport_url: str
    git_config: tuple[tuple[str, str], ...] = ()
    installation_id: int | None = None
    token_generated: bool = False
    adapter_kind: str | None = None
    credential_strategy: str = "anonymous"
    selection_reason: str | None = None


@dataclass(frozen=True)
class RepoPreflightResult:
    ok: bool
    provider: str
    auth_strategy: str
    auth_mode: str | None
    credential_strategy: str | None
    selection_reason: str | None
    transport_url: str | None
    repo_url: str
    default_branch: str
    installation_id: int | None = None
    token_generated: bool = False
    git_binary: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RepoBootstrapResult:
    ok: bool
    created: bool
    provider: str
    repo_url: str
    default_branch: str
    commit_sha: str | None = None
    message: str = ""
    error: str | None = None


@lru_cache(maxsize=1)
def _lazy_github_adapter_from_env() -> GitHubAppAdapter | None:
    return build_github_adapter(InMemoryGitHubIntegrationStore())


def _github_app_env_presence() -> dict[str, bool]:
    return {
        "app_id_present": bool(os.getenv("GITHUB_APP_ID")),
        "private_key_present": bool(os.getenv("GITHUB_PRIVATE_KEY")),
        "webhook_secret_present": bool(os.getenv("GITHUB_WEBHOOK_SECRET")),
    }


def github_app_runtime_configured() -> bool:
    env_presence = _github_app_env_presence()
    # Runtime clone/push via GitHub App only requires app id + private key.
    # Webhook secret is required for webhook ingestion, not git transport auth.
    return env_presence["app_id_present"] and env_presence["private_key_present"]


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
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
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


def _build_github_http_git_config(token: str, host: str = "https://github.com/") -> tuple[tuple[str, str], ...]:
    basic = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    return ((f"http.{host}.extraheader", f"AUTHORIZATION: Basic {basic}"),)


def _redact_transport_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    if "@" not in parsed.netloc:
        return url
    _, host = parsed.netloc.rsplit("@", 1)
    return parsed._replace(netloc=f"[redacted]@{host}").geturl()


def _redact_git_config_value(key: str, value: str) -> str:
    lowered_key = key.lower()
    if "extraheader" in lowered_key and "authorization" in value.lower():
        prefix = value.split(":", 1)[0] if ":" in value else "AUTHORIZATION"
        scheme = value.split(None, 2)[1] if len(value.split(None, 2)) > 1 else "Basic"
        return f"{prefix}: {scheme} [redacted]"
    if any(token in lowered_key for token in ("token", "authorization", "password")):
        return "[redacted]"
    return value


def _redacted_git_config(git_config: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    return tuple((key, _redact_git_config_value(key, value)) for key, value in git_config)


def _redacted_git_command(
    args: list[str],
    *,
    git_config: tuple[tuple[str, str], ...] | None = None,
) -> list[str]:
    command = ["git"]
    for key, value in _redacted_git_config(tuple(git_config or ())):
        command.extend(["-c", f"{key}={value}"])
    for arg in args:
        if isinstance(arg, str) and "://" in arg:
            command.append(_redact_transport_url(arg))
        else:
            command.append(arg)
    return command


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
    log.info(
        "Executing git command cwd=%s command=%s",
        str(cwd) if cwd else None,
        _redacted_git_command(args, git_config=tuple(git_config or ())),
    )
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


def _is_ssh_remote(repo_url: str) -> bool:
    value = repo_url.strip()
    if value.startswith("git@"):
        return True
    parsed = urlparse(value)
    return parsed.scheme == "ssh"


def normalize_auth_strategy(auth_strategy: str | None) -> str:
    value = (auth_strategy or "runtime_default").strip().lower()
    aliases = {
        "default": "runtime_default",
        "auto": "runtime_default",
        "none": "public_https",
        "plain": "public_https",
        "anonymous_https": "public_https",
        "github_app_https": "github_app",
    }
    value = aliases.get(value, value)
    allowed = {"runtime_default", "public_https", "github_app", "ssh"}
    if value not in allowed:
        raise ValueError("auth_strategy must be one of runtime_default, public_https, github_app, or ssh")
    return value


def _auth_mode_for_strategy(auth_strategy: str | None, runtime_auth_mode: str | None) -> str:
    strategy = normalize_auth_strategy(auth_strategy)
    if strategy == "public_https":
        return "none"
    if strategy == "github_app":
        return "github_app_https"
    if strategy == "ssh":
        return "ssh"
    return (runtime_auth_mode or "auto").strip().lower()


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
        # Respect an explicit HTTPS URL even when runtime mode is ssh so
        # public-repo testing can proceed without forcing SSH transport.
        if _is_ssh_remote(cleaned_repo_url):
            return f"git@github.com:{full_name}.git"
        return f"https://github.com/{full_name}.git"
    if mode in {"auto", "github_app_https", "none"}:
        return f"https://github.com/{full_name}.git"
    return cleaned_repo_url


def resolve_repo_runtime_access(
    *,
    provider: str,
    repo_url: str,
    repo_full_name: str | None = None,
    installation_id: int | None = None,
    auth_strategy: str | None = None,
) -> RepoRuntimeAccess:
    normalized_provider = _normalize_provider(provider)
    auth_mode = _auth_mode_for_strategy(auth_strategy, get_settings().runtime_git_auth_mode)
    cleaned_repo_url = _normalize_repo_url_for_mode(
        repo_url=repo_url.strip(),
        repo_full_name=repo_full_name,
        auth_mode=auth_mode,
    )
    full_name = _normalize_repo_full_name(cleaned_repo_url, repo_full_name)
    adapter = get_vcs_adapter(normalized_provider)
    if adapter is None and normalized_provider == "github":
        adapter = _lazy_github_adapter_from_env()
    adapter_kind = adapter.__class__.__name__ if adapter is not None else None
    resolved_installation_id = installation_id or get_default_installation_id(normalized_provider)
    selection_reason = "github_app_unavailable_or_not_applicable"
    # Only force authenticated GitHub App clone when explicitly requested
    # or when running in auto mode with an installation id present.
    # In `none` mode we should always allow plain HTTPS clone (public repos).
    requires_authenticated_clone = auth_mode == "github_app_https" or (
        auth_mode == "auto" and resolved_installation_id is not None
    )

    if normalized_provider == "github" and full_name and _looks_like_github_remote(cleaned_repo_url):
        if auth_mode == "ssh":
            if not _is_ssh_remote(cleaned_repo_url):
                return RepoRuntimeAccess(
                    auth_mode="plain",
                    clean_repo_url=cleaned_repo_url,
                    transport_url=cleaned_repo_url,
                    installation_id=resolved_installation_id,
                    token_generated=False,
                    adapter_kind=adapter_kind,
                    credential_strategy="anonymous_https",
                    selection_reason="ssh_mode_https_repo_url",
                )
            return RepoRuntimeAccess(
                auth_mode="ssh",
                clean_repo_url=cleaned_repo_url,
                transport_url=f"git@github.com:{full_name}.git",
                installation_id=resolved_installation_id,
                adapter_kind=adapter_kind,
                credential_strategy="ssh",
                selection_reason="explicit_ssh_mode",
            )

        if auth_mode in {"auto", "github_app_https"} and isinstance(adapter, GitHubAppAdapter):
            if resolved_installation_id:
                try:
                    token = str(adapter.get_installation_token(resolved_installation_id) or "").strip()
                except Exception as exc:
                    selection_reason = f"github_app_token_generation_failed:{exc.__class__.__name__}"
                    if requires_authenticated_clone:
                        raise RuntimeError(
                            "GitHub runtime clone auth could not generate an installation token "
                            f"(selection_reason={selection_reason}, installation_id={resolved_installation_id}, "
                            f"adapter={adapter_kind}): {exc.__class__.__name__}: {exc}"
                        ) from exc
                else:
                    if not token:
                        selection_reason = "github_app_token_generation_returned_empty"
                        if requires_authenticated_clone:
                            raise RuntimeError(
                                "GitHub runtime clone auth returned an empty installation token "
                                f"(selection_reason={selection_reason}, installation_id={resolved_installation_id}, "
                                f"adapter={adapter_kind})"
                            )
                    else:
                        return RepoRuntimeAccess(
                            auth_mode="github_app_https",
                            clean_repo_url=cleaned_repo_url,
                            transport_url=adapter.build_clone_url(full_name),
                            git_config=_build_github_http_git_config(token),
                            installation_id=resolved_installation_id,
                            token_generated=True,
                            adapter_kind=adapter_kind,
                            credential_strategy="http.extraheader",
                            selection_reason="github_app_installation_token",
                        )
            else:
                selection_reason = "github_app_installation_id_missing"
        elif auth_mode in {"auto", "github_app_https"}:
            selection_reason = "github_app_adapter_unconfigured"
        if auth_mode == "github_app_https" or requires_authenticated_clone:
            env_presence = _github_app_env_presence() if normalized_provider == "github" else {}
            raise RuntimeError(
                "GitHub runtime clone auth is unavailable "
                f"(selection_reason={selection_reason}, installation_id={resolved_installation_id}, adapter={adapter_kind}, "
                f"app_id_present={env_presence.get('app_id_present')}, "
                f"private_key_present={env_presence.get('private_key_present')}, "
                f"webhook_secret_present={env_presence.get('webhook_secret_present')})"
            )

    return RepoRuntimeAccess(
        auth_mode="plain",
        clean_repo_url=cleaned_repo_url,
        transport_url=cleaned_repo_url,
        installation_id=resolved_installation_id,
        token_generated=False,
        adapter_kind=adapter_kind,
        credential_strategy="anonymous_https",
        selection_reason=selection_reason,
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
    auth_strategy: str | None = None,
    created_by: str | None = None,
) -> ProjectRepository:
    normalized_provider = _normalize_provider(provider)
    cleaned_repo_url = repo_url.strip()
    if not cleaned_repo_url:
        raise ValueError("repo_url is required")

    normalized_auth_strategy = normalize_auth_strategy(auth_strategy)
    auth_mode = _auth_mode_for_strategy(normalized_auth_strategy, get_settings().runtime_git_auth_mode)
    normalized_repo_url = _normalize_repo_url_for_mode(
        repo_url=cleaned_repo_url,
        repo_full_name=repo_full_name,
        auth_mode=auth_mode,
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
    existing.auth_strategy = normalized_auth_strategy
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
    auth_strategy: str | None = None,
    work_branch: str | None = None,
) -> None:
    access = resolve_repo_runtime_access(
        provider=provider,
        repo_url=repo_url,
        repo_full_name=repo_full_name,
        installation_id=installation_id,
        auth_strategy=auth_strategy,
    )
    repo_dir = repo_dir.resolve()
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    base_branch = (default_branch or "main").strip() or "main"
    target_branch = (work_branch or base_branch).strip() or base_branch
    log.info(
        "Preparing workspace repository repo_dir=%s provider=%s auth_mode=%s adapter=%s installation_id=%s token_generated=%s credential_strategy=%s transport_url=%s git_config_present=%s git_config=%s clone_command=%s repo_url=%s base_branch=%s target_branch=%s git_binary=%s selection_reason=%s",
        repo_dir,
        provider,
        access.auth_mode,
        access.adapter_kind,
        access.installation_id,
        access.token_generated,
        access.credential_strategy,
        _redact_transport_url(access.transport_url),
        bool(access.git_config),
        _redacted_git_config(access.git_config),
        _redacted_git_command(["clone", access.transport_url, str(repo_dir)], git_config=access.git_config),
        access.clean_repo_url,
        base_branch,
        target_branch,
        git_binary_path() or "missing",
        access.selection_reason,
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
        _run_git(["reset", "--hard", "HEAD"], cwd=repo_dir)
        _run_git(["clean", "-fd"], cwd=repo_dir)
        return

    if remote_branch_exists(repo_dir, target_branch):
        _run_git(["checkout", "-B", target_branch, f"origin/{target_branch}"], cwd=repo_dir)
    else:
        try:
            _run_git(["checkout", "-B", target_branch, f"origin/{base_branch}"], cwd=repo_dir)
        except RuntimeError:
            _run_git(["checkout", "-B", target_branch, base_branch], cwd=repo_dir)

    _run_git(["reset", "--hard", "HEAD"], cwd=repo_dir)
    _run_git(["clean", "-fd"], cwd=repo_dir)


def checkout_workspace_branch_from_head(
    *,
    repo_dir: Path,
    provider: str,
    repo_url: str,
    branch_name: str,
    repo_full_name: str | None = None,
    installation_id: int | None = None,
    auth_strategy: str | None = None,
) -> None:
    access = resolve_repo_runtime_access(
        provider=provider,
        repo_url=repo_url,
        repo_full_name=repo_full_name,
        installation_id=installation_id,
        auth_strategy=auth_strategy,
    )
    repo_dir = repo_dir.resolve()
    target_branch = branch_name.strip()
    if not target_branch:
        raise ValueError("branch_name is required")

    try:
        _run_git(["remote", "set-url", "origin", access.transport_url], cwd=repo_dir)
    except RuntimeError:
        _run_git(["remote", "add", "origin", access.transport_url], cwd=repo_dir)

    _run_git(["fetch", "origin", "--prune"], cwd=repo_dir, git_config=access.git_config)

    if remote_branch_exists(repo_dir, target_branch):
        _run_git(["checkout", "-B", target_branch, f"origin/{target_branch}"], cwd=repo_dir)
    else:
        _run_git(["checkout", "-B", target_branch, "HEAD"], cwd=repo_dir)

    _run_git(["reset", "--hard", "HEAD"], cwd=repo_dir)
    _run_git(["clean", "-fd"], cwd=repo_dir)


def repo_has_changes(repo_dir: Path) -> bool:
    return bool(_run_git(["status", "--porcelain"], cwd=repo_dir))


def current_head_sha(repo_dir: Path) -> str:
    return _run_git(["rev-parse", "HEAD"], cwd=repo_dir)


def remote_branch_exists(repo_dir: Path, branch_name: str) -> bool:
    try:
        _run_git(["rev-parse", "--verify", f"origin/{branch_name}"], cwd=repo_dir)
    except RuntimeError:
        return False
    return True


def branch_has_commits_ahead(repo_dir: Path, base_branch: str) -> bool:
    try:
        ahead = _run_git(["rev-list", "--count", f"origin/{base_branch}..HEAD"], cwd=repo_dir)
    except RuntimeError:
        return False
    return ahead.strip().isdigit() and int(ahead.strip()) > 0


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
    auth_strategy: str | None = None,
) -> None:
    access = resolve_repo_runtime_access(
        provider=provider,
        repo_url=repo_url,
        repo_full_name=repo_full_name,
        installation_id=installation_id,
        auth_strategy=auth_strategy,
    )
    _run_git(["push", "-u", "origin", branch_name], cwd=repo_dir, git_config=access.git_config)


def preflight_repo_access(
    *,
    provider: str,
    repo_url: str,
    default_branch: str,
    repo_full_name: str | None = None,
    installation_id: int | None = None,
    auth_strategy: str | None = None,
    clone: bool = True,
) -> RepoPreflightResult:
    normalized_provider = _normalize_provider(provider)
    strategy = normalize_auth_strategy(auth_strategy)
    base_branch = (default_branch or "main").strip() or "main"
    access: RepoRuntimeAccess | None = None
    try:
        access = resolve_repo_runtime_access(
            provider=normalized_provider,
            repo_url=repo_url,
            repo_full_name=repo_full_name,
            installation_id=installation_id,
            auth_strategy=strategy,
        )
        _run_git(["ls-remote", "--heads", access.transport_url, base_branch], git_config=access.git_config)
        if clone:
            root = Path(tempfile.mkdtemp(prefix="agentic-sdlc-repo-preflight-"))
            try:
                prepare_workspace_repo(
                    repo_dir=root / "repo",
                    provider=normalized_provider,
                    repo_url=repo_url,
                    default_branch=base_branch,
                    repo_full_name=repo_full_name,
                    installation_id=installation_id,
                    auth_strategy=strategy,
                    work_branch=base_branch,
                )
            finally:
                shutil.rmtree(root, ignore_errors=True)
        return RepoPreflightResult(
            ok=True,
            provider=normalized_provider,
            auth_strategy=strategy,
            auth_mode=access.auth_mode,
            credential_strategy=access.credential_strategy,
            selection_reason=access.selection_reason,
            transport_url=_redact_transport_url(access.transport_url),
            repo_url=access.clean_repo_url,
            default_branch=base_branch,
            installation_id=access.installation_id,
            token_generated=access.token_generated,
            git_binary=git_binary_path(),
        )
    except Exception as exc:
        return RepoPreflightResult(
            ok=False,
            provider=normalized_provider,
            auth_strategy=strategy,
            auth_mode=access.auth_mode if access else None,
            credential_strategy=access.credential_strategy if access else None,
            selection_reason=access.selection_reason if access else None,
            transport_url=_redact_transport_url(access.transport_url) if access else None,
            repo_url=repo_url,
            default_branch=base_branch,
            installation_id=access.installation_id if access else installation_id,
            token_generated=access.token_generated if access else False,
            git_binary=git_binary_path(),
            error=str(exc),
        )


def bootstrap_repo_remote(
    *,
    provider: str,
    repo_url: str,
    default_branch: str,
    repo_full_name: str | None = None,
    installation_id: int | None = None,
    auth_strategy: str | None = None,
    readme_title: str | None = None,
    commit_message: str = "chore(repo): bootstrap repository",
) -> RepoBootstrapResult:
    normalized_provider = _normalize_provider(provider)
    base_branch = (default_branch or "main").strip() or "main"
    access = resolve_repo_runtime_access(
        provider=normalized_provider,
        repo_url=repo_url,
        repo_full_name=repo_full_name,
        installation_id=installation_id,
        auth_strategy=auth_strategy,
    )
    try:
        existing_heads = _run_git(["ls-remote", "--heads", access.transport_url], git_config=access.git_config)
    except Exception as exc:
        return RepoBootstrapResult(
            ok=False,
            created=False,
            provider=normalized_provider,
            repo_url=access.clean_repo_url,
            default_branch=base_branch,
            message="Could not inspect remote repository heads.",
            error=str(exc),
        )

    if existing_heads.strip():
        return RepoBootstrapResult(
            ok=True,
            created=False,
            provider=normalized_provider,
            repo_url=access.clean_repo_url,
            default_branch=base_branch,
            message="Repository already has commits; bootstrap skipped.",
        )

    root = Path(tempfile.mkdtemp(prefix="agentic-sdlc-repo-bootstrap-"))
    repo_dir = root / "repo"
    try:
        repo_dir.mkdir(parents=True, exist_ok=True)
        _run_git(["init", "-b", base_branch], cwd=repo_dir)
        readme = repo_dir / "README.md"
        title = (readme_title or "").strip() or "Project Bootstrap"
        readme.write_text(f"# {title}\n", encoding="utf-8")
        _run_git(["add", "README.md"], cwd=repo_dir)
        _run_git(["commit", "-m", (commit_message or "chore(repo): bootstrap repository").strip()], cwd=repo_dir)
        commit_sha = _run_git(["rev-parse", "HEAD"], cwd=repo_dir)
        _run_git(["remote", "add", "origin", access.transport_url], cwd=repo_dir)
        _run_git(["push", "-u", "origin", base_branch], cwd=repo_dir, git_config=access.git_config)
        return RepoBootstrapResult(
            ok=True,
            created=True,
            provider=normalized_provider,
            repo_url=access.clean_repo_url,
            default_branch=base_branch,
            commit_sha=commit_sha,
            message="Repository initialized with README and first commit.",
        )
    except Exception as exc:
        return RepoBootstrapResult(
            ok=False,
            created=False,
            provider=normalized_provider,
            repo_url=access.clean_repo_url,
            default_branch=base_branch,
            message="Failed to bootstrap repository.",
            error=str(exc),
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)
