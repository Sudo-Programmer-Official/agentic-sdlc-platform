from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Run
from app.runtime.context import RunContext
from app.runtime.execution_contract import build_execution_contract, coerce_execution_contract
from app.services.event_log import record_event
from app.services.architecture_profile_service import get_architecture_runtime_meta
from app.services.repo_connector import (
    checkout_workspace_branch_from_head,
    get_project_repository,
    prepare_workspace_repo,
    resolve_repo_runtime_access,
)
from app.services.workspace_commands import (
    get_workspace_allowed_command_prefixes,
    workspace_command_audit_path,
)

log = logging.getLogger("app.workspace_supervisor")


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    repo: Path
    artifacts: Path
    logs: Path
    patches: Path
    context: Path
    branch_name: str
    repo_seeded: bool


def _resolve_repo_source() -> Path | None:
    settings = get_settings()
    if settings.workspace_repo_source:
        candidate = Path(settings.workspace_repo_source).expanduser().resolve()
        return candidate if candidate.exists() else None

    cwd = Path.cwd().resolve()
    if (cwd / ".git").exists():
        return cwd
    return None


def _workspace_root(run: Run) -> Path:
    settings = get_settings()
    return Path(settings.workspace_base_dir).expanduser().resolve() / str(run.project_id) / str(run.id)


def _workspace_branch(run: Run) -> str:
    return run.branch_name or f"run/{str(run.id)[:8]}"


def _workspace_uri(kind: str, filename: str) -> str:
    return f"workspace://{kind}/{filename}"


def _workspace_failure_message(run: Run, exc: Exception, access) -> str:
    base = str(exc).strip() or exc.__class__.__name__
    if access is None:
        return base
    details = [
        f"auth_mode={access.auth_mode}",
        f"selection_reason={access.selection_reason}",
        f"installation_id={access.installation_id}",
        f"token_generated={access.token_generated}",
    ]
    return f"{base} [{' '.join(details)}]"


def _manifest(
    paths: WorkspacePaths,
    run: Run,
    source: Path | None,
    repo_url: str | None,
    repo_branch: str | None,
    repo_auth_mode: str | None,
) -> dict:
    settings = get_settings()
    return {
        "run_id": str(run.id),
        "project_id": str(run.project_id),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "branch_name": paths.branch_name,
        "workspace_root": str(paths.root),
        "repo_path": str(paths.repo),
        "artifacts_path": str(paths.artifacts),
        "logs_path": str(paths.logs),
        "patches_path": str(paths.patches),
        "context_path": str(paths.context),
        "workspace_status": run.workspace_status,
        "repo_seeded": paths.repo_seeded,
        "repo_source": str(source) if source else None,
        "repo_url": repo_url,
        "repo_branch": repo_branch,
        "repo_auth_mode": repo_auth_mode,
        "executor": run.executor,
        "plan_snapshot_path": str(paths.context / "plan.json"),
        "execution_contract_path": str(paths.context / "execution_contract.json"),
        "simulation_mode": getattr(settings, "workspace_simulation_mode", "ephemeral"),
        "cleanup_policy": getattr(settings, "workspace_cleanup_policy", "retain"),
        "allowed_command_prefixes": get_workspace_allowed_command_prefixes(settings),
        "command_audit_log": str(workspace_command_audit_path(paths.logs)),
    }


def _seed_repo(source: Path, destination: Path) -> bool:
    if destination.exists() and any(destination.iterdir()):
        return (destination / ".git").exists() or any(destination.iterdir())
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            ".venv",
            "node_modules",
            "dist",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
        ),
    )
    return True


async def ensure_run_workspace(
    session: AsyncSession,
    run: Run,
    *,
    require_repo: bool = False,
    repo_source_path: Path | None = None,
    repo_url: str | None = None,
    repo_branch: str | None = None,
    repo_provider: str | None = None,
    repo_full_name: str | None = None,
    repo_installation_id: int | None = None,
    prefer_local_source: bool = True,
) -> WorkspacePaths:
    if require_repo and (not repo_url or not repo_provider):
        project_repo = await get_project_repository(session, project_id=run.project_id, tenant_id=run.tenant_id)
        if project_repo is not None:
            repo_url = repo_url or project_repo.repo_url
            repo_branch = repo_branch or project_repo.default_branch
            repo_provider = repo_provider or project_repo.provider
            repo_full_name = repo_full_name or project_repo.repo_full_name
            repo_installation_id = repo_installation_id or project_repo.installation_id

    source = (
        repo_source_path.resolve()
        if repo_source_path and repo_source_path.exists()
        else (_resolve_repo_source() if prefer_local_source else None)
    )
    root = _workspace_root(run)
    paths = WorkspacePaths(
        root=root,
        repo=root / "repo",
        artifacts=root / "artifacts",
        logs=root / "logs",
        patches=root / "patches",
        context=root / "context",
        branch_name=_workspace_branch(run),
        repo_seeded=False,
    )

    access = None

    try:
        if repo_url and repo_provider:
            access = resolve_repo_runtime_access(
                provider=repo_provider,
                repo_url=repo_url,
                repo_full_name=repo_full_name,
                installation_id=repo_installation_id,
            )
        for directory in (paths.root, paths.repo, paths.artifacts, paths.logs, paths.patches, paths.context):
            directory.mkdir(parents=True, exist_ok=True)

        repo_seeded = paths.repo.exists() and any(paths.repo.iterdir())
        if require_repo and not repo_seeded and source is not None:
            repo_seeded = _seed_repo(source, paths.repo)
            if repo_seeded and repo_url and repo_provider and (paths.repo / ".git").exists():
                checkout_workspace_branch_from_head(
                    repo_dir=paths.repo,
                    provider=repo_provider,
                    repo_url=repo_url,
                    repo_full_name=repo_full_name,
                    installation_id=repo_installation_id,
                    branch_name=paths.branch_name,
                )
        if require_repo and not repo_seeded and repo_url:
            prepare_workspace_repo(
                repo_dir=paths.repo,
                provider=repo_provider or "github",
                repo_url=repo_url,
                default_branch=repo_branch or "main",
                repo_full_name=repo_full_name,
                installation_id=repo_installation_id,
                work_branch=paths.branch_name,
            )
            repo_seeded = True

        run.workspace_root = str(paths.root)
        run.repo_path = str(paths.repo)
        run.branch_name = paths.branch_name
        run.workspace_status = "SEEDED" if repo_seeded else "READY"
        run.workspace_error = None
        session.add(run)
        await session.flush()

        materialized_paths = WorkspacePaths(
            root=paths.root,
            repo=paths.repo,
            artifacts=paths.artifacts,
            logs=paths.logs,
            patches=paths.patches,
            context=paths.context,
            branch_name=paths.branch_name,
            repo_seeded=repo_seeded,
        )
        manifest_path = paths.context / "workspace.json"
        manifest_path.write_text(
            json.dumps(
                _manifest(
                    materialized_paths,
                    run,
                    source,
                    access.clean_repo_url if access else repo_url,
                    repo_branch,
                    access.auth_mode if access else None,
                ),
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        return materialized_paths
    except Exception as exc:
        run.workspace_root = str(paths.root)
        run.repo_path = str(paths.repo)
        run.branch_name = paths.branch_name
        run.workspace_status = "ERROR"
        run.workspace_error = _workspace_failure_message(run, exc, access)
        log.exception(
            "Workspace prepare failed run_id=%s project_id=%s branch=%s repo_url=%s repo_branch=%s provider=%s auth_mode=%s installation_id=%s token_generated=%s credential_strategy=%s selection_reason=%s transport_url=%s git_config_present=%s",
            run.id,
            run.project_id,
            paths.branch_name,
            repo_url,
            repo_branch,
            repo_provider,
            access.auth_mode if access else None,
            access.installation_id if access else None,
            access.token_generated if access else None,
            access.credential_strategy if access else None,
            access.selection_reason if access else None,
            access.clean_repo_url if access else None,
            bool(access.git_config) if access else False,
            exc_info=exc,
        )
        session.add(run)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="WORKSPACE_PREPARE_FAILED",
            actor_type="SYSTEM",
            tenant_id=run.tenant_id,
            message="Workspace preparation failed",
            payload={
                "error": str(exc),
                "branch_name": paths.branch_name,
                "repo_url": repo_url,
                "repo_branch": repo_branch,
                "provider": repo_provider,
                "auth_mode": access.auth_mode if access else None,
                "installation_id": access.installation_id if access else None,
                "token_generated": access.token_generated if access else None,
                "credential_strategy": access.credential_strategy if access else None,
                "selection_reason": access.selection_reason if access else None,
            },
        )
        await session.flush()
        return WorkspacePaths(
            root=paths.root,
            repo=paths.repo,
            artifacts=paths.artifacts,
            logs=paths.logs,
            patches=paths.patches,
            context=paths.context,
            branch_name=paths.branch_name,
            repo_seeded=False,
        )


async def build_run_context(
    session: AsyncSession,
    run: Run,
    *,
    require_repo: bool = False,
    repo_source_path: Path | None = None,
    repo_url: str | None = None,
    repo_branch: str | None = None,
    repo_provider: str | None = None,
    repo_full_name: str | None = None,
    repo_installation_id: int | None = None,
) -> RunContext:
    settings = get_settings()
    architecture_profile = await get_architecture_runtime_meta(
        session,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
    )
    summary = dict(run.summary or {})
    execution_contract = coerce_execution_contract(summary.get("execution_contract"))
    if execution_contract is None:
        execution_contract = build_execution_contract(
            run_summary=summary,
            architecture_profile=architecture_profile,
            plan_snapshot=(summary.get("plan_snapshot") if isinstance(summary.get("plan_snapshot"), dict) else None),
            previous_contract=None,
            settings=settings,
        )
        summary["execution_contract"] = execution_contract.to_dict()
        run.summary = summary
        if hasattr(session, "add") and hasattr(session, "flush"):
            session.add(run)
            await session.flush()
    paths = await ensure_run_workspace(
        session,
        run,
        require_repo=require_repo,
        repo_source_path=repo_source_path,
        repo_url=repo_url,
        repo_branch=repo_branch,
        repo_provider=repo_provider,
        repo_full_name=repo_full_name,
        repo_installation_id=repo_installation_id,
    )
    if require_repo:
        if run.workspace_status == "ERROR":
            raise RuntimeError(run.workspace_error or "Workspace preparation failed")
        repo_path = Path(paths.repo)
        if not (repo_path / ".git").exists():
            raise RuntimeError("Workspace repository is unavailable for repo-backed execution")
    execution_contract_path = paths.context / "execution_contract.json"
    execution_contract_path.parent.mkdir(parents=True, exist_ok=True)
    execution_contract_path.write_text(json.dumps(execution_contract.to_dict(), indent=2) + "\n", encoding="utf-8")
    return RunContext(
        project_id=run.project_id,
        run_id=run.id,
        plan_snapshot=(run.summary or {}).get("plan_snapshot") if isinstance(run.summary, dict) else None,
        architecture_profile=architecture_profile,
        execution_contract=execution_contract,
        workspace_root=str(paths.root),
        repo_path=str(paths.repo),
        artifacts_path=str(paths.artifacts),
        logs_path=str(paths.logs),
        patches_path=str(paths.patches),
        context_path=str(paths.context),
        branch_name=paths.branch_name,
        workspace_status=run.workspace_status,
        simulation_mode=getattr(settings, "workspace_simulation_mode", "ephemeral"),
        command_audit_path=str(workspace_command_audit_path(paths.logs)),
        cleanup_policy=getattr(settings, "workspace_cleanup_policy", "retain"),
    )


def workspace_uri(kind: str, filename: str) -> str:
    return _workspace_uri(kind, filename)


def destroy_run_workspace(run: Run) -> bool:
    if not run.workspace_root:
        return False
    root = Path(run.workspace_root).expanduser().resolve()
    base_dir = Path(get_settings().workspace_base_dir).expanduser().resolve()
    if not str(root).startswith(str(base_dir)):
        raise ValueError("Workspace path escapes configured workspace base directory")
    if not root.exists():
        return False
    shutil.rmtree(root)
    return True
