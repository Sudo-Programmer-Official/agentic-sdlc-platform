import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.api.v1 import generation as generation_module
from app.db.base import Base
from app.db.models import Document, Project, Task, Trace
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app
from app.schemas.generation import GeneratedTask


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'generation.db'}", future=True)
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
async def test_public_generate_tasks_route_creates_tenant_scoped_tasks_and_traces(db_session, monkeypatch):
    session, tenant_id = db_session
    project = Project(name="Generation API", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    document = Document(
        project_id=project.id,
        tenant_id=tenant_id,
        type="prd",
        version=1,
        title="PRD",
        body="Build the feature",
    )
    session.add(document)
    await session.commit()

    async def fake_generate(self, title, body, payload):
        return (
            [GeneratedTask(title="Generated task", description="Do the work", category="func", confidence=0.9)],
            {"ai_model_name": "test-model", "ai_prompt_hash": "abc123"},
        )

    async def fake_health(project_id, session):
        return {"graph_cycles_detected": False}

    async def fake_lifecycle(project_id, session):
        return {"health_index": 100}

    monkeypatch.setattr(generation_module.LLMTaskGenerator, "generate", fake_generate)
    monkeypatch.setattr(generation_module, "project_health", fake_health)
    monkeypatch.setattr(generation_module, "lifecycle_score", fake_lifecycle)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/v1/projects/{project.id}/documents/{document.id}/generate-tasks", json={})

    assert resp.status_code == 201
    data = resp.json()
    assert data["tasks"][0]["title"] == "Generated task"

    tasks = (await session.execute(select(Task).where(Task.project_id == project.id))).scalars().all()
    assert len(tasks) == 1
    assert tasks[0].tenant_id == tenant_id

    traces = (
        await session.execute(
            select(Trace).where(Trace.project_id == project.id, Trace.relation_type.in_(["derives", "supersedes"]))
        )
    ).scalars().all()
    assert traces
    assert all(trace.tenant_id == tenant_id for trace in traces)
