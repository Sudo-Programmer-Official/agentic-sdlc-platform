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
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'run-memory.db'}", future=True)
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
async def test_run_memory_returns_similar_successful_runs(db_session):
    session, tenant_id = db_session
    project = Project(name="Run memory", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    started = datetime.utcnow() - timedelta(minutes=10)
    good_run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/login-fix",
        started_at=started,
        finished_at=started + timedelta(seconds=95),
        summary={
            "goal": "Fix failing login tests caused by import error",
            "pull_request_url": "https://github.com/acme/example/pull/7",
        },
    )
    other_run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/billing-fix",
        started_at=started + timedelta(minutes=2),
        finished_at=started + timedelta(minutes=2, seconds=50),
        summary={"goal": "Fix billing timeout"},
    )
    session.add_all([good_run, other_run])
    await session.flush()

    session.add_all(
        [
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=good_run.id,
                type="RUN_TESTS",
                key="RUN_TESTS",
                status="FAILED",
                priority=10,
                executor="test",
                payload={"title": "Run login tests"},
                result={"stderr": "ImportError: cannot import auth fixture"},
                last_error="ImportError: cannot import auth fixture",
            ),
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=other_run.id,
                type="RUN_TESTS",
                key="RUN_TESTS",
                status="DONE",
                priority=10,
                executor="test",
                payload={"title": "Run billing tests"},
                result={"stdout": "all passed"},
            ),
        ]
    )
    session.add(
        Artifact(
            tenant_id=tenant_id,
            project_id=project.id,
            run_id=good_run.id,
            work_item_id=None,
            type="git_diff",
            uri="workspace://patches/login.patch",
            version=1,
            extra_metadata={
                "content": (
                    "diff --git a/app/auth_service.py b/app/auth_service.py\n"
                    "--- a/app/auth_service.py\n"
                    "+++ b/app/auth_service.py\n"
                    "@@ -1 +1 @@\n-old\n+new\n"
                    "diff --git a/tests/test_auth.py b/tests/test_auth.py\n"
                    "--- a/tests/test_auth.py\n"
                    "+++ b/tests/test_auth.py\n"
                    "@@ -1 +1 @@\n-old\n+new\n"
                )
            },
        )
    )
    session.add(
        RunEvent(
            tenant_id=tenant_id,
            project_id=project.id,
            run_id=good_run.id,
            event_type="WORK_ITEM_RECOVERY",
            actor_type="SYSTEM",
            message="Auto recovery queued FIX_TEST_FAILURE for failed RUN_TESTS.",
            payload={"failure_class": "test_failure"},
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/projects/{project.id}/runs/memory",
            params={
                "goal": "login import error",
                "error": "ImportError auth fixture",
                "file": ["tests/test_auth.py"],
                "limit": 5,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["query"]["goal"] == "login import error"
    assert len(data["matches"]) >= 1
    top = data["matches"][0]
    assert top["run_id"] == str(good_run.id)
    assert top["score"] > 0
    assert top["recovery_count"] == 1
    assert top["pull_request_url"] == "https://github.com/acme/example/pull/7"
    assert "tests/test_auth.py" in top["files_changed"]
    assert top["score_breakdown"]["goal"] > 0
    assert top["score_breakdown"]["error"] > 0
    assert top["score_breakdown"]["files"] > 0

    summary = await session.scalar(select(RunSummary).where(RunSummary.run_id == good_run.id))
    assert summary is not None
    assert summary.goal_text == "Fix failing login tests caused by import error"
    assert summary.pr_created is True
    assert "tests/test_auth.py" in summary.changed_files


@pytest.mark.anyio
async def test_run_memory_requires_query_signal(db_session):
    session, tenant_id = db_session
    project = Project(name="Run memory validation", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/runs/memory")

    assert response.status_code == 400
    assert "Provide at least one" in response.json()["detail"]
