from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.db.models import Run
from app.services import workspace_supervisor
from app.services.workspace_supervisor import WorkspacePaths


@pytest.mark.anyio
async def test_build_run_context_raises_when_repo_backed_workspace_is_in_error(monkeypatch, tmp_path: Path):
    run = Run(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        status="RUNNING",
        executor="codex",
    )

    async def fake_ensure_run_workspace(*_args, **_kwargs):
        run.workspace_status = "ERROR"
        run.workspace_error = "clone auth failed"
        run.workspace_root = str(tmp_path / "workspace")
        run.repo_path = str(tmp_path / "workspace" / "repo")
        run.branch_name = "run/test"
        return WorkspacePaths(
            root=tmp_path / "workspace",
            repo=tmp_path / "workspace" / "repo",
            artifacts=tmp_path / "workspace" / "artifacts",
            logs=tmp_path / "workspace" / "logs",
            patches=tmp_path / "workspace" / "patches",
            context=tmp_path / "workspace" / "context",
            branch_name="run/test",
            repo_seeded=False,
        )

    monkeypatch.setattr(workspace_supervisor, "ensure_run_workspace", fake_ensure_run_workspace)
    monkeypatch.setattr(
        workspace_supervisor,
        "get_settings",
        lambda: type("Settings", (), {"workspace_simulation_mode": "ephemeral", "workspace_cleanup_policy": "retain"})(),
    )

    with pytest.raises(RuntimeError, match="clone auth failed"):
        await workspace_supervisor.build_run_context(object(), run, require_repo=True)
