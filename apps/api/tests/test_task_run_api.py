import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import ActivityLog, Artifact, Project, Run, RunEvent, Task
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


@pytest.mark.anyio
async def test_create_run_blocks_codex_when_architecture_not_derived(db_session):
    session, tenant_id = db_session
    project = Project(name="Architecture gate", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/projects/{project.id}/runs",
            json={"executor": "codex"},
        )

    assert response.status_code == 409
    payload = response.json()
    assert "Architecture profile must be derived before starting a run" in payload["detail"]


@pytest.mark.anyio
async def test_retry_push_endpoint_clears_manual_push_flag(monkeypatch, db_session):
    session, tenant_id = db_session
    project = Project(name="Retry push API", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        workspace_status="SEEDED",
        repo_path="/tmp/repo",
        branch_name="run/test-retry-push",
        summary={
            "delivery_manual_push_required": True,
            "remote_branch_push_error": "permission denied",
        },
    )
    session.add(run)
    await session.commit()

    captured: dict[str, str | None] = {"strategy": None}

    async def _publish(*_args, **_kwargs):
        captured["strategy"] = _kwargs.get("auth_strategy_override")
        run.summary = {
            **(run.summary or {}),
            "remote_branch_pushed": True,
            "remote_branch_name": run.branch_name,
        }
        return {"branch_name": run.branch_name, "commit_sha": "abc1234", "created_commit": False}

    from app.api.v1 import persistence as persistence_routes

    monkeypatch.setattr(persistence_routes, "publish_run_branch_if_ready", _publish)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/runs/{run.id}/retry-push",
            json={"auth_strategy": "ssh"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "COMPLETED"
    assert data["summary"]["delivery_manual_push_required"] is False
    assert captured["strategy"] == "ssh"


@pytest.mark.anyio
async def test_vision_run_creates_task_run_and_screenshot_artifacts(db_session):
    session, tenant_id = db_session
    project = Project(name="Vision run API", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    screenshot_b64 = "aGVsbG8="  # "hello"
    payload = {
        "project_id": str(project.id),
        "goal_text": "Make hero image full-width background on homepage",
        "screenshots": [
            {
                "filename": "hero-current.png",
                "content_type": "image/png",
                "data_base64": screenshot_b64,
            }
        ],
        "page_url": "http://127.0.0.1:5902",
        "auto_start": True,
        "auto_deploy": False,
        "metadata": {"request_source": "mobile"},
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/tasks/vision-run", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["source_type"] == "screenshot_guided_edit"
    assert data["status"] == "queued"
    assert data["task_id"]
    assert data["run_id"]
    assert data["status_url"].endswith(f"/projects/{project.id}/runs/{data['run_id']}")

    task = await session.get(Task, uuid.UUID(data["task_id"]))
    assert task is not None
    assert task.source_type == "screenshot_guided_edit"
    assert task.provenance["page_url"] == "http://127.0.0.1:5902"
    assert task.provenance["visual_intent"] == "Make hero image full-width background on homepage"
    assert task.provenance["request_source"] == "mobile"

    run = await session.get(Run, uuid.UUID(data["run_id"]))
    assert run is not None
    assert run.executor == "codex"

    artifacts = (
        await session.execute(
            select(Artifact).where(
                Artifact.task_id == task.id,
                Artifact.run_id == run.id,
                Artifact.type == "screenshot_input",
            )
        )
    ).scalars().all()
    assert len(artifacts) == 1
    assert artifacts[0].extra_metadata["filename"] == "hero-current.png"
    assert artifacts[0].extra_metadata["data_base64"] == screenshot_b64
