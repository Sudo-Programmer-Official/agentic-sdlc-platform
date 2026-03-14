import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import ActivityLog, Project, RunEvent, Task
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'task-run.db'}", future=True)
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
async def test_create_run_binds_selected_task_and_records_linkage(db_session):
    session, tenant_id = db_session
    project = Project(name="Task run API", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    task = Task(
        project_id=project.id,
        tenant_id=tenant_id,
        title="Implement queue hydration",
        description="Turn a manually created task into a concrete run.",
        source="manual",
    )
    session.add(task)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/projects/{project.id}/runs",
            json={"executor": "dummy", "task_id": str(task.id)},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["summary"]["task_id"] == str(task.id)
    assert data["summary"]["task_title"] == "Implement queue hydration"
    assert data["summary"]["goal"] == "Implement queue hydration: Turn a manually created task into a concrete run."

    await session.refresh(task)
    assert str(task.run_id) == data["id"]

    events = (
        await session.execute(
            select(RunEvent).where(RunEvent.run_id == task.run_id, RunEvent.event_type == "RUN_CREATED")
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].task_id == task.id
    assert events[0].payload["task_id"] == str(task.id)

    task_activity = (
        await session.execute(
            select(ActivityLog.extra_metadata).where(
                ActivityLog.project_id == project.id,
                ActivityLog.entity_type == "task",
                ActivityLog.action_type == "task.run.created",
            )
        )
    ).scalars().all()
    assert len(task_activity) == 1
    assert task_activity[0]["run_id"] == data["id"]
