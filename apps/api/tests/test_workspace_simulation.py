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
from app.runtime.execution_contract import build_execution_contract
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
async def test_test_executor_routes_frontend_run_tests_to_npm(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_COMMAND", "pytest -q")

    captured: dict[str, object] = {}

    async def fake_run_workspace_command_async(command, **kwargs):
        captured["command"] = command
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
    (repo_root / "apps" / "web").mkdir(parents=True, exist_ok=True)
    (repo_root / "apps" / "web" / "package.json").write_text('{"name":"web","scripts":{"test":"vitest run"}}\n', encoding="utf-8")

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="RUN_TESTS",
        executor="test",
        payload={"target_files": ["apps/web/src/components/landing/TestimonialsSection.vue"]},
    )
    context = RunContext(project_id=uuid.uuid4(), run_id=uuid.uuid4(), repo_path=str(repo_root), logs_path=str(tmp_path / "logs"))

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "DONE", f"result={result} calls={calls}"
    assert captured["command"] == ["npm", "-C", "apps/web", "run", "test"]
    assert result["payload"]["framework_router"] == "frontend_vite_vitest"
    assert result["payload"]["test_strategy"] == "vitest"


@pytest.mark.anyio
async def test_preview_validate_hydrates_missing_frontend_runtime_files(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    async def fake_run_workspace_command_async(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(
            status="SUCCEEDED",
            stdout="build ok",
            stderr="",
            exit_code=0,
            timed_out=False,
            log_path=None,
            audit_path=None,
        )

    monkeypatch.setattr("app.runtime.test_executor.run_workspace_command_async", fake_run_workspace_command_async)

    repo_root = tmp_path / "repo"
    (repo_root / "apps" / "web" / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "apps" / "web" / "src" / "main.ts").write_text("console.log('hi')\n", encoding="utf-8")
    # Intentionally omit package.json/vite.config/index.html to exercise hydration repair.

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="PREVIEW_VALIDATE",
        executor="test",
        payload={"target_files": ["apps/web/src/components/landing/TestimonialsSection.vue"]},
    )
    context = RunContext(project_id=uuid.uuid4(), run_id=uuid.uuid4(), repo_path=str(repo_root), logs_path=str(tmp_path / "logs"))

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "DONE", f"result={result} calls={calls}"
    assert (repo_root / "apps" / "web" / "package.json").exists()
    assert (repo_root / "apps" / "web" / "vite.config.ts").exists()
    assert (repo_root / "apps" / "web" / "index.html").exists()
    assert result["payload"]["preview_workspace_consistency"] in {"repaired", "ok"}
    assert isinstance(result["payload"]["workspace_hydration_repairs"], list)


@pytest.mark.anyio
async def test_preview_validate_reconciles_main_ts_when_app_vue_missing(tmp_path, monkeypatch):
    async def fake_run_workspace_command_async(command, **kwargs):
        return SimpleNamespace(
            status="SUCCEEDED",
            stdout="build ok",
            stderr="",
            exit_code=0,
            timed_out=False,
            log_path=None,
            audit_path=None,
        )

    monkeypatch.setattr("app.runtime.test_executor.run_workspace_command_async", fake_run_workspace_command_async)

    repo_root = tmp_path / "repo"
    src = repo_root / "apps" / "web" / "src"
    src.mkdir(parents=True, exist_ok=True)
    (repo_root / "apps" / "web" / "package.json").write_text('{"name":"web","scripts":{"build":"vite build"}}\n', encoding="utf-8")
    (src / "main.ts").write_text(
        'import { createApp } from "vue";\nimport App from "./App.vue";\n\ncreateApp(App).mount("#app");\n',
        encoding="utf-8",
    )

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="PREVIEW_VALIDATE",
        executor="test",
        payload={},
    )
    context = RunContext(project_id=uuid.uuid4(), run_id=uuid.uuid4(), repo_path=str(repo_root), logs_path=str(tmp_path / "logs"))

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "DONE"
    rewritten = (src / "main.ts").read_text(encoding="utf-8")
    assert './App.vue' in rewritten
    assert "createApp(App)" in rewritten
    assert (src / "App.vue").exists()
    assert any("entrypoint_reconciled" in item for item in result["payload"]["workspace_hydration_repairs"])


@pytest.mark.anyio
async def test_preview_validate_preserves_feature_graph_after_recovery(tmp_path, monkeypatch):
    async def fake_run_workspace_command_async(command, **kwargs):
        return SimpleNamespace(
            status="SUCCEEDED",
            stdout="build ok",
            stderr="",
            exit_code=0,
            timed_out=False,
            log_path=None,
            audit_path=None,
        )

    monkeypatch.setattr("app.runtime.test_executor.run_workspace_command_async", fake_run_workspace_command_async)

    repo_root = tmp_path / "repo"
    src = repo_root / "apps" / "web" / "src"
    landing = src / "pages" / "LandingPage.vue"
    feature = src / "components" / "landing" / "TestimonialsSection.vue"
    feature.parent.mkdir(parents=True, exist_ok=True)
    landing.parent.mkdir(parents=True, exist_ok=True)
    src.mkdir(parents=True, exist_ok=True)
    (repo_root / "apps" / "web" / "package.json").write_text('{"name":"web","scripts":{"build":"vite build"}}\n', encoding="utf-8")
    (src / "main.ts").write_text(
        'import { createApp } from "vue";\nimport App from "./App.vue";\n\ncreateApp(App).mount("#app");\n',
        encoding="utf-8",
    )
    landing.write_text(
        '<template><main><TestimonialsSection /></main></template>\n'
        '<script setup lang="ts">\n'
        'import TestimonialsSection from "../components/landing/TestimonialsSection.vue";\n'
        "</script>\n",
        encoding="utf-8",
    )
    feature.write_text("<template><section>Testimonials</section></template>\n", encoding="utf-8")

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="PREVIEW_VALIDATE",
        executor="test",
        payload={"target_files": ["apps/web/src/components/landing/TestimonialsSection.vue"]},
    )
    context = RunContext(project_id=uuid.uuid4(), run_id=uuid.uuid4(), repo_path=str(repo_root), logs_path=str(tmp_path / "logs"))

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "DONE"
    assert result["payload"]["composition_integrity_score"] >= 0.75
    assert result["payload"]["disconnected_feature_count"] == 0
    assert "apps/web/src/components/landing/TestimonialsSection.vue" in result["payload"]["preserved_feature_graph"]["reachable_features"]


@pytest.mark.anyio
async def test_preview_validate_fails_when_feature_component_disconnected(tmp_path, monkeypatch):
    async def fake_run_workspace_command_async(command, **kwargs):
        return SimpleNamespace(
            status="SUCCEEDED",
            stdout="build ok",
            stderr="",
            exit_code=0,
            timed_out=False,
            log_path=None,
            audit_path=None,
        )

    monkeypatch.setattr("app.runtime.test_executor.run_workspace_command_async", fake_run_workspace_command_async)

    repo_root = tmp_path / "repo"
    src = repo_root / "apps" / "web" / "src"
    (src / "components" / "landing").mkdir(parents=True, exist_ok=True)
    (src / "pages").mkdir(parents=True, exist_ok=True)
    (repo_root / "apps" / "web" / "package.json").write_text('{"name":"web","scripts":{"build":"vite build"}}\n', encoding="utf-8")
    (src / "main.ts").write_text(
        'import { createApp } from "vue";\nimport App from "./App.vue";\n\ncreateApp(App).mount("#app");\n',
        encoding="utf-8",
    )
    (src / "pages" / "LandingPage.vue").write_text("<template><main>No testimonials wired</main></template>\n", encoding="utf-8")
    (src / "components" / "landing" / "TestimonialsSection.vue").write_text(
        "<template><section>Testimonials</section></template>\n", encoding="utf-8"
    )

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="PREVIEW_VALIDATE",
        executor="test",
        payload={"target_files": ["apps/web/src/components/landing/TestimonialsSection.vue"]},
    )
    context = RunContext(project_id=uuid.uuid4(), run_id=uuid.uuid4(), repo_path=str(repo_root), logs_path=str(tmp_path / "logs"))

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "FAILED"
    assert result["payload"]["disconnected_feature_count"] == 1


@pytest.mark.anyio
async def test_preview_validate_repairs_runtime_shell_to_preserve_feature_reachability(tmp_path, monkeypatch):
    async def fake_run_workspace_command_async(command, **kwargs):
        return SimpleNamespace(
            status="SUCCEEDED",
            stdout="build ok",
            stderr="",
            exit_code=0,
            timed_out=False,
            log_path=None,
            audit_path=None,
        )

    monkeypatch.setattr("app.runtime.test_executor.run_workspace_command_async", fake_run_workspace_command_async)

    repo_root = tmp_path / "repo"
    src = repo_root / "apps" / "web" / "src"
    (src / "components" / "landing").mkdir(parents=True, exist_ok=True)
    (src / "pages").mkdir(parents=True, exist_ok=True)
    (repo_root / "apps" / "web" / "package.json").write_text('{"name":"web","scripts":{"build":"vite build"}}\n', encoding="utf-8")
    (src / "main.ts").write_text(
        'import { createApp } from "vue";\nimport App from "./App.vue";\n\ncreateApp(App).mount("#app");\n',
        encoding="utf-8",
    )
    # Broken runtime shell: does not compose LandingPage even though feature graph exists.
    (src / "App.vue").write_text("<template><main>stub</main></template>\n", encoding="utf-8")
    (src / "pages" / "LandingPage.vue").write_text(
        '<template><main><TestimonialsSection /></main></template>\n'
        '<script setup lang="ts">\n'
        'import TestimonialsSection from "../components/landing/TestimonialsSection.vue";\n'
        "</script>\n",
        encoding="utf-8",
    )
    (src / "components" / "landing" / "TestimonialsSection.vue").write_text(
        "<template><section>Testimonials</section></template>\n", encoding="utf-8"
    )

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="PREVIEW_VALIDATE",
        executor="test",
        payload={"target_files": ["apps/web/src/components/landing/TestimonialsSection.vue"]},
    )
    context = RunContext(project_id=uuid.uuid4(), run_id=uuid.uuid4(), repo_path=str(repo_root), logs_path=str(tmp_path / "logs"))

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "DONE"
    repaired_app = (src / "App.vue").read_text(encoding="utf-8")
    assert 'import LandingPage from "./pages/LandingPage.vue"' in repaired_app
    assert result["payload"]["disconnected_feature_count"] == 0


@pytest.mark.anyio
async def test_preview_validate_creates_landing_page_when_feature_exists(tmp_path, monkeypatch):
    async def fake_run_workspace_command_async(command, **kwargs):
        return SimpleNamespace(
            status="SUCCEEDED",
            stdout="build ok",
            stderr="",
            exit_code=0,
            timed_out=False,
            log_path=None,
            audit_path=None,
        )

    monkeypatch.setattr("app.runtime.test_executor.run_workspace_command_async", fake_run_workspace_command_async)

    repo_root = tmp_path / "repo"
    src = repo_root / "apps" / "web" / "src"
    (src / "components" / "landing").mkdir(parents=True, exist_ok=True)
    (repo_root / "apps" / "web" / "package.json").write_text('{"name":"web","scripts":{"build":"vite build"}}\n', encoding="utf-8")
    (src / "main.ts").write_text(
        'import { createApp } from "vue";\nimport App from "./App.vue";\n\ncreateApp(App).mount("#app");\n',
        encoding="utf-8",
    )
    (src / "App.vue").write_text("<template><main><h1>Landing Page</h1></main></template>\n", encoding="utf-8")
    (src / "components" / "landing" / "TestimonialsSection.vue").write_text(
        "<template><section>Testimonials</section></template>\n", encoding="utf-8"
    )

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="PREVIEW_VALIDATE",
        executor="test",
        payload={"target_files": ["apps/web/src/components/landing/TestimonialsSection.vue"]},
    )
    context = RunContext(project_id=uuid.uuid4(), run_id=uuid.uuid4(), repo_path=str(repo_root), logs_path=str(tmp_path / "logs"))

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "DONE"
    assert (src / "pages" / "LandingPage.vue").exists()
    assert result["payload"]["disconnected_feature_count"] == 0


@pytest.mark.anyio
async def test_preview_validate_normalizes_smart_quotes_in_vue_templates(tmp_path, monkeypatch):
    async def fake_run_workspace_command_async(command, **kwargs):
        return SimpleNamespace(
            status="SUCCEEDED",
            stdout="build ok",
            stderr="",
            exit_code=0,
            timed_out=False,
            log_path=None,
            audit_path=None,
        )

    monkeypatch.setattr("app.runtime.test_executor.run_workspace_command_async", fake_run_workspace_command_async)

    repo_root = tmp_path / "repo"
    src = repo_root / "apps" / "web" / "src"
    (src / "components" / "landing").mkdir(parents=True, exist_ok=True)
    (src / "pages").mkdir(parents=True, exist_ok=True)
    (repo_root / "apps" / "web" / "package.json").write_text('{"name":"web","scripts":{"build":"vite build"}}\n', encoding="utf-8")
    (src / "main.ts").write_text(
        'import { createApp } from "vue";\nimport App from "./App.vue";\n\ncreateApp(App).mount("#app");\n',
        encoding="utf-8",
    )
    (src / "App.vue").write_text(
        '<template>\n  <LandingPage />\n</template>\n<script setup lang="ts">\nimport LandingPage from "./pages/LandingPage.vue";\n</script>\n',
        encoding="utf-8",
    )
    (src / "pages" / "LandingPage.vue").write_text(
        '<template><main><TestimonialsSection /></main></template>\n'
        '<script setup lang="ts">\n'
        'import TestimonialsSection from "../components/landing/TestimonialsSection.vue";\n'
        "</script>\n",
        encoding="utf-8",
    )
    (src / "components" / "landing" / "TestimonialsSection.vue").write_text(
        "<template>\n  <blockquote class=“text-lg”>Quote</blockquote>\n</template>\n",
        encoding="utf-8",
    )

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="PREVIEW_VALIDATE",
        executor="test",
        payload={"target_files": ["apps/web/src/components/landing/TestimonialsSection.vue"]},
    )
    context = RunContext(project_id=uuid.uuid4(), run_id=uuid.uuid4(), repo_path=str(repo_root), logs_path=str(tmp_path / "logs"))

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "DONE"
    fixed = (src / "components" / "landing" / "TestimonialsSection.vue").read_text(encoding="utf-8")
    assert "class=\"text-lg\"" in fixed


@pytest.mark.anyio
async def test_preview_validate_repairs_missing_vite_binary_with_dependency_hydration(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.delenv("PREVIEW_URL", raising=False)

    async def fake_run_workspace_command_async(command, **kwargs):
        calls.append(list(command))
        if command[:4] == ["npm", "-C", "apps/web", "run"] and command[4] == "build":
            # First preview attempt fails because vite binary is missing.
            if len([c for c in calls if c[:4] == ["npm", "-C", "apps/web", "run"] and c[4] == "build"]) == 1:
                return SimpleNamespace(
                    status="FAILED",
                    stdout="",
                    stderr="sh: vite: command not found",
                    exit_code=127,
                    timed_out=False,
                    log_path=None,
                    audit_path=None,
                )
            # Retry after hydration succeeds.
            return SimpleNamespace(
                status="SUCCEEDED",
                stdout="build ok",
                stderr="",
                exit_code=0,
                timed_out=False,
                log_path=None,
                audit_path=None,
            )
        if command[:4] == ["npm", "-C", "apps/web", "install"]:
            return SimpleNamespace(
                status="SUCCEEDED",
                stdout="installed",
                stderr="",
                exit_code=0,
                timed_out=False,
                log_path=None,
                audit_path=None,
            )
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("app.runtime.test_executor.run_workspace_command_async", fake_run_workspace_command_async)

    repo_root = tmp_path / "repo"
    (repo_root / "apps" / "web" / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "apps" / "web" / "package.json").write_text('{"name":"web","scripts":{"build":"vite build"}}\n', encoding="utf-8")
    (repo_root / "apps" / "web" / "src" / "main.ts").write_text("console.log('hi')\n", encoding="utf-8")
    (repo_root / "apps" / "web" / "index.html").write_text("<!doctype html><html></html>\n", encoding="utf-8")

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="PREVIEW_VALIDATE",
        executor="test",
        payload={},
    )
    context = RunContext(project_id=uuid.uuid4(), run_id=uuid.uuid4(), repo_path=str(repo_root), logs_path=str(tmp_path / "logs"))

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "DONE", f"result={result} calls={calls}"
    assert ["npm", "-C", "apps/web", "install", "--no-audit", "--no-fund"] in calls
    assert result["payload"]["frontend_dependency_repair_attempted"] is True
    assert result["payload"]["frontend_dependency_repair_status"] == "repaired"
    assert any("node_modules" in item for item in result["payload"]["workspace_hydration_repairs"])


@pytest.mark.anyio
async def test_run_tests_reports_stack_mismatch_for_frontend_python_test_failure(tmp_path, monkeypatch):
    async def fake_run_workspace_command_async(command, **kwargs):
        return SimpleNamespace(
            status="SUCCEEDED",
            stdout="ModuleNotFoundError: No module named 'vue_test_utils'",
            stderr="",
            exit_code=2,
            timed_out=False,
            log_path=None,
            audit_path=None,
        )

    monkeypatch.setattr("app.runtime.test_executor.run_workspace_command_async", fake_run_workspace_command_async)

    repo_root = tmp_path / "repo"
    (repo_root / "apps" / "web").mkdir(parents=True, exist_ok=True)
    (repo_root / "apps" / "web" / "package.json").write_text('{"name":"web","scripts":{"test":"vitest run"}}\n', encoding="utf-8")

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="RUN_TESTS",
        executor="test",
        payload={"target_files": ["apps/web/src/components/landing/TestimonialsSection.vue"]},
    )
    context = RunContext(project_id=uuid.uuid4(), run_id=uuid.uuid4(), repo_path=str(repo_root), logs_path=str(tmp_path / "logs"))

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "FAILED"
    assert result["payload"]["stack_mismatch_detected"] is True
    assert result["payload"]["stack_mismatch_reason"] == "python_test_for_vue"
    assert result["payload"]["test_strategy"] == "vitest"


@pytest.mark.anyio
async def test_run_tests_reroutes_to_npm_on_frontend_stack_mismatch(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    async def fake_run_workspace_command_async(command, **kwargs):
        calls.append(list(command))
        is_pytest = bool(command and (command[0] == "pytest" or (len(command) >= 3 and command[1] == "-m" and command[2] == "pytest")))
        if is_pytest:
            return SimpleNamespace(
                status="SUCCEEDED",
                stdout="ModuleNotFoundError: No module named 'vue_test_utils'",
                stderr="",
                exit_code=2,
                timed_out=False,
                log_path=None,
                audit_path=None,
            )
        if command[:4] == ["npm", "-C", "apps/web", "run"] and command[4] == "test":
            return SimpleNamespace(
                status="SUCCEEDED",
                stdout="vitest ok",
                stderr="",
                exit_code=0,
                timed_out=False,
                log_path=None,
                audit_path=None,
            )
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("app.runtime.test_executor.run_workspace_command_async", fake_run_workspace_command_async)
    monkeypatch.setenv("TEST_COMMAND", "pytest -q")

    repo_root = tmp_path / "repo"
    (repo_root / "apps" / "web").mkdir(parents=True, exist_ok=True)
    (repo_root / "apps" / "web" / "package.json").write_text('{"name":"web","scripts":{"test":"vitest run"}}\n', encoding="utf-8")

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="RUN_TESTS",
        executor="test",
        payload={},
    )
    context = RunContext(project_id=uuid.uuid4(), run_id=uuid.uuid4(), repo_path=str(repo_root), logs_path=str(tmp_path / "logs"))

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "DONE"
    assert ["npm", "-C", "apps/web", "run", "test"] in calls
    assert result["payload"]["test_strategy"] == "vitest"
    assert result["payload"]["stack_mismatch_detected"] is True


@pytest.mark.anyio
async def test_test_executor_scopes_generic_pytest_to_work_item_targets(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_COMMAND", "pytest -q")

    captured: dict[str, object] = {}

    async def fake_run_workspace_command_async(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(
            status="SUCCEEDED",
            stdout="scoped ok",
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
        payload={
            "target_files": ["test_index_html.py"],
            "related_files": ["index.html"],
        },
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
    assert captured["command"] == [sys.executable, "-m", "pytest", "-q", "test_index_html.py"]


@pytest.mark.anyio
async def test_test_executor_prefers_execution_contract_command(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_COMMAND", "pytest -q")

    captured: dict[str, object] = {}

    async def fake_run_workspace_command_async(command, **kwargs):
        captured["command"] = command
        captured["allowed_prefixes"] = kwargs.get("allowed_prefixes")
        return SimpleNamespace(
            status="SUCCEEDED",
            stdout="contract ok",
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
    contract = build_execution_contract(
        run_summary={"target_files": ["apps/api/tests/test_runtime_flow.py"]},
        architecture_profile={
            "command_index": {
                "repo_tests": {
                    "command": "python3 -c \"print('contract tests')\"",
                    "kind": "test",
                    "paths": ["apps/api/tests"],
                }
            }
        },
        plan_snapshot=None,
    )

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
        execution_contract=contract,
    )

    result = await TestExecutor().execute(work_item, context)

    assert result["status"] == "DONE"
    assert captured["command"] == ["python3", "-c", "print('contract tests')"]
    assert captured["allowed_prefixes"] == contract.allowed_command_prefixes


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


@pytest.mark.anyio
async def test_test_executor_scopes_static_layout_changes_to_static_test_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_COMMAND", "pytest -q")

    captured: dict[str, object] = {}

    async def fake_run_workspace_command_async(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(
            status="SUCCEEDED",
            stdout="scoped",
            stderr="",
            exit_code=0,
            timed_out=False,
            log_path=None,
            audit_path=None,
        )

    monkeypatch.setattr("app.runtime.test_executor.run_workspace_command_async", fake_run_workspace_command_async)

    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "test_index_html.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    logs_root = tmp_path / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)

    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="RUN_TESTS",
        executor="test",
        payload={
            "target_files": ["index.html", "styles.css"],
        },
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
    assert captured["command"] == [sys.executable, "-m", "pytest", "-q", "test_index_html.py"]
