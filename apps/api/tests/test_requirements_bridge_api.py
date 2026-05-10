import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.api.v1 import generation as generation_module
from app.db.base import Base
from app.db.models import Task, Trace
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app
from app.schemas.generation import GeneratedTask


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'requirements_bridge.db'}", future=True)
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
        yield session
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_tenant_context, None)
        await session.close()
        await engine.dispose()


@pytest.mark.anyio
async def test_db_backed_project_can_use_requirements_graph_routes(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/v1/projects", json={"name": "Req Bridge"})
        assert create_resp.status_code == 201
        project_id = create_resp.json()["id"]

        prd_resp = await client.post(
            f"/api/v1/projects/{project_id}/prd",
            json={"text": "Must allow login\nSystem should be reliable"},
        )
        assert prd_resp.status_code == 200
        graph = prd_resp.json()
        assert graph["project_id"] == project_id
        assert len(graph["nodes"]) >= 1

        get_resp = await client.get(f"/api/v1/projects/{project_id}/requirements-graph")
        assert get_resp.status_code == 200
        assert get_resp.json()["project_id"] == project_id


@pytest.mark.anyio
async def test_prd_ingest_parses_structured_requirement_lines_without_collapsing_to_defaults(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/v1/projects", json={"name": "Structured PRD"})
        assert create_resp.status_code == 201
        project_id = create_resp.json()["id"]

        prd_resp = await client.post(
            f"/api/v1/projects/{project_id}/prd",
            json={
                "text": "\n".join(
                    [
                        "FR1: Create a homepage file index.html",
                        "FR2: Add a hero section with name and tagline",
                        "FR3: Add an about section",
                        "QR1: Homepage should load quickly",
                        "QR2: Content should remain secure",
                    ]
                )
            },
        )
        assert prd_resp.status_code == 200
        graph = prd_resp.json()

        fr_nodes = [node for node in graph["nodes"] if node["type"] == "FR"]
        qr_nodes = [node for node in graph["nodes"] if node["type"] == "QR"]

        assert [node["id"] for node in fr_nodes] == ["FR-001", "FR-002", "FR-003"]
        assert [node["text"] for node in fr_nodes] == [
            "Create a homepage file index.html",
            "Add a hero section with name and tagline",
            "Add an about section",
        ]
        assert [node["id"] for node in qr_nodes] == ["QR-001", "QR-002"]
        assert [node["text"] for node in qr_nodes] == [
            "Homepage should load quickly",
            "Content should remain secure",
        ]
        assert len(graph["edges"]) == 6
        assert "System must support core user flow." not in {node["text"] for node in graph["nodes"]}
        assert "System should be reliable and secure." not in {node["text"] for node in graph["nodes"]}


@pytest.mark.anyio
async def test_prd_ingest_fr_only_structured_input_does_not_invent_fallback_qr(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/v1/projects", json={"name": "FR Only PRD"})
        assert create_resp.status_code == 201
        project_id = create_resp.json()["id"]

        prd_resp = await client.post(
            f"/api/v1/projects/{project_id}/prd",
            json={
                "text": "\n".join(
                    [
                        "FR1: Create a homepage file index.html",
                        "FR2: Add a hero section",
                        "FR3: Add an about section",
                    ]
                )
            },
        )
        assert prd_resp.status_code == 200
        graph = prd_resp.json()

        assert [node["id"] for node in graph["nodes"] if node["type"] == "FR"] == ["FR-001", "FR-002", "FR-003"]
        assert [node for node in graph["nodes"] if node["type"] == "QR"] == []
        assert graph["edges"] == []


@pytest.mark.anyio
async def test_db_backed_project_gets_empty_requirements_graph_before_creation(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/v1/projects", json={"name": "Empty Req Bridge"})
        assert create_resp.status_code == 201
        project_id = create_resp.json()["id"]

        get_resp = await client.get(f"/api/v1/projects/{project_id}/requirements-graph")
        assert get_resp.status_code == 200

        graph = get_resp.json()
        assert graph["project_id"] == project_id
        assert graph["status"] == "DRAFT"
        assert graph["version"] == 0
        assert graph["approved_at"] is None
        assert graph["approved_by"] is None
        assert graph["nodes"] == []
        assert graph["edges"] == []


@pytest.mark.anyio
async def test_db_backed_project_can_save_manual_requirements_graph_from_empty_state(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/v1/projects", json={"name": "Manual Req Bridge"})
        assert create_resp.status_code == 201
        project_id = create_resp.json()["id"]

        update_resp = await client.put(
            f"/api/v1/projects/{project_id}/requirements-graph",
            json={
                "nodes": [
                    {
                        "id": "FR-001",
                        "type": "FR",
                        "text": "Post general comments on pull requests",
                        "confidence": 0.7,
                        "source": "HUMAN_EDITED",
                        "tags": [],
                    },
                    {
                        "id": "QR-001",
                        "type": "QR",
                        "text": "Keep comment delivery reliable",
                        "confidence": 0.7,
                        "source": "HUMAN_EDITED",
                        "quality_type": "reliability",
                        "tags": [],
                    },
                ],
                "edges": [
                    {
                        "id": "EDGE-001",
                        "from_id": "FR-001",
                        "to_id": "QR-001",
                        "relation": "constrains",
                        "weight": 0.5,
                        "rationale": "Reliability constrains posting behavior",
                    }
                ],
            },
        )
        assert update_resp.status_code == 200
        graph = update_resp.json()
        assert graph["project_id"] == project_id
        assert graph["version"] == 1
        assert graph["status"] == "DRAFT"
        assert len(graph["nodes"]) == 2
        assert len(graph["edges"]) == 1

        get_resp = await client.get(f"/api/v1/projects/{project_id}/requirements-graph")
        assert get_resp.status_code == 200
        persisted = get_resp.json()
        assert persisted["version"] == 1
        assert {node["id"] for node in persisted["nodes"]} == {"FR-001", "QR-001"}


@pytest.mark.anyio
async def test_approving_requirements_graph_updates_db_summary_and_creates_document(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/v1/projects", json={"name": "Requirements Overview Bridge"})
        assert create_resp.status_code == 201
        project_id = create_resp.json()["id"]

        prd_text = "# Portfolio App PRD\n\nUsers can create and manage investments."
        prd_resp = await client.post(
            f"/api/v1/projects/{project_id}/prd",
            json={"text": prd_text, "source": "typed", "format": "markdown"},
        )
        assert prd_resp.status_code == 200

        approve_resp = await client.post(
            f"/api/v1/projects/{project_id}/requirements-graph/approve",
            json={"approved_by": "ui-user"},
        )
        assert approve_resp.status_code == 200

        summary_resp = await client.get(f"/api/v1/projects/{project_id}/summary")
        assert summary_resp.status_code == 200
        summary = summary_resp.json()
        assert summary["requirements_status"] == "APPROVED"
        assert summary["requirements_version"] == 1
        assert summary["requirements_sha"]

        docs_resp = await client.get(f"/api/v1/projects/{project_id}/documents")
        assert docs_resp.status_code == 200
        docs = docs_resp.json()
        doc_types = {doc["type"] for doc in docs}
        assert "prd" in doc_types
        assert "requirements_graph" in doc_types
        requirements_doc = next(doc for doc in docs if doc["type"] == "requirements_graph")
        assert "Approved requirements graph v1" in requirements_doc["title"]


@pytest.mark.anyio
async def test_approved_requirements_document_can_generate_tasks_for_project_overview_flow(db_session, monkeypatch):
    session = db_session
    captured = {}

    async def fake_generate(self, title, body, payload):
        captured["title"] = title
        captured["body"] = body
        return (
            [GeneratedTask(title="Build portfolio dashboard", description="Create the dashboard flow", category="func", confidence=0.9)],
            {"ai_model_name": "test-model", "ai_prompt_hash": "req-bridge"},
        )

    async def fake_health(project_id, session):
        return {"graph_cycles_detected": False}

    async def fake_lifecycle(project_id, session):
        return {"health_index": 100}

    monkeypatch.setattr(generation_module.LLMTaskGenerator, "generate", fake_generate)
    monkeypatch.setattr(generation_module, "project_health", fake_health)
    monkeypatch.setattr(generation_module, "lifecycle_score", fake_lifecycle)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/v1/projects", json={"name": "Requirements To Tasks"})
        assert create_resp.status_code == 201
        project_id = create_resp.json()["id"]

        update_resp = await client.put(
            f"/api/v1/projects/{project_id}/requirements-graph",
            json={
                "nodes": [
                    {
                        "id": "FR-001",
                        "type": "FR",
                        "text": "Users can create a portfolio",
                        "confidence": 0.8,
                        "source": "HUMAN_EDITED",
                        "tags": [],
                    },
                    {
                        "id": "QR-001",
                        "type": "QR",
                        "text": "Portfolio creation should complete quickly",
                        "confidence": 0.8,
                        "source": "HUMAN_EDITED",
                        "quality_type": "performance",
                        "tags": [],
                    },
                ],
                "edges": [
                    {
                        "id": "EDGE-001",
                        "from_id": "FR-001",
                        "to_id": "QR-001",
                        "relation": "constrains",
                        "weight": 0.7,
                        "rationale": "Creation speed matters",
                    }
                ],
            },
        )
        assert update_resp.status_code == 200

        approve_resp = await client.post(
            f"/api/v1/projects/{project_id}/requirements-graph/approve",
            json={"approved_by": "ui-user"},
        )
        assert approve_resp.status_code == 200

        docs_resp = await client.get(f"/api/v1/projects/{project_id}/documents")
        assert docs_resp.status_code == 200
        requirements_doc = next(doc for doc in docs_resp.json() if doc["type"] == "requirements_graph")

        regen_resp = await client.post(
            f"/api/v1/projects/{project_id}/documents/{requirements_doc['id']}/generate-tasks",
            json={},
        )
        assert regen_resp.status_code == 201
        assert regen_resp.json()["tasks"][0]["title"] == "Build portfolio dashboard"

        tasks_resp = await client.get(f"/api/v1/projects/{project_id}/tasks")
        assert tasks_resp.status_code == 200
        tasks = tasks_resp.json()
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Build portfolio dashboard"
        assert tasks[0]["document_id"] == requirements_doc["id"]
        assert tasks[0]["source_type"] == "requirement_propagation"
        assert tasks[0]["derived_from_requirement_ids"] == ["FR-001", "QR-001"]
        assert tasks[0]["capability_id"] == "CAP-001"

        stored_task = await session.scalar(select(Task).where(Task.id == uuid.UUID(tasks[0]["id"])))
        assert stored_task is not None
        assert stored_task.architecture_slice == "frontend"

        traces = (
            await session.execute(
                select(Trace).where(
                    Trace.project_id == uuid.UUID(project_id),
                    Trace.to_id == stored_task.id,
                    Trace.from_type.in_(["requirement", "capability"]),
                )
            )
        ).scalars().all()
        assert {trace.from_type for trace in traces} == {"requirement", "capability"}

        assert captured["title"] == requirements_doc["title"]
        assert "Users can create a portfolio" in captured["body"]
        assert "Portfolio creation should complete quickly" in captured["body"]
