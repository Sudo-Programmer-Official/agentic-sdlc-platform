import uuid
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Artifact, Project, Run, RunEvent, RunSummary, WorkItem
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'run-timeline.db'}", future=True)
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
async def test_run_timeline_replays_events_and_artifacts(db_session):
    session, tenant_id = db_session
    project = Project(name="Run timeline", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    started = datetime.utcnow() - timedelta(minutes=2)
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/auth-fix",
        workspace_status="SEEDED",
        started_at=started,
        finished_at=started + timedelta(seconds=42),
        summary={"goal": "Fix failing auth tests", "pull_request_url": "https://github.com/acme/example/pull/42"},
    )
    session.add(run)
    await session.flush()

    work_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="RUN_TESTS",
        key="RUN_TESTS",
        status="FAILED",
        priority=10,
        executor="test",
        payload={"title": "Run auth tests"},
        result={"stderr": "ImportError: missing fixture"},
        last_error="ImportError: missing fixture",
    )
    session.add(work_item)
    await session.flush()

    session.add_all(
        [
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=run.id,
                event_type="RUN_CREATED",
                actor_type="USER",
                ts=started,
            ),
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=run.id,
                work_item_id=work_item.id,
                event_type="WORK_ITEM_FAILED",
                actor_type="SYSTEM",
                message="Tests failed with an import error.",
                ts=started + timedelta(seconds=10),
            ),
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=run.id,
                work_item_id=work_item.id,
                event_type="WORK_ITEM_RECOVERY",
                actor_type="SYSTEM",
                message="Auto recovery queued FIX_TEST_FAILURE for failed RUN_TESTS.",
                payload={"failure_class": "test_failure"},
                ts=started + timedelta(seconds=15),
            ),
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=run.id,
                event_type="RUN_PULL_REQUEST_CREATED",
                actor_type="SYSTEM",
                message="Pull request opened.",
                ts=started + timedelta(seconds=40),
            ),
        ]
    )
    session.add(
        Artifact(
            tenant_id=tenant_id,
            project_id=project.id,
            run_id=run.id,
            work_item_id=work_item.id,
            type="git_diff",
            uri="workspace://patches/auth.patch",
            version=1,
            extra_metadata={
                "content": (
                    "diff --git a/app/auth.py b/app/auth.py\n"
                    "--- a/app/auth.py\n"
                    "+++ b/app/auth.py\n"
                    "@@ -1 +1 @@\n-old\n+new\n"
                )
            },
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/runs/{run.id}/timeline")

    assert response.status_code == 200
    data = response.json()
    assert data["run"]["id"] == str(run.id)
    assert data["summary"]["goal_text"] == "Fix failing auth tests"
    assert data["summary"]["recovery_count"] == 1
    assert data["summary"]["artifact_count"] == 1
    assert data["summary"]["pull_request_url"] == "https://github.com/acme/example/pull/42"
    assert any(step["event_type"] == "WORK_ITEM_RECOVERY" for step in data["steps"])
    assert any(step["artifact_type"] == "git_diff" for step in data["steps"])
    assert any("app/auth.py" in step.get("changed_files", []) for step in data["steps"])

    summary = await session.scalar(select(RunSummary).where(RunSummary.run_id == run.id))
    assert summary is not None
    assert summary.goal_text == "Fix failing auth tests"
