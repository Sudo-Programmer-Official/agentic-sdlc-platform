import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import deps
from app.core.config import get_settings
from app.db.base import Base
from app.db.models.artifact import Artifact
from app.db.models.project import Project
from app.db.models.run import Run
from app.db.models.tenant import Tenant
from app.db.models.tenant_member import TenantMember
from app.db.models.workspace import Workspace
from app.db.models.workspace_member import WorkspaceMember
from app.db.models.workspace_entitlement import WorkspaceEntitlement
from app.db.models.project_deployment import ProjectDeployment
from app.db.models.admin_audit_log import AdminAuditLog
from app.db.models.environment_checklist import EnvironmentChecklist
from app.db.models.platform_config import PlatformConfig
from app.db.models.project_environment_variable import ProjectEnvironmentVariable
from app.db.models.deployment_provider_connector import DeploymentProviderConnector
from app.db.session import get_session
from app.main import app
from app.schemas.preview import RunPreviewOut, RunPreviewServiceRef


@pytest.fixture
async def tenant_auth_client(tmp_path, monkeypatch):
    monkeypatch.setenv("TENANCY_ENFORCEMENT", "true")
    get_settings.cache_clear()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tenant-auth.db'}", future=True)
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

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, session_factory

    app.dependency_overrides.pop(get_session, None)
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_tenant_header_missing_denied(tenant_auth_client):
    client, _ = tenant_auth_client
    response = await client.get("/api/v1/projects", headers={"X-Correlation-Id": "corr-missing-tenant"})
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "TENANT_HEADER_MISSING"
    assert response.json()["detail"]["correlation_id"] == "corr-missing-tenant"


@pytest.mark.anyio
async def test_tenant_header_invalid_denied(tenant_auth_client):
    client, _ = tenant_auth_client
    response = await client.get(
        "/api/v1/projects",
        headers={"X-Tenant-Id": "not-a-uuid", "X-User-Id": "ui-user", "X-Correlation-Id": "corr-invalid-tenant"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "TENANT_HEADER_INVALID"
    assert response.json()["detail"]["correlation_id"] == "corr-invalid-tenant"


@pytest.mark.anyio
async def test_cross_tenant_member_denied(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(Tenant(id=tenant_id, name="Tenant A"))
        await session.commit()

    response = await client.get("/api/v1/projects", headers={"X-Tenant-Id": str(tenant_id), "X-User-Id": "ui-user"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "TENANT_MEMBERSHIP_REQUIRED"


@pytest.mark.anyio
async def test_tenant_member_allowed(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(Tenant(id=tenant_id, name="Tenant A"))
        session.add(TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"))
        await session.commit()

    response = await client.get("/api/v1/projects", headers={"X-Tenant-Id": str(tenant_id), "X-User-Id": "ui-user"})
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_workspace_scoped_project_list_and_get_denied_for_wrong_workspace_header(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_a_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_a_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_a_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        project = Project(name="Scoped project", tenant_id=tenant_id, workspace_id=workspace_a_id, description="workspace A")
        session.add(project)
        await session.commit()

    headers_wrong_workspace = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(uuid.uuid4()),
        "X-User-Id": "ui-user",
    }
    list_resp = await client.get("/api/v1/projects", headers=headers_wrong_workspace)
    assert list_resp.status_code == 403
    assert list_resp.json()["detail"]["code"] == "WORKSPACE_NOT_FOUND"


@pytest.mark.anyio
async def test_project_defaults_to_active_workspace_assignment(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.post("/api/v1/projects", headers=headers, json={"name": "Workspace scoped project"})
    assert response.status_code == 201
    project_id = uuid.UUID(response.json()["id"])

    async with session_factory() as session:
        project = await session.get(Project, project_id)
        assert project is not None
        assert project.workspace_id == workspace_id


@pytest.mark.anyio
async def test_wrong_workspace_header_denies_project_runs_and_deployments(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        project = Project(name="Scoped project", tenant_id=tenant_id, workspace_id=workspace_id)
        session.add(project)
        await session.commit()
        project_id = project.id

    headers_wrong_workspace = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(uuid.uuid4()),
        "X-User-Id": "ui-user",
    }
    runs_resp = await client.get(f"/api/v1/projects/{project_id}/runs", headers=headers_wrong_workspace)
    deployments_resp = await client.get(f"/api/v1/projects/{project_id}/deployments", headers=headers_wrong_workspace)

    assert runs_resp.status_code == 403
    assert runs_resp.json()["detail"]["code"] == "WORKSPACE_NOT_FOUND"
    assert deployments_resp.status_code == 403
    assert deployments_resp.json()["detail"]["code"] == "WORKSPACE_NOT_FOUND"


@pytest.mark.anyio
async def test_mission_control_overview_stable_after_workspace_switch(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        project = Project(name="Mission Control stable", tenant_id=tenant_id, workspace_id=workspace_id)
        session.add(project)
        await session.commit()
        project_id = project.id

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    switch_resp = await client.get(f"/api/v1/workspaces/{workspace_id}/switch", headers=headers)
    assert switch_resp.status_code == 200

    overview_resp = await client.get(f"/api/v1/projects/{project_id}/mission-control/overview", headers=headers)
    assert overview_resp.status_code == 200
    payload = overview_resp.json()
    assert "work_intake" in payload
    assert "imported_references" in payload


@pytest.mark.anyio
async def test_workspace_entitlements_default_seeded_and_readable(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.get(f"/api/v1/workspaces/{workspace_id}/entitlements", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_id"] == str(workspace_id)
    assert payload["plan"] == "starter"
    assert payload["limits"]["projects"] == 5
    assert payload["features"]["preview_deployments"] is True


@pytest.mark.anyio
async def test_project_environment_checklists_seeded_and_readable(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        project = Project(name="Readiness project", tenant_id=tenant_id, workspace_id=workspace_id)
        session.add(project)
        await session.commit()
        project_id = project.id

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.get(f"/api/v1/projects/{project_id}/environment-checklists", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == str(project_id)
    assert payload["score_pct"] >= 0
    assert len(payload["environments"]) == 3
    assert any(item["owner"] == "platform" for item in payload["items"])
    assert any(item["owner"] == "user" for item in payload["items"])

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(EnvironmentChecklist).where(EnvironmentChecklist.project_id == project_id)
            )
        ).scalars().all()
        assert len(rows) >= 10


@pytest.mark.anyio
async def test_workspace_environment_checklists_denied_without_membership(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
            ]
        )
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.get(f"/api/v1/workspaces/{workspace_id}/environment-checklists", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "WORKSPACE_MEMBERSHIP_REQUIRED"


@pytest.mark.anyio
async def test_workspace_usage_summary_available_for_member(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.get(f"/api/v1/workspaces/{workspace_id}/usage?days=7", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_id"] == str(workspace_id)
    assert payload["days"] == 7
    assert isinstance(payload["daily"], list)
    assert len(payload["daily"]) == 7


@pytest.mark.anyio
async def test_admin_workspaces_requires_super_admin_allowlist(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.get("/api/v1/admin/workspaces", headers=headers)
    assert response.status_code == 403


@pytest.mark.anyio
async def test_workspace_usage_materialize_persists_daily_rows(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.post(f"/api/v1/workspaces/{workspace_id}/usage/materialize?days=7", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_id"] == str(workspace_id)
    assert payload["days"] == 7
    assert payload["rows_upserted"] == 7


@pytest.mark.anyio
async def test_admin_workspace_detail_allowed_for_super_admin(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("SUPER_ADMIN_USERS", "ui-user")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.get(f"/api/v1/admin/workspaces/{workspace_id}", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace"]["id"] == str(workspace_id)


@pytest.mark.anyio
async def test_workspace_project_limit_warn_mode_does_not_block_create(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("WORKSPACE_ENTITLEMENTS_ENABLED", "true")
    monkeypatch.setenv("WORKSPACE_ENTITLEMENTS_ENFORCE", "false")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
                WorkspaceEntitlement(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    plan="starter",
                    limits={"projects": 1, "monthly_tokens": 500000, "deployments_per_month": 20},
                    features={"preview_deployments": True},
                ),
            ]
        )
        session.add(Project(name="Existing", tenant_id=tenant_id, workspace_id=workspace_id))
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.post("/api/v1/projects", headers=headers, json={"name": "Still allowed in warn mode"})
    assert response.status_code == 201


@pytest.mark.anyio
async def test_workspace_project_limit_enforce_mode_blocks_create(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("WORKSPACE_ENTITLEMENTS_ENABLED", "true")
    monkeypatch.setenv("WORKSPACE_ENTITLEMENTS_ENFORCE", "true")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
                WorkspaceEntitlement(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    plan="starter",
                    limits={"projects": 1, "monthly_tokens": 500000, "deployments_per_month": 20},
                    features={"preview_deployments": True},
                ),
            ]
        )
        session.add(Project(name="Existing", tenant_id=tenant_id, workspace_id=workspace_id))
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.post("/api/v1/projects", headers=headers, json={"name": "Should block in enforce mode"})
    assert response.status_code == 403
    assert "limit" in str(response.json().get("detail", "")).lower()


@pytest.mark.anyio
async def test_workspace_deployment_limit_warn_mode_does_not_block_create(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("WORKSPACE_ENTITLEMENTS_ENABLED", "true")
    monkeypatch.setenv("WORKSPACE_ENTITLEMENTS_ENFORCE", "false")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
                WorkspaceEntitlement(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    plan="starter",
                    limits={"projects": 50, "monthly_tokens": 500000, "deployments_per_month": 1},
                    features={"preview_deployments": True},
                ),
            ]
        )
        project = Project(name="Deploy project", tenant_id=tenant_id, workspace_id=workspace_id)
        session.add(project)
        await session.flush()
        session.add(
            ProjectDeployment(
                tenant_id=tenant_id,
                project_id=project.id,
                provider="vercel",
                environment="PREVIEW",
                deployment_strategy="static_frontend",
                target="user_app",
                status="COMPLETED",
            )
        )
        await session.commit()
        project_id = project.id

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.post(
        f"/api/v1/projects/{project_id}/deployments",
        headers=headers,
        json={"provider": "vercel", "environment": "PREVIEW", "deployment_strategy": "static_frontend"},
    )
    assert response.status_code == 200


@pytest.mark.anyio
async def test_workspace_deployment_limit_enforce_mode_blocks_create(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("WORKSPACE_ENTITLEMENTS_ENABLED", "true")
    monkeypatch.setenv("WORKSPACE_ENTITLEMENTS_ENFORCE", "true")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
                WorkspaceEntitlement(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    plan="starter",
                    limits={"projects": 50, "monthly_tokens": 500000, "deployments_per_month": 1},
                    features={"preview_deployments": True},
                ),
            ]
        )
        project = Project(name="Deploy project", tenant_id=tenant_id, workspace_id=workspace_id)
        session.add(project)
        await session.flush()
        session.add(
            ProjectDeployment(
                tenant_id=tenant_id,
                project_id=project.id,
                provider="vercel",
                environment="PREVIEW",
                deployment_strategy="static_frontend",
                target="user_app",
                status="COMPLETED",
            )
        )
        await session.commit()
        project_id = project.id

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.post(
        f"/api/v1/projects/{project_id}/deployments",
        headers=headers,
        json={"provider": "vercel", "environment": "PREVIEW", "deployment_strategy": "static_frontend"},
    )
    assert response.status_code == 403
    assert "limit" in str(response.json().get("detail", "")).lower()


@pytest.mark.anyio
async def test_workspace_token_limit_warn_mode_does_not_block_run_create(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("WORKSPACE_ENTITLEMENTS_ENABLED", "true")
    monkeypatch.setenv("WORKSPACE_ENTITLEMENTS_ENFORCE", "false")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
                WorkspaceEntitlement(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    plan="starter",
                    limits={"projects": 50, "monthly_tokens": 1, "deployments_per_month": 20},
                    features={"preview_deployments": True},
                ),
            ]
        )
        project = Project(name="Token project", tenant_id=tenant_id, workspace_id=workspace_id)
        session.add(project)
        await session.flush()
        session.add(
            Run(
                tenant_id=tenant_id,
                project_id=project.id,
                status="COMPLETED",
                executor="codex",
                summary={"usage": {"input_tokens": 1, "output_tokens": 1}},
            )
        )
        await session.commit()
        project_id = project.id

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.post(f"/api/v1/projects/{project_id}/runs", headers=headers, json={"executor": "codex"})
    assert response.status_code in {201, 409, 400}


@pytest.mark.anyio
async def test_workspace_token_limit_enforce_mode_blocks_run_create(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("WORKSPACE_ENTITLEMENTS_ENABLED", "true")
    monkeypatch.setenv("WORKSPACE_ENTITLEMENTS_ENFORCE", "true")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
                WorkspaceEntitlement(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    plan="starter",
                    limits={"projects": 50, "monthly_tokens": 1, "deployments_per_month": 20},
                    features={"preview_deployments": True},
                ),
            ]
        )
        project = Project(name="Token project", tenant_id=tenant_id, workspace_id=workspace_id)
        session.add(project)
        await session.flush()
        session.add(
            Run(
                tenant_id=tenant_id,
                project_id=project.id,
                status="COMPLETED",
                executor="codex",
                summary={"usage": {"input_tokens": 1, "output_tokens": 1}},
            )
        )
        await session.commit()
        project_id = project.id

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.post(f"/api/v1/projects/{project_id}/runs", headers=headers, json={"executor": "codex"})
    assert response.status_code == 403
    assert "token" in str(response.json().get("detail", "")).lower()


@pytest.mark.anyio
async def test_admin_impersonation_start_end_and_audit_logs(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("SUPER_ADMIN_USERS", "ui-user")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    started = await client.post(
        "/api/v1/admin/impersonation/start",
        headers=headers,
        json={"workspace_id": str(workspace_id), "reason": "debug ticket", "duration_minutes": 30},
    )
    assert started.status_code == 201
    started_payload = started.json()
    assert started_payload["target_workspace_id"] == str(workspace_id)
    assert started_payload["is_active"] is True

    ended = await client.post(f"/api/v1/admin/impersonation/{started_payload['id']}/end", headers=headers)
    assert ended.status_code == 200
    ended_payload = ended.json()
    assert ended_payload["is_active"] is False
    assert ended_payload["ended_by"] == "ui-user"

    audit = await client.get("/api/v1/admin/audit-logs?limit=20", headers=headers)
    assert audit.status_code == 200
    actions = [row["action"] for row in audit.json()]
    assert "impersonation.start" in actions
    assert "impersonation.end" in actions


@pytest.mark.anyio
async def test_admin_endpoints_require_super_admin_for_detail_impersonation_and_audit(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    detail = await client.get(f"/api/v1/admin/workspaces/{workspace_id}", headers=headers)
    assert detail.status_code == 403

    start = await client.post(
        "/api/v1/admin/impersonation/start",
        headers=headers,
        json={"workspace_id": str(workspace_id), "reason": "unauthorized check", "duration_minutes": 30},
    )
    assert start.status_code == 403

    random_session_id = uuid.uuid4()
    end = await client.post(f"/api/v1/admin/impersonation/{random_session_id}/end", headers=headers)
    assert end.status_code == 403

    audit = await client.get("/api/v1/admin/audit-logs?limit=20", headers=headers)
    assert audit.status_code == 403
    usage = await client.get(f"/api/v1/admin/workspaces/{workspace_id}/usage?days=7", headers=headers)
    assert usage.status_code == 403
    usage_materialize = await client.post(f"/api/v1/admin/workspaces/{workspace_id}/usage/materialize?days=7", headers=headers)
    assert usage_materialize.status_code == 403
    anomaly_materialize = await client.post("/api/v1/admin/anomalies/materialize?days=30", headers=headers)
    assert anomaly_materialize.status_code == 403
    anomaly_list = await client.get("/api/v1/admin/anomalies?days=30&limit=20", headers=headers)
    assert anomaly_list.status_code == 403
    daemon_health = await client.get("/api/v1/admin/daemon-health", headers=headers)
    assert daemon_health.status_code == 403


@pytest.mark.anyio
async def test_admin_workspace_entitlement_read_and_patch(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("SUPER_ADMIN_USERS", "ui-user")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    before = await client.get(f"/api/v1/admin/workspaces/{workspace_id}/entitlements", headers=headers)
    assert before.status_code == 200
    before_payload = before.json()
    assert before_payload["workspace_id"] == str(workspace_id)

    patched = await client.patch(
        f"/api/v1/admin/workspaces/{workspace_id}/entitlements",
        headers=headers,
        json={
            "plan": "pro",
            "limits": {"projects": 20, "monthly_tokens": 900000, "deployments_per_month": 60},
            "features": {"production_deployments": True, "workspace_connectors": True},
        },
    )
    assert patched.status_code == 200
    payload = patched.json()
    assert payload["plan"] == "pro"
    assert payload["limits"]["projects"] == 20
    assert payload["features"]["production_deployments"] is True

    audit = await client.get("/api/v1/admin/audit-logs?limit=20", headers=headers)
    assert audit.status_code == 200
    actions = [row["action"] for row in audit.json()]
    assert "entitlement.update" in actions


@pytest.mark.anyio
async def test_admin_workspace_usage_available_for_super_admin(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("SUPER_ADMIN_USERS", "ui-user")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.get(f"/api/v1/admin/workspaces/{workspace_id}/usage?days=14", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_id"] == str(workspace_id)
    assert payload["days"] == 14
    assert isinstance(payload["daily"], list)


@pytest.mark.anyio
async def test_admin_workspace_usage_materialize_available_for_super_admin(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("SUPER_ADMIN_USERS", "ui-user")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.post(f"/api/v1/admin/workspaces/{workspace_id}/usage/materialize?days=7", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_id"] == str(workspace_id)
    assert payload["days"] == 7
    assert payload["rows_upserted"] == 7


@pytest.mark.anyio
async def test_admin_workspace_anomaly_snapshot_materialize_and_list(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("SUPER_ADMIN_USERS", "ui-user")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    materialize = await client.post("/api/v1/admin/anomalies/materialize?days=30", headers=headers)
    assert materialize.status_code == 200
    materialized_rows = materialize.json()
    assert isinstance(materialized_rows, list)
    assert materialized_rows
    assert materialized_rows[0]["window_days"] == 30

    listed = await client.get("/api/v1/admin/anomalies?days=30&limit=20", headers=headers)
    assert listed.status_code == 200
    listed_rows = listed.json()
    assert isinstance(listed_rows, list)
    assert listed_rows


@pytest.mark.anyio
async def test_admin_daemon_health_returns_latest_cycle_and_error(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("SUPER_ADMIN_USERS", "ui-user")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
                AdminAuditLog(
                    admin_user_id="system-daemon",
                    action="workspace_ops.workspace_error",
                    target_workspace_id=workspace_id,
                    extra_metadata={"window_days": 30},
                ),
                AdminAuditLog(
                    admin_user_id="system-daemon",
                    action="workspace_ops.cycle",
                    extra_metadata={"window_days": 30, "workspaces_processed": 3, "workspace_failures": 1},
                ),
            ]
        )
        await session.commit()

    headers = {
        "X-Tenant-Id": str(tenant_id),
        "X-Workspace-Id": str(workspace_id),
        "X-User-Id": "ui-user",
    }
    response = await client.get("/api/v1/admin/daemon-health", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["last_cycle_window_days"] == 30
    assert payload["last_cycle_workspaces_processed"] == 3
    assert payload["last_cycle_workspace_failures"] == 1
    assert payload["last_error_workspace_id"] == str(workspace_id)
    assert payload["alert_level"] == "warn"
    assert "latest_cycle_has_workspace_failures" in payload["alert_reasons"]

@pytest.mark.anyio
async def test_cross_tenant_run_actions_denied(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    run_id: uuid.UUID
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_a, name="Tenant A"),
                Tenant(id=tenant_b, name="Tenant B"),
                TenantMember(tenant_id=tenant_b, user_id="ui-user", role="ADMIN"),
            ]
        )
        project = Project(name="Cross tenant", tenant_id=tenant_a, description="owner is tenant A")
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, tenant_id=tenant_a, status="RUNNING", executor="codex")
        session.add(run)
        await session.commit()
        run_id = run.id

    headers = {"X-Tenant-Id": str(tenant_b), "X-User-Id": "ui-user"}
    resp_fetch = await client.get(f"/api/v1/runs/{run_id}", headers=headers)
    resp_resume = await client.post(f"/api/v1/runs/{run_id}/resume", headers=headers, json={"start_now": False})
    resp_unblock = await client.post(f"/api/v1/runs/{run_id}/unblock", headers=headers, json={})
    resp_pr = await client.post(f"/api/v1/runs/{run_id}/create-pr", headers=headers, json={})

    assert resp_fetch.status_code == 404
    assert resp_resume.status_code == 404
    assert resp_unblock.status_code == 404
    assert resp_pr.status_code == 404


@pytest.mark.anyio
async def test_same_tenant_resume_conflict_is_consistent(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        project = Project(name="Resume consistency", tenant_id=tenant_id, description="same tenant")
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.commit()
        run_id = run.id

    headers = {"X-Tenant-Id": str(tenant_id), "X-User-Id": "ui-user"}
    first = await client.post(f"/api/v1/runs/{run_id}/resume", headers=headers, json={"start_now": False})
    second = await client.post(f"/api/v1/runs/{run_id}/resume", headers=headers, json={"start_now": False})

    assert first.status_code == 409
    assert second.status_code == 409
    assert first.json().get("detail") == second.json().get("detail")


@pytest.mark.anyio
async def test_same_tenant_unblock_repeat_call_is_stable(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        project = Project(name="Unblock stability", tenant_id=tenant_id, description="same tenant")
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.commit()
        run_id = run.id

    headers = {"X-Tenant-Id": str(tenant_id), "X-User-Id": "ui-user"}
    first = await client.post(f"/api/v1/runs/{run_id}/unblock", headers=headers, json={})
    second = await client.post(f"/api/v1/runs/{run_id}/unblock", headers=headers, json={})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json().get("run_id") == str(run_id)
    assert second.json().get("run_id") == str(run_id)


@pytest.mark.anyio
async def test_same_tenant_create_pr_repeat_returns_existing_pr(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        project = Project(name="PR idempotency", tenant_id=tenant_id, description="same tenant")
        session.add(project)
        await session.flush()
        run = Run(
            project_id=project.id,
            tenant_id=tenant_id,
            status="COMPLETED",
            executor="codex",
            branch_name="run/demo-pr",
            summary={
                "pull_request_url": "https://github.com/acme/repo/pull/42",
                "pull_request_number": 42,
                "pull_request_branch": "run/demo-pr",
                "pull_request_commit_sha": "abc123",
            },
        )
        session.add(run)
        await session.flush()
        pr_artifact = Artifact(
            tenant_id=tenant_id,
            project_id=project.id,
            run_id=run.id,
            type="pull_request",
            uri="https://github.com/acme/repo/pull/42",
            version=1,
            extra_metadata={
                "number": 42,
                "head": "run/demo-pr",
                "base": "main",
                "commit_sha": "abc123",
            },
        )
        session.add(pr_artifact)
        await session.commit()
        run_id = run.id

    headers = {"X-Tenant-Id": str(tenant_id), "X-User-Id": "ui-user"}
    first = await client.post(f"/api/v1/runs/{run_id}/create-pr", headers=headers, json={})
    second = await client.post(f"/api/v1/runs/{run_id}/create-pr", headers=headers, json={"branch_name": "run/demo-pr"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json().get("pull_request_url") == "https://github.com/acme/repo/pull/42"
    assert second.json().get("pull_request_url") == "https://github.com/acme/repo/pull/42"
    assert first.json().get("branch_name") == "run/demo-pr"
    assert second.json().get("branch_name") == "run/demo-pr"


@pytest.mark.anyio
async def test_same_tenant_start_run_request_key_is_idempotent(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        project = Project(name="Start idempotency", tenant_id=tenant_id, workspace_id=workspace_id)
        session.add(project)
        await session.commit()
        project_id = project.id

    headers = {"X-Tenant-Id": str(tenant_id), "X-Workspace-Id": str(workspace_id), "X-User-Id": "ui-user"}
    payload = {"executor": "codex", "request_key": "run-start-001"}
    first = await client.post(f"/api/v1/projects/{project_id}/runs", headers=headers, json=payload)
    second = await client.post(f"/api/v1/projects/{project_id}/runs", headers=headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    async with session_factory() as session:
        run_rows = (
            await session.execute(
                select(Run).where(Run.tenant_id == tenant_id, Run.project_id == project_id)
            )
        ).scalars().all()
        assert len(run_rows) == 1
        summary = run_rows[0].summary if isinstance(run_rows[0].summary, dict) else {}
        assert summary.get("request_key") == "run-start-001"


@pytest.mark.anyio
async def test_same_tenant_fork_run_request_key_is_idempotent(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        project = Project(name="Fork idempotency", tenant_id=tenant_id, workspace_id=workspace_id)
        session.add(project)
        await session.flush()
        source_run = Run(project_id=project.id, tenant_id=tenant_id, status="COMPLETED", executor="codex")
        session.add(source_run)
        await session.commit()
        source_run_id = source_run.id
        project_id = project.id

    headers = {"X-Tenant-Id": str(tenant_id), "X-Workspace-Id": str(workspace_id), "X-User-Id": "ui-user"}
    payload = {"start_now": False, "request_key": "run-fork-001"}
    first = await client.post(f"/api/v1/runs/{source_run_id}/fork", headers=headers, json=payload)
    second = await client.post(f"/api/v1/runs/{source_run_id}/fork", headers=headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    async with session_factory() as session:
        run_rows = (
            await session.execute(
                select(Run).where(Run.tenant_id == tenant_id, Run.project_id == project_id).order_by(Run.created_at.asc())
            )
        ).scalars().all()
        assert len(run_rows) == 2  # source + exactly one forked run
        forked = run_rows[-1]
        summary = forked.summary if isinstance(forked.summary, dict) else {}
        assert summary.get("request_key") == "run-fork-001"
        assert summary.get("fork_source_run_id") == str(source_run_id)


@pytest.mark.anyio
async def test_tenant_workspace_happy_path_smoke_task_run_preview_pr(tenant_auth_client, monkeypatch):
    from app.api.v1 import persistence

    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        project = Project(name="Smoke project", tenant_id=tenant_id, workspace_id=workspace_id)
        session.add(project)
        await session.commit()
        project_id = project.id

    async def fake_launch_preview(*_args, **kwargs):
        return RunPreviewOut(
            run_id=run_id,
            project_id=project_id,
            status="READY",
            mode="local",
            branch_name="run/smoke",
            reusable=False,
            launched_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ttl_hours=24,
            preview_url="http://127.0.0.1:3100",
            frontend=RunPreviewServiceRef(
                kind="frontend",
                status="READY",
                url="http://127.0.0.1:3100",
                port=3100,
                root="apps/web",
                start_command="npm run dev",
                healthcheck_path="/",
                log_path="/tmp/preview-frontend.log",
            ),
            backend=None,
            profile_configured=True,
            repository_connected=True,
        )

    async def fake_create_pr_from_artifact(*_args, **_kwargs):
        return {
            "run_id": run_id,
            "artifact_id": str(uuid.uuid4()),
            "pull_request_url": "https://github.com/acme/repo/pull/100",
            "pull_request_number": 100,
            "branch_name": "run/smoke",
            "base_branch": "main",
            "commit_sha": "abc123",
        }

    monkeypatch.setattr(persistence, "launch_run_preview", fake_launch_preview)
    monkeypatch.setattr(persistence, "create_pr_from_artifact", fake_create_pr_from_artifact)

    headers = {"X-Tenant-Id": str(tenant_id), "X-Workspace-Id": str(workspace_id), "X-User-Id": "ui-user"}
    task_resp = await client.post(
        f"/api/v1/projects/{project_id}/tasks",
        headers=headers,
        json={"title": "Smoke task"},
    )
    assert task_resp.status_code == 201, task_resp.text
    task_id = task_resp.json()["id"]

    run_resp = await client.post(
        f"/api/v1/projects/{project_id}/runs",
        headers=headers,
        json={"executor": "codex", "task_id": task_id, "request_key": "smoke-run-001"},
    )
    assert run_resp.status_code == 201, run_resp.text
    run_id = uuid.UUID(run_resp.json()["id"])

    async with session_factory() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        run.status = "COMPLETED"
        run.summary = {**(run.summary or {}), "goal": "Smoke run", "branch_name": "run/smoke"}
        session.add(run)
        await session.commit()

    preview_resp = await client.post(f"/api/v1/runs/{run_id}/preview", headers=headers, json={"reuse_if_healthy": True})
    assert preview_resp.status_code == 200, preview_resp.text
    assert preview_resp.json()["status"] == "READY"
    assert preview_resp.json()["preview_url"] == "http://127.0.0.1:3100"

    pr_resp = await client.post(f"/api/v1/runs/{run_id}/create-pr", headers=headers, json={})
    assert pr_resp.status_code == 200, pr_resp.text
    assert pr_resp.json()["pull_request_url"] == "https://github.com/acme/repo/pull/100"


@pytest.mark.anyio
async def test_firebase_auth_enforcement_requires_bearer_token(tenant_auth_client, monkeypatch):
    client, _ = tenant_auth_client
    monkeypatch.setenv("FIREBASE_AUTH_ENFORCEMENT", "true")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "prompt2pr-test")
    get_settings.cache_clear()
    response = await client.get("/api/v1/projects", headers={"X-Tenant-Id": str(uuid.uuid4())})
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_TOKEN_MISSING"


@pytest.mark.anyio
async def test_firebase_auth_enforcement_accepts_verified_claims(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("FIREBASE_AUTH_ENFORCEMENT", "true")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "prompt2pr-test")
    get_settings.cache_clear()

    tenant_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(Tenant(id=tenant_id, name="Tenant A"))
        session.add(TenantMember(tenant_id=tenant_id, user_id="firebase-user-1", role="ADMIN"))
        await session.commit()

    monkeypatch.setattr(
        deps,
        "verify_firebase_bearer_token",
        lambda token, project_id: {"sub": "firebase-user-1", "tenant_id": str(tenant_id)},
    )
    response = await client.get(
        "/api/v1/projects",
        headers={"X-Tenant-Id": str(tenant_id), "Authorization": "Bearer fake-token"},
    )
    assert response.status_code == 200


@pytest.mark.anyio
async def test_admin_system_config_requires_super_admin(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        session.add(
            PlatformConfig(
                config_key="openai.provider",
                config_scope="global",
                value_type="secret_ref",
                vault_ref="platform/openai/prod",
                description="OpenAI provider key reference",
            )
        )
        await session.commit()
    headers = {"X-Tenant-Id": str(tenant_id), "X-Workspace-Id": str(workspace_id), "X-User-Id": "ui-user"}
    response = await client.get("/api/v1/admin/system-config", headers=headers)
    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_system_config_masks_values_for_super_admin(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("SUPER_ADMIN_USERS", "super-admin")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="super-admin", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="super-admin", role="ADMIN"),
            ]
        )
        session.add(
            PlatformConfig(
                config_key="openai.provider",
                config_scope="global",
                value_type="secret_ref",
                plain_value="super-secret-value",
                vault_ref="platform/openai/prod",
                description="OpenAI provider key reference",
                updated_by="ops-user",
            )
        )
        await session.commit()
    headers = {"X-Tenant-Id": str(tenant_id), "X-Workspace-Id": str(workspace_id), "X-User-Id": "super-admin"}
    response = await client.get("/api/v1/admin/system-config", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["config_key"] == "openai.provider"
    assert payload[0]["vault_ref"] == "platform/openai/prod"
    assert payload[0]["has_plain_value"] is True
    assert "plain_value" not in payload[0]
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_project_environment_variables_are_masked_and_scoped(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        project = Project(name="Env Center", tenant_id=tenant_id, workspace_id=workspace_id)
        session.add(project)
        await session.flush()
        session.add(
            ProjectEnvironmentVariable(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                project_id=project.id,
                environment="PRODUCTION",
                var_key="DATABASE_URL",
                value_kind="secret",
                vault_ref="workspace/a/prod/database_url",
                required=True,
                source="detected",
                updated_by="ui-user",
            )
        )
        await session.commit()
        project_id = project.id
    headers = {"X-Tenant-Id": str(tenant_id), "X-Workspace-Id": str(workspace_id), "X-User-Id": "ui-user"}
    response = await client.get(f"/api/v1/projects/{project_id}/environments/production/variables", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["var_key"] == "DATABASE_URL"
    assert payload[0]["has_value"] is True
    assert "vault_ref" not in payload[0]
    assert "plain_value" not in payload[0]


@pytest.mark.anyio
async def test_admin_system_config_upsert_and_rotate(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    monkeypatch.setenv("SUPER_ADMIN_USERS", "super-admin")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="super-admin", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="super-admin", role="ADMIN"),
            ]
        )
        await session.commit()
    headers = {"X-Tenant-Id": str(tenant_id), "X-Workspace-Id": str(workspace_id), "X-User-Id": "super-admin"}
    upsert = await client.put(
        "/api/v1/admin/system-config/openai.provider",
        headers=headers,
        json={"value_type": "secret_ref", "vault_ref": "platform/openai/v1", "description": "primary"},
    )
    assert upsert.status_code == 200
    assert upsert.json()["vault_ref"] == "platform/openai/v1"
    assert upsert.json()["has_plain_value"] is False
    rotate = await client.post(
        "/api/v1/admin/system-config/openai.provider/rotate",
        headers=headers,
        json={"vault_ref": "platform/openai/v2", "reason": "rotation"},
    )
    assert rotate.status_code == 200
    assert rotate.json()["vault_ref"] == "platform/openai/v2"
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_project_environment_variable_upsert_validate_and_sync(tenant_auth_client, monkeypatch):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        project = Project(name="Env Mutation", tenant_id=tenant_id, workspace_id=workspace_id)
        session.add(project)
        session.add(
            DeploymentProviderConnector(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                provider="vercel",
                label="main",
                vault_ref="vercel/main",
                scopes={"type": "preview"},
                created_by="ui-user",
            )
        )
        await session.commit()
        project_id = project.id
    monkeypatch.setenv("DEPLOYMENT_SECRET_VERCEL_MAIN", "token-123")
    headers = {"X-Tenant-Id": str(tenant_id), "X-Workspace-Id": str(workspace_id), "X-User-Id": "ui-user"}
    upsert = await client.put(
        f"/api/v1/projects/{project_id}/environments/production/variables/DATABASE_URL",
        headers=headers,
        json={"value_kind": "secret", "vault_ref": "workspace/a/prod/database_url", "required": True},
    )
    assert upsert.status_code == 200
    assert upsert.json()["var_key"] == "DATABASE_URL"
    assert upsert.json()["has_value"] is True
    assert "vault_ref" not in upsert.json()

    validate = await client.post(
        f"/api/v1/projects/{project_id}/environments/production/validate",
        headers=headers,
        json={"checks": ["DATABASE_URL"]},
    )
    assert validate.status_code == 200
    assert validate.json()[0]["status"] == "pass"

    sync = await client.post(
        f"/api/v1/projects/{project_id}/environments/production/sync/vercel",
        headers=headers,
        json={"reason": "deploy prep"},
    )
    assert sync.status_code == 200
    assert sync.json()["status"] == "synced"
    assert sync.json()["provider"] == "vercel"


@pytest.mark.anyio
async def test_project_environment_secret_write_uses_vault_and_masks_storage(tenant_auth_client):
    client, session_factory = tenant_auth_client
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Tenant A"),
                TenantMember(tenant_id=tenant_id, user_id="ui-user", role="ADMIN"),
                Workspace(id=workspace_id, tenant_id=tenant_id, name="Workspace A"),
                WorkspaceMember(workspace_id=workspace_id, user_id="ui-user", role="ADMIN"),
            ]
        )
        project = Project(name="Secret Write", tenant_id=tenant_id, workspace_id=workspace_id)
        session.add(project)
        await session.commit()
        project_id = project.id
    headers = {"X-Tenant-Id": str(tenant_id), "X-Workspace-Id": str(workspace_id), "X-User-Id": "ui-user"}
    upsert = await client.put(
        f"/api/v1/projects/{project_id}/environments/staging/variables/STRIPE_SECRET_KEY",
        headers=headers,
        json={"value_kind": "secret", "required": True, "source": "manual"},
    )
    assert upsert.status_code == 400  # missing vault_ref/plain_value

    upsert = await client.put(
        f"/api/v1/projects/{project_id}/environments/staging/variables/STRIPE_SECRET_KEY",
        headers=headers,
        json={"value_kind": "secret", "required": True, "source": "manual", "plain_value": "sk_live_abc"},
    )
    assert upsert.status_code == 200
    write_secret = await client.post(
        f"/api/v1/projects/{project_id}/environments/staging/variables/STRIPE_SECRET_KEY/secret",
        headers=headers,
        json={"value": "sk_live_def"},
    )
    assert write_secret.status_code == 200
    assert write_secret.json()["has_value"] is True
    async with session_factory() as session:
        row = await session.scalar(
            select(ProjectEnvironmentVariable).where(
                ProjectEnvironmentVariable.project_id == project_id,
                ProjectEnvironmentVariable.environment == "STAGING",
                ProjectEnvironmentVariable.var_key == "STRIPE_SECRET_KEY",
            )
        )
        assert row is not None
        assert row.vault_ref
        assert row.plain_value is None
