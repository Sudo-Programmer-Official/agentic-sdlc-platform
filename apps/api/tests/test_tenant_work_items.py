import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.db.session import engine, SessionLocal
from app.db.base import Base
from app.db.models import Project, Run, WorkItem

ZERO = uuid.UUID(int=0)


@pytest.fixture
async def db_session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session: AsyncSession = SessionLocal()
    try:
        yield session
    finally:
        await session.close()


async def seed(session: AsyncSession):
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    project = Project(id=uuid.uuid4(), tenant_id=tenant_a, name="A", status="INTAKE")
    session.add(project)
    await session.flush()
    run = Run(id=uuid.uuid4(), project_id=project.id, tenant_id=tenant_a, status="QUEUED")
    session.add(run)
    await session.flush()
    wi = WorkItem(
        id=uuid.uuid4(),
        tenant_id=tenant_a,
        project_id=project.id,
        run_id=run.id,
        type="CODE",
        status="QUEUED",
        priority=1,
    )
    session.add(wi)
    await session.commit()
    return tenant_a, tenant_b, project, run, wi


@pytest.mark.anyio
async def test_cross_tenant_cannot_view_work_items(db_session):
    tenant_a, tenant_b, project, run, wi = await seed(db_session)
    async with AsyncClient(app=app, base_url="http://test") as client:
        # tenant A can list
        resp = await client.get(
            f"/api/v1/store/projects/{project.id}/runs/{run.id}/work-items",
            headers={"X-Tenant-Id": str(tenant_a)},
        )
        assert resp.status_code == 200
        ids = [w["id"] for w in resp.json()]
        assert str(wi.id) in ids

        # tenant B cannot list
        resp_b = await client.get(
            f"/api/v1/store/projects/{project.id}/runs/{run.id}/work-items",
            headers={"X-Tenant-Id": str(tenant_b)},
        )
        assert resp_b.status_code in (403, 404)

        # tenant B cannot get work item
        resp_b_wi = await client.get(
            f"/api/v1/store/work-items/{wi.id}", headers={"X-Tenant-Id": str(tenant_b)}
        )
        assert resp_b_wi.status_code in (403, 404)

        # tenant A sees work dag; tenant B blocked
        dag_a = await client.get(
            f"/api/v1/store/runs/{run.id}/work-dag", headers={"X-Tenant-Id": str(tenant_a)}
        )
        assert dag_a.status_code == 200
        dag_b = await client.get(
            f"/api/v1/store/runs/{run.id}/work-dag", headers={"X-Tenant-Id": str(tenant_b)}
        )
        assert dag_b.status_code in (403, 404)
