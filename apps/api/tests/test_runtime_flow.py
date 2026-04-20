import asyncio
import uuid
from datetime import datetime, timedelta, timezone
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
from app.runtime.leases import keep_work_item_lease_alive
from app.runtime.scheduler_service import tick as scheduler_tick
from app.runtime import worker_service
from app.runtime.worker_service import tick_worker
from app.services import run_launch as run_launch_module
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
async def test_embedded_runtime_marks_run_failed_when_branch_publish_fails(monkeypatch, runtime_db, tmp_path):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("RUN_AUTO_PUSH_BRANCH_ON_COMPLETION", "true")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async def _fail_publish(*_args, **_kwargs):
        raise RuntimeError("push failed")

    monkeypatch.setattr(orchestrator_module, "publish_run_branch_if_ready", _fail_publish)

    async with runtime_db() as session:
        project = Project(name="Publish failure runtime project", tenant_id=tenant_id)
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
        assert run.status == "FAILED"
        assert run.summary["remote_branch_push_error"] == "push failed"

        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        event_types = [event.event_type for event in events]
        assert "RUN_BRANCH_PUSH_FAILED" in event_types
        assert "RUN_FAILED" in event_types


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
async def test_scheduler_requeues_expired_running_items_and_run_can_finish(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Expired lease project", tenant_id=tenant_id)
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
            status="RUNNING",
            priority=10_000,
            executor="dummy",
            assigned_agent_id=agent.id,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            required_capabilities=["runtime-worker"],
        )
        session.add(work_item)
        await session.commit()
        agent_id = agent.id
        run_id = run.id
        work_item_id = work_item.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        assert work_item.status == "QUEUED"
        assert work_item.assigned_agent_id is None
        assert work_item.started_at is None

        lease_event = (
            await session.execute(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.event_type == "WORK_ITEM_LEASE_EXPIRED")
                .order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().one()
        assert lease_event.work_item_id == work_item_id
        assert lease_event.payload == {
            "work_item_id": str(work_item_id),
            "previous_status": "RUNNING",
            "lease_expires_at": lease_event.payload["lease_expires_at"],
        }

    await tick_worker(agent_id)

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "COMPLETED"

        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        assert work_item.status == "DONE"

        event_types = [
            event.event_type
            for event in (
                await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
            ).scalars().all()
        ]
        assert "WORK_ITEM_LEASE_EXPIRED" in event_types
        assert "WORK_ITEM_DONE" in event_types
        assert "RUN_COMPLETED" in event_types


@pytest.mark.anyio
async def test_keep_work_item_lease_alive_refreshes_running_item(runtime_db):
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Lease refresh project", tenant_id=tenant_id)
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

        original_lease = datetime.now(timezone.utc) + timedelta(seconds=1)
        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_BACKEND",
            key="CODE_BACKEND",
            status="RUNNING",
            priority=10_000,
            executor="dummy",
            assigned_agent_id=agent.id,
            started_at=datetime.now(timezone.utc),
            lease_expires_at=original_lease,
            required_capabilities=["runtime-worker"],
        )
        session.add(work_item)
        await session.commit()
        agent_id = agent.id
        work_item_id = work_item.id

    lease_task = asyncio.create_task(
        keep_work_item_lease_alive(
            runtime_db,
            agent_id=agent_id,
            work_item_id=work_item_id,
            lease_seconds=1,
            interval_seconds=0.05,
        )
    )
    await asyncio.sleep(0.12)
    lease_task.cancel()
    await lease_task

    async with runtime_db() as session:
        agent = await session.get(Agent, agent_id)
        work_item = await session.get(WorkItem, work_item_id)
        assert agent is not None
        assert work_item is not None
        assert agent.last_heartbeat_at is not None
        assert work_item.lease_expires_at is not None
        refreshed_lease = work_item.lease_expires_at
        if refreshed_lease.tzinfo is None:
            refreshed_lease = refreshed_lease.replace(tzinfo=timezone.utc)
        assert refreshed_lease > original_lease


@pytest.mark.anyio
async def test_external_worker_marks_item_failed_when_executor_raises(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    class BrokenExecutor:
        name = "dummy"

        async def execute(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(worker_service, "build_executor", lambda *_args, **_kwargs: BrokenExecutor())

    async with runtime_db() as session:
        project = Project(name="Broken worker project", tenant_id=tenant_id)
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
        run_id = run.id
        work_item_id = work_item.id

    await tick_worker(agent_id)

    async with runtime_db() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        assert work_item.status == "FAILED"
        assert work_item.last_error == "boom"

        failed_events = (
            await session.execute(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.event_type == "WORK_ITEM_FAILED")
                .order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        assert failed_events
        assert failed_events[-1].work_item_id == work_item_id
        assert failed_events[-1].payload == {
            "work_item_id": str(work_item_id),
            "error": "boom",
            "exception_class": "RuntimeError",
            "failure_stage": "executor_execute",
        }


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
async def test_launch_run_fails_closed_when_workspace_prepare_errors(monkeypatch, runtime_db, tmp_path):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(tmp_path / "workspaces"))
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async def fake_ensure_run_workspace(session, run, **kwargs):
        run.workspace_root = str(tmp_path / "workspaces" / str(run.id))
        run.repo_path = str(tmp_path / "workspaces" / str(run.id) / "repo")
        run.workspace_status = "ERROR"
        run.workspace_error = "clone auth failed"
        session.add(run)
        await session.flush()

    async def fail_if_bootstrap_called(*args, **kwargs):
        raise AssertionError("bootstrap should not run after a workspace preparation failure")

    monkeypatch.setattr(run_launch_module, "ensure_run_workspace", fake_ensure_run_workspace)
    monkeypatch.setattr(RunOrchestrator, "bootstrap_in_session", fail_if_bootstrap_called)

    async with runtime_db() as session:
        project = Project(name="Repo failure launch project", tenant_id=tenant_id)
        session.add(project)
        await session.commit()

        run = await launch_run_for_project(
            session,
            tenant_id=tenant_id,
            project_id=project.id,
            executor_name="codex",
            schedule=True,
        )
        run_id = run.id

        assert run.status == "FAILED"
        assert run.workspace_status == "ERROR"
        assert run.workspace_error == "clone auth failed"

        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        event_types = [event.event_type for event in events]
        assert "RUN_CREATED" in event_types
        assert "WORKSPACE_PREPARE_FAILED" not in event_types
        assert "RUN_FAILED" in event_types

        work_items = (
            await session.execute(select(WorkItem).where(WorkItem.run_id == run_id))
        ).scalars().all()
        assert work_items == []


@pytest.mark.anyio
async def test_bootstrap_marks_repo_run_failed_when_workspace_prepare_errors(monkeypatch, runtime_db, tmp_path):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(tmp_path / "workspaces"))
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    require_repo_calls: list[bool] = []

    async def fake_ensure_run_workspace(session, run, **kwargs):
        require_repo_calls.append(bool(kwargs.get("require_repo")))
        run.workspace_root = str(tmp_path / "workspaces" / str(run.id))
        run.repo_path = str(tmp_path / "workspaces" / str(run.id) / "repo")
        run.workspace_status = "ERROR"
        run.workspace_error = "clone auth failed"
        session.add(run)
        await session.flush()

    async def fail_if_dag_called(*args, **kwargs):
        raise AssertionError("bootstrap should not seed work items after a workspace preparation failure")

    monkeypatch.setattr(orchestrator_module, "ensure_run_workspace", fake_ensure_run_workspace)
    monkeypatch.setattr(orchestrator_module, "generate_template_dag", fail_if_dag_called)

    async with runtime_db() as session:
        project = Project(name="Repo failure bootstrap project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="QUEUED", executor="codex")
        session.add(run)
        await session.commit()
        run_id = run.id

    orchestrator = RunOrchestrator(runtime_db, executor_name="codex")
    bootstrapped = await orchestrator.bootstrap(run_id)
    assert bootstrapped is False
    assert require_repo_calls == [True]

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "FAILED"
        assert run.workspace_status == "ERROR"
        assert run.workspace_error == "clone auth failed"

        work_items = (
            await session.execute(select(WorkItem).where(WorkItem.run_id == run_id))
        ).scalars().all()
        assert work_items == []


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


@pytest.mark.anyio
async def test_task_bound_run_extracts_expected_file_hints_from_goal(monkeypatch, runtime_db, tmp_path):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(tmp_path / "workspaces"))
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Scoped smoke runtime project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        task = Task(
            project_id=project.id,
            tenant_id=tenant_id,
            title="GitHub smoke commit test",
            description="Create docs/pipeline-smoke-test.md and add exactly: Prompt2PR pipeline test via codex executor.",
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
        assert run is not None
        assert isinstance(run.summary, dict)
        assert run.summary["plan_snapshot"]["expected_files"] == ["docs/pipeline-smoke-test.md"]

        work_items = (
            await session.execute(
                select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.priority.desc(), WorkItem.created_at)
            )
        ).scalars().all()
        assert work_items
        assert work_items[0].payload["expected_files"] == ["docs/pipeline-smoke-test.md"]


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


class ExhaustedHealingExecutor:
    name = "dummy"

    def __init__(self):
        self.test_attempts = 0

    async def execute(self, work_item, context):
        if work_item.type == "RUN_TESTS":
            self.test_attempts += 1
            return {
                "status": "FAILED",
                "message": "tests failed",
                "payload": {
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": f"test failed on attempt {self.test_attempts}",
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
            "payload": {"executor": "exhausted-healing"},
        }


class PassingExecutor:
    name = "dummy"

    async def execute(self, work_item, context):
        if work_item.type == "RUN_TESTS":
            return {
                "status": "DONE",
                "message": "tests passed",
                "payload": {
                    "exit_code": 0,
                    "stdout": "ok",
                    "stderr": "",
                },
            }
        return {
            "status": "DONE",
            "message": "ok",
            "payload": {"executor": "passing"},
        }


class PolicyBlockedExecutor:
    name = "dummy"

    async def execute(self, work_item, context):
        if work_item.type == "CODE_BACKEND":
            return {
                "status": "FAILED",
                "message": "human_review_required",
                "payload": {
                    "stop_reason": "human_review_required",
                    "next_action": "Obtain approval or reduce risk before attempting autonomous execution.",
                    "policy": {
                        "task_type": "implementation",
                        "risk_level": "high",
                        "requires_human_review": True,
                    },
                },
            }
        return {
            "status": "DONE",
            "message": "ok",
            "payload": {"executor": "policy-blocked"},
        }


class OptionalFailureExecutor:
    name = "dummy"

    async def execute(self, work_item, context):
        if work_item.type == "REVIEW_INTEGRATION":
            return {
                "status": "FAILED",
                "message": "optional integration review unavailable",
                "payload": {
                    "review_surface": "preview",
                    "reason": "preview_unavailable",
                },
            }
        return {
            "status": "DONE",
            "message": "ok",
            "payload": {"executor": "optional-failure"},
        }


class SkippingExecutor:
    name = "dummy"

    async def execute(self, work_item, context):
        if work_item.type == "RUN_TESTS":
            return {
                "status": "SKIPPED",
                "message": "No relevant tests were collected; validation skipped.",
                "payload": {
                    "skip_reason": "no_tests_collected",
                    "message": "No relevant tests were collected; validation skipped.",
                },
            }
        return {
            "status": "DONE",
            "message": "ok",
            "payload": {"executor": "skipping"},
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


@pytest.mark.anyio
async def test_embedded_runtime_allows_optional_review_failure_without_failing_run(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Optional failure runtime project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="QUEUED", executor="dummy")
        session.add(run)
        await session.commit()
        run_id = run.id

    monkeypatch.setattr(orchestrator_module, "build_executor", lambda *_args, **_kwargs: OptionalFailureExecutor())
    orchestrator = RunOrchestrator(runtime_db, executor_name="dummy")
    await orchestrator.bootstrap(run_id)

    async with runtime_db() as session:
        review_item = await session.scalar(
            select(WorkItem).where(WorkItem.run_id == run_id, WorkItem.type == "REVIEW_INTEGRATION")
        )
        assert review_item is not None
        review_item.payload = {**(review_item.payload or {}), "blocking": False}
        session.add(review_item)
        await session.commit()

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
        assert len(work_items) == 7

        review_item = next(wi for wi in work_items if wi.type == "REVIEW_INTEGRATION")
        assert review_item.status == "FAILED"
        assert review_item.payload["blocking"] is False
        assert review_item.result == {
            "review_surface": "preview",
            "reason": "preview_unavailable",
        }
        assert all(wi.status == "DONE" for wi in work_items if wi.type != "REVIEW_INTEGRATION")

        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        event_types = [event.event_type for event in events]
        assert "WORK_ITEM_FAILED" in event_types
        assert "WORK_ITEM_RECOVERY" not in event_types
        assert "WORK_ITEM_CANCELED" not in event_types
        assert "RUN_FAILED" not in event_types
        assert "RUN_COMPLETED" in event_types
        assert any(
            event.work_item_id == review_item.id
            and event.payload
            and event.payload.get("message") == "optional integration review unavailable"
            for event in events
            if event.event_type == "WORK_ITEM_FAILED"
        )


@pytest.mark.anyio
async def test_embedded_runtime_surfaces_policy_block_and_stops_cleanly(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Policy blocked runtime project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="QUEUED", executor="dummy")
        session.add(run)
        await session.commit()
        run_id = run.id

    monkeypatch.setattr(orchestrator_module, "build_executor", lambda *_args, **_kwargs: PolicyBlockedExecutor())
    orchestrator = RunOrchestrator(runtime_db, executor_name="dummy")
    await orchestrator.start(run_id)

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "FAILED"

        work_items = (
            await session.execute(
                select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.created_at, WorkItem.id)
            )
        ).scalars().all()
        assert len(work_items) == 7

        backend_item = next(wi for wi in work_items if wi.type == "CODE_BACKEND")
        frontend_item = next(wi for wi in work_items if wi.type == "CODE_FRONTEND")
        canceled_items = [wi for wi in work_items if wi.status == "CANCELED"]

        assert backend_item.status == "FAILED"
        assert backend_item.result == {
            "stop_reason": "human_review_required",
            "next_action": "Obtain approval or reduce risk before attempting autonomous execution.",
            "policy": {
                "task_type": "implementation",
                "risk_level": "high",
                "requires_human_review": True,
            },
        }
        assert frontend_item.status == "DONE"
        assert {wi.type for wi in canceled_items} == {"WRITE_TESTS", "REVIEW_DIFF", "RUN_TESTS", "REVIEW_INTEGRATION"}

        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        failed_events = [event for event in events if event.event_type == "WORK_ITEM_FAILED"]
        canceled_events = [event for event in events if event.event_type == "WORK_ITEM_CANCELED"]
        assert any(
            event.work_item_id == backend_item.id
            and event.payload
            and event.payload.get("message") == "human_review_required"
            for event in failed_events
        )
        assert len(canceled_events) == 4
        assert all(
            event.payload == {
                "work_item_id": str(event.work_item_id),
                "reason": "blocked_by_terminal_failure",
            }
            for event in canceled_events
        )
        event_types = [event.event_type for event in events]
        assert "WORK_ITEM_RECOVERY" not in event_types
        assert "RUN_FAILED" in event_types
        assert "RUN_COMPLETED" not in event_types


@pytest.mark.anyio
async def test_embedded_runtime_completes_cleanly_when_validation_passes(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Passing runtime project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="QUEUED", executor="dummy")
        session.add(run)
        await session.commit()
        run_id = run.id

    monkeypatch.setattr(orchestrator_module, "build_executor", lambda *_args, **_kwargs: PassingExecutor())
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
        assert len(work_items) == 7
        assert sum(1 for wi in work_items if wi.type == "FIX_TEST_FAILURE") == 0

        run_tests = next(wi for wi in work_items if wi.type == "RUN_TESTS")
        integration_review = next(wi for wi in work_items if wi.type == "REVIEW_INTEGRATION")
        assert run_tests.status == "DONE"
        assert run_tests.result["exit_code"] == 0
        assert integration_review.status == "DONE"
        assert all(wi.status == "DONE" for wi in work_items)

        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        event_types = [event.event_type for event in events]
        assert "WORK_ITEM_DONE" in event_types
        assert "WORK_ITEM_RECOVERY" not in event_types
        assert "WORK_ITEM_CANCELED" not in event_types
        assert "RUN_FAILED" not in event_types
        assert "RUN_COMPLETED" in event_types


@pytest.mark.anyio
async def test_embedded_runtime_fails_cleanly_after_exhausting_test_recovery(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("MAX_FIX_ATTEMPTS_PER_RUN", "1")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Exhausted healing runtime project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="QUEUED", executor="dummy")
        session.add(run)
        await session.commit()
        run_id = run.id

    exhausted_executor = ExhaustedHealingExecutor()
    monkeypatch.setattr(orchestrator_module, "build_executor", lambda *_args, **_kwargs: exhausted_executor)

    orchestrator = RunOrchestrator(runtime_db, executor_name="dummy")
    await orchestrator.start(run_id)

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "FAILED"

        work_items = (
            await session.execute(
                select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.created_at, WorkItem.id)
            )
        ).scalars().all()
        assert len(work_items) == 9
        assert sum(1 for wi in work_items if wi.type == "FIX_TEST_FAILURE") == 1
        assert sum(1 for wi in work_items if wi.type == "RUN_TESTS") == 2

        failed_tests = [wi for wi in work_items if wi.type == "RUN_TESTS" and wi.status == "FAILED"]
        assert len(failed_tests) == 2
        original_failed = next(wi for wi in failed_tests if wi.result.get("superseded") is True)
        retried_failed = next(wi for wi in failed_tests if wi.id != original_failed.id)
        fix_item = next(wi for wi in work_items if wi.type == "FIX_TEST_FAILURE")
        integration_review = next(wi for wi in work_items if wi.type == "REVIEW_INTEGRATION")

        assert original_failed.result["failure_class"] == "test_failure"
        assert original_failed.result["recovery_action"] == "spawn_fix_node"
        assert original_failed.result["superseded_by"] == str(retried_failed.id)
        assert retried_failed.result["failure_class"] == "test_failure"
        assert retried_failed.result["recovery_action"] == "spawn_fix_node"
        assert retried_failed.result.get("superseded") is not True
        assert fix_item.status == "DONE"
        assert fix_item.result["recovery_action"] == "spawn_retry_node"
        assert integration_review.status == "CANCELED"
        assert exhausted_executor.test_attempts == 2

        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        recovery_events = [event for event in events if event.event_type == "WORK_ITEM_RECOVERY"]
        canceled_events = [event for event in events if event.event_type == "WORK_ITEM_CANCELED"]
        assert len(recovery_events) == 2
        assert any(event.payload and event.payload.get("recovery_type") == "FIX_TEST_FAILURE" for event in recovery_events)
        assert any(event.payload and event.payload.get("recovery_type") == "RUN_TESTS" for event in recovery_events)
        assert len(canceled_events) == 1
        assert canceled_events[0].work_item_id == integration_review.id
        assert canceled_events[0].payload == {
            "work_item_id": str(integration_review.id),
            "reason": "blocked_by_terminal_failure",
        }
        assert any(event.event_type == "RUN_FAILED" for event in events)


@pytest.mark.anyio
async def test_embedded_runtime_treats_no_tests_collected_as_skipped(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Skipping runtime project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="QUEUED", executor="dummy")
        session.add(run)
        await session.commit()
        run_id = run.id

    monkeypatch.setattr(orchestrator_module, "build_executor", lambda *_args, **_kwargs: SkippingExecutor())
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
        run_tests = next(wi for wi in work_items if wi.type == "RUN_TESTS")
        assert run_tests.status == "SKIPPED"
        assert run_tests.result["skip_reason"] == "no_tests_collected"

        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        event_types = [event.event_type for event in events]
        assert "WORK_ITEM_SKIPPED" in event_types
        assert "WORK_ITEM_RECOVERY" not in event_types
        assert "RUN_COMPLETED" in event_types
