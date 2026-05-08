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
    async def fake_architecture_meta(*_args, **_kwargs):
        return None

    async def fake_project_contract_meta(*_args, **_kwargs):
        return None

    monkeypatch.setattr(workspace_supervisor, "get_architecture_runtime_meta", fake_architecture_meta)
    monkeypatch.setattr(workspace_supervisor, "get_project_contract_runtime_meta", fake_project_contract_meta)
    monkeypatch.setattr(
        workspace_supervisor,
        "get_settings",
        lambda: type("Settings", (), {"workspace_simulation_mode": "ephemeral", "workspace_cleanup_policy": "retain"})(),
    )

    with pytest.raises(RuntimeError, match="clone auth failed"):
        await workspace_supervisor.build_run_context(object(), run, require_repo=True)


@pytest.mark.anyio
async def test_build_run_context_includes_architecture_runtime_meta(monkeypatch, tmp_path: Path):
    run = Run(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        status="RUNNING",
        executor="codex",
        summary={"plan_snapshot": {"goal": "Bounded change"}},
    )

    async def fake_ensure_run_workspace(*_args, **_kwargs):
        workspace_root = tmp_path / "workspace"
        repo_root = workspace_root / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)
        (repo_root / ".git").mkdir()
        return WorkspacePaths(
            root=workspace_root,
            repo=repo_root,
            artifacts=workspace_root / "artifacts",
            logs=workspace_root / "logs",
            patches=workspace_root / "patches",
            context=workspace_root / "context",
            branch_name="run/test",
            repo_seeded=True,
        )

    async def fake_architecture_meta(*_args, **_kwargs):
        return {
            "summary": {"packages": ["apps/web"], "protected_zones": ["apps/api/app/db/models"]},
            "protected_paths": ["apps/api/app/db/models"],
            "safe_paths": ["apps/web/src"],
            "validation_recipe_index": {"frontend_validation": {"paths": ["apps/web"]}},
            "command_index": {"frontend_build": {"command": "npm -C apps/web run build"}},
        }

    async def fake_project_contract_meta(*_args, **_kwargs):
        return {
            "summary": {"enforcement_enabled": True, "active_rules": ["disallow_inline_styles"]},
            "brand_kit": {"tokens": {"brand-primary": "#2563eb"}},
            "design_system": {"components": ["HeroSection"]},
            "enforcement": {"enabled": True, "disallow_inline_styles": True},
        }

    monkeypatch.setattr(workspace_supervisor, "ensure_run_workspace", fake_ensure_run_workspace)
    monkeypatch.setattr(workspace_supervisor, "get_architecture_runtime_meta", fake_architecture_meta)
    monkeypatch.setattr(workspace_supervisor, "get_project_contract_runtime_meta", fake_project_contract_meta)
    monkeypatch.setattr(
        workspace_supervisor,
        "get_settings",
        lambda: type("Settings", (), {"workspace_simulation_mode": "ephemeral", "workspace_cleanup_policy": "retain"})(),
    )

    context = await workspace_supervisor.build_run_context(object(), run, require_repo=True)

    assert context.architecture_profile is not None
    assert context.architecture_profile["protected_paths"] == ["apps/api/app/db/models"]
    assert context.architecture_profile["safe_paths"] == ["apps/web/src"]
    assert context.project_contract is not None
    assert context.project_contract["summary"]["enforcement_enabled"] is True
