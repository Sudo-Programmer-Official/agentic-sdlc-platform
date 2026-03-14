import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import Agent, Artifact, Project, Run, RunEvent, Task, Trace, WorkItem
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.runtime import orchestrator as orchestrator_module
from app.runtime.orchestrator import RunOrchestrator
from app.runtime import worker_service
from app.runtime.worker_service import tick_worker
from app.services.run_launch import launch_run_for_project


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
async def test_embedded_orchestrator_completes_dummy_run(monkeypatch, runtime_db, tmp_path):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(tmp_path / "workspaces"))
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
        assert run.workspace_status == "READY"
        assert run.workspace_root is not None
        assert run.repo_path is not None
        assert Path(run.workspace_root).exists()
        assert Path(run.repo_path).exists()
        assert Path(run.workspace_root, "context", "workspace.json").exists()
        assert Path(run.workspace_root, "context", "plan.json").exists()
        assert isinstance(run.summary, dict)
        assert isinstance(run.summary.get("plan_snapshot"), dict)
        assert run.summary["plan_snapshot"]["steps"]
        assert run.summary["plan_snapshot"]["steps"][0]["title"] == "PLAN_DAG"

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
        assert "RUN_BOOTSTRAP_STARTED" in event_types
        assert "RUN_EXECUTION_HANDOFF" in event_types
        assert "RUN_RUNNING" in event_types
        assert "WORK_DAG_CREATED" in event_types
        assert "RUN_PLAN_CAPTURED" in event_types
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


@pytest.mark.anyio
async def test_external_mode_falls_back_to_embedded_when_no_workers_exist(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Fallback runtime project", tenant_id=tenant_id)
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

        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        event_types = [event.event_type for event in events]
        assert "RUN_BOOTSTRAP_STARTED" in event_types
        assert "RUN_EXECUTION_HANDOFF" in event_types
        assert "RUN_RUNTIME_FALLBACK" in event_types
        fallback = next(event for event in events if event.event_type == "RUN_RUNTIME_FALLBACK")
        assert fallback.payload == {
            "requested_mode": "external",
            "effective_mode": "embedded",
            "reason": "no_active_workers",
        }


@pytest.mark.anyio
async def test_launch_run_bootstraps_work_items_before_background_execution(monkeypatch, runtime_db, tmp_path):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(tmp_path / "workspaces"))
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Bootstrapped launch project", tenant_id=tenant_id)
        session.add(project)
        await session.commit()

        run = await launch_run_for_project(
            session,
            tenant_id=tenant_id,
            project_id=project.id,
            executor_name="dummy",
            schedule=True,
        )
        run_id = run.id

        work_items = (
            await session.execute(select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.created_at.asc()))
        ).scalars().all()
        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()

        assert run.status == "RUNNING"
        assert len(work_items) == 7
        assert any(event.event_type == "RUN_BOOTSTRAP_STARTED" for event in events)
        assert any(event.event_type == "RUN_RUNNING" for event in events)
        assert any(event.event_type == "WORK_DAG_CREATED" for event in events)


@pytest.mark.anyio
async def test_task_bound_run_generates_task_scoped_work_items(monkeypatch, runtime_db, tmp_path):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(tmp_path / "workspaces"))
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Task bound runtime project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        task = Task(
            project_id=project.id,
            tenant_id=tenant_id,
            title="Add audit trail to mission control",
            description="Generate planner work items and execute the task through the connected repo.",
            source="manual",
        )
        session.add(task)
        await session.commit()
        task_id = task.id

        run = await launch_run_for_project(
            session,
            tenant_id=tenant_id,
            project_id=project.id,
            executor_name="dummy",
            task_id=task_id,
            schedule=False,
        )
        run_id = run.id

    orchestrator = RunOrchestrator(runtime_db, executor_name="dummy")
    await orchestrator.start(run_id)

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        task = await session.get(Task, task_id)
        assert run is not None
        assert task is not None
        assert run.status == "COMPLETED"
        assert task.run_id == run_id
        assert isinstance(run.summary, dict)
        assert run.summary["task_id"] == str(task_id)
        assert run.summary["task_title"] == "Add audit trail to mission control"
        assert run.summary["goal"] == (
            "Add audit trail to mission control: Generate planner work items and execute the task through the connected repo."
        )
        assert run.summary["plan_snapshot"]["steps"][0]["title"] == "Add audit trail to mission control"

        work_items = (
            await session.execute(
                select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.priority.desc(), WorkItem.created_at)
            )
        ).scalars().all()
        assert len(work_items) == 7
        assert all(item.payload.get("task_id") == str(task_id) for item in work_items)
        assert work_items[0].payload["title"] == "Add audit trail to mission control"
        assert work_items[1].payload["title"] == "Implement backend for Add audit trail to mission control"

        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        run_created = next(event for event in events if event.event_type == "RUN_CREATED")
        dag_created = next(event for event in events if event.event_type == "WORK_DAG_CREATED")
        assert run_created.task_id == task_id
        assert run_created.payload["task_id"] == str(task_id)
        assert dag_created.task_id == task_id
        assert dag_created.payload["task_id"] == str(task_id)
        assert dag_created.payload["work_item_count"] == 7


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

    monkeypatch.setattr(orchestrator_module, "build_executor", lambda *_args, **_kwargs: ArtifactExecutor())
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


class HealingExecutor:
    name = "dummy"

    def __init__(self):
        self.test_attempts = 0

    async def execute(self, work_item, context):
        if work_item.type == "RUN_TESTS":
            self.test_attempts += 1
            if self.test_attempts == 1:
                return {
                    "status": "FAILED",
                    "message": "tests failed",
                    "payload": {
                        "exit_code": 1,
                        "stdout": "",
                        "stderr": "test failed for auth flow",
                    },
                }
            return {
                "status": "DONE",
                "message": "tests passed",
                "payload": {
                    "exit_code": 0,
                    "stdout": "ok",
                    "stderr": "",
                },
            }
        if work_item.type == "FIX_TEST_FAILURE":
            return {
                "status": "DONE",
                "message": "fix applied",
                "payload": {"artifacts": [{"type": "git_diff", "content": "diff --git a/auth.py b/auth.py"}]},
            }
        return {
            "status": "DONE",
            "message": "ok",
            "payload": {"executor": "healing"},
        }


@pytest.mark.anyio
async def test_embedded_runtime_self_heals_test_failure(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Healing runtime project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="QUEUED", executor="dummy")
        session.add(run)
        await session.commit()
        run_id = run.id
        project_id = project.id

    healing_executor = HealingExecutor()
    monkeypatch.setattr(orchestrator_module, "build_executor", lambda *_args, **_kwargs: healing_executor)

    orchestrator = RunOrchestrator(runtime_db, executor_name="dummy")
    await orchestrator.start(run_id)

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "COMPLETED"

        work_items = (
            await session.execute(
                select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.created_at, WorkItem.id)
            )
        ).scalars().all()
        assert len(work_items) == 9
        assert sum(1 for wi in work_items if wi.type == "FIX_TEST_FAILURE") == 1
        assert sum(1 for wi in work_items if wi.type == "RUN_TESTS") == 2

        failed_test = next(wi for wi in work_items if wi.type == "RUN_TESTS" and wi.status == "FAILED")
        retried_test = next(wi for wi in work_items if wi.type == "RUN_TESTS" and wi.status == "DONE" and wi.id != failed_test.id)
        fix_item = next(wi for wi in work_items if wi.type == "FIX_TEST_FAILURE")
        assert failed_test.result["failure_class"] == "test_failure"
        assert failed_test.result["recovery_action"] == "spawn_fix_node"
        assert failed_test.result["superseded"] is True
        assert failed_test.result["superseded_by"] == str(retried_test.id)
        assert fix_item.result["recovery_action"] == "spawn_retry_node"

        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        recovery_events = [event for event in events if event.event_type == "WORK_ITEM_RECOVERY"]
        assert len(recovery_events) == 2
        assert any(event.payload and event.payload.get("recovery_type") == "FIX_TEST_FAILURE" for event in recovery_events)
        assert any(event.payload and event.payload.get("recovery_type") == "RUN_TESTS" for event in recovery_events)

        traces = (
            await session.execute(
                select(Trace).where(
                    Trace.project_id == project_id,
                    Trace.from_type == "work_item",
                    Trace.to_type == "work_item",
                    Trace.relation_type == "supersedes",
                )
            )
        ).scalars().all()
        assert any(trace.from_id == failed_test.id and trace.to_id == fix_item.id for trace in traces)
        assert any(trace.from_id == failed_test.id and trace.to_id == retried_test.id for trace in traces)
