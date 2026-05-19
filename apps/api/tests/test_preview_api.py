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
