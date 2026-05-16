import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Project, ProjectDeployment, Run
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'deployments-api.db'}", future=True)
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
async def test_create_project_deployment_and_list(db_session):
    session, tenant_id = db_session
    project = Project(name="Deployable app", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    run = Run(project_id=project.id, tenant_id=tenant_id, status="COMPLETED", executor="codex", branch_name="run/deploy")
    session.add(run)
    await session.commit()

    payload = {
        "provider": "vercel",
        "target": "user_app",
        "run_id": str(run.id),
        "request_key": "deploy:run:1",
        "repository_url": "https://github.com/acme/deployable-app",
        "repository_full_name": "acme/deployable-app",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(f"/api/v1/projects/{project.id}/deployments", json=payload)
        listed = await client.get(f"/api/v1/projects/{project.id}/deployments")

    assert created.status_code == 200, created.text
    assert listed.status_code == 200, listed.text
    created_body = created.json()
    assert created_body["provider"] == "vercel"
    assert created_body["status"] == "QUEUED"
    assert "vercel.com/new/clone" in (created_body.get("deployment_url") or "")
    assert len(listed.json()) == 1


@pytest.mark.anyio
async def test_create_project_deployment_is_idempotent_by_request_key(db_session):
    session, tenant_id = db_session
    project = Project(name="Deploy dedupe", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    payload = {
        "provider": "render",
        "target": "user_app",
        "request_key": "deploy:stable-key",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(f"/api/v1/projects/{project.id}/deployments", json=payload)
        second = await client.post(f"/api/v1/projects/{project.id}/deployments", json=payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.anyio
async def test_retry_project_deployment_moves_back_to_queue(db_session):
    session, tenant_id = db_session
    project = Project(name="Deploy retry", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    payload = {
        "provider": "vercel",
        "target": "user_app",
        "request_key": "deploy:retry-key",
        "repository_url": "https://github.com/acme/retry-app",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(f"/api/v1/projects/{project.id}/deployments", json=payload)
        deployment_id = created.json()["id"]
    deployment = await session.get(ProjectDeployment, uuid.UUID(deployment_id))
    assert deployment is not None
    deployment.status = "MANUAL_ACTION_REQUIRED"
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        retry = await client.post(f"/api/v1/deployments/{deployment_id}/retry", json={"force": True})

    assert created.status_code == 200, created.text
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "QUEUED"


@pytest.mark.anyio
async def test_upsert_and_get_deployment_profile(db_session):
    session, tenant_id = db_session
    project = Project(name="Deploy profile", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    payload = {
        "environment": "PREVIEW",
        "provider": "vercel",
        "deployment_strategy": "static_frontend",
        "framework": "vite",
        "build_command": "npm run build",
        "output_dir": "dist",
        "healthcheck_path": "/",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        saved = await client.post(f"/api/v1/projects/{project.id}/deployment-profile", json=payload)
        fetched = await client.get(f"/api/v1/projects/{project.id}/deployment-profile?environment=PREVIEW")

    assert saved.status_code == 200, saved.text
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["provider"] == "vercel"
    assert fetched.json()["framework"] == "vite"


@pytest.mark.anyio
async def test_create_project_deployment_uses_profile_managed_mode(db_session):
    session, tenant_id = db_session
    project = Project(name="Managed profile deploy", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    connector_payload = {
        "provider": "vercel",
        "label": "main",
        "vault_ref": "vercel/main",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        connector_resp = await client.post("/api/v1/deployment-connectors", json=connector_payload)
    assert connector_resp.status_code == 200, connector_resp.text
    connector_id = connector_resp.json()["id"]

    profile_payload = {
        "environment": "PREVIEW",
        "provider": "vercel",
        "deployment_strategy": "static_frontend",
        "provider_connector_id": connector_id,
        "env_schema": {
            "integration_mode": "managed_api",
        },
    }
    deploy_payload = {
        "environment": "PREVIEW",
        "target": "user_app",
        "request_key": "deploy:managed-profile",
        "repository_url": "https://github.com/acme/managed-app",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        prof = await client.post(f"/api/v1/projects/{project.id}/deployment-profile", json=profile_payload)
        created = await client.post(f"/api/v1/projects/{project.id}/deployments", json=deploy_payload)

    assert prof.status_code == 200, prof.text
    assert created.status_code == 200, created.text
    meta = created.json().get("extra_metadata") or {}
    assert meta.get("integration_mode") == "managed_api"
    assert meta.get("provider_connector_vault_ref") == "vercel/main"


@pytest.mark.anyio
async def test_upsert_and_list_deployment_connectors(db_session):
    session, tenant_id = db_session
    project = Project(name="Connectors", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    payload = {
        "provider": "render",
        "label": "primary",
        "vault_ref": "render/primary",
        "scopes": {"services": ["svc-123"]},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/v1/deployment-connectors", json=payload)
        listed = await client.get("/api/v1/deployment-connectors?provider=render")

    assert created.status_code == 200, created.text
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["vault_ref"] == "render/primary"


@pytest.mark.anyio
async def test_promote_and_rollback_deployment_and_events(db_session):
    session, tenant_id = db_session
    project = Project(name="Governed deploy", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    ready = ProjectDeployment(
        tenant_id=tenant_id,
        project_id=project.id,
        provider="vercel",
        environment="PREVIEW",
        deployment_strategy="static_frontend",
        target="user_app",
        status="READY",
        request_key="seed-ready",
    )
    session.add(ready)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        promoted = await client.post(
            f"/api/v1/deployments/{ready.id}/promote",
            json={"target_environment": "STAGING", "request_key": "promote-1"},
        )
        rolled = await client.post(
            f"/api/v1/deployments/{ready.id}/rollback",
            json={"reason": "manual check failed", "request_key": "rollback-1"},
        )
        events = await client.get(f"/api/v1/deployments/{rolled.json()['id']}/events")

    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["environment"] == "STAGING"
    assert promoted.json()["promoted_from_environment"] == "PREVIEW"
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["status"] == "ROLLBACK_PENDING"
    assert events.status_code == 200, events.text


@pytest.mark.anyio
async def test_deployment_preflight_validates_profile_connector(db_session):
    session, tenant_id = db_session
    project = Project(name="Preflight", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        preflight_missing = await client.post(
            f"/api/v1/projects/{project.id}/deployments/preflight",
            json={"provider": "vercel", "environment": "PREVIEW", "deployment_strategy": "static_frontend"},
        )
        connector = await client.post(
            "/api/v1/deployment-connectors",
            json={"provider": "vercel", "label": "main", "vault_ref": "vercel/main"},
        )
        connector_id = connector.json()["id"]
        await client.post(
            f"/api/v1/projects/{project.id}/deployment-profile",
            json={
                "environment": "PREVIEW",
                "provider": "vercel",
                "deployment_strategy": "static_frontend",
                "provider_connector_id": connector_id,
                "build_command": "npm run build",
                "healthcheck_path": "/",
            },
        )
        preflight_ok = await client.post(
            f"/api/v1/projects/{project.id}/deployments/preflight",
            json={"provider": "vercel", "environment": "PREVIEW", "deployment_strategy": "static_frontend"},
        )

    assert preflight_missing.status_code == 200, preflight_missing.text
    assert preflight_missing.json()["ok"] is False
    assert preflight_ok.status_code == 200, preflight_ok.text
    assert preflight_ok.json()["ok"] is True


@pytest.mark.anyio
async def test_deployment_intelligence_clusters_and_confidence(db_session):
    session, tenant_id = db_session
    project = Project(name="Deploy intelligence", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add_all([
        ProjectDeployment(
            tenant_id=tenant_id,
            project_id=project.id,
            provider="vercel",
            environment="PREVIEW",
            deployment_strategy="static_frontend",
            target="user_app",
            status="READY",
            deployment_confidence_score=0.92,
        ),
        ProjectDeployment(
            tenant_id=tenant_id,
            project_id=project.id,
            provider="vercel",
            environment="PREVIEW",
            deployment_strategy="static_frontend",
            target="user_app",
            status="FAILED_HEALTH_CHECK",
            error_message="Deployment failed runtime health checks.",
            deployment_confidence_score=0.15,
        ),
        ProjectDeployment(
            tenant_id=tenant_id,
            project_id=project.id,
            provider="render",
            environment="PREVIEW",
            deployment_strategy="api_service",
            target="user_app",
            status="MANUAL_ACTION_REQUIRED",
            error_message="Provider API orchestration failed.",
            deployment_confidence_score=0.2,
        ),
    ])
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/projects/{project.id}/deployments/intelligence")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_deployments"] == 3
    assert body["success_rate"] > 0.3
    assert body["avg_confidence"] > 0.3
    assert body["top_failure_clusters"]
