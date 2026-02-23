import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine, SessionLocal
from app.db.models import Project, Document, Task
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


async def seed(doc_body: str, session: AsyncSession):
    project = Project(name="ImpactProj")
    session.add(project)
    await session.flush()
    doc = Document(project_id=project.id, type="requirement", version=1, title="Req", body=doc_body, content_hash=None)
    session.add(doc)
    await session.flush()
    task = Task(project_id=project.id, document_id=doc.id, title="T1", status="PENDING", generated_from_document_version=1)
    session.add(task)
    await session.commit()
    return project, doc, task


@pytest.mark.anyio
async def test_impact_preview_no_change(db_session):
    project, doc, task = await seed("same body", db_session)
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/store/projects/{project.id}/documents/{doc.id}/impact-preview",
            json={"proposed_body": "same body"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["similarity"] == 1.0
        assert data["regeneration_required"] is False
        assert data["risk_tier"] == "LOW"


@pytest.mark.anyio
async def test_impact_preview_change(db_session):
    project, doc, task = await seed("alpha beta", db_session)
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/store/projects/{project.id}/documents/{doc.id}/impact-preview",
            json={"proposed_body": "completely different text"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["similarity"] < 1.0
        assert data["regeneration_required"] is True
        assert len(data["impacted_tasks"]) == 1
