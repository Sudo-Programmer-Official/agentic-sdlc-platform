from __future__ import annotations

import types
import uuid

import pytest

from app.db.models import Project, Run
from app.runtime import orchestrator as orchestrator_module
from app.runtime.orchestrator import RunOrchestrator
from app.runtime.dag import TaskScopeError
from app.services import run_launch as run_launch_module


class FakeLaunchSession:
    def __init__(self, project: Project):
        self._scalar_results = [project, 0]
        self.added: list[object] = []
        self.commit_count = 0

    async def scalar(self, _statement):
        return self._scalar_results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, _obj):
        return None

    def get_bind(self):
        return None


class FakeBootstrapSession:
    def __init__(self, run: Run | None = None):
        self.added: list[object] = []
        self.commit_count = 0
        self._run = run

    async def scalar(self, _statement):
        return None

    async def get(self, _model, _id):
        return self._run

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        self.commit_count += 1


@pytest.mark.anyio
async def test_launch_run_fails_closed_when_workspace_prepare_errors(monkeypatch):
    tenant_id = uuid.uuid4()
    project = Project(id=uuid.uuid4(), name="Repo launch failure", tenant_id=tenant_id)
    session = FakeLaunchSession(project)
    event_types: list[str] = []

    async def fake_record_event(*args, event_type: str, **kwargs):
        event_types.append(event_type)

    async def fake_log_activity(*args, **kwargs):
        return None

    async def fake_ensure_run_workspace(session, run, **kwargs):
        run.workspace_status = "ERROR"
        run.workspace_error = "clone auth failed"
        session.add(run)

    async def fake_get_project_repository(*args, **kwargs):
        return None

    class UnexpectedOrchestrator:
        def __init__(self, *args, **kwargs):
            raise AssertionError("bootstrap should not be constructed after a workspace failure")

    monkeypatch.setattr(run_launch_module, "get_project_repository", fake_get_project_repository)
    monkeypatch.setattr(run_launch_module, "ensure_run_workspace", fake_ensure_run_workspace)
    monkeypatch.setattr(run_launch_module, "record_event", fake_record_event)
    monkeypatch.setattr(run_launch_module, "log_activity", fake_log_activity)
    monkeypatch.setattr(run_launch_module, "RunOrchestrator", UnexpectedOrchestrator)

    run = await run_launch_module.launch_run_for_project(
        session,
        tenant_id=tenant_id,
        project_id=project.id,
        executor_name="codex",
        schedule=True,
    )

    assert run.status == "FAILED"
    assert run.workspace_status == "ERROR"
    assert run.workspace_error == "clone auth failed"
    assert session.commit_count == 1
    assert event_types == ["RUN_CREATED", "RUN_FAILED"]


@pytest.mark.anyio
async def test_bootstrap_fails_repo_runs_before_marking_them_running(monkeypatch):
    run = Run(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        status="QUEUED",
        executor="codex",
    )
    session = FakeBootstrapSession(run)
    require_repo_calls: list[bool] = []
    event_types: list[str] = []

    async def fake_load_run_for_update(self, _session, _run_id):
        return run

    async def fake_record_event(*args, event_type: str, **kwargs):
        event_types.append(event_type)

    async def fake_ensure_run_workspace(session, current_run, **kwargs):
        require_repo_calls.append(bool(kwargs.get("require_repo")))
        current_run.workspace_status = "ERROR"
        current_run.workspace_error = "clone auth failed"
        session.add(current_run)

    monkeypatch.setattr(
        orchestrator_module,
        "get_settings",
        lambda: types.SimpleNamespace(runtime_mode="external", max_workitem_concurrency=1),
    )
    monkeypatch.setattr(orchestrator_module, "get_executor", lambda name: types.SimpleNamespace(name=name))
    monkeypatch.setattr(orchestrator_module, "record_event", fake_record_event)
    monkeypatch.setattr(orchestrator_module, "ensure_run_workspace", fake_ensure_run_workspace)
    monkeypatch.setattr(RunOrchestrator, "_load_run_for_update", fake_load_run_for_update)

    orchestrator = RunOrchestrator(lambda: session, executor_name="codex")
    bootstrapped = await orchestrator.bootstrap_in_session(session, run.id)

    assert bootstrapped is False
    assert require_repo_calls == [True]
    assert run.status == "FAILED"
    assert run.workspace_status == "ERROR"
    assert run.workspace_error == "clone auth failed"
    assert run.finished_at is not None
    assert session.commit_count == 1
    assert event_types == ["RUN_FAILED"]


@pytest.mark.anyio
async def test_bootstrap_fails_closed_when_task_scope_is_missing(monkeypatch):
    run = Run(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        status="QUEUED",
        executor="codex",
        summary={
            "task_id": "task-noscope",
            "task_title": "Implement backend",
            "goal": "Implement backend",
        },
    )
    session = FakeBootstrapSession(run)
    event_types: list[str] = []

    async def fake_load_run_for_update(self, _session, _run_id):
        return run

    async def fake_record_event(*args, event_type: str, **kwargs):
        event_types.append(event_type)

    async def fake_ensure_run_workspace(session, current_run, **kwargs):
        current_run.workspace_status = "READY"
        current_run.workspace_root = "/tmp/workspace"
        current_run.repo_path = "/tmp/workspace/repo"
        session.add(current_run)

    async def fail_generate_template_dag(*args, **kwargs):
        raise TaskScopeError("Task task-noscope has no file scope")

    monkeypatch.setattr(
        orchestrator_module,
        "get_settings",
        lambda: types.SimpleNamespace(runtime_mode="external", max_workitem_concurrency=1),
    )
    monkeypatch.setattr(orchestrator_module, "get_executor", lambda name: types.SimpleNamespace(name=name))
    monkeypatch.setattr(orchestrator_module, "record_event", fake_record_event)
    monkeypatch.setattr(orchestrator_module, "ensure_run_workspace", fake_ensure_run_workspace)
    monkeypatch.setattr(orchestrator_module, "generate_template_dag", fail_generate_template_dag)
    monkeypatch.setattr(RunOrchestrator, "_load_run_for_update", fake_load_run_for_update)

    orchestrator = RunOrchestrator(lambda: session, executor_name="codex")
    bootstrapped = await orchestrator.bootstrap_in_session(session, run.id)

    assert bootstrapped is False
    assert run.status == "FAILED"
    assert isinstance(run.summary, dict)
    assert run.summary["bootstrap_error"] == "Task task-noscope has no file scope"
    assert session.commit_count == 2
    assert event_types == ["RUN_RUNNING", "RUN_BOOTSTRAP_STARTED", "RUN_FAILED"]
