import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Project
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'public-routes.db'}", future=True)
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
async def test_public_project_routes_resolve_to_db_backed_handlers(db_session):
    session, tenant_id = db_session
    project = Project(name="Router order", tenant_id=tenant_id, description="db-backed")
    session.add(project)
    await session.commit()
    await session.refresh(project)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project_resp = await client.get(f"/api/v1/projects/{project.id}")
        runs_resp = await client.get(f"/api/v1/projects/{project.id}/runs")
        summary_resp = await client.get(f"/api/v1/projects/{project.id}/summary")

    assert project_resp.status_code == 200
    assert project_resp.json()["name"] == "Router order"

    assert runs_resp.status_code == 200
    assert runs_resp.json() == []

    assert summary_resp.status_code == 200
    assert summary_resp.json()["name"] == "Router order"
