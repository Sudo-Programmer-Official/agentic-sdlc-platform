import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Project, ProjectDeployment
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.services import deployment_runtime
from app.services.deployment_executors import ManagedApiExecutor


@pytest.fixture
async def db_session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'deployment-runtime.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_runtime_moves_bootstrap_deployment_to_manual_action_required(db_session_factory, monkeypatch):
    tenant_id = uuid.uuid4()
    async with db_session_factory() as session:
        project = Project(name="Runtime deploy", tenant_id=tenant_id)
        session.add(project)
        await session.flush()
        deployment = ProjectDeployment(
            tenant_id=tenant_id,
            project_id=project.id,
            provider="vercel",
            target="user_app",
            status="QUEUED",
            deployment_url="https://vercel.com/new",
            extra_metadata={"repository_url": "https://github.com/acme/app", "integration_mode": "bootstrap_link"},
        )
        session.add(deployment)
        await session.commit()
        deployment_id = deployment.id

    monkeypatch.setattr(deployment_runtime, "SessionLocal", db_session_factory)
    settings = deployment_runtime.get_settings()
    monkeypatch.setattr(settings, "deployment_runtime_batch_size", 10, raising=False)

    await deployment_runtime.process_deployments_once()
    await deployment_runtime.process_deployments_once()
    await deployment_runtime.process_deployments_once()

    async with db_session_factory() as session:
        refreshed = await session.get(ProjectDeployment, deployment_id)
        assert refreshed is not None
        assert refreshed.status == "MANUAL_ACTION_REQUIRED"


@pytest.mark.anyio
async def test_runtime_health_check_promotes_ready(db_session_factory, monkeypatch):
    tenant_id = uuid.uuid4()
    async with db_session_factory() as session:
        project = Project(name="Runtime health", tenant_id=tenant_id)
        session.add(project)
        await session.flush()
        deployment = ProjectDeployment(
            tenant_id=tenant_id,
            project_id=project.id,
            provider="vercel",
            target="user_app",
            status="HEALTH_CHECKING",
            deployment_url="https://example.com",
            extra_metadata={"integration_mode": "managed_api", "healthcheck_url": "https://example.com/health"},
        )
        session.add(deployment)
        await session.commit()
        deployment_id = deployment.id

    async def fake_probe(url: str, timeout_seconds: int):
        return True, 200, None, "<html><title>ok</title></html>"

    monkeypatch.setattr(deployment_runtime, "_probe_url", fake_probe)
    monkeypatch.setattr(deployment_runtime, "SessionLocal", db_session_factory)

    await deployment_runtime.process_deployments_once()
    async with db_session_factory() as session:
        refreshed = await session.get(ProjectDeployment, deployment_id)
        assert refreshed is not None
        assert refreshed.status == "READY"
        assert refreshed.extra_metadata.get("last_health_root_status") == 200


@pytest.mark.anyio
async def test_runtime_managed_api_vercel_flow_to_ready(db_session_factory, monkeypatch):
    tenant_id = uuid.uuid4()
    async with db_session_factory() as session:
        project = Project(name="Managed vercel", tenant_id=tenant_id)
        session.add(project)
        await session.flush()
        deployment = ProjectDeployment(
            tenant_id=tenant_id,
            project_id=project.id,
            provider="vercel",
            environment="PREVIEW",
            deployment_strategy="static_frontend",
            target="user_app",
            status="QUEUED",
            extra_metadata={
                "integration_mode": "managed_api",
                "repository_url": "https://github.com/acme/app",
                "branch_name": "main",
                "provider_connector_vault_ref": "vercel/main",
                "healthcheck_url": "https://example.com/health",
            },
        )
        session.add(deployment)
        await session.commit()
        deployment_id = deployment.id

    async def fake_trigger(self, token: str, payload: dict):
        return True, {"url": "https://example.com"}, None

    async def fake_probe(url: str, timeout_seconds: int):
        return True, 200, None, "<html><title>ok</title></html>"

    monkeypatch.setattr(ManagedApiExecutor, "_trigger_vercel_api", fake_trigger)
    monkeypatch.setenv("DEPLOYMENT_SECRET_VERCEL_MAIN", "test-token")
    monkeypatch.setattr(deployment_runtime, "_probe_url", fake_probe)
    monkeypatch.setattr(deployment_runtime, "SessionLocal", db_session_factory)

    for _ in range(6):
        await deployment_runtime.process_deployments_once()

    async with db_session_factory() as session:
        refreshed = await session.get(ProjectDeployment, deployment_id)
        assert refreshed is not None
        assert refreshed.status == "READY"
        assert refreshed.deployment_url == "https://example.com"
        assert refreshed.deployment_confidence_score >= 0.8


@pytest.mark.anyio
async def test_runtime_processes_rollback_states(db_session_factory, monkeypatch):
    tenant_id = uuid.uuid4()
    async with db_session_factory() as session:
        project = Project(name="Rollback runtime", tenant_id=tenant_id)
        session.add(project)
        await session.flush()
        deployment = ProjectDeployment(
            tenant_id=tenant_id,
            project_id=project.id,
            provider="vercel",
            environment="PREVIEW",
            deployment_strategy="static_frontend",
            target="user_app",
            status="ROLLBACK_PENDING",
            extra_metadata={"integration_mode": "managed_api", "repository_url": "https://github.com/acme/app"},
        )
        session.add(deployment)
        await session.commit()
        deployment_id = deployment.id

    monkeypatch.setattr(deployment_runtime, "SessionLocal", db_session_factory)
    await deployment_runtime.process_deployments_once()
    await deployment_runtime.process_deployments_once()

    async with db_session_factory() as session:
        refreshed = await session.get(ProjectDeployment, deployment_id)
        assert refreshed is not None
        assert refreshed.status == "ROLLBACK_SUCCEEDED"
