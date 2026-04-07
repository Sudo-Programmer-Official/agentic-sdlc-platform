from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import Project, Run, WorkItem
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.runtime.context import RunContext
from app.runtime.test_executor import TestExecutor
from app.services.workspace_commands import COMMAND_AUDIT_LOG_NAME, run_workspace_command
from app.services.workspace_supervisor import build_run_context, destroy_run_workspace


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'workspace-simulation.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session: AsyncSession = session_factory()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


def test_workspace_command_runner_audits_and_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ALLOWED_COMMAND_PREFIXES", "python3")
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    log_dir = tmp_path / "logs"

    allowed = run_workspace_command(
        ["python3", "-c", "print('hello from workspace')"],
        cwd=repo_root,
        log_dir=log_dir,
        label="probe",
        timeout_seconds=5,
    )
    blocked = run_workspace_command(
        ["git", "status"],
        cwd=repo_root,
        log_dir=log_dir,
        label="blocked-probe",
        timeout_seconds=5,
    )

    assert allowed.status == "SUCCEEDED"
    assert "hello from workspace" in allowed.stdout
    assert blocked.status == "BLOCKED"
    assert blocked.blocked_reason is not None

    audit_path = log_dir / COMMAND_AUDIT_LOG_NAME
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 3
    assert records[0]["status"] == "RUNNING"
    assert records[0]["phase"] == "started"
    assert records[1]["status"] == "SUCCEEDED"
    assert records[1]["phase"] == "finished"
    assert records[1]["command_id"] == records[0]["command_id"]
    assert records[2]["status"] == "BLOCKED"
    assert records[2]["blocked_reason"] is not None


@pytest.mark.anyio
async def test_workspace_manifest_contains_simulation_metadata_and_cleanup_hook(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("WORKSPACE_ALLOWED_COMMAND_PREFIXES", "git,pytest,python3")
    monkeypatch.setenv("WORKSPACE_SIMULATION_MODE", "ephemeral")
    monkeypatch.setenv("WORKSPACE_CLEANUP_POLICY", "retain")

    tenant_id = uuid.uuid4()
    project = Project(name="Workspace simulation project", tenant_id=tenant_id)
    db_session.add(project)
    await db_session.flush()

    run = Run(project_id=project.id, tenant_id=tenant_id, status="QUEUED", executor="dummy")
    db_session.add(run)
    await db_session.commit()

    context = await build_run_context(db_session, run)
    manifest_path = Path(context.workspace_root or "") / "context" / "workspace.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert context.simulation_mode == "ephemeral"
    assert context.cleanup_policy == "retain"
    assert context.command_audit_path is not None
    assert manifest["simulation_mode"] == "ephemeral"
    assert manifest["cleanup_policy"] == "retain"
    assert manifest["allowed_command_prefixes"] == ["git", "pytest", "python3"]
    assert manifest["command_audit_log"].endswith(COMMAND_AUDIT_LOG_NAME)

    assert destroy_run_workspace(run) is True
    assert not Path(context.workspace_root or "").exists()


@pytest.mark.anyio
async def test_test_executor_respects_workspace_command_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_COMMAND", "python3 -c \"print('ok from tests')\"")
    monkeypatch.setenv("WORKSPACE_ALLOWED_COMMAND_PREFIXES", "git")

    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    logs_root = tmp_path / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="RUN_TESTS",
        executor="test",
    )
    context = RunContext(
        project_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        repo_path=str(repo_root),
        logs_path=str(logs_root),
        workspace_status="READY",
    )

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "FAILED"
    assert "blocked" in result["message"].lower()
    assert result["payload"]["command_status"] == "BLOCKED"

    audit_path = logs_root / COMMAND_AUDIT_LOG_NAME
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["status"] == "BLOCKED"


@pytest.mark.anyio
async def test_test_executor_runs_pytest_via_active_interpreter(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_COMMAND", "pytest -q")

    captured: dict[str, object] = {}

    async def fake_run_workspace_command_async(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs.get("env")
        return SimpleNamespace(
            status="SUCCEEDED",
            stdout="ok",
            stderr="",
            exit_code=0,
            timed_out=False,
            log_path=None,
            audit_path=None,
        )

    monkeypatch.setattr("app.runtime.test_executor.run_workspace_command_async", fake_run_workspace_command_async)

    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    logs_root = tmp_path / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="RUN_TESTS",
        executor="test",
    )
    context = RunContext(
        project_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        repo_path=str(repo_root),
        logs_path=str(logs_root),
        workspace_status="READY",
    )

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "DONE"
    assert captured["command"] == [sys.executable, "-m", "pytest", "-q"]
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["PATH"].split(os.pathsep)[0] == str(Path(sys.executable).resolve().parent)


@pytest.mark.anyio
async def test_test_executor_skips_when_pytest_collects_no_tests(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_COMMAND", "pytest -q")

    async def fake_run_workspace_command_async(command, **kwargs):
        return SimpleNamespace(
            status="FAILED",
            stdout="no tests ran in 0.00s",
            stderr="",
            exit_code=5,
            timed_out=False,
            log_path=None,
            audit_path=None,
        )

    monkeypatch.setattr("app.runtime.test_executor.run_workspace_command_async", fake_run_workspace_command_async)

    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    logs_root = tmp_path / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="RUN_TESTS",
        executor="test",
    )
    context = RunContext(
        project_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        repo_path=str(repo_root),
        logs_path=str(logs_root),
        workspace_status="READY",
    )

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "SKIPPED"
    assert result["message"] == "No relevant tests were collected; validation skipped."
    assert result["payload"]["skip_reason"] == "no_tests_collected"
