import uuid
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Artifact, ImprovementRequest, Project, Run, RunEvent, RunSummary, WorkItem
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'run-strategy.db'}", future=True)
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
async def test_run_strategy_group_creates_candidate_forks(db_session):
    session, tenant_id = db_session
    project = Project(name="Strategy project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    source_run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="FAILED",
        executor="codex",
        branch_name="run/auth-fix",
        summary={"goal": "Fix failing authentication tests"},
    )
    session.add(source_run)
    await session.flush()
    session.add(
        WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=source_run.id,
            type="RUN_TESTS",
            key="RUN_TESTS",
            status="FAILED",
            priority=10,
            executor="test",
            payload={"title": "Run tests"},
            result={"stderr": "pytest import error"},
            last_error="pytest import error",
        )
    )
    await session.commit()
    await session.refresh(source_run)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/runs/{source_run.id}/strategies",
            json={
                "goal": "Fix failing authentication tests",
                "error": "pytest import error",
                "files": ["tests/test_auth.py"],
                "start_now": False,
                "limit": 3,
            },
        )

    assert response.status_code == 201
    data = response.json()
    assert data["source_run_id"] == str(source_run.id)
    assert len(data["candidates"]) == 3
    assert data["group_id"]
    assert {candidate["strategy_type"] for candidate in data["candidates"]} == {
        "minimal_patch",
        "update_test",
        "refactor_module",
    }

    runs = (
        await session.execute(
            select(Run).where(Run.project_id == project.id).order_by(Run.created_at.asc(), Run.id.asc())
        )
    ).scalars().all()
    assert len(runs) == 4
    forked = [run for run in runs if run.id != source_run.id]
    assert len(forked) == 3
    assert all((run.summary or {}).get("strategy_group_id") == data["group_id"] for run in forked)
    assert all((run.summary or {}).get("strategy_source_run_id") == str(source_run.id) for run in forked)
    assert all(run.status == "QUEUED" for run in forked)


@pytest.mark.anyio
async def test_run_strategy_group_persists_feedback_metadata(db_session):
    session, tenant_id = db_session
    project = Project(name="Feedback strategy project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    source_run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/portfolio",
        summary={"goal": "Build portfolio landing page"},
    )
    session.add(source_run)
    await session.flush()
    session.add(
        RunSummary(
            run_id=source_run.id,
            tenant_id=tenant_id,
            project_id=project.id,
            goal_text="Build portfolio landing page",
            status="COMPLETED",
            executor="codex",
            branch_name="run/portfolio",
            workspace_status="SEEDED",
            changed_files=["index.html", "styles.css", "test_index_html.py"],
            artifact_types=[],
            recovery_count=0,
            artifact_count=0,
        )
    )
    await session.commit()
    await session.refresh(source_run)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/runs/{source_run.id}/strategies",
            json={
                "goal": "Build portfolio landing page",
                "error": "Projects section is missing on the homepage preview.",
                "files": ["index.html", "styles.css"],
                "start_now": False,
                "limit": 1,
                "mode": "feedback",
                "feedback_text": "Projects section is missing on the homepage preview.",
                "feedback_source": "user",
            },
        )

    assert response.status_code == 201
    data = response.json()
    assert len(data["candidates"]) == 1
    assert data["candidates"][0]["strategy_type"] == "minimal_patch"

    forked_run = await session.scalar(select(Run).where(Run.project_id == project.id, Run.id != source_run.id))
    assert forked_run is not None
    assert forked_run.summary["strategy_mode"] == "feedback"
    assert "improvement_request_id" in forked_run.summary
    assert forked_run.summary["feedback_text"] == "Projects section is missing on the homepage preview."
    assert forked_run.summary["feedback_source"] == "user"
    assert forked_run.summary["strategy_error"] == "Projects section is missing on the homepage preview."
    assert forked_run.summary["strategy_files"] == ["index.html", "styles.css"]
    assert forked_run.summary["target_files"] == ["index.html", "styles.css"]
    assert forked_run.summary["target_reasons"]["index.html"][:2] == [
        "explicit_request",
        "changed_in_source_run",
    ]
    assert forked_run.summary["target_reasons"]["styles.css"][:2] == [
        "explicit_request",
        "changed_in_source_run",
    ]
    assert forked_run.summary["edit_budget"] == {
        "mode": "minimal_patch",
        "max_files": 2,
        "hard_max_files": 4,
    }
    request_id = uuid.UUID(forked_run.summary["improvement_request_id"])
    improvement_request = await session.get(ImprovementRequest, request_id)
    assert improvement_request is not None
    assert improvement_request.source_run_id == source_run.id
    assert improvement_request.goal_text == "Build portfolio landing page"
    assert improvement_request.issue_text == "Projects section is missing on the homepage preview."
    assert improvement_request.created_run_ids == [str(forked_run.id)]


@pytest.mark.anyio
async def test_run_strategy_group_recommends_best_candidate(db_session):
    session, tenant_id = db_session
    project = Project(name="Strategy scoring", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    source_run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="FAILED",
        executor="codex",
        branch_name="run/auth-fix",
        summary={"goal": "Fix failing authentication tests"},
    )
    session.add(source_run)
    await session.flush()
    await session.commit()
    await session.refresh(source_run)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post(
            f"/api/v1/runs/{source_run.id}/strategies",
            json={
                "goal": "Fix failing authentication tests",
                "error": "pytest import error",
                "files": ["app/auth_service.py"],
                "start_now": False,
                "limit": 3,
            },
        )
        assert create_response.status_code == 201

    forked_runs = (
        await session.execute(
            select(Run)
            .where(Run.project_id == project.id, Run.id != source_run.id)
            .order_by(Run.created_at.asc(), Run.id.asc())
        )
    ).scalars().all()
    assert len(forked_runs) == 3

    by_type = {(run.summary or {}).get("strategy_type"): run for run in forked_runs}
    now = datetime.utcnow()

    best = by_type["minimal_patch"]
    best.status = "COMPLETED"
    best.started_at = now - timedelta(seconds=80)
    best.finished_at = now
    best.summary = {
        **(best.summary or {}),
        "pull_request_url": "https://github.com/acme/example/pull/42",
    }
    session.add(
        Artifact(
            tenant_id=tenant_id,
            project_id=project.id,
            run_id=best.id,
            work_item_id=None,
            type="git_diff",
            uri="workspace://patches/minimal.patch",
            version=1,
            extra_metadata={
                "content": (
                    "diff --git a/app/auth_service.py b/app/auth_service.py\n"
                    "--- a/app/auth_service.py\n"
                    "+++ b/app/auth_service.py\n"
                    "@@ -1 +1 @@\n-old\n+new\n"
                )
            },
        )
    )

    slower = by_type["refactor_module"]
    slower.status = "COMPLETED"
    slower.started_at = now - timedelta(seconds=220)
    slower.finished_at = now
    session.add_all(
        [
            Artifact(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=slower.id,
                work_item_id=None,
                type="git_diff",
                uri="workspace://patches/refactor.patch",
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
            ),
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=slower.id,
                event_type="WORK_ITEM_RECOVERY",
                actor_type="SYSTEM",
                message="Auto recovery queued FIX_TEST_FAILURE for failed RUN_TESTS.",
                payload={"failure_class": "test_failure"},
            ),
        ]
    )

    failed = by_type["update_test"]
    failed.status = "FAILED"
    failed.started_at = now - timedelta(seconds=90)
    failed.finished_at = now
    session.add_all([best, slower, failed])
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/runs/{source_run.id}/strategies")

    assert response.status_code == 200
    data = response.json()
    assert data["recommendation"] is not None
    assert data["recommendation"]["run_id"] == str(best.id)
    assert data["recommendation"]["strategy_type"] == "minimal_patch"
    assert any("PR-ready" in line or "completed" in line.lower() for line in data["recommendation"]["rationale"])
