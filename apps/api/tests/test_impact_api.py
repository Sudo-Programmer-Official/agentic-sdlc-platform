import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.api.v1 import impact as impact_module
from app.db.base import Base
from app.db.models import Document, Project, Task
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'impact.db'}", future=True)
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
async def test_public_impact_preview_handles_uuid_metadata_in_activity_log(db_session, monkeypatch):
    session, tenant_id = db_session
    project = Project(name="Impact API", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    document = Document(
        project_id=project.id,
        tenant_id=tenant_id,
        type="prd",
        version=1,
        title="PRD",
        body="alpha beta",
    )
    session.add(document)
    await session.flush()

    session.add(
        Task(
            project_id=project.id,
            tenant_id=tenant_id,
            document_id=document.id,
            title="Task 1",
            status="PENDING",
            generated_from_document_version=1,
        )
    )
    await session.commit()

    async def fake_lifecycle_score(project_id, session):
        return {"health_index": 100}

    monkeypatch.setattr(impact_module, "lifecycle_score", fake_lifecycle_score)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/projects/{project.id}/documents/{document.id}/impact-preview",
            json={"proposed_body": "completely different text"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["regeneration_required"] is True
    assert len(data["impacted_tasks"]) == 1
