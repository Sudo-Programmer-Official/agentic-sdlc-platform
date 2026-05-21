import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.api.v1 import persistence
from app.db.base import Base
from app.db.models import Project, ProjectRepository, Run
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app
from app.schemas.preview import RunPreviewOut, RunPreviewServiceRef
from app.services import preview_service

ORIGINAL_ENSURE_VITE_FRONTEND_DEPENDENCIES = preview_service._ensure_vite_frontend_dependencies
ORIGINAL_ENSURE_BACKEND_RUNTIME_DEPENDENCIES = preview_service._ensure_backend_runtime_dependencies


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'preview-api.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    tenant_id = uuid.uuid4()

    async def override_get_tenant_context():
        return TenantContext(tenant_id=tenant_id, user_id="ui-user", role=None, enforcement=False)

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_tenant_context] = override_get_tenant_context
    session: AsyncSession = session_factory()
    try:
        yield session, tenant_id
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_tenant_context, None)
        await session.close()
        await engine.dispose()


@pytest.fixture(autouse=True)
def stub_preview_dependency_bootstrap(monkeypatch):
    async def fake_ensure_vite_frontend_dependencies(**_kwargs):
        frontend_root = _kwargs.get("frontend_root")
        if isinstance(frontend_root, Path):
            (frontend_root / "node_modules").mkdir(parents=True, exist_ok=True)
        return {"install_attempted": False, "install_succeeded": True}

    async def fake_ensure_backend_runtime_dependencies(**_kwargs):
        return {
            "install_attempted": False,
            "install_succeeded": True,
            "cached_hydration_state": "hit",
            "fastapi_import_ok": True,
            "uvicorn_import_ok": True,
            "app_import_ok": True,
        }

    monkeypatch.setattr(
        preview_service,
        "_ensure_vite_frontend_dependencies",
        fake_ensure_vite_frontend_dependencies,
    )
    monkeypatch.setattr(
        preview_service,
        "_ensure_backend_runtime_dependencies",
        fake_ensure_backend_runtime_dependencies,
    )
    monkeypatch.setattr(
        preview_service,
        "_probe_backend_runtime",
        lambda _url, _path=None: {"health_endpoint_ok": True, "health_probe": {"path": _path or "/health", "status": 200}},
    )


def test_collect_vite_preview_diagnostics_accepts_console_entry_module(monkeypatch):
    def fake_http_probe(_url: str, path: str):
        if path == "/":
            return {
                "path": path,
                "url": "http://127.0.0.1:4173/",
                "ok": True,
                "status": 200,
                "content_type": "text/html",
                "body_sample": "<!doctype html><script type='module' src='/src/main.ts'></script>",
            }
        if path == "/@vite/client":
            return {
                "path": path,
                "url": "http://127.0.0.1:4173/@vite/client",
                "ok": True,
                "status": 200,
                "content_type": "text/javascript",
                "body_sample": "import '/src/main.ts';",
            }
        return {
            "path": path,
            "url": "http://127.0.0.1:4173/src/main.ts",
            "ok": True,
            "status": 200,
            "content_type": "text/javascript",
            "body_sample": "console.log('ready');",
        }

    monkeypatch.setattr(preview_service, "_http_probe", fake_http_probe)
    diagnostics = preview_service._collect_vite_preview_diagnostics("http://127.0.0.1:4173")

    assert diagnostics["entry_path"] == "/src/main.ts"
    assert diagnostics["entry_probe"]["content_type"] == "text/javascript"
    assert diagnostics["entry_mime_ok"] is True
    assert diagnostics["mime_validation_passed"] is True


def test_collect_vite_preview_diagnostics_uses_entry_from_root_html(monkeypatch):
    def fake_http_probe(_url: str, path: str):
        if path == "/":
            return {
                "path": path,
                "url": "http://127.0.0.1:4173/",
                "ok": True,
                "status": 200,
                "content_type": "text/html",
                "body_sample": '<!doctype html><script type="module" src="/src/main.jsx"></script>',
            }
        if path == "/@vite/client":
            return {
                "path": path,
                "url": "http://127.0.0.1:4173/@vite/client",
                "ok": True,
                "status": 200,
                "content_type": "text/javascript",
                "body_sample": "import '/src/main.jsx';",
            }
        if path == "/src/main.jsx":
            return {
                "path": path,
                "url": "http://127.0.0.1:4173/src/main.jsx",
                "ok": True,
                "status": 200,
                "content_type": "text/javascript",
                "body_sample": "console.log('ready');",
            }
        return {
            "path": path,
            "url": f"http://127.0.0.1:4173{path}",
            "ok": False,
            "status": 404,
            "content_type": "text/plain",
            "body_sample": "not found",
        }

    monkeypatch.setattr(preview_service, "_http_probe", fake_http_probe)
    diagnostics = preview_service._collect_vite_preview_diagnostics("http://127.0.0.1:4173")

    assert diagnostics["entry_path"] == "/src/main.jsx"
    assert diagnostics["entry_probe"]["path"] == "/src/main.jsx"
    assert diagnostics["mime_validation_passed"] is True


def test_autofix_missing_vite_entrypoint_repairs_missing_app_vue(tmp_path: Path):
    frontend_root = tmp_path / "apps" / "web"
    src = frontend_root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "main.ts").write_text(
        'import { createApp } from "vue";\nimport App from "./App.vue";\ncreateApp(App).mount("#app");\n',
        encoding="utf-8",
    )

    repaired = preview_service._autofix_missing_vite_entrypoint(frontend_root)

    assert (src / "App.vue").exists()
    assert repaired["repair_action_applied"] == "repair_frontend_entrypoint"
    assert "src/App.vue" in repaired["repaired_files"]


def test_autofix_missing_vite_entrypoint_app_shell_uses_landing_page(tmp_path: Path):
    frontend_root = tmp_path / "apps" / "web"
    src = frontend_root / "src"
    (src / "pages").mkdir(parents=True, exist_ok=True)
    (src / "main.ts").write_text(
        'import { createApp } from "vue";\nimport App from "./App.vue";\ncreateApp(App).mount("#app");\n',
        encoding="utf-8",
    )
    (src / "pages" / "LandingPage.vue").write_text("<template><section>Landing</section></template>\n", encoding="utf-8")

    repaired = preview_service._autofix_missing_vite_entrypoint(frontend_root)

    app_shell = (src / "App.vue").read_text(encoding="utf-8")
    assert 'import LandingPage from "./pages/LandingPage.vue"' in app_shell
    assert "<LandingPage />" in app_shell
    assert repaired["repair_action_applied"] == "repair_frontend_entrypoint"


def test_collect_vite_preview_diagnostics_rejects_html_fallback_for_entry(monkeypatch):
    def fake_http_probe(_url: str, path: str):
        if path == "/":
            return {
                "path": path,
                "url": "http://127.0.0.1:4173/",
                "ok": True,
                "status": 200,
                "content_type": "text/html",
                "body_sample": "<!doctype html><script type='module' src='/src/main.ts'></script>",
            }
        if path == "/@vite/client":
            return {
                "path": path,
                "url": "http://127.0.0.1:4173/@vite/client",
                "ok": True,
                "status": 200,
                "content_type": "text/javascript",
                "body_sample": "import '/src/main.ts';",
            }
        return {
            "path": path,
            "url": "http://127.0.0.1:4173/src/main.ts",
            "ok": True,
            "status": 200,
            "content_type": "text/javascript",
            "body_sample": "<!doctype html><html><body>fallback</body></html>",
        }

    monkeypatch.setattr(preview_service, "_http_probe", fake_http_probe)
    diagnostics = preview_service._collect_vite_preview_diagnostics("http://127.0.0.1:4173")

    assert diagnostics["entry_probe"]["content_type"] == "text/javascript"
    assert diagnostics["entry_mime_ok"] is False
    assert diagnostics["mime_validation_passed"] is False


@pytest.mark.anyio
async def test_project_preview_profile_roundtrip(db_session):
    session, tenant_id = db_session
    project = Project(name="Preview project", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    payload = {
        "enabled": True,
        "mode": "local",
        "frontend_root": "apps/web",
        "backend_root": "apps/api",
        "frontend_build_command": "npm run build",
        "backend_build_command": "pytest -q",
        "frontend_start_command": "npm run dev -- --host $HOST --port $PORT",
        "backend_start_command": "uvicorn app.main:app --host $HOST --port $PORT",
        "ttl_hours": 12,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        save_resp = await client.post(f"/api/v1/projects/{project.id}/preview-profile", json=payload)
        fetch_resp = await client.get(f"/api/v1/projects/{project.id}/preview-profile")

    assert save_resp.status_code == 200, save_resp.text
    assert fetch_resp.status_code == 200, fetch_resp.text
    assert save_resp.json()["frontend_root"] == "apps/web"
    assert fetch_resp.json()["backend_start_command"] == "uvicorn app.main:app --host $HOST --port $PORT"
    assert fetch_resp.json()["ttl_hours"] == 12


@pytest.mark.anyio
async def test_project_preview_profile_get_bootstraps_default_when_missing(db_session):
    session, tenant_id = db_session
    project = Project(name="Preview default", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        fetch_resp = await client.get(f"/api/v1/projects/{project.id}/preview-profile")

    assert fetch_resp.status_code == 200, fetch_resp.text
    data = fetch_resp.json()
    assert data["project_id"] == str(project.id)
    assert data["enabled"] is True
    assert data["mode"] == "local"
    assert data["ttl_hours"] == 24


@pytest.mark.anyio
async def test_run_preview_routes_return_launcher_payload(db_session, monkeypatch):
    session, tenant_id = db_session
    project = Project(name="Preview run", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/preview",
        workspace_status="SEEDED",
    )
    session.add(run)
    await session.commit()
    await session.refresh(project)
    await session.refresh(run)

    preview_response = RunPreviewOut(
        run_id=run.id,
        project_id=project.id,
        status="READY",
        mode="local",
        branch_name=run.branch_name,
        reusable=True,
        launched_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=24),
        ttl_hours=24,
        preview_url="http://127.0.0.1:3100",
        frontend=RunPreviewServiceRef(kind="frontend", status="READY", url="http://127.0.0.1:3100", port=3100),
        backend=RunPreviewServiceRef(kind="backend", status="READY", url="http://127.0.0.1:8100", port=8100),
        profile_configured=True,
        repository_connected=True,
    )

    async def fake_launch(*_args, **_kwargs):
        return preview_response

    async def fake_get(*_args, **_kwargs):
        return preview_response

    async def fake_stop(*_args, **_kwargs):
        return preview_response.model_copy(update={"status": "STOPPED"})

    monkeypatch.setattr(persistence, "launch_run_preview", fake_launch)
    monkeypatch.setattr(persistence, "get_run_preview", fake_get)
    monkeypatch.setattr(persistence, "stop_run_preview", fake_stop)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        launch_resp = await client.post(f"/api/v1/runs/{run.id}/preview", json={"reuse_if_healthy": True})
        fetch_resp = await client.get(f"/api/v1/runs/{run.id}/preview")
        delete_resp = await client.delete(f"/api/v1/runs/{run.id}/preview")

    assert launch_resp.status_code == 200, launch_resp.text
    assert fetch_resp.status_code == 200, fetch_resp.text
    assert delete_resp.status_code == 200, delete_resp.text
    assert launch_resp.json()["status"] == "READY"
    assert launch_resp.json()["frontend"]["url"] == "http://127.0.0.1:3100"
    assert fetch_resp.json()["backend"]["url"] == "http://127.0.0.1:8100"
    assert delete_resp.json()["status"] == "STOPPED"


@pytest.mark.anyio
async def test_run_preview_route_forwards_repair_action(db_session, monkeypatch):
    session, tenant_id = db_session
    project = Project(name="Preview repair route", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        workspace_status="SEEDED",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    captured: dict[str, object] = {}

    async def fake_launch(*_args, **kwargs):
        captured.update(kwargs)
        return RunPreviewOut(
            run_id=run.id,
            project_id=project.id,
            status="READY",
            mode="local",
            profile_configured=True,
            repository_connected=False,
        )

    monkeypatch.setattr(persistence, "launch_run_preview", fake_launch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/runs/{run.id}/preview",
            json={"reuse_if_healthy": False, "repair_action": "repair_frontend_entrypoint"},
        )

    assert response.status_code == 200, response.text
    assert captured["repair_action"] == "repair_frontend_entrypoint"


@pytest.mark.anyio
async def test_run_preview_launch_maps_verification_error_to_conflict(db_session, monkeypatch):
    session, tenant_id = db_session
    project = Project(name="Preview conflict", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="QUEUED",
        executor="codex",
        workspace_status="PENDING",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    async def fake_launch(*_args, **_kwargs):
        raise ValueError("Run must be completed before preview launch")

    monkeypatch.setattr(persistence, "launch_run_preview", fake_launch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/v1/runs/{run.id}/preview", json={})

    assert response.status_code == 409
    assert response.json()["detail"] == "Run must be completed before preview launch"


@pytest.mark.anyio
async def test_launch_run_preview_uses_default_static_profile_for_repo_backed_run(db_session, monkeypatch, tmp_path):
    session, tenant_id = db_session
    project = Project(name="Static preview default", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/static-site.git",
            repo_full_name="acme/static-site",
            default_branch="main",
        )
    )

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    (workspace_root / "context").mkdir(parents=True)
    repo_root.mkdir(parents=True)
    (repo_root / "index.html").write_text("<!doctype html><html><body>Preview</body></html>", encoding="utf-8")

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/static-preview",
        workspace_status="SEEDED",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(preview_service, "_pick_port", lambda _preferred=None: 3100)
    monkeypatch.setattr(preview_service, "_service_healthcheck", lambda _url, _path=None: True)
    monkeypatch.setattr(preview_service, "_terminate_process_group", lambda _pid=None: None)
    monkeypatch.setattr(
        preview_service,
        "_collect_vite_preview_diagnostics",
        lambda _url: {
            "runtime_validation": "vite_dev",
            "root_html_ok": True,
            "vite_client_ok": True,
            "entry_mime_ok": True,
            "hmr_ws_expected": True,
            "mime_validation_passed": True,
            "entry_probe": {"path": "/src/main.ts", "content_type": "text/javascript"},
        },
    )

    def fake_start_service_process(**_kwargs):
        return preview_service._PreviewProcess(
            pid=12345,
            log_path=str(Path(tmp_path) / "preview.log"),
            url="http://127.0.0.1:3100",
            port=3100,
        )

    monkeypatch.setattr(preview_service, "_start_service_process", fake_start_service_process)

    preview = await preview_service.launch_run_preview(session, tenant_id=tenant_id, run_id=run.id)

    assert preview.status == "READY"
    assert preview.preview_url == "http://127.0.0.1:3100"
    assert preview.profile_configured is True
    assert preview.repository_connected is True
    assert preview.frontend is not None
    assert preview.frontend.start_command == "python3 -m http.server $PORT --bind $HOST"
    assert preview.frontend.healthcheck_path == "/"


@pytest.mark.anyio
async def test_launch_run_preview_rejects_invalid_static_entrypoint(db_session, tmp_path):
    session, tenant_id = db_session
    project = Project(name="Broken static preview", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/static-site.git",
            repo_full_name="acme/static-site",
            default_branch="main",
        )
    )

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    (workspace_root / "context").mkdir(parents=True)
    repo_root.mkdir(parents=True)
    (repo_root / "index.html").write_text("<div>Broken preview entry</div>", encoding="utf-8")

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/static-preview",
        workspace_status="SEEDED",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    with pytest.raises(ValueError, match="Static preview contract requires index.html to contain a <body> element"):
        await preview_service.launch_run_preview(session, tenant_id=tenant_id, run_id=run.id)


@pytest.mark.anyio
async def test_launch_run_preview_auto_switches_explicit_static_profile_to_vite_dev(db_session, monkeypatch, tmp_path):
    session, tenant_id = db_session
    project = Project(name="Vite static mismatch", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/vite-site.git",
            repo_full_name="acme/vite-site",
            default_branch="main",
        )
    )
    await preview_service.upsert_project_preview_profile(
        session,
        project_id=project.id,
        tenant_id=tenant_id,
        payload={
            "enabled": True,
            "mode": "local",
            "frontend_start_command": "python3 -m http.server $PORT --bind $HOST",
        },
    )

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    (workspace_root / "context").mkdir(parents=True)
    repo_root.mkdir(parents=True)
    (repo_root / "index.html").write_text(
        "<!doctype html><html><body><div id='app'></div><script type=\"module\" src=\"/src/main.ts\"></script></body></html>",
        encoding="utf-8",
    )
    (repo_root / "package.json").write_text(
        '{"name":"vite-site","scripts":{"dev":"vite"},"devDependencies":{"vite":"^5.0.0"}}',
        encoding="utf-8",
    )
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "main.ts").write_text("console.log('vite preview');\n", encoding="utf-8")

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/vite-preview",
        workspace_status="SEEDED",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(preview_service, "_pick_port", lambda _preferred=None: 59491)
    monkeypatch.setattr(preview_service, "_service_healthcheck", lambda _url, _path=None: True)
    monkeypatch.setattr(preview_service, "_terminate_process_group", lambda _pid=None: None)
    monkeypatch.setattr(
        preview_service,
        "_collect_vite_preview_diagnostics",
        lambda _url: {
            "runtime_validation": "vite_dev",
            "root_html_ok": True,
            "vite_client_ok": True,
            "entry_mime_ok": True,
            "hmr_ws_expected": True,
            "mime_validation_passed": True,
            "entry_probe": {"path": "/src/main.ts", "content_type": "text/javascript"},
        },
    )

    def fake_start_service_process(**_kwargs):
        return preview_service._PreviewProcess(
            pid=12345,
            log_path=str(Path(tmp_path) / "preview.log"),
            url="http://127.0.0.1:59491",
            port=59491,
        )

    monkeypatch.setattr(preview_service, "_start_service_process", fake_start_service_process)

    preview = await preview_service.launch_run_preview(session, tenant_id=tenant_id, run_id=run.id)
    assert preview.status == "READY"
    assert preview.frontend is not None
    assert preview.frontend.start_command in {
        "npm run dev -- --host $HOST --port $PORT",
        "npx vite --host $HOST --port $PORT",
    }


@pytest.mark.anyio
async def test_launch_run_preview_auto_switches_default_static_profile_to_vite_dev(db_session, monkeypatch, tmp_path):
    session, tenant_id = db_session
    project = Project(name="Vite auto profile", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/vite-site.git",
            repo_full_name="acme/vite-site",
            default_branch="main",
        )
    )

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    (workspace_root / "context").mkdir(parents=True)
    repo_root.mkdir(parents=True)
    (repo_root / "index.html").write_text(
        "<!doctype html><html><body><div id='app'></div><script type=\"module\" src=\"/src/main.ts\"></script></body></html>",
        encoding="utf-8",
    )
    (repo_root / "package.json").write_text(
        '{"name":"vite-site","scripts":{"dev":"vite"},"devDependencies":{"vite":"^5.0.0"}}',
        encoding="utf-8",
    )
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "main.ts").write_text("console.log('vite auto preview');\n", encoding="utf-8")

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/vite-auto-preview",
        workspace_status="SEEDED",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(preview_service, "_pick_port", lambda _preferred=None: 59491)
    monkeypatch.setattr(preview_service, "_service_healthcheck", lambda _url, _path=None: True)
    monkeypatch.setattr(preview_service, "_terminate_process_group", lambda _pid=None: None)
    monkeypatch.setattr(
        preview_service,
        "_collect_vite_preview_diagnostics",
        lambda _url: {
            "runtime_validation": "vite_dev",
            "root_html_ok": True,
            "vite_client_ok": True,
            "entry_mime_ok": True,
            "hmr_ws_expected": True,
            "mime_validation_passed": True,
            "entry_probe": {"path": "/src/main.ts", "content_type": "text/javascript"},
        },
    )

    def fake_start_service_process(**_kwargs):
        return preview_service._PreviewProcess(
            pid=12345,
            log_path=str(Path(tmp_path) / "preview.log"),
            url="http://127.0.0.1:59491",
            port=59491,
        )

    monkeypatch.setattr(preview_service, "_start_service_process", fake_start_service_process)

    preview = await preview_service.launch_run_preview(session, tenant_id=tenant_id, run_id=run.id)

    assert preview.status == "READY"
    assert preview.frontend is not None
    assert preview.frontend.start_command in {
        "npm run dev -- --host $HOST --port $PORT",
        "npx vite --host $HOST --port $PORT",
    }


@pytest.mark.anyio
async def test_launch_run_preview_detects_apps_web_root_for_vite_auto_switch(db_session, monkeypatch, tmp_path):
    session, tenant_id = db_session
    project = Project(name="Vite monorepo auto root", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/monorepo.git",
            repo_full_name="acme/monorepo",
            default_branch="main",
        )
    )
    await preview_service.upsert_project_preview_profile(
        session,
        project_id=project.id,
        tenant_id=tenant_id,
        payload={
            "enabled": True,
            "mode": "local",
            "frontend_start_command": "python3 -m http.server $PORT --bind $HOST",
        },
    )

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    app_web = repo_root / "apps" / "web"
    (workspace_root / "context").mkdir(parents=True)
    app_web.mkdir(parents=True)
    (app_web / "index.html").write_text(
        "<!doctype html><html><body><div id='app'></div><script type=\"module\" src=\"/src/main.ts\"></script></body></html>",
        encoding="utf-8",
    )
    (app_web / "package.json").write_text(
        '{"name":"web","scripts":{"dev":"vite"},"devDependencies":{"vite":"^5.0.0"}}',
        encoding="utf-8",
    )
    (app_web / "src").mkdir(parents=True)
    (app_web / "src" / "main.ts").write_text("console.log('vite monorepo preview');\n", encoding="utf-8")

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/vite-monorepo-preview",
        workspace_status="SEEDED",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(preview_service, "_pick_port", lambda _preferred=None: 59491)
    monkeypatch.setattr(preview_service, "_service_healthcheck", lambda _url, _path=None: True)
    monkeypatch.setattr(preview_service, "_terminate_process_group", lambda _pid=None: None)
    monkeypatch.setattr(
        preview_service,
        "_collect_vite_preview_diagnostics",
        lambda _url: {
            "runtime_validation": "vite_dev",
            "root_html_ok": True,
            "vite_client_ok": True,
            "entry_mime_ok": True,
            "hmr_ws_expected": True,
            "mime_validation_passed": True,
            "entry_probe": {"path": "/src/main.ts", "content_type": "text/javascript"},
        },
    )

    observed_cwd: dict[str, str] = {}

    def fake_start_service_process(**kwargs):
        observed_cwd["cwd"] = str(kwargs["cwd"])
        return preview_service._PreviewProcess(
            pid=12345,
            log_path=str(Path(tmp_path) / "preview.log"),
            url="http://127.0.0.1:59491",
            port=59491,
        )

    monkeypatch.setattr(preview_service, "_start_service_process", fake_start_service_process)

    preview = await preview_service.launch_run_preview(session, tenant_id=tenant_id, run_id=run.id)
    assert preview.status == "READY"
    assert preview.frontend is not None
    assert preview.frontend.start_command in {
        "npm run dev -- --host $HOST --port $PORT",
        "npx vite --host $HOST --port $PORT",
    }
    assert observed_cwd["cwd"] == str(app_web)


@pytest.mark.anyio
async def test_launch_run_preview_records_vite_module_mime_diagnostics_for_monorepo_fastapi(db_session, monkeypatch, tmp_path):
    session, tenant_id = db_session
    project = Project(name="Vite fastapi diagnostics", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/monorepo-fastapi.git",
            repo_full_name="acme/monorepo-fastapi",
            default_branch="main",
        )
    )

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    app_web = repo_root / "apps" / "web"
    app_api = repo_root / "apps" / "api" / "app"
    (workspace_root / "context").mkdir(parents=True)
    app_web.mkdir(parents=True)
    app_api.mkdir(parents=True)
    (app_web / "index.html").write_text(
        "<!doctype html><html><body><div id='app'></div><script type=\"module\" src=\"/src/main.ts\"></script></body></html>",
        encoding="utf-8",
    )
    (app_web / "package.json").write_text(
        '{"name":"web","scripts":{"dev":"vite"},"devDependencies":{"vite":"^5.0.0"}}',
        encoding="utf-8",
    )
    (app_web / "src").mkdir(parents=True)
    (app_web / "src" / "main.ts").write_text("console.log('vite fastapi preview');\n", encoding="utf-8")
    (repo_root / "apps" / "api" / "main.py").write_text("from app.main import app\n", encoding="utf-8")
    (app_api / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/vite-fastapi-preview",
        workspace_status="SEEDED",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(preview_service, "_pick_port", lambda _preferred=None: 59491)
    monkeypatch.setattr(preview_service, "_service_healthcheck", lambda _url, _path=None: True)
    monkeypatch.setattr(preview_service, "_terminate_process_group", lambda _pid=None: None)
    monkeypatch.setattr(
        preview_service,
        "_start_service_process",
        lambda **_kwargs: preview_service._PreviewProcess(
            pid=12345,
            log_path=str(Path(tmp_path) / "preview.log"),
            url="http://127.0.0.1:59491",
            port=59491,
        ),
    )
    monkeypatch.setattr(
        preview_service,
        "_collect_vite_preview_diagnostics",
        lambda _url: {
            "runtime_validation": "vite_dev",
            "root_html_ok": True,
            "vite_client_ok": True,
            "entry_mime_ok": True,
            "hmr_ws_expected": True,
            "mime_validation_passed": True,
            "root_probe": {"path": "/", "content_type": "text/html"},
            "vite_client_probe": {"path": "/@vite/client", "content_type": "text/javascript"},
            "entry_probe": {"path": "/src/main.ts", "content_type": "text/javascript"},
        },
    )

    preview = await preview_service.launch_run_preview(session, tenant_id=tenant_id, run_id=run.id)

    assert preview.runtime_classification == "MONOREPO_VITE_FASTAPI"
    assert preview.preview_strategy == "VITE_DEV"
    assert preview.active_preview_command == "npx vite --host $HOST --port $PORT"
    assert preview.upstream_preview_port == 59491
    assert preview.preview_diagnostics["entry_probe"]["content_type"] == "text/javascript"
    assert preview.preview_diagnostics["vite_client_ok"] is True


@pytest.mark.anyio
async def test_launch_run_preview_rejects_vite_preview_when_module_asset_mime_is_invalid(db_session, monkeypatch, tmp_path):
    session, tenant_id = db_session
    project = Project(name="Vite mime failure", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/monorepo-fastapi.git",
            repo_full_name="acme/monorepo-fastapi",
            default_branch="main",
        )
    )

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    app_web = repo_root / "apps" / "web"
    app_api = repo_root / "apps" / "api" / "app"
    (workspace_root / "context").mkdir(parents=True)
    app_web.mkdir(parents=True)
    app_api.mkdir(parents=True)
    (app_web / "index.html").write_text(
        "<!doctype html><html><body><div id='app'></div><script type=\"module\" src=\"/src/main.ts\"></script></body></html>",
        encoding="utf-8",
    )
    (app_web / "package.json").write_text(
        '{"name":"web","scripts":{"dev":"vite"},"devDependencies":{"vite":"^5.0.0"}}',
        encoding="utf-8",
    )
    (app_web / "src").mkdir(parents=True)
    (app_web / "src" / "main.ts").write_text("console.log('vite mime failure');\n", encoding="utf-8")
    (repo_root / "apps" / "api" / "main.py").write_text("from app.main import app\n", encoding="utf-8")
    (app_api / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/vite-bad-mime",
        workspace_status="SEEDED",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
        summary={
            "preview": {
                "status": "READY",
                "preview_url": "http://127.0.0.1:62305",
                "frontend": {"url": "http://127.0.0.1:62305", "log_path": "/tmp/stale.log"},
                "verification_note": "stale previous failure",
            },
            "preview_status": "READY",
            "preview_url": "http://127.0.0.1:62305",
        },
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(preview_service, "_pick_port", lambda _preferred=None: 59491)
    monkeypatch.setattr(preview_service, "_service_healthcheck", lambda _url, _path=None: True)
    monkeypatch.setattr(preview_service, "_terminate_process_group", lambda _pid=None: None)
    monkeypatch.setattr(
        preview_service,
        "_start_service_process",
        lambda **_kwargs: preview_service._PreviewProcess(
            pid=12345,
            log_path=str(Path(tmp_path) / "preview.log"),
            url="http://127.0.0.1:59491",
            port=59491,
        ),
    )
    monkeypatch.setattr(
        preview_service,
        "_collect_vite_preview_diagnostics",
        lambda _url: {
            "runtime_validation": "vite_dev",
            "root_html_ok": True,
            "vite_client_ok": True,
            "entry_mime_ok": False,
            "hmr_ws_expected": True,
            "mime_validation_passed": False,
            "entry_probe": {"path": "/src/main.ts", "content_type": ""},
        },
    )

    with pytest.raises(ValueError, match="module asset validation failed"):
        await preview_service.launch_run_preview(
            session,
            tenant_id=tenant_id,
            run_id=run.id,
            reuse_if_healthy=False,
        )

    await session.refresh(run)
    assert isinstance(run.summary, dict)
    assert run.summary["preview"]["status"] == "FAILED"
    assert run.summary["preview"]["verification_note"].startswith("Vite preview started, but module asset validation failed")
    assert run.summary["preview"].get("preview_url") is None
    assert run.summary.get("preview_url") is None


@pytest.mark.anyio
async def test_preview_convergence_reconciles_after_successful_vite_boot(db_session, monkeypatch, tmp_path):
    session, tenant_id = db_session
    project = Project(name="Vite convergence reconciler", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/monorepo-fastapi.git",
            repo_full_name="acme/monorepo-fastapi",
            default_branch="main",
        )
    )

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    app_web = repo_root / "apps" / "web"
    app_api = repo_root / "apps" / "api" / "app"
    (workspace_root / "context").mkdir(parents=True)
    app_web.mkdir(parents=True)
    app_api.mkdir(parents=True)
    (app_web / "index.html").write_text(
        "<!doctype html><html><body><div id='app'></div><script type=\"module\" src=\"/src/main.ts\"></script></body></html>",
        encoding="utf-8",
    )
    (app_web / "package.json").write_text(
        '{"name":"web","scripts":{"dev":"vite"},"devDependencies":{"vite":"^5.0.0"}}',
        encoding="utf-8",
    )
    (app_web / "src").mkdir(parents=True)
    (app_web / "src" / "main.ts").write_text("console.log('converged');\n", encoding="utf-8")
    (repo_root / "apps" / "api" / "main.py").write_text("from app.main import app\n", encoding="utf-8")
    (app_api / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/vite-convergence",
        workspace_status="SEEDED",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
        summary={
            "preview": {
                "status": "FAILED",
                "verification_note": "stale validator failure",
            },
            "preview_status": "FAILED",
        },
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(preview_service, "_pick_port", lambda _preferred=None: 59491)
    monkeypatch.setattr(preview_service, "_service_healthcheck", lambda _url, _path=None: True)
    monkeypatch.setattr(preview_service, "_terminate_process_group", lambda _pid=None: None)
    monkeypatch.setattr(
        preview_service,
        "_start_service_process",
        lambda **_kwargs: preview_service._PreviewProcess(
            pid=12345,
            log_path=str(Path(tmp_path) / "preview.log"),
            url="http://127.0.0.1:59491",
            port=59491,
        ),
    )
    monkeypatch.setattr(
        preview_service,
        "_reconcile_vite_preview_convergence",
        lambda _url: {
            "healthy": True,
            "verification_note": None,
            "preview_launch_state": {"phase": "launch", "probe_count": 1, "checks": {"mime_validation_passed": False}},
            "preview_runtime_state": {
                "phase": "stabilizing",
                "probe_count": 2,
                "checks": {
                    "runtime_validation": "vite_dev",
                    "root_html_ok": True,
                    "vite_client_ok": True,
                    "entry_mime_ok": True,
                    "mime_validation_passed": True,
                    "entry_probe": {"path": "/src/main.ts", "content_type": "text/javascript"},
                },
                "stabilization_window_seconds": 0.8,
            },
            "preview_terminal_state": {"phase": "terminal", "status": "READY", "authoritative": True, "failed_checks": ""},
        },
    )

    preview = await preview_service.launch_run_preview(session, tenant_id=tenant_id, run_id=run.id)
    await session.refresh(run)

    assert preview.status == "READY"
    assert preview.verification_note is None
    assert preview.preview_diagnostics["preview_terminal_state"]["status"] == "READY"
    assert run.summary["preview"]["status"] == "READY"
    assert run.summary["preview"]["verification_note"] is None


@pytest.mark.anyio
async def test_launch_run_preview_rejects_monorepo_vite_fastapi_when_apps_web_entrypoint_is_missing(db_session, monkeypatch, tmp_path):
    session, tenant_id = db_session
    project = Project(name="Vite missing monorepo entry", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/monorepo-fastapi.git",
            repo_full_name="acme/monorepo-fastapi",
            default_branch="main",
        )
    )

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    app_web = repo_root / "apps" / "web"
    app_api = repo_root / "apps" / "api" / "app"
    (workspace_root / "context").mkdir(parents=True)
    app_web.mkdir(parents=True)
    app_api.mkdir(parents=True)
    (app_web / "index.html").write_text(
        "<!doctype html><html><body><div id='app'></div><script type=\"module\" src=\"/src/main.ts\"></script></body></html>",
        encoding="utf-8",
    )
    (app_web / "package.json").write_text(
        '{"name":"web","scripts":{"dev":"vite"},"devDependencies":{"vite":"^5.0.0"}}',
        encoding="utf-8",
    )
    (repo_root / "apps" / "api" / "main.py").write_text("from app.main import app\n", encoding="utf-8")
    (app_api / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/vite-missing-entry",
        workspace_status="SEEDED",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
        summary={
            "preview": {
                "status": "READY",
                "preview_url": "http://127.0.0.1:62305",
                "frontend": {"url": "http://127.0.0.1:62305", "log_path": "/tmp/stale.log"},
            },
            "preview_status": "READY",
            "preview_url": "http://127.0.0.1:62305",
        },
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(preview_service, "_pick_port", lambda _preferred=None: 59491)
    monkeypatch.setattr(preview_service, "_service_healthcheck", lambda _url, _path=None: True)
    monkeypatch.setattr(preview_service, "_terminate_process_group", lambda _pid=None: None)

    with pytest.raises(ValueError, match="requires apps/web/src/main.ts or apps/web/src/main.js"):
        await preview_service.launch_run_preview(
            session,
            tenant_id=tenant_id,
            run_id=run.id,
            reuse_if_healthy=False,
        )

    await session.refresh(run)
    assert isinstance(run.summary, dict)
    assert run.summary["preview"]["status"] == "FAILED"
    assert "requires apps/web/src/main.ts or apps/web/src/main.js" in run.summary["preview"]["verification_note"]
    assert run.summary["preview"].get("preview_url") is None
    assert run.summary.get("preview_url") is None


@pytest.mark.anyio
async def test_launch_run_preview_repairs_missing_monorepo_entrypoint_when_requested(db_session, monkeypatch, tmp_path):
    session, tenant_id = db_session
    project = Project(name="Vite repair entrypoint", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/monorepo-fastapi.git",
            repo_full_name="acme/monorepo-fastapi",
            default_branch="main",
        )
    )

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    app_web = repo_root / "apps" / "web"
    app_api = repo_root / "apps" / "api" / "app"
    (workspace_root / "context").mkdir(parents=True)
    app_web.mkdir(parents=True)
    app_api.mkdir(parents=True)
    (app_web / "index.html").write_text(
        "<!doctype html><html><body><div id='app'></div><script type=\"module\" src=\"/src/main.ts\"></script></body></html>",
        encoding="utf-8",
    )
    (app_web / "package.json").write_text(
        '{"name":"web","scripts":{"dev":"vite"},"devDependencies":{"vite":"^5.0.0"}}',
        encoding="utf-8",
    )
    (repo_root / "apps" / "api" / "main.py").write_text("from app.main import app\n", encoding="utf-8")
    (app_api / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/vite-repair-entry",
        workspace_status="SEEDED",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(preview_service, "_pick_port", lambda _preferred=None: 59491)
    monkeypatch.setattr(preview_service, "_service_healthcheck", lambda _url, _path=None: True)
    monkeypatch.setattr(preview_service, "_terminate_process_group", lambda _pid=None: None)
    monkeypatch.setattr(
        preview_service,
        "_start_service_process",
        lambda **_kwargs: preview_service._PreviewProcess(
            pid=12345,
            log_path=str(Path(tmp_path) / "preview.log"),
            url="http://127.0.0.1:59491",
            port=59491,
        ),
    )
    monkeypatch.setattr(
        preview_service,
        "_collect_vite_preview_diagnostics",
        lambda _url: {
            "runtime_validation": "vite_dev",
            "root_html_ok": True,
            "vite_client_ok": True,
            "entry_mime_ok": True,
            "hmr_ws_expected": True,
            "mime_validation_passed": True,
            "entry_probe": {"path": "/src/main.ts", "content_type": "text/javascript"},
        },
    )

    preview = await preview_service.launch_run_preview(
        session,
        tenant_id=tenant_id,
        run_id=run.id,
        repair_action="repair_frontend_entrypoint",
        reuse_if_healthy=False,
    )

    assert preview.status == "READY"
    assert preview.preview_diagnostics["repair_action_applied"] == "repair_frontend_entrypoint"
    assert (app_web / "src" / "main.ts").exists()
    assert (app_web / "package.json").exists()
    assert (app_web / "vite.config.ts").exists()
    assert (app_web / "src" / "pages" / "LandingPage.vue").exists()
    assert (app_web / "src" / "components" / "landing" / "HeroSection.vue").exists()
    assert (app_web / "src" / "components" / "landing" / "LeadCaptureForm.vue").exists()


@pytest.mark.anyio
async def test_launch_run_preview_installs_vite_dependencies_before_start(db_session, monkeypatch, tmp_path):
    session, tenant_id = db_session
    project = Project(name="Vite install bootstrap", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/monorepo-fastapi.git",
            repo_full_name="acme/monorepo-fastapi",
            default_branch="main",
        )
    )

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    app_web = repo_root / "apps" / "web"
    app_api = repo_root / "apps" / "api" / "app"
    (workspace_root / "context").mkdir(parents=True)
    app_web.mkdir(parents=True)
    app_api.mkdir(parents=True)
    (app_web / "index.html").write_text(
        "<!doctype html><html><body><div id='app'></div><script type=\"module\" src=\"/src/main.ts\"></script></body></html>",
        encoding="utf-8",
    )
    (app_web / "package.json").write_text(
        '{"name":"web","private":true,"scripts":{"dev":"vite"},"dependencies":{"vue":"^3.5.13"},"devDependencies":{"vite":"^5.4.10","@vitejs/plugin-vue":"^5.2.1"}}',
        encoding="utf-8",
    )
    (app_web / "vite.config.ts").write_text(
        'import { defineConfig } from "vite";\nimport vue from "@vitejs/plugin-vue";\nexport default defineConfig({ plugins: [vue()] });\n',
        encoding="utf-8",
    )
    (app_web / "src").mkdir(parents=True)
    (app_web / "src" / "main.ts").write_text("console.log('vite install bootstrap');\n", encoding="utf-8")
    (repo_root / "apps" / "api" / "main.py").write_text("from app.main import app\n", encoding="utf-8")
    (app_api / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/vite-install-bootstrap",
        workspace_status="SEEDED",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(preview_service, "_ensure_vite_frontend_dependencies", ORIGINAL_ENSURE_VITE_FRONTEND_DEPENDENCIES)
    monkeypatch.setattr(preview_service, "_pick_port", lambda _preferred=None: 59491)
    monkeypatch.setattr(preview_service, "_service_healthcheck", lambda _url, _path=None: True)
    monkeypatch.setattr(preview_service, "_terminate_process_group", lambda _pid=None: None)
    monkeypatch.setattr(
        preview_service,
        "_start_service_process",
        lambda **_kwargs: preview_service._PreviewProcess(
            pid=12345,
            log_path=str(Path(tmp_path) / "preview.log"),
            url="http://127.0.0.1:59491",
            port=59491,
        ),
    )
    monkeypatch.setattr(
        preview_service,
        "_collect_vite_preview_diagnostics",
        lambda _url: {
            "runtime_validation": "vite_dev",
            "root_html_ok": True,
            "vite_client_ok": True,
            "entry_mime_ok": True,
            "hmr_ws_expected": True,
            "mime_validation_passed": True,
            "entry_probe": {"path": "/src/main.ts", "content_type": "text/javascript"},
        },
    )

    async def fake_run_workspace_command_async(command, **_kwargs):
        assert command == ["npm", "install", "--no-fund", "--no-audit"]
        (app_web / "node_modules").mkdir(parents=True, exist_ok=True)
        return type("Result", (), {"status": "SUCCEEDED", "stdout": "", "stderr": ""})()

    monkeypatch.setattr(preview_service, "run_workspace_command_async", fake_run_workspace_command_async)

    preview = await preview_service.launch_run_preview(session, tenant_id=tenant_id, run_id=run.id)

    assert preview.status == "READY"
    assert preview.frontend_install_status == "installed"
    assert preview.preview_diagnostics["frontend_bootstrap"]["install_attempted"] is True
    assert preview.preview_diagnostics["frontend_bootstrap"]["install_succeeded"] is True


@pytest.mark.anyio
async def test_launch_run_preview_autofixes_missing_package_json_for_vite_workspace(db_session, monkeypatch, tmp_path):
    session, tenant_id = db_session
    project = Project(name="Vite autofix", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/vite-missing-pkg.git",
            repo_full_name="acme/vite-missing-pkg",
            default_branch="main",
        )
    )
    await preview_service.upsert_project_preview_profile(
        session,
        project_id=project.id,
        tenant_id=tenant_id,
        payload={
            "enabled": True,
            "mode": "local",
            "frontend_start_command": "python3 -m http.server $PORT --bind $HOST",
        },
    )

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    src_root = repo_root / "src"
    (workspace_root / "context").mkdir(parents=True)
    src_root.mkdir(parents=True)
    (repo_root / "index.html").write_text(
        "<!doctype html><html><body><div id='app'></div><script type=\"module\" src=\"/src/main.ts\"></script></body></html>",
        encoding="utf-8",
    )
    (src_root / "main.ts").write_text("console.log('preview');\n", encoding="utf-8")

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/vite-autofix-preview",
        workspace_status="SEEDED",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(preview_service, "_pick_port", lambda _preferred=None: 59491)
    monkeypatch.setattr(preview_service, "_service_healthcheck", lambda _url, _path=None: True)
    monkeypatch.setattr(preview_service, "_terminate_process_group", lambda _pid=None: None)
    monkeypatch.setattr(
        preview_service,
        "_collect_vite_preview_diagnostics",
        lambda _url: {
            "runtime_validation": "vite_dev",
            "root_html_ok": True,
            "vite_client_ok": True,
            "entry_mime_ok": True,
            "hmr_ws_expected": True,
            "mime_validation_passed": True,
            "entry_probe": {"path": "/src/main.ts", "content_type": "text/javascript"},
        },
    )

    def fake_start_service_process(**_kwargs):
        return preview_service._PreviewProcess(
            pid=12345,
            log_path=str(Path(tmp_path) / "preview.log"),
            url="http://127.0.0.1:59491",
            port=59491,
        )

    monkeypatch.setattr(preview_service, "_start_service_process", fake_start_service_process)

    preview = await preview_service.launch_run_preview(session, tenant_id=tenant_id, run_id=run.id)
    assert preview.status == "READY"
    assert preview.frontend is not None
    assert preview.frontend.start_command == "npx vite --host $HOST --port $PORT"
    assert (repo_root / "package.json").exists()


@pytest.mark.anyio
async def test_launch_run_preview_sanitizes_stale_vite_script_when_static_fallback(db_session, monkeypatch, tmp_path):
    session, tenant_id = db_session
    project = Project(name="Stale vite static fallback", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/static-fallback.git",
            repo_full_name="acme/static-fallback",
            default_branch="main",
        )
    )
    await preview_service.upsert_project_preview_profile(
        session,
        project_id=project.id,
        tenant_id=tenant_id,
        payload={
            "enabled": True,
            "mode": "local",
            "frontend_start_command": "python3 -m http.server $PORT --bind $HOST",
        },
    )

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    (workspace_root / "context").mkdir(parents=True)
    repo_root.mkdir(parents=True)
    index_path = repo_root / "index.html"
    index_path.write_text(
        "<!doctype html><html><body><div>hello</div><script type=\"module\" src=\"/src/main.ts\"></script></body></html>",
        encoding="utf-8",
    )

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/static-fallback",
        workspace_status="SEEDED",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(preview_service, "_pick_port", lambda _preferred=None: 65079)
    monkeypatch.setattr(preview_service, "_service_healthcheck", lambda _url, _path=None: True)
    monkeypatch.setattr(preview_service, "_terminate_process_group", lambda _pid=None: None)

    def fake_start_service_process(**_kwargs):
        return preview_service._PreviewProcess(
            pid=12345,
            log_path=str(Path(tmp_path) / "preview.log"),
            url="http://127.0.0.1:65079",
            port=65079,
        )

    monkeypatch.setattr(preview_service, "_start_service_process", fake_start_service_process)

    preview = await preview_service.launch_run_preview(session, tenant_id=tenant_id, run_id=run.id)
    assert preview.status == "READY"
    assert preview.frontend is not None
    assert preview.frontend.start_command == "python3 -m http.server $PORT --bind $HOST"
    assert "/src/main.ts" not in index_path.read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_launch_run_preview_static_fallback_rewrites_framework_only_markup(db_session, monkeypatch, tmp_path):
    session, tenant_id = db_session
    project = Project(name="Framework markup fallback", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/framework-markup.git",
            repo_full_name="acme/framework-markup",
            default_branch="main",
        )
    )
    await preview_service.upsert_project_preview_profile(
        session,
        project_id=project.id,
        tenant_id=tenant_id,
        payload={"enabled": True, "mode": "local", "frontend_start_command": "python3 -m http.server $PORT --bind $HOST"},
    )

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    (workspace_root / "context").mkdir(parents=True)
    repo_root.mkdir(parents=True)
    index_path = repo_root / "index.html"
    index_path.write_text(
        """<!doctype html><html><body><div id="app"><HeroSection><template #title><span>AI-Powered B2B Sales Automation</span></template><template #subtitle><span>Accelerate your sales pipeline.</span></template><template #primaryCta><PrimaryButton>Get Started</PrimaryButton></template></HeroSection></div></body></html>""",
        encoding="utf-8",
    )

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/framework-fallback",
        workspace_status="SEEDED",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(preview_service, "_pick_port", lambda _preferred=None: 49567)
    monkeypatch.setattr(preview_service, "_service_healthcheck", lambda _url, _path=None: True)
    monkeypatch.setattr(preview_service, "_terminate_process_group", lambda _pid=None: None)
    monkeypatch.setattr(
        preview_service,
        "_start_service_process",
        lambda **_kwargs: preview_service._PreviewProcess(
            pid=12345,
            log_path=str(Path(tmp_path) / "preview.log"),
            url="http://127.0.0.1:49567",
            port=49567,
        ),
    )

    preview = await preview_service.launch_run_preview(session, tenant_id=tenant_id, run_id=run.id)
    assert preview.status == "READY"
    rendered = index_path.read_text(encoding="utf-8")
    assert "<HeroSection" not in rendered
    assert "AI-Powered B2B Sales Automation" in rendered


def test_service_healthcheck_rejects_malformed_slot_rewrite_html(monkeypatch):
    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _n: int = -1):
            return b"<!doctype html><html><head><title><ContentSlot x /><//title></head></html>"

    monkeypatch.setattr(preview_service, "urlopen", lambda *_args, **_kwargs: _Response())
    assert preview_service._service_healthcheck("http://127.0.0.1:57966", "/") is False


def test_service_healthcheck_rejects_unresolved_contentslot_in_static_html(monkeypatch):
    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _n: int = -1):
            return b"<!doctype html><html><body><ContentSlot content-key=\"hero\" /></body></html>"

    monkeypatch.setattr(preview_service, "urlopen", lambda *_args, **_kwargs: _Response())
    assert preview_service._service_healthcheck("http://127.0.0.1:57966", "/") is False
