import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Document, Task, Trace, Artifact
from app.db.session import SessionLocal, engine
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


async def seed_graph(session: AsyncSession):
    project = Project(name="Traversal", description="test")
    session.add(project)
    await session.flush()

    doc = Document(project_id=project.id, type="requirement", version=1, title="Req", body="body")
    session.add(doc)
    await session.flush()

    task = Task(project_id=project.id, document_id=doc.id, title="Task", status="PENDING")
    session.add(task)
    await session.flush()

    art = Artifact(project_id=project.id, task_id=task.id, type="code", uri="s3://x", version=1)
    session.add(art)
    await session.flush()

    t1 = Trace(project_id=project.id, from_type="document", from_id=doc.id, to_type="task", to_id=task.id, relation_type="derives")
    t2 = Trace(project_id=project.id, from_type="task", from_id=task.id, to_type="artifact", to_id=art.id, relation_type="produces")
    session.add_all([t1, t2])
    await session.commit()
    return project, doc, task, art


@pytest.mark.anyio
async def test_backtrace_and_impact(db_session):
    project, doc, task, art = await seed_graph(db_session)
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/store/projects/{project.id}/impact/task/{task.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert any(edge["relation_type"] == "produces" for edge in data["edges"])

        resp = await client.get(f"/api/v1/store/projects/{project.id}/backtrace/artifact/{art.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert any(node["type"] == "document" for node in data["nodes"])

@pytest.mark.anyio
async def test_document_history(db_session):
    project, doc, task, art = await seed_graph(db_session)
    # create second version
    doc2 = Document(project_id=project.id, type="requirement", version=2, title="Req2", body="body2")
    db_session.add(doc2)
    await db_session.commit()
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/store/projects/{project.id}/documents/{doc.id}/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["version"] == 1
        assert data[1]["version"] == 2
