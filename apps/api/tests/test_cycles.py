import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine, SessionLocal
from app.db.models import Project, Task, Trace
from app.main import app


@pytest.fixture
async def db_session():
    async with engine.begin() as conn:
        await conn.run_sync(Project.metadata.create_all)
    session: AsyncSession = SessionLocal()
    try:
        yield session
    finally:
        await session.close()


@pytest.mark.anyio
async def test_cycle_detection(db_session):
    # seed project and tasks A,B,C
    project = Project(name="CycleProj")
    db_session.add(project)
    await db_session.flush()
    a = Task(project_id=project.id, title="A", status="PENDING")
    b = Task(project_id=project.id, title="B", status="PENDING")
    c = Task(project_id=project.id, title="C", status="PENDING")
    db_session.add_all([a, b, c])
    await db_session.flush()
    db_session.add_all(
        [
            Trace(project_id=project.id, from_type="task", from_id=a.id, to_type="task", to_id=b.id, relation_type="rel"),
            Trace(project_id=project.id, from_type="task", from_id=b.id, to_type="task", to_id=c.id, relation_type="rel"),
            Trace(project_id=project.id, from_type="task", from_id=c.id, to_type="task", to_id=a.id, relation_type="rel"),
        ]
    )
    await db_session.commit()

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/store/projects/{project.id}/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["counts"]["cycles"] >= 1
        sample = data["sample_cycles"]
        assert sample and len(sample[0]) >= 3
        assert data["counts"]["longest_chain"] >= 3
