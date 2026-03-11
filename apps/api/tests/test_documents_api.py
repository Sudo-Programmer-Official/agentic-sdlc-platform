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
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'documents.db'}", future=True)
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
@pytest.mark.parametrize(
    "payload",
    [
        {"type": "PRD", "title": "Body doc", "body": "body text", "created_by": "ui-user"},
        {"type": "PRD", "title": "Content doc", "content": "content text", "created_by": "ui-user"},
    ],
)
async def test_public_document_route_accepts_flat_body_and_legacy_content(db_session, payload):
    session, tenant_id = db_session
    project = Project(name="Docs API", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    project_id = project.id
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/v1/projects/{project_id}/documents", json=payload)

    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == payload["title"]
    assert data["body"] == payload.get("body") or payload.get("content")
