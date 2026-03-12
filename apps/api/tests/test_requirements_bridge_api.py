import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'requirements_bridge.db'}", future=True)
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
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_tenant_context, None)
        await engine.dispose()


@pytest.mark.anyio
async def test_db_backed_project_can_use_requirements_graph_routes(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/v1/projects", json={"name": "Req Bridge"})
        assert create_resp.status_code == 201
        project_id = create_resp.json()["id"]

        prd_resp = await client.post(
            f"/api/v1/projects/{project_id}/prd",
            json={"text": "Must allow login\nSystem should be reliable"},
        )
        assert prd_resp.status_code == 200
        graph = prd_resp.json()
        assert graph["project_id"] == project_id
        assert len(graph["nodes"]) >= 1

        get_resp = await client.get(f"/api/v1/projects/{project_id}/requirements-graph")
        assert get_resp.status_code == 200
        assert get_resp.json()["project_id"] == project_id
