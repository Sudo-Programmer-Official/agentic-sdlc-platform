import uuid
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Artifact, Project, Run, RunEvent, WorkItem
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'run-narrative.db'}", future=True)
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
async def test_run_narrative_returns_plan_reflections_and_working_context(db_session):
    session, tenant_id = db_session
    project = Project(name="Narrative", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    started = datetime.utcnow() - timedelta(minutes=3)
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="FAILED",
        executor="codex",
        branch_name="run/auth-fix",
        workspace_status="SEEDED",
        started_at=started,
        finished_at=started + timedelta(seconds=75),
        summary={"goal": "Fix failing auth tests"},
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
        priority=0,
        executor="dummy",
        payload={"title": "Plan auth fix"},
        result={},
        started_at=started,
        finished_at=started + timedelta(seconds=5),
    )
    code_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="CODE_BACKEND",
        key="CODE_BACKEND",
        status="DONE",
        priority=10,
        executor="codex",
        payload={"title": "Patch auth backend"},
        result={"review": {"risk_score": 0.32, "confidence": 0.74, "patch_lines": 12}},
        started_at=started + timedelta(seconds=6),
        finished_at=started + timedelta(seconds=20),
    )
    test_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="RUN_TESTS",
        key="RUN_TESTS",
        status="FAILED",
        priority=20,
        executor="test",
        payload={"title": "Run auth tests"},
        result={},
        last_error="ImportError: missing fixture",
        started_at=started + timedelta(seconds=21),
        finished_at=started + timedelta(seconds=35),
    )
    review_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="REVIEW_DIFF",
        key="REVIEW_DIFF",
        status="QUEUED",
        priority=30,
        executor="dummy",
        payload={"title": "Review generated patch"},
        result={},
    )
    session.add_all([plan_item, code_item, test_item, review_item])
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
                work_item_id=test_item.id,
                event_type="WORK_ITEM_FAILED",
                actor_type="SYSTEM",
                message="Tests failed with an import error.",
                ts=started + timedelta(seconds=35),
            ),
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=run.id,
                work_item_id=test_item.id,
                event_type="WORK_ITEM_RECOVERY",
                actor_type="SYSTEM",
                message="Auto recovery queued FIX_TEST_FAILURE for failed RUN_TESTS.",
                payload={"failure_class": "test_failure"},
                ts=started + timedelta(seconds=40),
            ),
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=run.id,
                event_type="RUN_FAILED",
                actor_type="SYSTEM",
                message="Run failed after validation did not recover.",
                ts=started + timedelta(seconds=75),
            ),
        ]
    )
    session.add(
        Artifact(
            tenant_id=tenant_id,
            project_id=project.id,
            run_id=run.id,
            work_item_id=code_item.id,
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
        response = await client.get(f"/api/v1/runs/{run.id}/narrative")

    assert response.status_code == 200
    data = response.json()
    assert data["run"]["id"] == str(run.id)
    assert data["plan"]["goal"] == "Fix failing auth tests"
    assert data["plan"]["risk_level"] == "HIGH"
    assert data["plan"]["confidence_score"] == 0.74
    assert any(step["title"] == "Patch auth backend" for step in data["plan"]["steps"])
    assert "app/auth.py" in data["plan"]["expected_files"]
    assert "Run auth tests" in data["plan"]["validation_steps"]
    assert data["task_decomposition"]["template_key"] == "test_fix"
    assert data["task_decomposition"]["template_label"] == "Test Fix"
    assert data["task_decomposition"]["requires_confirmation"] is False
    assert len(data["task_decomposition"]["subtasks"]) == 4
    assert data["task_decomposition"]["subtasks"][0]["title"] == "Isolate failure"
    assert data["task_decomposition"]["subtasks"][0]["status"] == "DONE"
    assert data["task_decomposition"]["subtasks"][2]["title"] == "Rerun tests"
    assert data["task_decomposition"]["subtasks"][2]["status"] == "FAILED"
    assert data["task_decomposition"]["subtasks"][2]["retry_scope"] == "subtask"
    assert data["patch_plan"]["primary_files"] == ["app/auth.py"]
    assert data["patch_plan"]["risk_level"] == "HIGH"
    assert "Patch auth backend" in data["patch_plan"]["steps"]
    assert data["verification"]["status"] == "REQUIRES_CONFIRMATION"
    assert data["verification"]["requires_confirmation"] is True
    assert data["verification"]["risk_level"] == "HIGH"
    assert data["verification"]["verified_files"] == ["app/auth.py"]
    assert data["verification"]["actual_files"] == ["app/auth.py"]
    assert data["verification"]["extra_files"] == []
    assert data["verification"]["missing_files"] == []
    assert data["verification"]["scope_match"] is True
    assert any(finding["code"] == "sensitive_scope" for finding in data["verification"]["findings"])

    failed_reflection = next(item for item in data["reflections"] if item["title"] == "Run auth tests")
    assert failed_reflection["matched_plan"] is False
    assert "import error" in failed_reflection["happened"].lower()
    assert "Auto recovery queued" in failed_reflection["changed_next"]

    context = data["working_context"]
    assert context["latest_failure"] == "ImportError: missing fixture"
    assert context["validation_state"] == "FAILED"
    assert context["review_state"] == "PENDING_REVIEW"
    assert context["next_best_step"] == "Queue Review generated patch next."
    assert "app/auth.py" in context["files_touched"]


@pytest.mark.anyio
async def test_run_narrative_treats_superseded_failures_and_skipped_validation_as_healthy(db_session):
    session, tenant_id = db_session
    project = Project(name="Smoke narrative", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    started = datetime.utcnow() - timedelta(minutes=2)
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/smoke",
        workspace_status="SEEDED",
        started_at=started,
        finished_at=started + timedelta(seconds=30),
        summary={"goal": "GitHub smoke commit test"},
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
        priority=0,
        executor="dummy",
        payload={"title": "Plan smoke commit"},
        result={},
        started_at=started,
        finished_at=started + timedelta(seconds=3),
    )
    failed_test_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="RUN_TESTS",
        key="RUN_TESTS_OLD",
        status="FAILED",
        priority=10,
        executor="test",
        payload={"title": "Run smoke validation"},
        result={"superseded": True, "message": "tests failed"},
        last_error="tests failed",
        started_at=started + timedelta(seconds=4),
        finished_at=started + timedelta(seconds=10),
    )
    skipped_test_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="RUN_TESTS",
        key="RUN_TESTS",
        status="SKIPPED",
        priority=20,
        executor="test",
        payload={"title": "Run smoke validation"},
        result={
            "message": "No relevant tests were collected; validation skipped.",
            "skip_reason": "no_tests_collected",
        },
        started_at=started + timedelta(seconds=11),
        finished_at=started + timedelta(seconds=14),
    )
    review_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="REVIEW_INTEGRATION",
        key="REVIEW_INTEGRATION",
        status="DONE",
        priority=30,
        executor="dummy",
        payload={"title": "Confirm smoke integration"},
        result={},
        started_at=started + timedelta(seconds=15),
        finished_at=started + timedelta(seconds=20),
    )
    session.add_all([plan_item, failed_test_item, skipped_test_item, review_item])
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
                work_item_id=failed_test_item.id,
                event_type="WORK_ITEM_FAILED",
                actor_type="SYSTEM",
                message="Tests failed before the retry path was created.",
                ts=started + timedelta(seconds=10),
            ),
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=run.id,
                work_item_id=failed_test_item.id,
                event_type="WORK_ITEM_RECOVERY",
                actor_type="SYSTEM",
                message="Recovery queued RUN_TESTS retry after FIX_TEST_FAILURE.",
                ts=started + timedelta(seconds=11),
            ),
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=run.id,
                work_item_id=skipped_test_item.id,
                event_type="WORK_ITEM_SKIPPED",
                actor_type="SYSTEM",
                message="No relevant tests were collected; validation skipped.",
                ts=started + timedelta(seconds=14),
            ),
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=run.id,
                event_type="RUN_COMPLETED",
                actor_type="SYSTEM",
                ts=started + timedelta(seconds=30),
            ),
        ]
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/runs/{run.id}/narrative")

    assert response.status_code == 200
    data = response.json()
    context = data["working_context"]
    assert context["latest_failure"] is None
    assert context["validation_state"] == "PASSED"
    assert context["review_state"] == "REVIEWED"
    assert context["next_best_step"] == "Open the review surface and create a pull request."

    skipped_reflection = next(item for item in data["reflections"] if item["work_item_id"] == str(skipped_test_item.id))
    assert skipped_reflection["status"] == "SKIPPED"
    assert skipped_reflection["matched_plan"] is True
    assert "validation skipped" in skipped_reflection["happened"].lower()

    rerun_subtask = next(item for item in data["task_decomposition"]["subtasks"] if item["title"] == "Rerun tests")
    assert rerun_subtask["status"] == "SKIPPED"


@pytest.mark.anyio
async def test_run_narrative_surfaces_optional_review_failures_as_warnings(db_session):
    session, tenant_id = db_session
    project = Project(name="Optional warning narrative", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    started = datetime.utcnow() - timedelta(minutes=1)
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/optional-warning",
        workspace_status="SEEDED",
        started_at=started,
        finished_at=started + timedelta(seconds=40),
        summary={"goal": "Optional preview review warning"},
    )
    session.add(run)
    await session.flush()

    session.add_all(
        [
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=run.id,
                type="PLAN_DAG",
                key="PLAN_DAG",
                status="DONE",
                priority=0,
                executor="dummy",
                payload={"title": "Plan warning path"},
                result={},
                started_at=started,
                finished_at=started + timedelta(seconds=3),
            ),
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=run.id,
                type="CODE_BACKEND",
                key="CODE_BACKEND",
                status="DONE",
                priority=10,
                executor="codex",
                payload={"title": "Patch backend"},
                result={},
                started_at=started + timedelta(seconds=4),
                finished_at=started + timedelta(seconds=10),
            ),
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=run.id,
                type="RUN_TESTS",
                key="RUN_TESTS",
                status="DONE",
                priority=20,
                executor="test",
                payload={"title": "Run validation"},
                result={"exit_code": 0, "stdout": "ok", "stderr": ""},
                started_at=started + timedelta(seconds=11),
                finished_at=started + timedelta(seconds=18),
            ),
        ]
    )
    await session.flush()

    optional_review_item = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="REVIEW_INTEGRATION",
        key="REVIEW_INTEGRATION",
        status="FAILED",
        priority=30,
        executor="dummy",
        payload={"title": "Confirm preview integration", "blocking": False},
        result={"reason": "preview_unavailable"},
        last_error="Preview environment was unavailable.",
        started_at=started + timedelta(seconds=19),
        finished_at=started + timedelta(seconds=25),
    )
    session.add(optional_review_item)
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
                work_item_id=optional_review_item.id,
                event_type="WORK_ITEM_FAILED",
                actor_type="SYSTEM",
                message="Preview environment was unavailable.",
                ts=started + timedelta(seconds=25),
            ),
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=run.id,
                event_type="RUN_COMPLETED",
                actor_type="SYSTEM",
                ts=started + timedelta(seconds=40),
            ),
        ]
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/runs/{run.id}/narrative")

    assert response.status_code == 200
    data = response.json()
    context = data["working_context"]
    assert context["latest_failure"] is None
    assert context["latest_warning"] == "Preview environment was unavailable."
    assert context["blocking_failure_count"] == 0
    assert context["warning_failure_count"] == 1
    assert context["validation_state"] == "PASSED_WITH_WARNINGS"
    assert context["review_state"] == "REVIEWED_WITH_WARNINGS"
    assert context["next_best_step"] == "Review the warning and decide whether to continue with pull request creation."

    optional_reflection = next(item for item in data["reflections"] if item["work_item_id"] == str(optional_review_item.id))
    assert optional_reflection["status"] == "FAILED"
    assert optional_reflection["blocking"] is False
    assert "remaining delivery steps can still continue" in optional_reflection["changed_next"].lower()

    review_subtask = next(item for item in data["task_decomposition"]["subtasks"] if item["title"] == "Review delivery")
    assert review_subtask["status"] == "WARNING"
    assert review_subtask["blocking"] is False
