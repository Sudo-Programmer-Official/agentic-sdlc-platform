from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Run
from app.runtime.context import RunContext
from app.services.repo_connector import prepare_workspace_repo


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


def _manifest(
    paths: WorkspacePaths,
    run: Run,
    source: Path | None,
    repo_url: str | None,
    repo_branch: str | None,
) -> dict:
    return {
        "run_id": str(run.id),
        "project_id": str(run.project_id),
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
        "executor": run.executor,
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
) -> WorkspacePaths:
    source = repo_source_path.resolve() if repo_source_path and repo_source_path.exists() else _resolve_repo_source()
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

    try:
        for directory in (paths.root, paths.repo, paths.artifacts, paths.logs, paths.patches, paths.context):
            directory.mkdir(parents=True, exist_ok=True)

        repo_seeded = paths.repo.exists() and any(paths.repo.iterdir())
        if require_repo and not repo_seeded and source is not None:
            repo_seeded = _seed_repo(source, paths.repo)
        if require_repo and not repo_seeded and repo_url:
            prepare_workspace_repo(
                repo_dir=paths.repo,
                repo_url=repo_url,
                default_branch=repo_branch or "main",
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
            json.dumps(_manifest(materialized_paths, run, source, repo_url, repo_branch), indent=2) + "\n",
            encoding="utf-8",
        )

        return materialized_paths
    except Exception as exc:
        run.workspace_root = str(paths.root)
        run.repo_path = str(paths.repo)
        run.branch_name = paths.branch_name
        run.workspace_status = "ERROR"
        run.workspace_error = str(exc)
        session.add(run)
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
) -> RunContext:
    paths = await ensure_run_workspace(
        session,
        run,
        require_repo=require_repo,
        repo_source_path=repo_source_path,
        repo_url=repo_url,
        repo_branch=repo_branch,
    )
    return RunContext(
        project_id=run.project_id,
        run_id=run.id,
        workspace_root=str(paths.root),
        repo_path=str(paths.repo),
        artifacts_path=str(paths.artifacts),
        logs_path=str(paths.logs),
        patches_path=str(paths.patches),
        context_path=str(paths.context),
        branch_name=paths.branch_name,
        workspace_status=run.workspace_status,
    )


def workspace_uri(kind: str, filename: str) -> str:
    return _workspace_uri(kind, filename)
