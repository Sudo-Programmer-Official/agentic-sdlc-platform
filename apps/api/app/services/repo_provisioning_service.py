from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ProjectRepository
from app.core.config import get_settings
from app.services import get_default_installation_id
from app.services.activity_log import log_activity
from app.services.repo_connector import (
    bootstrap_repo_from_local_source,
    checkout_workspace_branch_from_head,
    commit_all,
    connect_repo,
    preflight_repo_access,
    prepare_workspace_repo,
    push_branch,
    repo_has_changes,
)
from app.services.repo_ownership_resolver import resolve_repo_ownership
from dataclasses import dataclass


def _slugify_repo_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "agentic-project"


@dataclass(frozen=True)
class RepoProvisioningResult:
    attempted: bool
    connected: bool
    failed: bool
    reason: str | None = None


@dataclass(frozen=True)
class RepoShapeClassification:
    kind: str
    tracked_files: int


async def auto_provision_project_repository(
    session: AsyncSession,
    *,
    project: Project,
    project_intent: dict[str, Any] | None,
    template_repo_root: str | None,
    actor_id: str | None,
    github_adapter: Any,
    github_allowed_org: str | None,
) -> RepoProvisioningResult:
    if not isinstance(project_intent, dict):
        return RepoProvisioningResult(attempted=False, connected=False, failed=False)
    repo_type = str(project_intent.get("repo_type") or "").strip().lower()
    repository_mode = str(project_intent.get("repository_mode") or "").strip().lower()
    if repo_type != "new_repo" and repository_mode not in {"create_new", "connect_existing"}:
        return RepoProvisioningResult(attempted=False, connected=False, failed=False)
    connect_existing = repository_mode == "connect_existing" or repo_type in {"existing_repo", "connect_existing"}

    try:
        installation_id = project_intent.get("installation_id")
        parsed_installation_id = int(installation_id) if installation_id is not None else get_default_installation_id("github")
        default_branch = str(project_intent.get("default_branch") or "main").strip() or "main"

        if connect_existing:
            repo_url = str(project_intent.get("repo_url") or "").strip()
            repo_full_name = str(project_intent.get("repo_full_name") or "").strip() or None
            if not repo_url and repo_full_name:
                repo_url = f"https://github.com/{repo_full_name.removesuffix('.git')}.git"
            if not repo_url:
                raise ValueError("repo_url or repo_full_name is required when repository_mode=connect_existing")
            preflight = preflight_repo_access(
                provider="github",
                repo_url=repo_url,
                repo_full_name=repo_full_name,
                default_branch=default_branch,
                installation_id=int(parsed_installation_id) if parsed_installation_id is not None else None,
                auth_strategy="runtime_default",
                clone=True,
            )
            if not preflight.ok:
                raise ValueError(preflight.error or "Could not access existing repository")
            connected = await connect_repo(
                session,
                project=project,
                provider="github",
                repo_url=repo_url,
                repo_full_name=repo_full_name,
                default_branch=default_branch,
                installation_id=int(parsed_installation_id) if parsed_installation_id is not None else None,
                auth_strategy="runtime_default",
                created_by=actor_id,
            )
            classification = _classify_repository_shape(
                provider="github",
                repo_url=repo_url,
                repo_full_name=repo_full_name,
                default_branch=default_branch,
                installation_id=int(parsed_installation_id) if parsed_installation_id is not None else None,
                auth_strategy=connected.auth_strategy,
            )
            if template_repo_root and classification.kind == "nearly_empty":
                bootstrap_result = _bootstrap_template_into_existing_repo(
                    source_dir=Path(template_repo_root),
                    provider="github",
                    repo_url=repo_url,
                    repo_full_name=repo_full_name,
                    default_branch=default_branch,
                    installation_id=int(parsed_installation_id) if parsed_installation_id is not None else None,
                    auth_strategy=connected.auth_strategy,
                    foundation_branch_name=_foundation_branch_name(project.name),
                    project_id=str(project.id),
                )
                if (
                    repo_full_name
                    and bootstrap_result.branch_name
                ):
                    pr_url, pr_number = _upsert_foundation_pr(
                        github_adapter=github_adapter,
                        repo_full_name=repo_full_name,
                        head_branch=bootstrap_result.branch_name,
                        base_branch=default_branch,
                        installation_id=int(parsed_installation_id) if parsed_installation_id is not None else None,
                    )
                    bootstrap_result = ExistingRepoBootstrapResult(
                        created=bootstrap_result.created,
                        commit_sha=bootstrap_result.commit_sha,
                        reason=bootstrap_result.reason,
                        branch_name=bootstrap_result.branch_name,
                        pull_request_url=pr_url,
                        pull_request_number=pr_number,
                        local_clone_path=bootstrap_result.local_clone_path,
                    )
                await log_activity(
                    session,
                    project_id=project.id,
                    entity_type="project_repository",
                    entity_id=connected.id,
                    action_type="repo.bootstrap_existing_repo",
                    metadata={
                        "repo_url": repo_url,
                        "repo_full_name": repo_full_name,
                        "default_branch": default_branch,
                        "classification": classification.kind,
                        "created": bootstrap_result.created,
                        "commit_sha": bootstrap_result.commit_sha,
                        "branch_name": bootstrap_result.branch_name,
                        "pull_request_url": bootstrap_result.pull_request_url,
                        "pull_request_number": bootstrap_result.pull_request_number,
                        "local_clone_path": bootstrap_result.local_clone_path,
                        "message": bootstrap_result.reason,
                    },
                )
            await log_activity(
                session,
                project_id=project.id,
                entity_type="project_repository",
                entity_id=connected.id,
                action_type="repo.connected_existing",
                metadata={
                    "repo_url": repo_url,
                    "repo_full_name": repo_full_name,
                    "default_branch": default_branch,
                    "installation_id": parsed_installation_id,
                    "classification": classification.kind,
                    "tracked_files": classification.tracked_files,
                },
            )
            return RepoProvisioningResult(attempted=True, connected=True, failed=False)

        ownership = resolve_repo_ownership(
            project_intent=project_intent,
            github_allowed_org=github_allowed_org,
            github_adapter=github_adapter,
        )
        owner = str(ownership.owner or "").strip()
        if not owner:
            await log_activity(
                session,
                project_id=project.id,
                entity_type="project",
                entity_id=project.id,
                action_type="repo.auto_create_skipped",
                metadata={
                    "reason": ownership.reason or "repo_owner_missing",
                    "detail": ownership.error_message
                    or "Repository ownership is not configured yet. Connect GitHub and choose Personal repository or Organization repository.",
                },
            )
            return RepoProvisioningResult(
                attempted=False,
                connected=False,
                failed=False,
                reason=ownership.reason or "repo_owner_missing",
            )
        suggested_name = str(project_intent.get("repo_name") or project.name or "agentic-project")
        repo_name = _slugify_repo_name(suggested_name)
        full_name = f"{owner}/{repo_name}"
        if github_adapter is None or not hasattr(github_adapter, "create_repository"):
            raise ValueError("GitHub repository auto-create is unavailable; configure GitHub App integration first")
        created_repo = github_adapter.create_repository(
            installation_id=int(parsed_installation_id),
            owner=owner,
            name=repo_name,
            private=bool(project_intent.get("repo_private", True)),
            description=(project.description or f"Runtime template project for {project.name}"),
        )
        clone_url = str(created_repo.get("clone_url") or "").strip() or f"https://github.com/{full_name}.git"
        default_branch = str(created_repo.get("default_branch") or default_branch).strip() or "main"
        connected = await connect_repo(
            session,
            project=project,
            provider="github",
            repo_url=clone_url,
            repo_full_name=full_name,
            default_branch=default_branch,
            installation_id=int(parsed_installation_id),
            auth_strategy="runtime_default",
            created_by=actor_id,
        )
        if template_repo_root:
            bootstrap_result = bootstrap_repo_from_local_source(
                source_dir=Path(template_repo_root),
                provider="github",
                repo_url=clone_url,
                repo_full_name=full_name,
                default_branch=default_branch,
                installation_id=int(parsed_installation_id),
                auth_strategy=connected.auth_strategy,
            )
            if bootstrap_result.ok:
                await log_activity(
                    session,
                    project_id=project.id,
                    entity_type="project_repository",
                    entity_id=connected.id,
                    action_type="repo.bootstrap_from_template",
                    metadata={
                        "repo_full_name": full_name,
                        "repo_url": clone_url,
                        "default_branch": default_branch,
                        "created": bootstrap_result.created,
                        "commit_sha": bootstrap_result.commit_sha,
                    },
                )
        await log_activity(
            session,
            project_id=project.id,
            entity_type="project_repository",
            entity_id=connected.id,
            action_type="repo.auto_created_and_connected",
            metadata={
                "repo_full_name": full_name,
                "repo_url": clone_url,
                "default_branch": default_branch,
                "installation_id": parsed_installation_id,
            },
        )
        return RepoProvisioningResult(attempted=True, connected=True, failed=False)
    except Exception as exc:
        await log_activity(
            session,
            project_id=project.id,
            entity_type="project",
            entity_id=project.id,
            action_type="repo.auto_create_failed",
            metadata={"reason": str(exc)},
        )
        return RepoProvisioningResult(attempted=True, connected=False, failed=True, reason=str(exc))


async def reconcile_connected_repository_foundation(
    session: AsyncSession,
    *,
    project: Project,
    project_repo: ProjectRepository,
    template_repo_root: str | None,
    github_adapter: Any,
) -> FoundationPrTriggerResult:
    if not template_repo_root:
        return FoundationPrTriggerResult(ok=False, attempted=False, message="Runtime template source is unavailable.")
    classification = _classify_repository_shape(
        provider=project_repo.provider,
        repo_url=project_repo.repo_url,
        repo_full_name=project_repo.repo_full_name,
        default_branch=project_repo.default_branch,
        installation_id=project_repo.installation_id,
        auth_strategy=project_repo.auth_strategy,
    )
    if classification.kind != "nearly_empty":
        return FoundationPrTriggerResult(
            ok=True,
            attempted=False,
            classification=classification.kind,
            message=f"Foundation PR is only auto-generated for nearly-empty repositories (detected: {classification.kind}).",
        )
    bootstrap_result = _bootstrap_template_into_existing_repo(
        source_dir=Path(template_repo_root),
        provider=project_repo.provider,
        repo_url=project_repo.repo_url,
        repo_full_name=project_repo.repo_full_name,
        default_branch=project_repo.default_branch,
        installation_id=project_repo.installation_id,
        auth_strategy=project_repo.auth_strategy,
        foundation_branch_name=_foundation_branch_name(project.name),
        project_id=str(project.id),
    )
    if project_repo.repo_full_name and bootstrap_result.branch_name:
        pr_url, pr_number = _upsert_foundation_pr(
            github_adapter=github_adapter,
            repo_full_name=project_repo.repo_full_name,
            head_branch=bootstrap_result.branch_name,
            base_branch=project_repo.default_branch,
            installation_id=project_repo.installation_id,
        )
        bootstrap_result = ExistingRepoBootstrapResult(
            created=bootstrap_result.created,
            commit_sha=bootstrap_result.commit_sha,
            reason=bootstrap_result.reason,
            branch_name=bootstrap_result.branch_name,
            pull_request_url=pr_url,
            pull_request_number=pr_number,
            local_clone_path=bootstrap_result.local_clone_path,
        )
    await log_activity(
        session,
        project_id=project.id,
        entity_type="project_repository",
        entity_id=project_repo.id,
        action_type="repo.bootstrap_existing_repo",
        metadata={
            "repo_url": project_repo.repo_url,
            "repo_full_name": project_repo.repo_full_name,
            "default_branch": project_repo.default_branch,
            "classification": classification.kind,
            "created": bootstrap_result.created,
            "commit_sha": bootstrap_result.commit_sha,
            "branch_name": bootstrap_result.branch_name,
            "pull_request_url": bootstrap_result.pull_request_url,
            "pull_request_number": bootstrap_result.pull_request_number,
            "local_clone_path": bootstrap_result.local_clone_path,
            "message": bootstrap_result.reason,
        },
    )
    return FoundationPrTriggerResult(
        ok=True,
        attempted=True,
        classification=classification.kind,
        branch_name=bootstrap_result.branch_name,
        pull_request_url=bootstrap_result.pull_request_url,
        pull_request_number=bootstrap_result.pull_request_number,
        message=bootstrap_result.reason or "Foundation reconcile attempted.",
    )


@dataclass(frozen=True)
class ExistingRepoBootstrapResult:
    created: bool
    commit_sha: str | None = None
    reason: str | None = None
    branch_name: str | None = None
    pull_request_url: str | None = None
    pull_request_number: int | None = None
    local_clone_path: str | None = None


@dataclass(frozen=True)
class FoundationPrTriggerResult:
    ok: bool
    attempted: bool
    classification: str | None = None
    branch_name: str | None = None
    pull_request_url: str | None = None
    pull_request_number: int | None = None
    message: str | None = None


def _classify_repository_shape(
    *,
    provider: str,
    repo_url: str,
    default_branch: str,
    repo_full_name: str | None,
    installation_id: int | None,
    auth_strategy: str | None,
) -> RepoShapeClassification:
    root = Path(tempfile.mkdtemp(prefix="agentic-sdlc-repo-classify-"))
    repo_dir = root / "repo"
    try:
        prepare_workspace_repo(
            repo_dir=repo_dir,
            provider=provider,
            repo_url=repo_url,
            default_branch=default_branch,
            repo_full_name=repo_full_name,
            installation_id=installation_id,
            auth_strategy=auth_strategy,
            work_branch=default_branch,
        )
        files = [
            path
            for path in repo_dir.rglob("*")
            if path.is_file() and ".git" not in path.parts
        ]
        top_files = {str(path.relative_to(repo_dir)) for path in files}
        if not files:
            return RepoShapeClassification(kind="empty", tracked_files=0)
        benign = {"README.md", ".gitignore", "LICENSE", "LICENSE.md"}
        if top_files.issubset(benign):
            return RepoShapeClassification(kind="nearly_empty", tracked_files=len(files))
        if any(part in {"apps", "packages"} for path in files for part in path.parts):
            return RepoShapeClassification(kind="existing_monorepo", tracked_files=len(files))
        if any(path.suffix.lower() in {".html", ".tsx", ".jsx", ".vue"} for path in files):
            return RepoShapeClassification(kind="existing_frontend", tracked_files=len(files))
        if any(path.suffix.lower() in {".py", ".go", ".java", ".rb"} for path in files):
            return RepoShapeClassification(kind="existing_backend", tracked_files=len(files))
        return RepoShapeClassification(kind="unknown", tracked_files=len(files))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _bootstrap_template_into_existing_repo(
    *,
    source_dir: Path,
    provider: str,
    repo_url: str,
    default_branch: str,
    repo_full_name: str | None,
    installation_id: int | None,
    auth_strategy: str | None,
    foundation_branch_name: str,
    project_id: str,
) -> ExistingRepoBootstrapResult:
    if not source_dir.exists() or not source_dir.is_dir():
        return ExistingRepoBootstrapResult(created=False, reason="template_source_unavailable")
    root = Path(tempfile.mkdtemp(prefix="agentic-sdlc-existing-bootstrap-"))
    repo_dir = root / "repo"
    try:
        prepare_workspace_repo(
            repo_dir=repo_dir,
            provider=provider,
            repo_url=repo_url,
            default_branch=default_branch,
            repo_full_name=repo_full_name,
            installation_id=installation_id,
            auth_strategy=auth_strategy,
            work_branch=default_branch,
        )
        checkout_workspace_branch_from_head(
            repo_dir=repo_dir,
            provider=provider,
            repo_url=repo_url,
            branch_name=foundation_branch_name,
            repo_full_name=repo_full_name,
            installation_id=installation_id,
            auth_strategy=auth_strategy,
        )
        for child in repo_dir.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        for child in source_dir.iterdir():
            if child.name == ".git":
                continue
            dst = repo_dir / child.name
            if child.is_dir():
                shutil.copytree(
                    child,
                    dst,
                    ignore=shutil.ignore_patterns(
                        ".git", ".venv", "node_modules", "dist", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"
                    ),
                )
            else:
                shutil.copy2(child, dst)
        if not repo_has_changes(repo_dir):
            return ExistingRepoBootstrapResult(created=False, reason="no_changes", branch_name=foundation_branch_name)
        commit_sha = commit_all(repo_dir, "chore(repo): bootstrap from runtime template")
        push_branch(
            repo_dir,
            foundation_branch_name,
            provider=provider,
            repo_url=repo_url,
            repo_full_name=repo_full_name,
            installation_id=installation_id,
            auth_strategy=auth_strategy,
        )
        local_clone_path = _sync_local_repo_clone(
            provider=provider,
            repo_url=repo_url,
            repo_full_name=repo_full_name,
            installation_id=installation_id,
            auth_strategy=auth_strategy,
            branch_name=foundation_branch_name,
            project_id=project_id,
        )
        return ExistingRepoBootstrapResult(
            created=True,
            commit_sha=commit_sha,
            reason="bootstrapped",
            branch_name=foundation_branch_name,
            local_clone_path=local_clone_path,
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _foundation_branch_name(project_name: str) -> str:
    return f"foundation/{_slugify_repo_name(project_name)}"


def _sync_local_repo_clone(
    *,
    provider: str,
    repo_url: str,
    repo_full_name: str | None,
    installation_id: int | None,
    auth_strategy: str | None,
    branch_name: str,
    project_id: str,
) -> str | None:
    try:
        settings = get_settings()
        local_root = Path(settings.workspace_base_dir).expanduser().resolve() / project_id / "repo"
        prepare_workspace_repo(
            repo_dir=local_root,
            provider=provider,
            repo_url=repo_url,
            default_branch=branch_name,
            repo_full_name=repo_full_name,
            installation_id=installation_id,
            auth_strategy=auth_strategy,
            work_branch=branch_name,
        )
        return str(local_root)
    except Exception:
        return None


def _extract_pr_metadata(pr_payload: dict | None) -> tuple[str | None, int | None]:
    if not isinstance(pr_payload, dict):
        return None, None
    pr_url = str(pr_payload.get("html_url") or "").strip() or None
    pr_number = pr_payload.get("number") if isinstance(pr_payload.get("number"), int) else None
    return pr_url, pr_number


def _upsert_foundation_pr(
    *,
    github_adapter: Any,
    repo_full_name: str,
    head_branch: str,
    base_branch: str,
    installation_id: int | None,
) -> tuple[str | None, int | None]:
    if github_adapter is None or not hasattr(github_adapter, "create_pull_request"):
        return None, None
    existing_finder = getattr(github_adapter, "find_open_pull_request", None)
    if callable(existing_finder):
        existing = existing_finder(
            repo=repo_full_name,
            head_branch=head_branch,
            base_branch=base_branch,
            installation_id=installation_id,
        )
        pr_url, pr_number = _extract_pr_metadata(existing)
        if pr_url or pr_number:
            return pr_url, pr_number
    try:
        created = github_adapter.create_pull_request(
            repo=repo_full_name,
            title="chore: bootstrap monorepo foundation",
            body=(
                "Initialize repository with runtime monorepo foundation template.\n\n"
                "This PR was opened automatically during runtime initialization."
            ),
            head=head_branch,
            base=base_branch,
            installation_id=installation_id,
        )
        return _extract_pr_metadata(created)
    except Exception:
        if callable(existing_finder):
            existing = existing_finder(
                repo=repo_full_name,
                head_branch=head_branch,
                base_branch=base_branch,
                installation_id=installation_id,
            )
            return _extract_pr_metadata(existing)
        return None, None
