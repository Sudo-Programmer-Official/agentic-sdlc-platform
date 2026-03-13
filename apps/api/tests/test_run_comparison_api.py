import uuid
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Approval, Artifact, Project, Run, RunEvent, WorkItem
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'run-comparison.db'}", future=True)
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
async def test_run_comparison_reports_artifacts_recovery_and_pr_outcome(db_session):
    session, tenant_id = db_session
    project = Project(name="Compare runs", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    started = datetime.utcnow() - timedelta(minutes=5)
    run_a_id = uuid.uuid4()
    run_b_id = uuid.uuid4()
    run_a = Run(
        id=run_a_id,
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/original",
        workspace_status="SEEDED",
        started_at=started,
        finished_at=started + timedelta(seconds=30),
        summary={"goal": "Fix failing tests"},
    )
    run_b = Run(
        id=run_b_id,
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/forked",
        workspace_status="SEEDED",
        started_at=started + timedelta(minutes=1),
        finished_at=started + timedelta(minutes=1, seconds=45),
        summary={
            "goal": "Fix failing tests",
            "forked_from_run_id": str(run_a_id),
            "pull_request_url": "https://github.com/acme/example/pull/42",
            "pull_request_number": 42,
        },
    )
    session.add_all([run_a, run_b])
    await session.flush()

    session.add_all(
        [
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=run_a.id,
                type="RUN_TESTS",
                key="RUN_TESTS",
                status="DONE",
                priority=10,
                executor="test",
                payload={"title": "Run tests"},
                result={},
            ),
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=run_b.id,
                type="RUN_TESTS",
                key="RUN_TESTS",
                status="FAILED",
                priority=10,
                executor="test",
                payload={"title": "Run tests"},
                result={"stderr": "tests failed", "superseded": True},
                last_error="tests failed",
            ),
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=run_b.id,
                type="FIX_TEST_FAILURE",
                key="FIX_TEST_FAILURE_1",
                status="DONE",
                priority=9,
                executor="codex",
                payload={"title": "Fix tests"},
                result={},
            ),
        ]
    )
    await session.flush()

    artifact_a = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        run_id=run_a.id,
        work_item_id=None,
        type="git_diff",
        uri="workspace://patches/original.patch",
        version=1,
        extra_metadata={
            "content": "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-print('old')\n+print('new')\n"
        },
    )
    artifact_b = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        run_id=run_b.id,
        work_item_id=None,
        type="git_diff",
        uri="workspace://patches/forked.patch",
        version=1,
        extra_metadata={
            "content": (
                "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
                "@@ -1 +1 @@\n-print('old')\n+print('newer')\n"
                "diff --git a/tests/test_app.py b/tests/test_app.py\n--- a/tests/test_app.py\n+++ b/tests/test_app.py\n"
                "@@ -1 +1 @@\n-assert False\n+assert True\n"
            )
        },
    )
    artifact_pr = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        run_id=run_b.id,
        work_item_id=None,
        type="pull_request",
        uri="https://github.com/acme/example/pull/42",
        version=1,
        extra_metadata={"number": 42},
    )
    session.add_all([artifact_a, artifact_b, artifact_pr])
    await session.flush()

    session.add(
        RunEvent(
            tenant_id=tenant_id,
            project_id=project.id,
            run_id=run_b.id,
            work_item_id=None,
            task_id=None,
            event_type="WORK_ITEM_RECOVERY",
            actor_type="SYSTEM",
            message="Auto recovery queued FIX_TEST_FAILURE for failed RUN_TESTS.",
            payload={
                "failure_class": "test_failure",
                "recovery_action": "spawn_fix_node",
                "recovery_type": "FIX_TEST_FAILURE",
            },
        )
    )
    session.add(
        Approval(
            tenant_id=tenant_id,
            project_id=project.id,
            target_type="artifact",
            target_id=artifact_b.id,
            status="APPROVED",
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/runs/compare?run_a={run_a.id}&run_b={run_b.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["run_a"]["id"] == str(run_a.id)
    assert data["run_b"]["id"] == str(run_b.id)
    assert data["run_a"]["artifact_count"] == 1
    assert data["run_b"]["artifact_count"] == 2
    assert data["run_b"]["recovery_count"] == 1
    assert data["run_b"]["approval_status"] == "APPROVED"
    assert data["run_b"]["pull_request_url"] == "https://github.com/acme/example/pull/42"
    assert data["summary"]["faster_run_id"] == str(run_a.id)
    assert data["summary"]["more_recoveries_run_id"] == str(run_b.id)
    assert data["summary"]["pull_request_run_id"] == str(run_b.id)
    assert data["summary"]["files_only_in_b"] == ["tests/test_app.py"]
