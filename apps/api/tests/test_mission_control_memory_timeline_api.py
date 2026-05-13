import uuid
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import (
    Document,
    ImprovementRequest,
    MemorySummaryArtifact,
    Project,
    ProjectEvolutionEvent,
    RecoveryAttempt,
    Run,
    RunEvent,
    RunSummary,
    Task,
)
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mission-control-memory.db'}", future=True)
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
async def test_project_memory_timeline_returns_and_persists_events(db_session):
    session, tenant_id = db_session
    project = Project(name="Timeline", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    started = datetime.utcnow() - timedelta(minutes=10)
    run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="FAILED",
        executor="codex",
        branch_name="run/timeline",
        workspace_status="ERROR",
        started_at=started,
        finished_at=started + timedelta(minutes=2),
    )
    session.add(run)
    await session.flush()

    session.add_all(
        [
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=run.id,
                event_type="RUN_FAILED",
                ts=started + timedelta(minutes=2),
                message="Validation failed",
            ),
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=run.id,
                event_type="WORK_ITEM_RECOVERY",
                ts=started + timedelta(minutes=2, seconds=20),
                message="Queued recovery step",
            ),
        ]
    )

    session.add(
        RecoveryAttempt(
            tenant_id=tenant_id,
            project_id=project.id,
            run_id=run.id,
            failure_type="test_failed",
            recovery_action="retry_with_smaller_patch",
            attempt_number=1,
            result="succeeded",
            rationale="Narrow scope",
        )
    )
    session.add(
        Document(
            tenant_id=tenant_id,
            project_id=project.id,
            type="requirements",
            version=1,
            title="Homepage redesign",
            body="Add hero and mobile fixes",
            source="manual",
            created_by="ui-user",
        )
    )
    session.add(
        ImprovementRequest(
            tenant_id=tenant_id,
            project_id=project.id,
            source_run_id=run.id,
            source_requirement_id="FR-001",
            goal_text="Fix mobile validation",
            issue_text="Layout overflows on small screens",
            status="CREATED",
        )
    )
    session.add(
        Task(
            tenant_id=tenant_id,
            project_id=project.id,
            run_id=run.id,
            title="Fix mobile validation issue",
            category="func",
            stage="RUN",
            status="PENDING",
            source="manual",
            created_by="ui-user",
            requirement_id="FR-001",
        )
    )
    session.add(
        RunSummary(
            run_id=run.id,
            tenant_id=tenant_id,
            project_id=project.id,
            status="FAILED",
            executor="codex",
            workspace_status="ERROR",
            pr_created=True,
            pr_url="https://github.com/acme/example/pull/123",
            pull_request_number=123,
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/memory/timeline?limit=25")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["items"]
    domains = {item["domain"] for item in payload["items"]}
    assert "run" in domains
    assert "recovery" in domains
    assert "requirement" in domains
    assert "improvement" in domains
    assert "deployment" in domains
    assert any(item.get("retention_class") in {"keep", "compress", "discard"} for item in payload["items"])
    assert any(item.get("requirement_id") == "FR-001" for item in payload["items"])

    persisted_count = (
        await session.execute(
            select(ProjectEvolutionEvent).where(
                ProjectEvolutionEvent.project_id == project.id,
                ProjectEvolutionEvent.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    assert len(persisted_count) > 0

    # second call should not duplicate persisted rows
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        second = await client.get(f"/api/v1/projects/{project.id}/memory/timeline?limit=25")
    assert second.status_code == 200, second.text
    persisted_again = (
        await session.execute(
            select(ProjectEvolutionEvent).where(
                ProjectEvolutionEvent.project_id == project.id,
                ProjectEvolutionEvent.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    assert len(persisted_again) == len(persisted_count)


@pytest.mark.anyio
async def test_project_memory_timeline_backfill_endpoint_is_idempotent(db_session):
    session, tenant_id = db_session
    project = Project(name="Timeline backfill", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/backfill",
        workspace_status="SEEDED",
    )
    session.add(run)
    await session.flush()
    session.add(
        RunEvent(
            tenant_id=tenant_id,
            project_id=project.id,
            run_id=run.id,
            event_type="RUN_COMPLETED",
            message="Done",
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(f"/api/v1/projects/{project.id}/memory/timeline/backfill?limit=100")
        second = await client.post(f"/api/v1/projects/{project.id}/memory/timeline/backfill?limit=100")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["inserted_count"] >= 1
    assert second_payload["inserted_count"] == 0
    assert second_payload["after_count"] == first_payload["after_count"]


@pytest.mark.anyio
async def test_project_memory_timeline_handles_long_requirement_document_titles(db_session):
    session, tenant_id = db_session
    project = Project(name="Timeline long title", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    session.add(
        Document(
            tenant_id=tenant_id,
            project_id=project.id,
            type="requirements",
            version=1,
            title="Build a responsive personal portfolio web app with Home, About, Projects, Contact, a robust mobile menu, accessibility-first semantics, and extended validation coverage to prove end-to-end runtime reliability under long requirement narratives",
            body="Long title regression case",
            source="manual",
            created_by="ui-user",
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/memory/timeline?limit=20")
    assert response.status_code == 200, response.text

    persisted = (
        await session.execute(
            select(ProjectEvolutionEvent).where(
                ProjectEvolutionEvent.project_id == project.id,
                ProjectEvolutionEvent.tenant_id == tenant_id,
                ProjectEvolutionEvent.domain == "requirement",
            )
        )
    ).scalars().all()
    assert persisted
    assert all(len(row.title) <= 220 for row in persisted)


@pytest.mark.anyio
async def test_project_memory_summaries_and_explain_api(db_session):
    session, tenant_id = db_session
    project = Project(name="Timeline intelligence", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="FAILED",
        executor="codex",
        requirement_id="FR-777",
        workspace_status="ERROR",
    )
    session.add(run)
    await session.flush()

    session.add_all(
        [
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=run.id,
                event_type="RUN_FAILED",
                message="Schema drift",
            ),
            RunEvent(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=run.id,
                event_type="WORK_ITEM_RECOVERY",
                message="Retry queued",
            ),
        ]
    )
    session.add(
        ImprovementRequest(
            tenant_id=tenant_id,
            project_id=project.id,
            source_run_id=run.id,
            source_requirement_id="FR-777",
            issue_text="Regression on checkout flow",
            status="CREATED",
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        backfill = await client.post(f"/api/v1/projects/{project.id}/memory/timeline/backfill?limit=120")
        assert backfill.status_code == 200, backfill.text

        materialize = await client.post(f"/api/v1/projects/{project.id}/memory/summaries/materialize")
        assert materialize.status_code == 200, materialize.text
        materialize_payload = materialize.json()
        assert materialize_payload["items"]

        summaries = await client.get(f"/api/v1/projects/{project.id}/memory/summaries")
        assert summaries.status_code == 200, summaries.text
        summary_payload = summaries.json()
        assert summary_payload["items"]
        assert any(item["summary_type"] == "project_evolution_daily" for item in summary_payload["items"])
        daily = next((item for item in summary_payload["items"] if item["summary_type"] == "project_evolution_daily"), None)
        assert daily is not None
        assert daily["payload"].get("synthesis_version") == "v1"
        assert "source_event_window" in daily["payload"]
        assert daily["payload"].get("compression_strategy") == "daily_operational_summary"

        explain = await client.get(f"/api/v1/projects/{project.id}/memory/explain?requirement_id=FR-777&limit=25")
        assert explain.status_code == 200, explain.text
        explain_payload = explain.json()
        assert explain_payload["top_causes"]
        assert explain_payload["linked_events"]
        assert "FR-777" in explain_payload["linked_requirements"]

        understanding = await client.get(f"/api/v1/projects/{project.id}/memory/project-understanding")
        assert understanding.status_code == 200, understanding.text
        understanding_payload = understanding.json()
        assert understanding_payload["project_id"] == str(project.id)
        assert isinstance(understanding_payload["summary_artifact_count"], int)
        assert isinstance(understanding_payload["latest_summaries"], dict)

    persisted_summaries = (
        await session.execute(
            select(MemorySummaryArtifact).where(
                MemorySummaryArtifact.project_id == project.id,
                MemorySummaryArtifact.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    assert len(persisted_summaries) > 0
