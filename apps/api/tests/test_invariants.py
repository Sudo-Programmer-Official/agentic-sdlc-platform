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


async def seed(session: AsyncSession):
    project = Project(name="Invariant")
    session.add(project)
    await session.flush()
    doc1 = Document(project_id=project.id, type="requirement", version=1, title="Req1", body="body1", content_hash=None)
    session.add(doc1)
    await session.commit()
    return project, doc1


@pytest.mark.anyio
async def test_regeneration_invariants(db_session):
    project, doc1 = await seed(db_session)
    async with AsyncClient(app=app, base_url="http://test") as client:
        # generate for v1
        resp = await client.post(
            f"/api/v1/store/projects/{project.id}/documents/{doc1.id}/generate-tasks",
            json={},
        )
        assert resp.status_code == 201

        # create doc v2
        resp = await client.post(
            f"/api/v1/store/projects/{project.id}/documents",
            json={"type": "requirement", "title": "Req2", "body": "body2"},
        )
        assert resp.status_code == 201
        doc2_id = resp.json()["id"]

        # regenerate for v2 (first time ok)
        resp = await client.post(
            f"/api/v1/store/projects/{project.id}/documents/{doc2_id}/generate-tasks",
            json={},
        )
        assert resp.status_code == 201

        # second regenerate without force should 409
        resp = await client.post(
            f"/api/v1/store/projects/{project.id}/documents/{doc2_id}/generate-tasks",
            json={},
        )
        assert resp.status_code == 409

        # with force should succeed
        resp = await client.post(
            f"/api/v1/store/projects/{project.id}/documents/{doc2_id}/generate-tasks?force=true",
            json={},
        )
        assert resp.status_code == 201

        # explain a new task
        tasks_resp = await client.get(f"/api/v1/store/projects/{project.id}/tasks")
        assert tasks_resp.status_code == 200
        tasks = tasks_resp.json()
        new_task = [t for t in tasks if t["document_id"] == doc2_id][0]
        # ensure only one active set for doc2
        active_doc2 = [t for t in tasks if t["document_id"] == doc2_id and t["status"] != "DEPRECATED"]
        assert len(active_doc2) == len(set([t["id"] for t in active_doc2]))

        explain_resp = await client.get(
            f"/api/v1/store/projects/{project.id}/tasks/{new_task['id']}/explain"
        )
        assert explain_resp.status_code == 200
        data = explain_resp.json()
        assert data["task"]["generated_from_document_version"] == 2
        assert any(edge["relation_type"] == "supersedes" for edge in data["graph"]["edges"])
        assert "supersede_depth" in data
        assert data["supersede_depth"] >= 0
        assert "origin_document_chain" in data
        assert data["provenance_summary"] is None or "generation_runs" in data["provenance_summary"]

        # check activity log exists
        activity_resp = await client.get(f"/api/v1/store/projects/{project.id}/activity")
        assert activity_resp.status_code == 200
        logs = activity_resp.json()
        assert any(log["action_type"] == "tasks.generated" for log in logs)

