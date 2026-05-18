import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Project
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'component-capability.db'}", future=True)
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
async def test_component_capability_resolution_api(db_session):
    session, tenant_id = db_session
    project = Project(name="Capability API", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/projects/{project.id}/component-capabilities/HeroSection?variant=premium_saas"
        )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["capability"] == "HeroSection"
    assert payload["variant"] == "premium_saas"
    assert "slots" in payload


@pytest.mark.anyio
async def test_component_capability_resolution_api_rejects_unknown(db_session):
    session, tenant_id = db_session
    project = Project(name="Capability API 2", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/projects/{project.id}/component-capabilities/UnknownWidget?variant=premium_saas"
        )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_component_capability_contract_approval_flow_and_resolution(db_session):
    session, tenant_id = db_session
    project = Project(name="Capability API 3", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    contract = {
        "capability": "HeroSection",
        "variant": "enterprise",
        "allowed_props": ["align", "tone"],
        "slots": ["title", "subtitle"],
        "tokens": ["--brand"],
        "variants": ["enterprise", "premium_saas"],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        upsert = await client.post(
            f"/api/v1/projects/{project.id}/component-capability-contracts",
            json={"environment": "PRODUCTION", "capability": "HeroSection", "contract_json": contract},
        )
        assert upsert.status_code == 200, upsert.text
        assert upsert.json()["status"] == "DRAFT"

        pre_resolve = await client.get(
            f"/api/v1/projects/{project.id}/component-capabilities/HeroSection?environment=PRODUCTION&variant=enterprise"
        )
        assert pre_resolve.status_code == 200
        # fallback static map is used before approval and won't emit our custom token
        assert "--brand" not in pre_resolve.json().get("tokens", [])

        approve = await client.post(
            f"/api/v1/projects/{project.id}/component-capability-contracts/approve",
            json={"environment": "PRODUCTION", "capability": "HeroSection", "approved_by": "architect-user"},
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()["status"] == "APPROVED"
        assert approve.json()["approved_by"] == "architect-user"

        resolved = await client.get(
            f"/api/v1/projects/{project.id}/component-capabilities/HeroSection?environment=PRODUCTION&variant=enterprise"
        )
        assert resolved.status_code == 200, resolved.text
        payload = resolved.json()
        assert payload["variant"] == "enterprise"
        assert "--brand" in payload["tokens"]
