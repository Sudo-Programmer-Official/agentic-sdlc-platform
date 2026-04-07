import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Artifact, Project, Run, WorkItem, WorkItemEdge, Trace
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


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
    assert latest_run["pull_request_url"] == "https://github.com/acme/example/pull/42"
    assert latest_run["pull_request_number"] == 42
    assert latest_run["delivery_pushed"] is True
    assert latest_run["delivery_branch_name"] == "run/delivery-1234"
    assert latest_run["delivery_commit_sha"] == "abcdef1234567890"
    assert latest_run["delivery_pushed_at"] == "2026-04-06T02:35:00Z"


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
