import asyncio
import contextlib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import Agent, Artifact, Project, ProjectBlueprint, ProjectGenesisRun, RecoveryMemoryProfile, Run, RunEvent, Task, Trace, WorkItem, WorkItemEdge
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.runtime import orchestrator as orchestrator_module
from app.runtime import scheduler_service as scheduler_module
from app.runtime.orchestrator import RunOrchestrator
from app.runtime.leases import keep_work_item_lease_alive
from app.runtime.scheduler_service import tick as scheduler_tick
from app.runtime import worker_service
from app.runtime.worker_service import tick_worker
from app.runtime.recovery_policy import classify_failure, maybe_apply_recovery, recovery_tier_for_failure
from app.runtime.runtime_recovery_service import RuntimeRecoveryService
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
        assert isinstance(run.summary.get("resume_checkpoints"), list)
        assert run.summary["resume_checkpoints"]
        assert isinstance(run.summary.get("resume_state"), dict)
        assert run.summary["resume_state"]["checkpoint_count"] >= 1

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
async def test_embedded_runtime_marks_run_completed_when_branch_publish_fails(monkeypatch, runtime_db, tmp_path):
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
        assert run.status == "COMPLETED"
        assert run.summary["remote_branch_push_error"] == "push failed"
        assert run.summary["delivery_manual_push_required"] is True

        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        event_types = [event.event_type for event in events]
        assert "RUN_BRANCH_PUSH_FAILED" in event_types
        assert "RUN_COMPLETED" in event_types
        assert "RUN_FAILED" not in event_types


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
            last_heartbeat_at=datetime.now(timezone.utc),
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
async def test_external_worker_respects_dependency_edges_before_claiming(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Dependency ordered worker project", tenant_id=tenant_id)
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
            last_heartbeat_at=datetime.now(timezone.utc),
        )
        session.add(agent)
        await session.flush()

        parent_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="RUN_TESTS",
            key="RUN_TESTS",
            status="QUEUED",
            priority=1,
            executor="dummy",
            required_capabilities=["runtime-worker"],
        )
        child_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="REVIEW_INTEGRATION",
            key="REVIEW_INTEGRATION",
            status="QUEUED",
            priority=10_000,
            executor="dummy",
            required_capabilities=["runtime-worker"],
            depends_on_count=1,
        )
        session.add_all([parent_item, child_item])
        await session.flush()
        session.add(
            WorkItemEdge(
                tenant_id=tenant_id,
                run_id=run.id,
                from_work_item_id=parent_item.id,
                to_work_item_id=child_item.id,
            )
        )
        await session.commit()
        agent_id = agent.id
        parent_item_id = parent_item.id
        child_item_id = child_item.id
        run_id = run.id

    await tick_worker(agent_id)

    async with runtime_db() as session:
        parent_item = await session.get(WorkItem, parent_item_id)
        child_item = await session.get(WorkItem, child_item_id)
        assert parent_item is not None
        assert child_item is not None
        assert parent_item.status == "DONE"
        assert child_item.status == "QUEUED"

        claimed_events = (
            await session.execute(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.event_type == "WORK_ITEM_CLAIMED")
                .order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        assert claimed_events
        assert claimed_events[0].work_item_id == parent_item_id

    await tick_worker(agent_id)

    async with runtime_db() as session:
        child_item = await session.get(WorkItem, child_item_id)
        assert child_item is not None
        assert child_item.status == "DONE"


@pytest.mark.anyio
async def test_recovery_retry_marks_pending_contract_state(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Recovery retry project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="dummy")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="RUN_TESTS",
            key="RUN_TESTS",
            status="FAILED",
            executor="test",
            attempt=0,
            max_attempts=3,
            result={"stderr": "network timeout"},
        )
        session.add(work_item)
        await session.commit()
        work_item_id = work_item.id

    async with runtime_db() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None

        recovery = await maybe_apply_recovery(session, work_item)
        await session.commit()

        assert recovery == {"action": "retry", "work_item_id": work_item_id}
        assert work_item.status == "QUEUED"
        assert work_item.result["retry_state"] == "PENDING"


@pytest.mark.anyio
async def test_recovery_retry_requeues_code_frontend_patch_apply_failure(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Frontend patch recovery project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="FAILED",
            executor="codex",
            attempt=0,
            max_attempts=3,
            last_error="Patch apply error: Patch check failed: error: patch failed: index.html:97 error: index.html: patch does not apply",
        )
        session.add(work_item)
        await session.commit()
        work_item_id = work_item.id

    async with runtime_db() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None

        recovery = await maybe_apply_recovery(session, work_item)
        await session.commit()

        assert recovery == {"action": "retry", "work_item_id": work_item_id}
        assert work_item.status == "QUEUED"
        assert work_item.attempt == 1
        assert work_item.result["failure_class"] == "patch_apply_failure"
        assert work_item.result["retry_state"] == "PENDING"
        assert work_item.payload["recovery_action"] == "retry_with_smaller_patch"
        assert work_item.payload["recovery_strategy"] == "minimal_patch_preferred"


@pytest.mark.anyio
async def test_recovery_retry_requeues_invalid_patch_repair_output_with_write_file_strategy(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Frontend contract-output recovery project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="FAILED",
            executor="codex",
            attempt=0,
            max_attempts=3,
            last_error="Action error: Patch repair output was invalid: Unterminated string starting at: line 9 column 18 (char 221)",
        )
        session.add(work_item)
        await session.commit()
        work_item_id = work_item.id

    async with runtime_db() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None

        recovery = await maybe_apply_recovery(session, work_item)
        await session.commit()

        assert recovery == {"action": "retry", "work_item_id": work_item_id}
        assert work_item.status == "QUEUED"
        assert work_item.attempt == 1
        assert work_item.result["failure_class"] == "output_contract_invalid"
        assert work_item.result["retry_state"] == "PENDING"
        assert work_item.payload["recovery_action"] == "retry_with_write_file"
        assert work_item.payload["recovery_strategy"] == "write_file_preferred"
        assert work_item.payload["recovery_reason"] == "patch_apply_failed"
        assert work_item.payload["strict_output_contract_mode"] is True
        assert work_item.payload["prior_output_contract_failures"] == 1


@pytest.mark.anyio
async def test_test_failure_recovery_scopes_fix_node_to_implementation_files(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Scoped recovery project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="RUN_TESTS",
            key="RUN_TESTS",
            status="FAILED",
            executor="test",
            attempt=0,
            max_attempts=3,
            payload={
                "target_files": ["test_index_html.py"],
                "files": ["test_index_html.py"],
                "expected_files": ["test_index_html.py"],
                "related_files": ["index.html"],
            },
            result={
                "exit_code": 1,
                "stdout": "FAILED test_index_html.py::test_hero_section_stands_out",
                "stderr": "",
            },
        )
        session.add(work_item)
        await session.commit()
        work_item_id = work_item.id
        run_id = run.id

    async with runtime_db() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None

        recovery = await maybe_apply_recovery(session, work_item)
        await session.commit()

        assert recovery is not None
        assert recovery["action"] == "spawn_fix_node"

        fix_item = (
            await session.execute(
                select(WorkItem).where(WorkItem.run_id == run_id, WorkItem.type == "FIX_TEST_FAILURE")
            )
        ).scalars().one()
        assert fix_item.payload["target_files"] == ["index.html"]
        assert fix_item.payload["files"] == ["index.html"]
        assert fix_item.payload["expected_files"] == ["index.html"]
        assert fix_item.payload["related_files"] == ["test_index_html.py"]
        assert fix_item.payload["failing_test_files"] == ["test_index_html.py"]
        assert fix_item.payload["failure_class"] == "test_assertion_failure"
        assert fix_item.payload["recovery_tier"] == "code_repair"


@pytest.mark.anyio
async def test_recovery_classifier_routes_pytest_collection_errors_to_code_repair(runtime_db):
    tenant_id = uuid.uuid4()
    async with runtime_db() as session:
        project = Project(name="Collection failure project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()
        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="RUN_TESTS",
            key="RUN_TESTS",
            status="FAILED",
            executor="test",
            payload={"target_files": ["test_index_html.py"], "related_files": ["index.html"]},
            result={
                "exit_code": 2,
                "stdout": (
                    "ERROR collecting test_index_html.py\n"
                    "NameError: name 'ProjectsSectionParser' is not defined"
                ),
                "stderr": "",
            },
        )
        session.add(work_item)
        await session.commit()
        work_item_id = work_item.id
        run_id = run.id

    async with runtime_db() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None

        failure_class = classify_failure(work_item)
        recovery = await maybe_apply_recovery(session, work_item)
        await session.commit()

        assert failure_class == "syntax_failure"
        assert recovery_tier_for_failure(failure_class) == "code_repair"
        assert recovery is not None
        fix_item = (
            await session.execute(
                select(WorkItem).where(WorkItem.run_id == run_id, WorkItem.type == "FIX_TEST_FAILURE")
            )
        ).scalars().one()
        assert fix_item.payload["failure_class"] == "syntax_failure"
        assert fix_item.payload["recovery_tier"] == "code_repair"


@pytest.mark.anyio
async def test_fix_recovery_retry_reuses_failed_run_tests_scope(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Scoped test retry project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        failed_test = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="RUN_TESTS",
            key="RUN_TESTS",
            status="FAILED",
            executor="test",
            payload={
                "target_files": ["test_index_html.py"],
                "files": ["test_index_html.py"],
                "expected_files": ["test_index_html.py"],
                "related_files": ["index.html"],
                "title": "Validate Hero section enhancement",
            },
            result={"exit_code": 1, "stdout": "FAILED test_index_html.py::test_hero", "stderr": ""},
        )
        session.add(failed_test)
        await session.flush()

        fix_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="FIX_TEST_FAILURE",
            key="FIX_TEST_FAILURE_1",
            status="DONE",
            executor="codex",
            payload={
                "target_files": ["index.html"],
                "related_files": ["test_index_html.py"],
            },
            result={"message": "fix applied"},
        )
        session.add(fix_item)
        await session.commit()
        failed_test_id = failed_test.id
        fix_item_id = fix_item.id
        run_id = run.id

    async with runtime_db() as session:
        fix_item = await session.get(WorkItem, fix_item_id)
        assert fix_item is not None

        recovery = await maybe_apply_recovery(session, fix_item)
        await session.commit()

        assert recovery is not None
        assert recovery["action"] == "spawn_retry_node"

        retried_test = (
            await session.execute(
                select(WorkItem).where(
                    WorkItem.run_id == run_id,
                    WorkItem.type == "RUN_TESTS",
                    WorkItem.id != failed_test_id,
                )
            )
        ).scalars().one()
        assert retried_test.payload["target_files"] == ["test_index_html.py"]
        assert retried_test.payload["files"] == ["test_index_html.py"]
        assert retried_test.payload["expected_files"] == ["test_index_html.py"]
        assert retried_test.payload["related_files"] == ["index.html"]
        assert retried_test.payload["recovery_source_id"] == str(fix_item_id)
        assert retried_test.payload["recovery_action"] == "spawn_retry_node"


@pytest.mark.anyio
async def test_recovery_memory_emits_miss_event(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_RECOVERY_MEMORY_ENABLED", "true")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Recovery memory miss project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()
        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="FAILED",
            executor="codex",
            attempt=0,
            max_attempts=2,
            last_error="Patch apply failed at index.html",
        )
        session.add(work_item)
        await session.commit()
        work_item_id = work_item.id
        run_id = run.id

    async with runtime_db() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        recovery = await maybe_apply_recovery(session, work_item)
        await session.commit()
        assert recovery == {"action": "retry", "work_item_id": work_item_id}

        events = (
            await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
        ).scalars().all()
        assert any(event.event_type == "RECOVERY_MEMORY_MISS" for event in events)


@pytest.mark.anyio
async def test_recovery_memory_can_override_action_when_confident(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_RECOVERY_MEMORY_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_RECOVERY_MEMORY_MIN_SAMPLES", "2")
    monkeypatch.setenv("RUNTIME_RECOVERY_MEMORY_MIN_SUCCESS_RATE", "0.8")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Recovery memory override project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="test")
        session.add(run)
        await session.flush()
        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="RUN_TESTS",
            key="RUN_TESTS",
            status="FAILED",
            executor="test",
            attempt=0,
            max_attempts=2,
            result={"stderr": "network timeout"},
        )
        session.add(work_item)
        await session.flush()
        signature = RuntimeRecoveryService(session).build_failure_signature(work_item, "unknown")
        session.add(
            RecoveryMemoryProfile(
                tenant_id=tenant_id,
                project_id=project.id,
                failure_signature=signature,
                failure_type="unknown",
                recovery_action="requeue_work_item",
                total_attempts=5,
                success_count=5,
                failure_count=0,
                success_rate=1.0,
                average_recovery_attempts=1.2,
            )
        )
        await session.commit()
        work_item_id = work_item.id
        run_id = run.id

    async with runtime_db() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        recovery = await maybe_apply_recovery(session, work_item)
        await session.commit()
        assert recovery == {"action": "retry", "work_item_id": work_item_id}

        events = (
            await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
        ).scalars().all()
        assert any(event.event_type == "RECOVERY_MEMORY_MATCHED" for event in events)
        assert any(event.event_type == "RECOVERY_POLICY_OVERRIDDEN_BY_MEMORY" for event in events)


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
            last_heartbeat_at=datetime.now(timezone.utc),
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
async def test_scheduler_does_not_complete_run_before_work_items_exist(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Bootstrap race project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(
            project_id=project.id,
            tenant_id=tenant_id,
            status="RUNNING",
            executor="codex",
            started_at=datetime.now(timezone.utc),
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "RUNNING"
        assert run.finished_at is None

        event_types = [
            event.event_type
            for event in (
                await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
            ).scalars().all()
        ]
        assert "RUN_COMPLETED" not in event_types


@pytest.mark.anyio
async def test_external_scheduler_fails_run_when_only_blocked_work_items_remain(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Blocked queue scheduler project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        failed_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="WRITE_TESTS",
            key="WRITE_TESTS",
            status="FAILED",
            priority=10,
            executor="codex",
            result={"message": "generated test parser is invalid"},
        )
        blocked_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="RUN_TESTS",
            key="RUN_TESTS",
            status="QUEUED",
            priority=9,
            executor="test",
            depends_on_count=1,
        )
        session.add_all([failed_item, blocked_item])
        await session.flush()
        session.add(
            WorkItemEdge(
                tenant_id=tenant_id,
                run_id=run.id,
                from_work_item_id=failed_item.id,
                to_work_item_id=blocked_item.id,
            )
        )
        await session.commit()
        run_id = run.id
        blocked_item_id = blocked_item.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        blocked_item = await session.get(WorkItem, blocked_item_id)
        assert run is not None
        assert blocked_item is not None
        assert run.status == "FAILED"
        assert blocked_item.status == "CANCELED"

        canceled_events = (
            await session.execute(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.event_type == "WORK_ITEM_CANCELED")
                .order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        assert canceled_events
        assert canceled_events[0].work_item_id == blocked_item_id
        assert canceled_events[0].payload == {
            "work_item_id": str(blocked_item_id),
            "reason": "blocked_by_terminal_failure",
        }
        assert any(
            event.event_type == "RUN_FAILED"
            for event in (
                await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
            ).scalars().all()
        )


@pytest.mark.anyio
async def test_external_worker_treats_optional_write_tests_failure_as_satisfied_dependency(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async def _fake_execute_item(session, wi, _agent):
        wi.status = "DONE"
        wi.finished_at = datetime.now(timezone.utc)
        session.add(wi)

    monkeypatch.setattr(worker_service, "execute_item", _fake_execute_item)

    async with runtime_db() as session:
        project = Project(name="Optional failed write-tests dependency project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="test")
        session.add(run)
        await session.flush()

        agent = Agent(
            tenant_id=tenant_id,
            name="runtime-worker",
            kind="worker",
            executors=["test", "codex"],
            capabilities=["test", "review"],
            max_concurrency=1,
            status="ACTIVE",
            last_heartbeat_at=datetime.now(timezone.utc),
        )
        session.add(agent)
        await session.flush()

        write_tests = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="WRITE_TESTS",
            key="WRITE_TESTS",
            status="FAILED",
            priority=8,
            executor="codex",
            payload={"blocking": False},
        )
        review_diff = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="REVIEW_DIFF",
            key="REVIEW_DIFF",
            status="DONE",
            priority=7,
            executor="codex",
        )
        run_tests = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="RUN_TESTS",
            key="RUN_TESTS",
            status="QUEUED",
            priority=6,
            executor="test",
            depends_on_count=1,
            required_capabilities=["test"],
        )
        session.add_all([write_tests, review_diff, run_tests])
        await session.flush()
        session.add_all(
            [
                WorkItemEdge(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    from_work_item_id=write_tests.id,
                    to_work_item_id=review_diff.id,
                ),
                WorkItemEdge(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    from_work_item_id=review_diff.id,
                    to_work_item_id=run_tests.id,
                ),
            ]
        )
        await session.commit()
        agent_id = agent.id
        run_id = run.id
        run_tests_id = run_tests.id

    await tick_worker(agent_id)

    async with runtime_db() as session:
        run_tests = await session.get(WorkItem, run_tests_id)
        assert run_tests is not None
        assert run_tests.status == "DONE"

        events = (
            await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
        ).scalars().all()
        assert any(event.event_type == "WORK_ITEM_CLAIMED" and event.work_item_id == run_tests_id for event in events)


@pytest.mark.anyio
async def test_external_scheduler_terminalizes_stalled_run_after_90_seconds_without_progress(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "false")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    monkeypatch.setattr(scheduler_module, "STALL_TIMEOUT_SECONDS", 90)
    monkeypatch.setattr(scheduler_module, "STALL_RECOVERY_MAX_ATTEMPTS", 2)

    stale_anchor = datetime.now(timezone.utc) - timedelta(seconds=95)

    async def _stale_progress_ts(_session, _run):
        return stale_anchor

    monkeypatch.setattr(scheduler_module, "_latest_progress_ts", _stale_progress_ts)

    async with runtime_db() as session:
        project = Project(name="Stalled run terminalization project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        agent = Agent(
            tenant_id=tenant_id,
            name="runtime-worker",
            kind="worker",
            executors=["dummy"],
            capabilities=[],
            max_concurrency=1,
            status="ACTIVE",
            last_heartbeat_at=datetime.now(timezone.utc),
        )
        session.add(agent)
        await session.flush()

        queued_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="RUN_TESTS",
            key="RUN_TESTS",
            status="QUEUED",
            priority=6,
            executor="test",
            depends_on_count=0,
            required_capabilities=["test"],
        )
        session.add(queued_item)
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()
        mid = await session.get(Run, run_id)
        assert mid is not None
        assert mid.status in {"RUNNING", "QUEUED"}

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()
        mid = await session.get(Run, run_id)
        assert mid is not None
        assert mid.status in {"RUNNING", "QUEUED"}

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "FAILED"
        assert run.finished_at is not None

        events = (
            await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
        ).scalars().all()
        assert any(event.event_type == "RUN_STALLED" for event in events)
        assert sum(1 for event in events if event.event_type == "RUN_STALL_RECOVERY_ATTEMPT") >= 2
        assert any(
            event.event_type == "RUN_FAILED" and (event.payload or {}).get("reason") == "stalled_no_progress"
            for event in events
        )


@pytest.mark.anyio
async def test_external_scheduler_does_not_mark_terminal_failure_as_stall(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "false")
    monkeypatch.setenv("RUNTIME_GOAL_ORCHESTRATION_ENABLED", "false")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    monkeypatch.setattr(scheduler_module, "STALL_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(scheduler_module, "STALL_RECOVERY_MAX_ATTEMPTS", 1)

    stale_anchor = datetime.now(timezone.utc) - timedelta(seconds=120)

    async def _stale_progress_ts(_session, _run):
        return stale_anchor

    monkeypatch.setattr(scheduler_module, "_latest_progress_ts", _stale_progress_ts)

    async with runtime_db() as session:
        project = Project(name="Terminal failure should not stall project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        failed_frontend = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="FAILED",
            priority=10,
            executor="codex",
            last_error="AI policy halted execution: output_contract_invalid",
            result={"error": "AI policy halted execution: output_contract_invalid"},
        )
        blocked_tests = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="RUN_TESTS",
            key="RUN_TESTS",
            status="QUEUED",
            priority=5,
            executor="test",
            depends_on_count=1,
        )
        session.add_all([failed_frontend, blocked_tests])
        await session.flush()
        session.add(
            WorkItemEdge(
                tenant_id=tenant_id,
                run_id=run.id,
                from_work_item_id=failed_frontend.id,
                to_work_item_id=blocked_tests.id,
            )
        )
        await session.commit()
        run_id = run.id
        blocked_id = blocked_tests.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        blocked = await session.get(WorkItem, blocked_id)
        assert run is not None
        assert blocked is not None
        assert run.status == "FAILED"
        assert blocked.status == "CANCELED"

        events = (
            await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
        ).scalars().all()
        event_types = [event.event_type for event in events]
        assert "RUN_STALLED" not in event_types
        assert "RUN_STALL_RECOVERY_ATTEMPT" not in event_types
        assert any(event.event_type == "RUN_FAILED" for event in events)


@pytest.mark.anyio
async def test_external_scheduler_publishes_branch_on_completion(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("RUN_AUTO_PUSH_BRANCH_ON_COMPLETION", "true")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()
    published: dict[str, str] = {}

    async def _publish(_session, *, run, actor_type="SYSTEM", actor_id=None):
        summary = dict(run.summary or {})
        summary.update(
            {
                "remote_branch_pushed": True,
                "remote_branch_name": run.branch_name,
                "remote_branch_commit_sha": "abc1234",
            }
        )
        run.summary = summary
        published["run_id"] = str(run.id)
        return {
            "branch_name": run.branch_name,
            "commit_sha": "abc1234",
            "created_commit": True,
        }

    monkeypatch.setattr(scheduler_module, "publish_run_branch_if_ready", _publish)

    async with runtime_db() as session:
        project = Project(name="External publish success project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(
            project_id=project.id,
            tenant_id=tenant_id,
            status="RUNNING",
            executor="codex",
            workspace_status="SEEDED",
            workspace_root="/tmp/run-workspace",
            repo_path="/tmp/run-workspace/repo",
            branch_name="run/publish-success",
        )
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="DONE",
            priority=10_000,
            executor="codex",
        )
        session.add(work_item)
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "COMPLETED"
        assert run.summary["remote_branch_pushed"] is True
        assert run.summary["remote_branch_name"] == "run/publish-success"
        assert published["run_id"] == str(run_id)

        event_types = [
            event.event_type
            for event in (
                await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
            ).scalars().all()
        ]
        assert "RUN_COMPLETED" in event_types
        assert "RUN_BRANCH_PUSH_FAILED" not in event_types


@pytest.mark.anyio
async def test_external_scheduler_marks_run_completed_when_branch_publish_fails(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("RUN_AUTO_PUSH_BRANCH_ON_COMPLETION", "true")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async def _fail_publish(*_args, **_kwargs):
        raise RuntimeError("push failed")

    monkeypatch.setattr(scheduler_module, "publish_run_branch_if_ready", _fail_publish)

    async with runtime_db() as session:
        project = Project(name="External publish failure project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(
            project_id=project.id,
            tenant_id=tenant_id,
            status="RUNNING",
            executor="codex",
            workspace_status="SEEDED",
            workspace_root="/tmp/run-workspace",
            repo_path="/tmp/run-workspace/repo",
            branch_name="run/publish-fail",
        )
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="DONE",
            priority=10_000,
            executor="codex",
        )
        session.add(work_item)
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "COMPLETED"
        assert run.summary["remote_branch_push_error"] == "push failed"
        assert run.summary["delivery_manual_push_required"] is True

        event_types = [
            event.event_type
            for event in (
                await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
            ).scalars().all()
        ]
        assert "RUN_BRANCH_PUSH_FAILED" in event_types
        assert "RUN_FAILED" not in event_types
        assert "RUN_COMPLETED" in event_types


@pytest.mark.anyio
async def test_external_orchestrator_waits_for_recovery_queue_before_terminal_failure(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="External recovery wait project", tenant_id=tenant_id)
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
            last_heartbeat_at=datetime.now(timezone.utc),
        )
        session.add(agent)
        await session.flush()

        failed_test = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="RUN_TESTS",
            key="RUN_TESTS",
            status="FAILED",
            executor="test",
            payload={"blocking": True},
            result={"failure_class": "test_failure", "recovery_action": "spawn_fix_node"},
        )
        fix_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="FIX_TEST_FAILURE",
            key="FIX_TEST_FAILURE",
            status="QUEUED",
            executor="dummy",
            payload={"recovery_source_id": "seeded"},
        )
        session.add_all([failed_test, fix_item])
        await session.flush()

        session.add(
            WorkItemEdge(
                tenant_id=tenant_id,
                run_id=run.id,
                from_work_item_id=failed_test.id,
                to_work_item_id=fix_item.id,
            )
        )
        await session.commit()
        run_id = run.id

    orchestrator = RunOrchestrator(runtime_db, executor_name="dummy")
    task = asyncio.create_task(orchestrator.start(run_id))
    try:
        await asyncio.sleep(0.6)
        assert task.done() is False

        async with runtime_db() as session:
            run = await session.get(Run, run_id)
            assert run is not None
            assert run.status == "RUNNING"
            assert run.finished_at is None
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def test_classify_failure_treats_run_test_assertion_not_found_as_test_failure():
    work_item = WorkItem(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        type="RUN_TESTS",
        status="FAILED",
        executor="test",
        result={"stdout": "AssertionError: Theme color <meta> tag not found."},
    )

    assert classify_failure(work_item) == "test_failure"


def test_classify_failure_routes_patch_apply_error_to_patch_apply_failure():
    work_item = WorkItem(
        type="CODE_FRONTEND",
        status="FAILED",
        key="CODE_FRONTEND",
        last_error="Patch apply error: Patch check failed: error: patch failed: index.html:97",
    )
    assert classify_failure(work_item) == "patch_apply_failure"


def test_classify_failure_routes_invalid_patch_repair_output_to_output_contract_invalid():
    work_item = WorkItem(
        type="CODE_FRONTEND",
        status="FAILED",
        key="CODE_FRONTEND",
        last_error="Action error: Patch repair output was invalid: Unterminated string starting at: line 9 column 18 (char 221)",
    )
    assert classify_failure(work_item) == "output_contract_invalid"


@pytest.mark.anyio
async def test_scheduler_degrades_terminal_failure_when_never_fail_enabled(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Never fail scheduler project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        failed_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="FAILED",
            priority=10,
            executor="codex",
            payload={"blocking": True},
            result={"message": "terminal failure"},
        )
        session.add(failed_item)
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "COMPLETED"
        assert isinstance(run.summary, dict)
        assert run.summary.get("degraded_completion") is True
        assert run.summary.get("degraded_reason") == "goal_concluded_unresolvable"

        event_types = [
            event.event_type
            for event in (
                await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
            ).scalars().all()
        ]
        assert "RUN_DEGRADED" in event_types
        assert "RUN_COMPLETED" in event_types


@pytest.mark.anyio
async def test_scheduler_spawns_goal_recovery_retry_before_conclusion(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "true")
    monkeypatch.setenv("RUNTIME_GOAL_ORCHESTRATION_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_GOAL_MAX_RECOVERY_CYCLES", "3")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Goal recovery scheduler project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        failed_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="FAILED",
            priority=10,
            executor="codex",
            payload={"blocking": True},
            result={"message": "terminal failure"},
        )
        session.add(failed_item)
        await session.commit()
        run_id = run.id
        failed_item_id = failed_item.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "RUNNING"
        assert isinstance(run.summary, dict)
        assert run.summary.get("goal_state") == "RECOVERING"
        assert run.summary.get("goal_recovery_cycles") == 1
        superseded = await session.get(WorkItem, failed_item_id)
        assert superseded is not None
        assert superseded.result.get("superseded") is True
        recovery_items = (
            await session.execute(
                select(WorkItem).where(
                    WorkItem.run_id == run_id,
                    WorkItem.status == "QUEUED",
                    WorkItem.id != failed_item_id,
                )
            )
        ).scalars().all()
        assert recovery_items
        assert recovery_items[0].payload.get("recovery_action") == "goal_recovery_retry"


@pytest.mark.anyio
async def test_scheduler_goal_recovery_adapts_output_contract_invalid_frontend(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "true")
    monkeypatch.setenv("RUNTIME_GOAL_ORCHESTRATION_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_GOAL_MAX_RECOVERY_CYCLES", "3")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Output contract recovery project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        failed_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="FAILED",
            priority=10,
            executor="codex",
            payload={"blocking": True},
            result={"failure_class": "output_contract_invalid"},
            last_error="AI policy halted execution: output_contract_invalid",
        )
        session.add(failed_item)
        await session.commit()
        run_id = run.id
        failed_item_id = failed_item.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        recovery_items = (
            await session.execute(
                select(WorkItem).where(
                    WorkItem.run_id == run_id,
                    WorkItem.status == "QUEUED",
                    WorkItem.id != failed_item_id,
                )
            )
        ).scalars().all()
        assert recovery_items
        payload = recovery_items[0].payload or {}
        assert payload.get("recovery_strategy") == "write_file_preferred"
        assert payload.get("strict_output_contract_mode") is True
        assert payload.get("prior_output_contract_failures") == 1
        assert payload.get("recovery_action") == "retry_with_write_file"


@pytest.mark.anyio
async def test_scheduler_goal_recovery_does_not_loop_after_adaptive_output_contract_retry(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "true")
    monkeypatch.setenv("RUNTIME_GOAL_ORCHESTRATION_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_GOAL_MAX_RECOVERY_CYCLES", "3")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="No loop recovery project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        failed_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND_RECOVERY_1",
            status="FAILED",
            priority=10,
            executor="codex",
            payload={
                "blocking": True,
                "recovery_strategy": "write_file_preferred",
                "strict_output_contract_mode": True,
            },
            result={"failure_class": "output_contract_invalid"},
            last_error="AI policy halted execution: output_contract_invalid",
        )
        session.add(failed_item)
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        queued_frontend = (
            await session.execute(
                select(WorkItem).where(
                    WorkItem.run_id == run_id,
                    WorkItem.status == "QUEUED",
                    WorkItem.type == "CODE_FRONTEND",
                )
            )
        ).scalars().all()
        assert not queued_frontend

@pytest.mark.anyio
async def test_scheduler_patch_too_large_spawns_recovery_before_pause(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "true")
    monkeypatch.setenv("RUNTIME_GOAL_ORCHESTRATION_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_GOAL_MAX_RECOVERY_CYCLES", "3")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Patch too large recovery project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        failed_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_BACKEND",
            key="CODE_BACKEND",
            status="FAILED",
            priority=10,
            executor="codex",
            payload={"blocking": True, "target_files": ["app.py"]},
            result={"message": "Patch too large for app.py (>40% change)"},
        )
        session.add(failed_item)
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "RUNNING"
        recovery_items = (
            await session.execute(
                select(WorkItem).where(
                    WorkItem.run_id == run_id,
                    WorkItem.status == "QUEUED",
                    WorkItem.type == "CODE_BACKEND",
                )
            )
        ).scalars().all()
        assert recovery_items
        assert recovery_items[0].payload.get("recovery_action") == "goal_recovery_retry"


@pytest.mark.anyio
async def test_scheduler_pauses_when_patch_too_large_repeats_after_recovery(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "true")
    monkeypatch.setenv("RUNTIME_GOAL_ORCHESTRATION_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_GOAL_MAX_RECOVERY_CYCLES", "3")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Patch too large pause project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        failed_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_BACKEND",
            key="CODE_BACKEND_RECOVERY_1",
            status="FAILED",
            priority=10,
            executor="codex",
            payload={
                "blocking": True,
                "target_files": ["app.py"],
                "recovery_action": "goal_recovery_retry",
                "recovery_strategy": "write_file_preferred",
            },
            result={"message": "Patch too large for app.py (>40% change)"},
        )
        session.add(failed_item)
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "PAUSED"
        assert isinstance(run.summary, dict)
        pause = run.summary.get("patch_scope_pause")
        assert isinstance(pause, dict)
        assert pause.get("reason") == "patch_scope_too_large_requires_decomposition"
        event_types = [
            event.event_type
            for event in (
                await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
            ).scalars().all()
        ]
        assert "RUN_DECOMPOSITION_REQUIRED" in event_types


@pytest.mark.anyio
async def test_scheduler_bootstrap_mode_does_not_pause_patch_too_large(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "true")
    monkeypatch.setenv("RUNTIME_GOAL_ORCHESTRATION_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_GOAL_MAX_RECOVERY_CYCLES", "3")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Bootstrap patch-too-large project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(
            project_id=project.id,
            tenant_id=tenant_id,
            status="RUNNING",
            executor="codex",
            summary={"repository_state": "GENESIS", "task_source": "genesis"},
        )
        session.add(run)
        await session.flush()

        failed_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_BACKEND",
            key="CODE_BACKEND_RECOVERY_1",
            status="FAILED",
            priority=10,
            executor="codex",
            payload={"blocking": True, "recovery_action": "goal_recovery_retry"},
            result={"message": "Patch too large for app.py (>40% change)"},
        )
        session.add(failed_item)
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "RUNNING"
        assert isinstance(run.summary, dict)
        assert run.summary.get("patch_scope_pause") is None


@pytest.mark.anyio
async def test_scheduler_replays_validation_after_successful_recovery(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Validation replay scheduler project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        session.add(
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=run.id,
                type="CODE_FRONTEND",
                key="CODE_FRONTEND",
                status="DONE",
                priority=10,
                executor="codex",
                payload={"files": ["index.html"]},
            )
        )
        session.add(
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=run.id,
                type="CODE_BACKEND",
                key="CODE_BACKEND_RECOVERY_1",
                status="DONE",
                priority=10,
                executor="codex",
                payload={
                    "files": ["app.py"],
                    "recovery_action": "goal_recovery_retry",
                    "recovery_source_id": str(uuid.uuid4()),
                },
            )
        )
        for stage_type, stage_key, stage_executor in (
            ("WRITE_TESTS", "WRITE_TESTS", "test"),
            ("RUN_TESTS", "RUN_TESTS", "test"),
            ("REVIEW_DIFF", "REVIEW_DIFF", "review"),
            ("REVIEW_INTEGRATION", "REVIEW_INTEGRATION", "review"),
        ):
            session.add(
                WorkItem(
                    project_id=project.id,
                    tenant_id=tenant_id,
                    run_id=run.id,
                    type=stage_type,
                    key=stage_key,
                    status="CANCELED",
                    priority=8,
                    executor=stage_executor,
                    payload={"files": ["index.html", "app.py"]},
                )
            )
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "RUNNING"
        assert isinstance(run.summary, dict)
        replay = run.summary.get("validation_replay")
        assert isinstance(replay, dict)
        assert replay.get("reason") == "recovery_completed_before_validation"

        replay_items = (
            await session.execute(
                select(WorkItem).where(WorkItem.run_id == run_id, WorkItem.status == "QUEUED").order_by(WorkItem.created_at.asc())
            )
        ).scalars().all()
        replay_types = [item.type for item in replay_items]
        assert replay_types == ["WRITE_TESTS", "RUN_TESTS", "REVIEW_DIFF", "REVIEW_INTEGRATION"]
        for item in replay_items:
            assert item.payload.get("recovery_action") == "replay_validation_after_recovery"

        events = (
            await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
        ).scalars().all()
        event_types = [event.event_type for event in events]
        assert "RUN_VALIDATION_REPLAY_QUEUED" in event_types
        assert "RUN_COMPLETED" not in event_types


@pytest.mark.anyio
async def test_scheduler_replay_validation_is_idempotent_per_recovery_source(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Validation replay idempotency project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        recovery_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND_RECOVERY_1",
            status="DONE",
            priority=10,
            executor="codex",
            payload={
                "files": ["index.html"],
                "recovery_action": "goal_recovery_retry",
            },
        )
        session.add(recovery_item)
        await session.flush()
        recovery_item_id = recovery_item.id

        for stage_type, stage_key, stage_executor in (
            ("WRITE_TESTS", "WRITE_TESTS", "test"),
            ("RUN_TESTS", "RUN_TESTS", "test"),
            ("REVIEW_DIFF", "REVIEW_DIFF", "review"),
            ("REVIEW_INTEGRATION", "REVIEW_INTEGRATION", "review"),
        ):
            session.add(
                WorkItem(
                    project_id=project.id,
                    tenant_id=tenant_id,
                    run_id=run.id,
                    type=stage_type,
                    key=stage_key,
                    status="CANCELED",
                    priority=8,
                    executor=stage_executor,
                    payload={"files": ["index.html"]},
                )
            )
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        first_replays = (
            await session.execute(
                select(WorkItem).where(
                    WorkItem.run_id == run_id,
                    WorkItem.status == "QUEUED",
                    WorkItem.key.like("%_REPLAY_%"),
                )
            )
        ).scalars().all()
        assert len(first_replays) == 4
        for replay in first_replays:
            replay.status = "DONE"
            session.add(replay)
        await session.commit()

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        replay_count = (
            await session.execute(
                select(func.count()).where(
                    WorkItem.run_id == run_id,
                    WorkItem.key.like("%_REPLAY_%"),
                )
            )
        ).scalar_one()
        assert replay_count == 4
        run = await session.get(Run, run_id)
        assert run is not None
        assert isinstance(run.summary, dict)
        replay_sources = run.summary.get("validation_replay_sources")
        assert isinstance(replay_sources, list)
        assert str(recovery_item_id) in replay_sources


@pytest.mark.anyio
async def test_scheduler_marks_linked_task_done_when_run_completes(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Task completion sync project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        task = Task(
            tenant_id=tenant_id,
            project_id=project.id,
            title="initialize monorepo",
            category="func",
            stage="RUN",
            status="PENDING",
            source="manual",
            source_type="manual",
        )
        session.add(task)
        await session.flush()

        run = Run(
            project_id=project.id,
            tenant_id=tenant_id,
            status="RUNNING",
            executor="codex",
            summary={"task_id": str(task.id)},
        )
        session.add(run)
        await session.flush()

        task.run_id = run.id
        session.add(task)
        session.add(
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=run.id,
                type="PLAN_DAG",
                key="PLAN_DAG",
                status="DONE",
                priority=10,
                executor="codex",
                payload={"task_id": str(task.id)},
                result={"status": "DONE"},
            )
        )
        await session.commit()
        run_id = run.id
        task_id = task.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        task = await session.get(Task, task_id)
        assert run is not None
        assert task is not None
        assert run.status == "COMPLETED"
        assert task.status == "DONE"
        assert task.finished_at is not None


@pytest.mark.anyio
async def test_scheduler_does_not_spawn_goal_recovery_retry_for_insufficient_quota(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "false")
    monkeypatch.setenv("RUNTIME_GOAL_ORCHESTRATION_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_GOAL_MAX_RECOVERY_CYCLES", "3")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Quota fast-fail project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        failed_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="PLAN_DAG",
            key="PLAN_DAG",
            status="FAILED",
            priority=10,
            executor="codex",
            payload={"blocking": True},
            result={
                "error_kind": "model_error",
                "error_message": "Error code: 429 ... insufficient_quota ... exceeded your current quota",
            },
        )
        session.add(failed_item)
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "FAILED"

        items = (
            await session.execute(select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.created_at.asc()))
        ).scalars().all()
        assert len(items) == 1
        assert items[0].key == "PLAN_DAG"
        assert items[0].status == "FAILED"

        event_types = [
            event.event_type
            for event in (
                await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
            ).scalars().all()
        ]
        assert "WORK_ITEM_RECOVERY" not in event_types


@pytest.mark.anyio
async def test_scheduler_pauses_run_for_operator_confirmation_required(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "false")
    monkeypatch.setenv("RUNTIME_GOAL_ORCHESTRATION_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_GOAL_MAX_RECOVERY_CYCLES", "3")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Operator confirmation pause project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        failed_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="FAILED",
            priority=10,
            executor="codex",
            payload={"blocking": True},
            result={"message": "Patch execution requires operator confirmation before mutating the repository."},
            last_error="Patch execution requires operator confirmation before mutating the repository.",
        )
        session.add(failed_item)
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "PAUSED"
        assert isinstance(run.summary, dict)
        assert run.summary.get("goal_state") == "NEEDS_HUMAN_INPUT"
        pause_meta = run.summary.get("operator_confirmation_pause")
        assert isinstance(pause_meta, dict)
        assert pause_meta.get("reason") == "operator_confirmation_required"

        items = (
            await session.execute(select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.created_at.asc()))
        ).scalars().all()
        assert len(items) == 1
        assert items[0].status == "FAILED"

        events = (
            await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
        ).scalars().all()
        event_types = [event.event_type for event in events]
        assert "RUN_OPERATOR_ACTION_REQUIRED" in event_types
        assert "WORK_ITEM_RECOVERY" not in event_types
        assert "WORK_ITEM_CREATED" not in event_types


@pytest.mark.anyio
async def test_scheduler_bootstrap_mode_retries_operator_confirmation_instead_of_pause(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "true")
    monkeypatch.setenv("RUNTIME_GOAL_ORCHESTRATION_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Bootstrap operator confirmation project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(
            project_id=project.id,
            tenant_id=tenant_id,
            status="RUNNING",
            executor="codex",
            summary={"repository_state": "GENESIS", "task_source": "genesis"},
        )
        session.add(run)
        await session.flush()

        failed_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="FAILED",
            priority=10,
            executor="codex",
            payload={"blocking": True},
            result={"message": "Patch execution requires operator confirmation before mutating the repository."},
            last_error="Patch execution requires operator confirmation before mutating the repository.",
        )
        session.add(failed_item)
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "RUNNING"
        items = (
            await session.execute(select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.created_at.asc()))
        ).scalars().all()
        queued_recovery = [item for item in items if item.status == "QUEUED" and item.type == "CODE_FRONTEND"]
        assert queued_recovery
        assert queued_recovery[0].payload.get("recovery_action") == "goal_recovery_retry"
        assert queued_recovery[0].payload.get("recovery_strategy") == "write_file_preferred"


@pytest.mark.anyio
async def test_scheduler_auto_decomposes_operator_confirmation_for_medium_scope(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "false")
    monkeypatch.setenv("RUNTIME_GOAL_ORCHESTRATION_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    scoped_files = [
        "apps/web/src/views/MissionControl.vue",
        "apps/web/src/components/ExecutionTimeline.vue",
        "apps/web/src/components/AuditTimeline.vue",
        "apps/web/src/views/AiOpsDashboard.vue",
        "apps/web/src/views/AgentRuns.vue",
        "apps/web/src/views/SdlcTimeline.vue",
        "apps/web/src/api/aiOps.ts",
        "apps/web/src/views/ProjectOverview.vue",
    ]

    async with runtime_db() as session:
        project = Project(name="Operator confirmation decomposition project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        failed_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="FAILED",
            priority=10,
            executor="codex",
            payload={"blocking": True, "files": scoped_files},
            result={
                "message": "Patch execution requires operator confirmation before mutating the repository.",
                "payload": {
                    "verification": {
                        "status": "REQUIRES_CONFIRMATION",
                        "requires_confirmation": True,
                        "risk_level": "MEDIUM",
                        "file_count": len(scoped_files),
                        "verified_files": scoped_files,
                        "scope_match": True,
                    }
                },
            },
            last_error="Patch execution requires operator confirmation before mutating the repository.",
        )
        session.add(failed_item)
        session.add(
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=run.id,
                type="RUN_TESTS",
                key="RUN_TESTS",
                status="CANCELED",
                priority=8,
                executor="test",
                payload={"files": ["tests/test_runtime_flow.py"]},
            )
        )
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "RUNNING"
        assert isinstance(run.summary, dict)
        assert run.summary.get("goal_state") == "RECOVERING"
        assert run.summary.get("auto_phase_decomposition_in_progress") is True

        items = (
            await session.execute(select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.created_at.asc()))
        ).scalars().all()
        phase_items = [item for item in items if (item.key or "").startswith("CODE_FRONTEND_PHASE_")]
        assert len(phase_items) == 2
        for item in phase_items:
            assert item.status == "QUEUED"
            assert item.payload.get("recovery_action") == "auto_phase_decomposition"
            assert len(item.payload.get("files") or []) <= 6

        source_failed = next(item for item in items if item.key == "CODE_FRONTEND" and item.status == "FAILED")
        assert isinstance(source_failed.result, dict)
        assert source_failed.result.get("superseded") is True
        assert source_failed.result.get("superseded_reason") == "auto_phase_decomposition"

        events = (
            await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id))
        ).scalars().all()
        event_types = [event.event_type for event in events]
        assert "RUN_AUTO_DECOMPOSED" in event_types
        assert "RUN_OPERATOR_ACTION_REQUIRED" not in event_types


@pytest.mark.anyio
async def test_scheduler_pauses_run_when_budget_is_exhausted(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Budget pause scheduler project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        failed_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="FAILED",
            priority=10,
            executor="codex",
            payload={"blocking": True},
            result={"message": "run_budget_exhausted", "failure_class": "budget_exhausted"},
        )
        session.add(failed_item)
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "PAUSED"
        assert isinstance(run.summary, dict)
        assert run.summary.get("goal_state") == "NEEDS_HUMAN_INPUT"
        assert isinstance(run.summary.get("budget_pause"), dict)
        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.event_type == "RUN_BUDGET_PAUSED")
            )
        ).scalars().all()
        assert events


@pytest.mark.anyio
async def test_scheduler_pauses_run_when_spend_hard_limit_reached(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "external")
    monkeypatch.setenv("RUNTIME_NEVER_FAIL_RUNS", "true")
    monkeypatch.setenv("RUNTIME_RUN_SPEND_HARD_LIMIT_CENTS", "5")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Spend hard-limit scheduler project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(
            project_id=project.id,
            tenant_id=tenant_id,
            status="RUNNING",
            executor="codex",
            summary={
                "execution_contract": {
                    "budget": {
                        "used_cost_cents": 6.25,
                    }
                }
            },
        )
        session.add(run)
        await session.flush()

        # Ensure the run has at least one work item so scheduler evaluates lifecycle paths.
        session.add(
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=run.id,
                type="PLAN_DAG",
                key="PLAN_DAG",
                status="DONE",
                priority=1,
                executor="codex",
                payload={},
            )
        )
        await session.commit()
        run_id = run.id

    async with runtime_db() as session:
        await scheduler_tick(session)
        await session.commit()

    async with runtime_db() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "PAUSED"
        assert isinstance(run.summary, dict)
        assert run.summary.get("goal_state") == "NEEDS_HUMAN_INPUT"
        assert isinstance(run.summary.get("spend_pause"), dict)
        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.event_type == "RUN_SPEND_PAUSED")
            )
        ).scalars().all()
        assert events


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
async def test_launch_run_rejects_when_queued_run_already_exists(runtime_db):
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Queued run guard project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        session.add(Run(project_id=project.id, tenant_id=tenant_id, status="QUEUED", executor="codex"))
        await session.commit()

        with pytest.raises(ValueError, match="already in progress"):
            await launch_run_for_project(
                session,
                tenant_id=tenant_id,
                project_id=project.id,
                executor_name="codex",
                schedule=False,
            )


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


class OptionalWriteTestsFailureExecutor:
    name = "dummy"

    async def execute(self, work_item, context):
        if work_item.type == "WRITE_TESTS":
            return {
                "status": "FAILED",
                "message": "test patch generation failed",
                "payload": {
                    "reason": "patch_apply_failed",
                },
            }
        return {
            "status": "DONE",
            "message": "ok",
            "payload": {"executor": "optional-write-tests-failure"},
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
        assert len(work_items) >= 8
        assert sum(1 for wi in work_items if wi.type == "FIX_TEST_FAILURE") == 1
        assert sum(1 for wi in work_items if wi.type == "RUN_TESTS") >= 1

        failed_tests = [wi for wi in work_items if wi.type == "RUN_TESTS" and wi.status == "FAILED"]
        assert len(failed_tests) >= 1
        original_failed = failed_tests[0]
        fix_item = next(wi for wi in work_items if wi.type == "FIX_TEST_FAILURE")
        integration_review = next(wi for wi in work_items if wi.type == "REVIEW_INTEGRATION")

        assert original_failed.result["failure_class"] in {"test_failure", "test_assertion_failure"}
        assert original_failed.result["recovery_action"] == "spawn_fix_node"
        assert fix_item.status in {"DONE", "FAILED"}
        if fix_item.status == "DONE":
            assert fix_item.result["recovery_action"] == "spawn_retry_node"
        assert integration_review.status == "CANCELED"
        assert exhausted_executor.test_attempts >= 1

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
async def test_embedded_runtime_allows_write_tests_failure_without_blocking_pipeline(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Write tests optional failure project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="QUEUED", executor="dummy")
        session.add(run)
        await session.commit()
        run_id = run.id

    monkeypatch.setattr(orchestrator_module, "build_executor", lambda *_args, **_kwargs: OptionalWriteTestsFailureExecutor())
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
        write_tests = next(wi for wi in work_items if wi.type == "WRITE_TESTS")
        run_tests = next(wi for wi in work_items if wi.type == "RUN_TESTS")
        review_diff = next(wi for wi in work_items if wi.type == "REVIEW_DIFF")
        review_integration = next(wi for wi in work_items if wi.type == "REVIEW_INTEGRATION")

        assert write_tests.status == "FAILED"
        assert write_tests.payload["blocking"] is False
        assert review_diff.status == "DONE"
        assert run_tests.status == "DONE"
        assert review_integration.status == "DONE"

        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        event_types = [event.event_type for event in events]
        assert "WORK_ITEM_FAILED" in event_types
        assert "WORK_ITEM_CANCELED" not in event_types
        assert "RUN_FAILED" not in event_types
        assert "RUN_COMPLETED" in event_types


@pytest.mark.anyio
async def test_embedded_runtime_allows_write_tests_failure_without_blocking_flag(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Write tests failure without blocking flag", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="QUEUED", executor="dummy")
        session.add(run)
        await session.commit()
        run_id = run.id

    monkeypatch.setattr(orchestrator_module, "build_executor", lambda *_args, **_kwargs: OptionalWriteTestsFailureExecutor())
    orchestrator = RunOrchestrator(runtime_db, executor_name="dummy")
    await orchestrator.bootstrap(run_id)

    async with runtime_db() as session:
        write_tests = await session.scalar(
            select(WorkItem).where(WorkItem.run_id == run_id, WorkItem.type == "WRITE_TESTS")
        )
        assert write_tests is not None
        write_tests.payload = {k: v for k, v in (write_tests.payload or {}).items() if k != "blocking"}
        session.add(write_tests)
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
        write_tests = next(wi for wi in work_items if wi.type == "WRITE_TESTS")
        review_diff = next(wi for wi in work_items if wi.type == "REVIEW_DIFF")
        run_tests = next(wi for wi in work_items if wi.type == "RUN_TESTS")
        review_integration = next(wi for wi in work_items if wi.type == "REVIEW_INTEGRATION")

        assert write_tests.status == "FAILED"
        assert review_diff.status == "DONE"
        assert run_tests.status == "DONE"
        assert review_integration.status == "DONE"


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


@pytest.mark.anyio
async def test_run_launch_blocks_feature_runs_when_blueprint_enforces_readiness(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Readiness gate project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()
        session.add(
            ProjectBlueprint(
                tenant_id=tenant_id,
                project_id=project.id,
                blueprint_key="fullstack_monorepo",
                stack_preset_key="vue_fastapi",
                deployment_profile="local_preview",
                architecture="fullstack_monorepo",
                status="ACTIVE",
                readiness_enforced=True,
            )
        )
        session.add(
            ProjectGenesisRun(
                tenant_id=tenant_id,
                project_id=project.id,
                status="COMPLETED",
                validation={"status": "PARTIAL"},
            )
        )
        await session.commit()
        project_id = project.id

    async with runtime_db() as session:
        with pytest.raises(ValueError, match="Foundation readiness is not READY"):
            await launch_run_for_project(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                executor_name="dummy",
                schedule=False,
            )


@pytest.mark.anyio
async def test_run_launch_allows_genesis_setup_runs_before_readiness(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Genesis setup exemption project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()
        session.add(
            ProjectBlueprint(
                tenant_id=tenant_id,
                project_id=project.id,
                blueprint_key="fullstack_monorepo",
                stack_preset_key="vue_fastapi",
                deployment_profile="local_preview",
                architecture="fullstack_monorepo",
                status="ACTIVE",
                readiness_enforced=True,
            )
        )
        session.add(
            ProjectGenesisRun(
                tenant_id=tenant_id,
                project_id=project.id,
                status="COMPLETED",
                validation={"status": "PARTIAL"},
            )
        )
        await session.commit()
        project_id = project.id

    async with runtime_db() as session:
        run = await launch_run_for_project(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            executor_name="dummy",
            run_kind="genesis_setup",
            schedule=False,
        )
        assert run.status == "QUEUED"
        assert isinstance(run.summary, dict)
        assert run.summary.get("repository_state") == "GENESIS"


@pytest.mark.anyio
async def test_run_launch_does_not_block_projects_without_genesis(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Legacy project", tenant_id=tenant_id)
        session.add(project)
        await session.commit()
        project_id = project.id

    async with runtime_db() as session:
        run = await launch_run_for_project(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            executor_name="dummy",
            schedule=False,
        )
        assert run.status == "QUEUED"


@pytest.mark.anyio
async def test_run_launch_emits_governance_transition_event(monkeypatch, runtime_db):
    monkeypatch.setenv("RUNTIME_MODE", "embedded")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant_id = uuid.uuid4()

    async with runtime_db() as session:
        project = Project(name="Governance transition launch project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        session.add(
            Run(
                project_id=project.id,
                tenant_id=tenant_id,
                status="COMPLETED",
                executor="dummy",
                summary={"repository_state": "GENESIS"},
            )
        )
        session.add(
            Run(
                project_id=project.id,
                tenant_id=tenant_id,
                status="COMPLETED",
                executor="dummy",
                summary={"repository_state": "EARLY_BUILD"},
            )
        )
        await session.commit()
        project_id = project.id

    async with runtime_db() as session:
        run = await launch_run_for_project(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            executor_name="dummy",
            schedule=False,
        )
        run_id = run.id
        assert isinstance(run.summary, dict)
        assert run.summary.get("repository_state") == "ACTIVE_PRODUCT"
        assert run.summary.get("repository_state_previous") in {"GENESIS", "EARLY_BUILD"}
        previous_state = run.summary.get("repository_state_previous")

    async with runtime_db() as session:
        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts, RunEvent.id)
            )
        ).scalars().all()
        transition = [event for event in events if event.event_type == "RUN_GOVERNANCE_TRANSITION"]
        assert len(transition) == 1
        payload = transition[0].payload if isinstance(transition[0].payload, dict) else {}
        assert payload.get("from_repository_state") == previous_state
        assert payload.get("to_repository_state") == "ACTIVE_PRODUCT"
