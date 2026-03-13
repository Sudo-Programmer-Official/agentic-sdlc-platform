import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Project, Document, Task, Trace, Artifact, Run, WorkItem
from app.db.base import Base
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'traversal.db'}", future=True)
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

    app.dependency_overrides[get_session] = override_get_session
    session: AsyncSession = session_factory()
    try:
        yield session
    finally:
        app.dependency_overrides.pop(get_session, None)
        await session.close()
        await engine.dispose()


async def seed_graph(session: AsyncSession):
    tenant_id = uuid.uuid4()
    project = Project(name="Traversal", description="test", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    doc = Document(project_id=project.id, tenant_id=tenant_id, type="requirement", version=1, title="Req", body="body")
    session.add(doc)
    await session.flush()

    task = Task(project_id=project.id, tenant_id=tenant_id, document_id=doc.id, title="Task", status="PENDING")
    session.add(task)
    await session.flush()

    run = Run(project_id=project.id, tenant_id=tenant_id, status="COMPLETED", executor="dummy")
    session.add(run)
    await session.flush()

    work_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="CODE_BACKEND",
        key="CODE_BACKEND",
        status="DONE",
        priority=1,
    )
    session.add(work_item)
    await session.flush()

    art = Artifact(
        project_id=project.id,
        tenant_id=tenant_id,
        task_id=task.id,
        run_id=run.id,
        work_item_id=work_item.id,
        type="code",
        uri="s3://x",
        version=1,
    )
    session.add(art)
    await session.flush()

    t1 = Trace(project_id=project.id, tenant_id=tenant_id, from_type="document", from_id=doc.id, to_type="task", to_id=task.id, relation_type="derives")
    t2 = Trace(project_id=project.id, tenant_id=tenant_id, from_type="task", from_id=task.id, to_type="run", to_id=run.id, relation_type="references")
    t3 = Trace(project_id=project.id, tenant_id=tenant_id, from_type="run", from_id=run.id, to_type="work_item", to_id=work_item.id, relation_type="executes")
    t4 = Trace(project_id=project.id, tenant_id=tenant_id, from_type="work_item", from_id=work_item.id, to_type="artifact", to_id=art.id, relation_type="produces")
    session.add_all([t1, t2, t3, t4])
    await session.commit()
    return project, doc, task, run, work_item, art, tenant_id


@pytest.mark.anyio
async def test_backtrace_and_impact(db_session):
    project, doc, task, run, work_item, art, tenant_id = await seed_graph(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/store/projects/{project.id}/impact/task/{task.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert any(edge["relation_type"] == "produces" for edge in data["edges"])

        resp = await client.get(f"/api/v1/store/projects/{project.id}/backtrace/artifact/{art.id}?max_depth=4")
        assert resp.status_code == 200
        data = resp.json()
        assert any(node["type"] == "document" for node in data["nodes"])
        assert any(node["type"] == "run" for node in data["nodes"])
        assert any(node["type"] == "work_item" for node in data["nodes"])

        resp = await client.get(f"/api/v1/projects/{project.id}/graph/context/artifact/{art.id}?max_depth=4")
        assert resp.status_code == 200
        data = resp.json()
        assert data["root"]["type"] == "artifact"
        assert any(node["type"] == "document" for node in data["ancestors"])
        assert any(node["type"] == "work_item" for node in data["ancestors"])
        assert "documents" in data["project_brief"]
        assert data["root"]["meta"]["semantics"]["node_type"] == "artifact"
        assert data["budget"]["max_depth"] == 4
        assert data["budget"]["returned_counts"]["ancestors"] == len(data["ancestors"])

        resp = await client.get(f"/api/v1/projects/{project.id}/artifacts/context", params={"uri": art.uri})
        assert resp.status_code == 200
        data = resp.json()
        assert data["root"]["id"] == str(art.id)

        resp = await client.get(f"/api/v1/projects/{project.id}/artifacts/{art.id}/explain")
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifact"]["id"] == str(art.id)
        assert data["run"]["id"] == str(run.id)
        assert data["work_item"]["id"] == str(work_item.id)
        assert any(origin["id"] == str(doc.id) for origin in data["origin_documents"])
        assert data["context"]["root"]["type"] == "artifact"

@pytest.mark.anyio
async def test_document_history(db_session):
    project, doc, task, run, work_item, art, tenant_id = await seed_graph(db_session)
    # create second version
    doc2 = Document(project_id=project.id, tenant_id=tenant_id, type="requirement", version=2, title="Req2", body="body2")
    db_session.add(doc2)
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/store/projects/{project.id}/documents/{doc.id}/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["version"] == 1
        assert data[1]["version"] == 2


@pytest.mark.anyio
async def test_graph_context_applies_window_limits(db_session):
    project, doc, task, run, work_item, art, tenant_id = await seed_graph(db_session)

    extra_work_items = []
    for idx in range(12):
        wi = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_BACKEND",
            key=f"CODE_BACKEND_{idx}",
            status="DONE",
            priority=idx,
        )
        db_session.add(wi)
        await db_session.flush()
        extra_work_items.append(wi)
        db_session.add(
            Trace(
                project_id=project.id,
                tenant_id=tenant_id,
                from_type="work_item",
                from_id=wi.id,
                to_type="artifact",
                to_id=art.id,
                relation_type="references",
            )
        )

    for idx in range(8):
        db_session.add(
            Document(
                project_id=project.id,
                tenant_id=tenant_id,
                type="note",
                version=idx + 2,
                title=f"Doc {idx}",
                body="supplemental context",
            )
        )
        db_session.add(
            Task(
                project_id=project.id,
                tenant_id=tenant_id,
                document_id=doc.id,
                title=f"Task {idx}",
                status="PENDING",
            )
        )
        db_session.add(
            Artifact(
                project_id=project.id,
                tenant_id=tenant_id,
                task_id=task.id,
                run_id=run.id,
                work_item_id=work_item.id,
                type="log",
                uri=f"inline://artifact-{idx}.log",
                version=idx + 2,
            )
        )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/projects/{project.id}/graph/context/artifact/{art.id}?max_depth=6")
        assert resp.status_code == 200
        data = resp.json()
        assert data["budget"]["truncated"] is True
        assert len(data["ancestors"]) <= data["budget"]["max_ancestor_nodes"]
        assert len(data["project_brief"]["documents"]) <= data["budget"]["max_documents"]
        assert len(data["project_brief"]["tasks"]) <= data["budget"]["max_tasks"]
        assert len(data["project_brief"]["artifacts"]) <= data["budget"]["max_artifacts"]
