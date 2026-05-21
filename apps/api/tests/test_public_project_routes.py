import uuid
import subprocess
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Artifact, ImprovementRequest, Project, ProjectRepository, Run, RunCheckpoint, WorkItem, WorkItemEdge, Trace, Task
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app
from app.services.run_resume import capture_run_checkpoint, sync_run_resume_state


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'public-routes.db'}", future=True)
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
async def test_public_project_routes_resolve_to_db_backed_handlers(db_session):
    session, tenant_id = db_session
    project = Project(name="Router order", tenant_id=tenant_id, description="db-backed")
    session.add(project)
    await session.commit()
    await session.refresh(project)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project_resp = await client.get(f"/api/v1/projects/{project.id}")
        runs_resp = await client.get(f"/api/v1/projects/{project.id}/runs")
        summary_resp = await client.get(f"/api/v1/projects/{project.id}/summary")

    assert project_resp.status_code == 200
    assert project_resp.json()["name"] == "Router order"

    assert runs_resp.status_code == 200
    assert runs_resp.json() == []

    assert summary_resp.status_code == 200
    assert summary_resp.json()["name"] == "Router order"


@pytest.mark.anyio
async def test_public_runs_list_prioritizes_active_run_over_newer_failed_run(db_session):
    session, tenant_id = db_session
    project = Project(name="Run ordering", tenant_id=tenant_id, description="db-backed")
    session.add(project)
    await session.flush()

    running_run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="RUNNING",
        executor="codex",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=2),
    )
    session.add(running_run)
    await session.flush()

    failed_run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="FAILED",
        executor="codex",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        finished_at=datetime.now(timezone.utc) - timedelta(seconds=20),
    )
    session.add(failed_run)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        runs_resp = await client.get(f"/api/v1/projects/{project.id}/runs")

    assert runs_resp.status_code == 200
    data = runs_resp.json()
    assert [row["id"] for row in data[:2]] == [str(failed_run.id), str(running_run.id)]
    assert data[1]["status"] == "COMPLETED"


@pytest.mark.anyio
async def test_public_runs_list_auto_finalizes_stale_running_run_when_work_is_terminal(db_session):
    session, tenant_id = db_session
    project = Project(name="Run auto finalize", tenant_id=tenant_id, description="db-backed")
    session.add(project)
    await session.flush()

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="RUNNING",
        executor="codex",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=3),
    )
    session.add(run)
    await session.flush()
    run_id = run.id
    run_id = run.id

    session.add(
        WorkItem(
            tenant_id=tenant_id,
            project_id=project.id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="finalize-nav-restyle",
            status="DONE",
            priority=100,
            executor="codex",
            required_capabilities=[],
            max_attempts=1,
            attempt=0,
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        runs_resp = await client.get(f"/api/v1/projects/{project.id}/runs")

    assert runs_resp.status_code == 200
    data = runs_resp.json()
    assert data[0]["id"] == str(run.id)
    assert data[0]["status"] == "COMPLETED"

    await session.refresh(run)
    assert run.status == "COMPLETED"
    assert run.finished_at is not None


@pytest.mark.anyio
async def test_public_project_summary_exposes_latest_delivery_state(db_session):
    session, tenant_id = db_session
    project = Project(name="Delivery summary", tenant_id=tenant_id, description="db-backed")
    session.add(project)
    await session.flush()

    started = datetime.now(timezone.utc) - timedelta(minutes=4)
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/delivery-1234",
        workspace_status="SEEDED",
        started_at=started,
        finished_at=started + timedelta(seconds=54),
        summary={
            "goal": "Ship delivery summary",
            "remote_branch_pushed": True,
            "remote_branch_name": "run/delivery-1234",
            "remote_branch_commit_sha": "abcdef1234567890",
            "remote_branch_pushed_at": "2026-04-06T02:35:00Z",
            "pull_request_url": "https://github.com/acme/example/pull/42",
            "pull_request_number": 42,
        },
    )
    session.add(run)
    await session.flush()
    session.add(
        Artifact(
            tenant_id=tenant_id,
            project_id=project.id,
            run_id=run.id,
            type="git_diff",
            uri="workspace://patches/delivery.patch",
            version=1,
            extra_metadata={
                "content": (
                    "diff --git a/docs/delivery.md b/docs/delivery.md\n"
                    "--- a/docs/delivery.md\n"
                    "+++ b/docs/delivery.md\n"
                    "@@ -0,0 +1 @@\n"
                    "+delivery summary\n"
                )
            },
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/summary")

    assert response.status_code == 200
    data = response.json()
    latest_run = data["latest_run"]
    assert latest_run["status"] == "COMPLETED"
    assert latest_run["executor"] == "codex"
    assert latest_run["goal_text"] == "Ship delivery summary"
    assert latest_run["branch_name"] == "run/delivery-1234"
    assert latest_run["workspace_status"] == "SEEDED"
    assert latest_run["artifact_count"] == 1
    assert latest_run["files_changed"] == ["docs/delivery.md"]
    assert latest_run["diff_summary"] == "Updated docs/delivery.md"
    assert latest_run["pull_request_url"] == "https://github.com/acme/example/pull/42"
    assert latest_run["pull_request_number"] == 42


@pytest.mark.anyio
async def test_public_tasks_list_supports_active_and_latest_title_filters(db_session):
    session, tenant_id = db_session
    project = Project(name="Task filtering", tenant_id=tenant_id, description="db-backed")
    session.add(project)
    await session.flush()

    session.add_all(
        [
            Task(
                tenant_id=tenant_id,
                project_id=project.id,
                title="Polish Projects section",
                status="DONE",
                source="manual",
                source_type="manual",
                provenance={"rerun_of_task_id": str(uuid.uuid4())},
            ),
            Task(
                tenant_id=tenant_id,
                project_id=project.id,
                title="Polish Projects section",
                status="PENDING",
                source="manual",
                source_type="manual",
                provenance={"rerun_of_task_id": str(uuid.uuid4())},
            ),
            Task(
                tenant_id=tenant_id,
                project_id=project.id,
                title="Keep hero unchanged",
                status="RUNNING",
                source="manual",
                source_type="manual",
            ),
        ]
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/projects/{project.id}/tasks?active_only=true&latest_per_title=true"
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    titles = [row["title"] for row in data]
    assert "Polish Projects section" in titles
    assert "Keep hero unchanged" in titles
    assert all(row["status"] in {"PENDING", "RUNNING", "FAILED"} for row in data)


@pytest.mark.anyio
async def test_public_improvement_requests_list_returns_latest_first(db_session):
    session, tenant_id = db_session
    project = Project(name="Improvement requests", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    source_run = Run(project_id=project.id, tenant_id=tenant_id, status="COMPLETED", executor="codex")
    session.add(source_run)
    await session.flush()

    older = ImprovementRequest(
        tenant_id=tenant_id,
        project_id=project.id,
        source_run_id=source_run.id,
        goal_text="Old goal",
        issue_text="Old issue",
        files=["index.html"],
        status="QUEUED",
        created_run_ids=[],
    )
    newer = ImprovementRequest(
        tenant_id=tenant_id,
        project_id=project.id,
        source_run_id=source_run.id,
        goal_text="New goal",
        issue_text="New issue",
        files=["styles.css"],
        status="RUNNING",
        created_run_ids=[],
    )
    session.add_all([older, newer])
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/improvement-requests?limit=10")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["goal_text"] == "New goal"
    assert data[1]["goal_text"] == "Old goal"


@pytest.mark.anyio
async def test_requirement_summary_works_without_linked_tasks_or_runs(db_session):
    session, tenant_id = db_session
    project = Project(name="Req summary empty linkage", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ingest = await client.post(
            f"/api/v1/projects/{project.id}/prd",
            json={
                "text": "## Functional Requirements\n- User can browse portfolio sections quickly.\n## Quality Requirements\n- Page should remain responsive.",
                "source": "typed",
                "format": "markdown",
            },
        )
        assert ingest.status_code == 200
        response = await client.get(f"/api/v1/projects/{project.id}/requirements/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    row = payload["items"][0]
    assert row["status"] == "NOT_STARTED"
    assert row["task_counts"]["total"] == 0
    assert row["run_counts"]["total"] == 0


@pytest.mark.anyio
async def test_requirement_summary_aggregates_linked_task_states(db_session):
    session, tenant_id = db_session
    project = Project(name="Req task aggregation", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add_all(
        [
            Task(tenant_id=tenant_id, project_id=project.id, title="task open", status="PENDING", requirement_id="FR-100"),
            Task(tenant_id=tenant_id, project_id=project.id, title="task running", status="RUNNING", requirement_id="FR-100"),
            Task(tenant_id=tenant_id, project_id=project.id, title="task done", status="DONE", requirement_id="FR-100"),
            Task(tenant_id=tenant_id, project_id=project.id, title="task failed", status="FAILED", requirement_id="FR-100"),
        ]
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/requirements/summary")

    assert response.status_code == 200
    payload = response.json()
    row = next(item for item in payload["items"] if item["requirement_id"] == "FR-100")
    assert row["task_counts"]["total"] == 4
    assert row["task_counts"]["open"] == 1
    assert row["task_counts"]["in_progress"] == 1
    assert row["task_counts"]["completed"] == 1
    assert row["task_counts"]["failed"] == 1


@pytest.mark.anyio
async def test_requirement_timeline_includes_task_run_and_improvement_events(db_session):
    session, tenant_id = db_session
    project = Project(name="Req timeline", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    task = Task(
        tenant_id=tenant_id,
        project_id=project.id,
        title="Polish body sections",
        status="FAILED",
        requirement_id="FR-200",
    )
    session.add(task)
    await session.flush()

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="FAILED",
        executor="codex",
        summary={"task_id": str(task.id), "requirement_id": "FR-200", "goal": "Polish body"},
    )
    session.add(run)
    await session.flush()
    task.run_id = run.id
    session.add(task)
    await session.flush()

    session.add(
        ImprovementRequest(
            tenant_id=tenant_id,
            project_id=project.id,
            source_run_id=run.id,
            goal_text="Fix polish",
            issue_text="Cards still look old",
            status="QUEUED",
            files=["index.html"],
            created_run_ids=[],
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/requirements/FR-200/timeline")

    assert response.status_code == 200
    payload = response.json()
    event_types = {item["type"] for item in payload["items"]}
    assert "task.failed" in event_types
    assert "run.failed" in event_types
    assert "improvement.requested" in event_types


@pytest.mark.anyio
async def test_task_and_run_apis_allow_null_requirement_id(db_session):
    session, tenant_id = db_session
    project = Project(name="Null req linkage", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task_resp = await client.post(
            f"/api/v1/projects/{project.id}/tasks",
            json={"title": "Legacy task without requirement"},
        )
        assert task_resp.status_code == 201
        assert task_resp.json()["requirement_id"] is None

        task_id = task_resp.json()["id"]
        run_resp = await client.post(
            f"/api/v1/projects/{project.id}/runs",
            json={"executor": "dummy", "task_id": task_id},
        )
        assert run_resp.status_code == 201


@pytest.mark.anyio
async def test_requirement_relationship_create_and_list(db_session):
    session, tenant_id = db_session
    project = Project(name="Req relationships", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            f"/api/v1/projects/{project.id}/requirements/relationships",
            json={
                "from_requirement_id": "FR-1",
                "to_requirement_id": "QR-1",
                "relation_type": "depends_on",
                "rationale": "security depends on auth flow",
            },
        )
        assert create_resp.status_code == 201

        list_resp = await client.get(f"/api/v1/projects/{project.id}/requirements/FR-1/relationships")
        assert list_resp.status_code == 200
        rows = list_resp.json()
        assert len(rows) == 1
        assert rows[0]["relation_type"] == "depends_on"


@pytest.mark.anyio
async def test_requirement_execution_graph_and_memory(db_session):
    session, tenant_id = db_session
    project = Project(name="Req graph memory", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    task = Task(
        tenant_id=tenant_id,
        project_id=project.id,
        title="Fix FR-500",
        status="DONE",
        requirement_id="FR-500",
        derived_from_requirement_ids=["FR-500"],
    )
    session.add(task)
    await session.flush()

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        requirement_id="FR-500",
        summary={
            "task_id": str(task.id),
            "requirement_id": "FR-500",
            "goal": "Fix FR-500",
            "changed_files": ["apps/web/src/index.html"],
            "pull_request_url": "https://example.com/pr/1",
            "pull_request_number": 1,
        },
    )
    session.add(run)
    await session.flush()
    task.run_id = run.id
    session.add(task)
    await session.flush()
    session.add(
        ImprovementRequest(
            tenant_id=tenant_id,
            project_id=project.id,
            source_run_id=run.id,
            source_requirement_id="FR-500",
            goal_text="Improve FR-500 flow",
            issue_text="Needs better reliability",
            status="QUEUED",
            files=["apps/web/src/index.html"],
            created_run_ids=[],
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        graph_resp = await client.get(f"/api/v1/projects/{project.id}/requirements/FR-500/execution-graph")
        assert graph_resp.status_code == 200
        graph_payload = graph_resp.json()
        assert len(graph_payload["tasks"]) == 1
        assert len(graph_payload["runs"]) == 1
        assert len(graph_payload["improvements"]) == 1
        assert graph_payload["related_modules"]

        memory_resp = await client.post(f"/api/v1/projects/{project.id}/requirements/FR-500/memory")
        assert memory_resp.status_code == 200
        memory_payload = memory_resp.json()
        assert memory_payload["requirement_id"] == "FR-500"
        assert isinstance(memory_payload["compact_summary"], str)


@pytest.mark.anyio
async def test_run_launch_injects_requirement_context_pack(db_session):
    session, tenant_id = db_session
    project = Project(name="Req context injection", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task_resp = await client.post(
            f"/api/v1/projects/{project.id}/tasks",
            json={
                "title": "Improve accessibility",
                "requirement_id": "FR-CTX-1",
                "derived_from_requirement_ids": ["FR-CTX-1"],
            },
        )
        assert task_resp.status_code == 201
        task_id = task_resp.json()["id"]

        run_resp = await client.post(
            f"/api/v1/projects/{project.id}/runs",
            json={"executor": "dummy", "task_id": task_id},
        )
        assert run_resp.status_code == 201
        summary = run_resp.json().get("summary") or {}
        assert summary.get("requirement_context_pack", {}).get("requirement_id") == "FR-CTX-1"


@pytest.mark.anyio
async def test_public_run_status_patch_cancels_queued_run(db_session):
    session, tenant_id = db_session
    project = Project(name="Cancelable run", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    run = Run(project_id=project.id, tenant_id=tenant_id, status="QUEUED", executor="dummy")
    session.add(run)
    await session.commit()
    await session.refresh(run)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/api/v1/runs/{run.id}/status",
            json={"status": "CANCELED"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "CANCELED"


@pytest.mark.anyio
async def test_public_run_budget_extend_resumes_paused_budget_run(db_session):
    session, tenant_id = db_session
    project = Project(name="Budget extend run", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="PAUSED",
        executor="codex",
        summary={
            "execution_contract": {
                "budget": {
                    "max_tokens": 1000,
                    "max_cost_cents": 10.0,
                    "used_input_tokens": 1000,
                    "used_output_tokens": 200,
                    "used_tokens": 1200,
                    "remaining_tokens": 0,
                    "used_cost_cents": 10.0,
                    "remaining_cost_cents": 0.0,
                    "recovery_reserve_cost_cents": 0.0,
                    "used_recovery_cost_cents": 0.0,
                    "remaining_recovery_cost_cents": 0.0,
                    "active_budget_partition": "main",
                    "budget_mode": "BLOCKED",
                }
            }
        },
    )
    session.add(run)
    await session.flush()

    work_item = WorkItem(
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
    session.add(work_item)
    await session.commit()
    await session.refresh(run)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/runs/{run.id}/budget/extend",
            json={"additional_tokens": 2000, "additional_cost_cents": 15, "auto_resume": True, "reason": "operator approved"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "QUEUED"

    await session.refresh(run)
    assert run.status == "QUEUED"
    summary = run.summary or {}
    budget = ((summary.get("execution_contract") or {}).get("budget") or {})
    assert budget.get("max_tokens", 0) >= 3000
    assert float(budget.get("max_cost_cents", 0)) >= 25.0
    updated_item = await session.get(WorkItem, work_item.id)
    assert updated_item is not None
    await session.refresh(updated_item)
    assert updated_item.status == "QUEUED"


@pytest.mark.anyio
async def test_public_run_fork_clones_dag_and_metadata(db_session):
    session, tenant_id = db_session
    project = Project(name="Forkable run", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    source_run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="FAILED",
        executor="codex",
        branch_name="run/source-1234",
        summary={"goal": "Fix failing tests", "policy": "strict"},
    )
    session.add(source_run)
    await session.flush()

    wi_plan = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=source_run.id,
        type="PLAN_DAG",
        key="PLAN_DAG",
        status="DONE",
        priority=10,
        executor="codex",
        payload={"title": "Plan work"},
        result={"executor": "codex"},
    )
    wi_test = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=source_run.id,
        type="RUN_TESTS",
        key="RUN_TESTS",
        status="FAILED",
        priority=9,
        executor="test",
        payload={"title": "Run tests"},
        result={"stderr": "tests failed"},
        last_error="tests failed",
    )
    session.add_all([wi_plan, wi_test])
    await session.flush()
    session.add(
        WorkItemEdge(
            tenant_id=tenant_id,
            run_id=source_run.id,
            from_work_item_id=wi_plan.id,
            to_work_item_id=wi_test.id,
        )
    )
    await session.commit()
    await session.refresh(source_run)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/runs/{source_run.id}/fork",
            json={
                "executor": "dummy",
                "branch_name": "run/forked-9999",
                "start_now": False,
                "summary_overrides": {"fork_notes": "replay with dummy"},
            },
        )

    assert response.status_code == 201
    data = response.json()
    fork_id = data["id"]
    assert data["executor"] == "dummy"
    assert data["status"] == "QUEUED"
    assert data["branch_name"] == "run/forked-9999"
    assert data["summary"]["forked_from_run_id"] == str(source_run.id)
    assert data["summary"]["fork_notes"] == "replay with dummy"

    fork_run = await session.get(Run, uuid.UUID(fork_id))
    assert fork_run is not None
    assert fork_run.workspace_root is not None
    assert fork_run.repo_path is not None

    fork_items = (
        await session.execute(
            select(WorkItem).where(WorkItem.run_id == fork_run.id).order_by(WorkItem.created_at.asc(), WorkItem.id.asc())
        )
    ).scalars().all()
    assert len(fork_items) == 2
    assert {item.type for item in fork_items} == {"PLAN_DAG", "RUN_TESTS"}
    assert all(item.status == "QUEUED" for item in fork_items)
    assert all(item.result == {} for item in fork_items)
    assert all(item.last_error is None for item in fork_items)
    assert {item.executor for item in fork_items} == {"dummy", "test"}

    fork_edges = (
        await session.execute(select(WorkItemEdge).where(WorkItemEdge.run_id == fork_run.id))
    ).scalars().all()
    assert len(fork_edges) == 1
    fork_ids = {item.id for item in fork_items}
    assert fork_edges[0].from_work_item_id in fork_ids
    assert fork_edges[0].to_work_item_id in fork_ids

    fork_traces = (
        await session.execute(
            select(Trace).where(
                Trace.project_id == project.id,
                Trace.from_type == "run",
                Trace.from_id == source_run.id,
                Trace.to_type == "run",
                Trace.to_id == fork_run.id,
                Trace.relation_type == "forks",
            )
        )
    ).scalars().all()
    assert len(fork_traces) == 1


@pytest.mark.anyio
async def test_public_run_resume_restores_checkpoint_and_requeues_failed_slice(db_session, tmp_path: Path):
    session, tenant_id = db_session
    project = Project(name="Resumable run", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    context_root = workspace_root / "context"
    repo_root.mkdir(parents=True, exist_ok=True)
    context_root.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Runtime Tests"], cwd=repo_root, check=True, capture_output=True)
    target_file = repo_root / "app.py"
    target_file.write_text("print('base')\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo_root, check=True, capture_output=True)

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="FAILED",
        executor="codex",
        branch_name="run/resume-1234",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
        workspace_status="SEEDED",
        summary={"goal": "Resume a failed run safely"},
    )
    session.add(run)
    await session.flush()

    plan_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="PLAN_DAG",
        key="PLAN_DAG",
        status="DONE",
        priority=10,
        executor="codex",
        result={"message": "planned"},
    )
    code_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="CODE_BACKEND",
        key="CODE_BACKEND",
        status="DONE",
        priority=9,
        executor="codex",
        result={"message": "code applied"},
    )
    test_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="RUN_TESTS",
        key="RUN_TESTS",
        status="FAILED",
        priority=8,
        executor="test",
        result={"stderr": "tests failed"},
        last_error="tests failed",
    )
    review_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="REVIEW_INTEGRATION",
        key="REVIEW_INTEGRATION",
        status="CANCELED",
        priority=7,
        executor="codex",
        result={"message": "blocked by terminal failure"},
    )
    session.add_all([plan_item, code_item, test_item, review_item])
    await session.flush()

    target_file.write_text("print('safe')\n", encoding="utf-8")
    await capture_run_checkpoint(session, run, work_item=code_item, checkpoint_kind="safe")

    target_file.write_text("print('broken')\n", encoding="utf-8")
    (repo_root / "scratch.txt").write_text("junk\n", encoding="utf-8")
    await sync_run_resume_state(session, run, failed_work_item=test_item)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/v1/runs/{run.id}/resume", json={"start_now": False})

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "QUEUED"

    session.expire_all()
    await session.refresh(run)
    resumed_items = (
        await session.execute(
            select(WorkItem).where(WorkItem.run_id == run.id).order_by(WorkItem.priority.desc(), WorkItem.created_at.asc())
        )
    ).scalars().all()
    item_statuses = {item.type: item.status for item in resumed_items}
    assert item_statuses["PLAN_DAG"] == "DONE"
    assert item_statuses["CODE_BACKEND"] == "DONE"
    assert item_statuses["RUN_TESTS"] == "QUEUED"
    assert item_statuses["REVIEW_INTEGRATION"] == "QUEUED"
    assert target_file.read_text(encoding="utf-8") == "print('safe')\n"
    assert not (repo_root / "scratch.txt").exists()
    assert run.summary["resume_state"]["resume_count"] == 1
    assert run.summary["resume_history"][-1]["previous_status"] == "FAILED"


@pytest.mark.anyio
async def test_public_run_resume_rehydrates_workspace_from_durable_checkpoint(db_session, tmp_path: Path):
    session, tenant_id = db_session
    project = Project(name="Durable resumable run", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    source_repo = tmp_path / "source-repo"
    source_repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Runtime Tests"], cwd=source_repo, check=True, capture_output=True)
    source_file = source_repo / "app.py"
    source_file.write_text("print('base')\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=source_repo, check=True, capture_output=True)

    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url=str(source_repo),
            repo_full_name=None,
            default_branch="main",
        )
    )
    await session.flush()

    workspace_root = tmp_path / "workspace-rehydrate"
    repo_root = workspace_root / "repo"
    context_root = workspace_root / "context"
    context_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", str(source_repo), str(repo_root)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-B", "run/resume-durable"], cwd=repo_root, check=True, capture_output=True)

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="FAILED",
        executor="codex",
        branch_name="run/resume-durable",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
        workspace_status="SEEDED",
        summary={"goal": "Resume after workspace loss"},
    )
    session.add(run)
    await session.flush()

    code_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="CODE_BACKEND",
        key="CODE_BACKEND",
        status="DONE",
        priority=9,
        executor="codex",
        result={"message": "safe patch applied"},
    )
    test_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="RUN_TESTS",
        key="RUN_TESTS",
        status="FAILED",
        priority=8,
        executor="test",
        result={"stderr": "tests failed"},
        last_error="tests failed",
    )
    session.add_all([code_item, test_item])
    await session.flush()

    durable_file = repo_root / "app.py"
    durable_file.write_text("print('safe')\n", encoding="utf-8")
    checkpoint = await capture_run_checkpoint(session, run, work_item=code_item, checkpoint_kind="safe")
    durable_row = await session.scalar(select(RunCheckpoint).where(RunCheckpoint.run_id == run.id))
    assert durable_row is not None
    assert durable_row.patch_blob is not None
    assert durable_row.storage_mode == "database+workspace"

    durable_file.write_text("print('broken')\n", encoding="utf-8")
    await sync_run_resume_state(session, run, failed_work_item=test_item)
    await session.commit()

    patch_path = Path(str(durable_row.workspace_patch_path))
    assert patch_path.exists()
    shutil.rmtree(workspace_root)
    assert not patch_path.exists()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/v1/runs/{run.id}/resume", json={"start_now": False})

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "QUEUED"

    session.expire_all()
    await session.refresh(run)
    restored_repo = Path(str(run.repo_path))
    assert restored_repo.exists()
    assert (restored_repo / ".git").exists()
    assert (restored_repo / "app.py").read_text(encoding="utf-8") == "print('safe')\n"
    assert run.summary["resume_state"]["resume_count"] == 1
    assert run.summary["resume_state"]["last_resume_restore_source"] == "database_patch"
    assert run.summary["resume_state"]["last_resume_workspace_rehydrated"] is True
    assert run.summary["resume_state"]["durable_checkpoint_count"] >= 1


@pytest.mark.anyio
async def test_public_run_resume_retry_failed_step_mode_requeues_only_failed_node(db_session, tmp_path: Path):
    session, tenant_id = db_session
    project = Project(name="Resume mode retry failed step", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    workspace_root = tmp_path / "workspace-retry-failed"
    repo_root = workspace_root / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Runtime Tests"], cwd=repo_root, check=True, capture_output=True)
    target_file = repo_root / "app.py"
    target_file.write_text("print('safe')\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "safe"], cwd=repo_root, check=True, capture_output=True)

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="FAILED",
        executor="codex",
        branch_name="run/retry-failed-step",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
        workspace_status="SEEDED",
        summary={"goal": "Retry only failed step"},
    )
    session.add(run)
    await session.flush()
    run_id = run.id

    plan_item = WorkItem(project_id=project.id, tenant_id=tenant_id, run_id=run.id, type="PLAN_DAG", key="PLAN_DAG", status="DONE", priority=10, executor="codex")
    code_item = WorkItem(project_id=project.id, tenant_id=tenant_id, run_id=run.id, type="CODE_BACKEND", key="CODE_BACKEND", status="DONE", priority=9, executor="codex")
    failed_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="CODE_FRONTEND",
        key="CODE_FRONTEND",
        status="FAILED",
        priority=8,
        executor="codex",
        payload={"blocking": True},
        result={"failure_class": "structural_contract_violation"},
        last_error="CODE_FRONTEND structural contract violation in index.html",
    )
    canceled_downstream = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="WRITE_TESTS",
        key="WRITE_TESTS",
        status="CANCELED",
        priority=7,
        executor="codex",
    )
    session.add_all([plan_item, code_item, failed_item, canceled_downstream])
    await session.flush()
    failed_item_id = failed_item.id
    session.add(
        WorkItemEdge(
            tenant_id=tenant_id,
            run_id=run.id,
            from_work_item_id=failed_item.id,
            to_work_item_id=canceled_downstream.id,
        )
    )
    await session.flush()

    await capture_run_checkpoint(session, run, work_item=code_item, checkpoint_kind="safe")
    await sync_run_resume_state(session, run, failed_work_item=failed_item)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/runs/{run_id}/resume",
            json={"start_now": False, "mode": "retry_failed_step", "failed_work_item_id": str(failed_item_id)},
        )

    assert response.status_code == 200, response.text
    session.expire_all()
    resumed = (
        await session.execute(select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.created_at.asc()))
    ).scalars().all()
    statuses = {item.key: item.status for item in resumed}
    assert statuses["PLAN_DAG"] == "DONE"
    assert statuses["CODE_BACKEND"] == "DONE"
    assert statuses["CODE_FRONTEND"] == "QUEUED"
    assert statuses["WRITE_TESTS"] == "CANCELED"


@pytest.mark.anyio
async def test_public_run_resume_replay_with_repair_injects_strategy(db_session, tmp_path: Path):
    session, tenant_id = db_session
    project = Project(name="Resume mode repair inject", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    workspace_root = tmp_path / "workspace-repair"
    repo_root = workspace_root / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Runtime Tests"], cwd=repo_root, check=True, capture_output=True)
    (repo_root / "index.html").write_text("<html></html>\n", encoding="utf-8")
    subprocess.run(["git", "add", "index.html"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo_root, check=True, capture_output=True)

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="FAILED",
        executor="codex",
        branch_name="run/repair-inject",
        workspace_root=str(workspace_root),
        repo_path=str(repo_root),
        workspace_status="SEEDED",
        summary={"goal": "Repair and continue"},
    )
    session.add(run)
    await session.flush()
    run_id = run.id

    done_item = WorkItem(project_id=project.id, tenant_id=tenant_id, run_id=run.id, type="PLAN_DAG", key="PLAN_DAG", status="DONE", priority=10, executor="codex")
    failed_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="CODE_FRONTEND",
        key="CODE_FRONTEND",
        status="FAILED",
        priority=8,
        executor="codex",
        payload={"blocking": True},
        result={"failure_class": "structural_contract_violation"},
        last_error="CODE_FRONTEND structural contract violation in index.html",
    )
    session.add_all([done_item, failed_item])
    await session.flush()
    failed_item_id = failed_item.id

    await capture_run_checkpoint(session, run, work_item=done_item, checkpoint_kind="safe")
    await sync_run_resume_state(session, run, failed_work_item=failed_item)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/runs/{run_id}/resume",
                json={
                    "start_now": False,
                    "mode": "replay_with_repair",
                    "failed_work_item_id": str(failed_item_id),
                    "repair_strategy": "componentization_repair",
                },
            )
    assert response.status_code == 200, response.text

    session.expire_all()
    updated_failed = await session.get(WorkItem, failed_item_id)
    assert updated_failed is not None
    assert updated_failed.status == "QUEUED"
    assert (updated_failed.payload or {}).get("recovery_strategy") == "componentization_repair"
    assert (updated_failed.payload or {}).get("recovery_action") == "resume_repair_continue"
