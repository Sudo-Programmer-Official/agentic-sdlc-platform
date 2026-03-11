import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import Agent, Artifact, Project, Run, RunEvent, Trace, WorkItem
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.runtime import orchestrator as orchestrator_module
from app.runtime.orchestrator import RunOrchestrator
from app.runtime import worker_service
from app.runtime.worker_service import tick_worker


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture
async def runtime_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Project.metadata.create_all)
    monkeypatch.setattr(worker_service, "SessionLocal", session_factory)
    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_embedded_orchestrator_completes_dummy_run(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Embedded runtime project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="QUEUED", executor="dummy")
        session.add(run)
        await session.commit()
        run_id = run.id

    orchestrator = RunOrchestrator(runtime_db, executor_name="dummy")
    await orchestrator.start(run_id)

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "COMPLETED"

        work_items = (
            await session.execute(
                select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.priority.desc(), WorkItem.created_at)
            )
        ).scalars().all()
        assert len(work_items) == 7
        assert {wi.type for wi in work_items} == {
            "PLAN_DAG",
            "CODE_BACKEND",
            "CODE_FRONTEND",
            "WRITE_TESTS",
            "REVIEW_DIFF",
            "RUN_TESTS",
            "REVIEW_INTEGRATION",
        }
        assert all(wi.status == "DONE" for wi in work_items)
        assert all(wi.executor == "dummy" for wi in work_items)

        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        event_types = [event.event_type for event in events]
        assert "RUN_RUNNING" in event_types
        assert "WORK_DAG_CREATED" in event_types
        assert "RUN_COMPLETED" in event_types
        assert any(event.payload and event.payload.get("work_item_id") for event in events if event.event_type.startswith("WORK_ITEM_"))
        assert all(event.task_id is None for event in events if event.event_type.startswith("WORK_ITEM_"))
        assert all(event.work_item_id is not None for event in events if event.event_type.startswith("WORK_ITEM_"))

        traces = (
            await session.execute(
                select(Trace).where(
                    Trace.project_id == project.id,
                    Trace.from_type == "run",
                    Trace.to_type == "work_item",
                    Trace.relation_type == "executes",
                )
            )
        ).scalars().all()
        assert len(traces) == len(work_items)


@pytest.mark.anyio
async def test_external_worker_claims_and_executes_dummy_work_item(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="External worker project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="dummy")
        session.add(run)
        await session.flush()

        agent = Agent(
            tenant_id=tenant_id,
            name="runtime-worker",
            kind="worker",
            executors=["dummy"],
            capabilities=["runtime-worker"],
            max_concurrency=1,
            status="ACTIVE",
        )
        session.add(agent)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_BACKEND",
            key="CODE_BACKEND",
            status="QUEUED",
            priority=10_000,
            executor="dummy",
            required_capabilities=["runtime-worker"],
        )
        session.add(work_item)
        await session.commit()
        agent_id = agent.id
        work_item_id = work_item.id
        run_id = run.id

    await tick_worker(agent_id)

    async with runtime_db() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        assert work_item.status == "DONE"
        assert work_item.result == {"executor": "dummy"}

        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        payload_ids = [event.payload.get("work_item_id") for event in events if event.payload]
        assert str(work_item_id) in payload_ids
        event_types = [event.event_type for event in events if event.payload and event.payload.get("work_item_id") == str(work_item_id)]
        assert "WORK_ITEM_CLAIMED" in event_types
        assert "WORK_ITEM_DONE" in event_types
        assert all(event.work_item_id is not None for event in events if event.payload and event.payload.get("work_item_id"))


class ArtifactExecutor:
    name = "dummy"

    async def execute(self, work_item, context):
        return {
            "status": "DONE",
            "message": "artifact generated",
            "payload": {
                "artifacts": [
                    {
                        "type": "git_diff",
                        "content": "diff --git a/file b/file",
                    }
                ]
            },
        }


@pytest.mark.anyio
async def test_embedded_runtime_persists_canonical_artifacts_and_produces_traces(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Artifact runtime project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="QUEUED", executor="dummy")
        session.add(run)
        await session.commit()
        run_id = run.id
        project_id = project.id

    monkeypatch.setattr(orchestrator_module, "get_executor", lambda _: ArtifactExecutor())
    orchestrator = RunOrchestrator(runtime_db, executor_name="dummy")
    await orchestrator.start(run_id)

    async with runtime_db() as session:
        artifacts = (
            await session.execute(
                select(Artifact).where(Artifact.project_id == project_id).order_by(Artifact.created_at, Artifact.id)
            )
        ).scalars().all()
        assert artifacts
        assert all(artifact.run_id == run_id for artifact in artifacts)
        assert all(artifact.work_item_id is not None for artifact in artifacts)
        assert all(artifact.uri.startswith("inline://work-items/") for artifact in artifacts)

        produce_edges = (
            await session.execute(
                select(Trace).where(
                    Trace.project_id == project_id,
                    Trace.from_type == "work_item",
                    Trace.to_type == "artifact",
                    Trace.relation_type == "produces",
                )
            )
        ).scalars().all()
        assert len(produce_edges) == len(artifacts)
