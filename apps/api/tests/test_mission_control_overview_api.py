import uuid
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Approval, Artifact, Document, Project, ProjectPreviewProfile, ProjectRepository, Run, Task
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mission-control-overview.db'}", future=True)
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
async def test_mission_control_overview_returns_intake_impact_and_insights(db_session):
    session, tenant_id = db_session
    project = Project(name="Mission control", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="https://github.com/acme/example.git",
            repo_full_name="acme/example",
            default_branch="main",
        )
    )
    session.add(
        ProjectPreviewProfile(
            project_id=project.id,
            tenant_id=tenant_id,
            enabled=True,
            mode="local",
            frontend_root="apps/web",
            backend_root="apps/api",
            frontend_start_command="npm run dev",
            backend_start_command="uvicorn app.main:app --host $HOST --port $PORT",
            ttl_hours=24,
        )
    )

    document = Document(
        tenant_id=tenant_id,
        project_id=project.id,
        type="PRD",
        version=1,
        title="Fix authentication test failure",
        body="GET /login returns 500 when auth fixture is missing. Update auth flow and tests.",
        source="manual",
        created_by="ui-user",
    )
    session.add(document)
    await session.flush()

    session.add(
        Task(
            tenant_id=tenant_id,
            project_id=project.id,
            document_id=document.id,
            title="Inspect auth service and update failing tests",
            category="func",
            stage="PLAN",
            status="PENDING",
            source="manual",
            created_by="ui-user",
        )
    )

    started = datetime.utcnow() - timedelta(minutes=6)
    older_run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/minimal-patch",
        workspace_status="SEEDED",
        started_at=started,
        finished_at=started + timedelta(seconds=70),
        summary={
            "goal": "Fix failing auth tests with a minimal patch",
            "strategy_type": "minimal_patch",
            "strategy_label": "Minimal Patch",
        },
    )
    latest_run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/auth-fix",
        workspace_status="SEEDED",
        started_at=started + timedelta(minutes=2),
        finished_at=started + timedelta(minutes=2, seconds=84),
        summary={
            "goal": "Fix failing auth tests and open a PR",
            "pull_request_url": "https://github.com/acme/example/pull/42",
            "pull_request_number": 42,
            "strategy_type": "minimal_patch",
            "strategy_label": "Minimal Patch",
            "preview": {
                "status": "READY",
                "mode": "local",
                "preview_url": "http://127.0.0.1:3100",
                "frontend": {"url": "http://127.0.0.1:3100"},
                "backend": {"url": "http://127.0.0.1:8100"},
                "expires_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            },
        },
    )
    session.add_all([older_run, latest_run])
    await session.flush()

    patch = (
        "diff --git a/app/auth_service.py b/app/auth_service.py\n"
        "--- a/app/auth_service.py\n"
        "+++ b/app/auth_service.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
        "diff --git a/tests/test_auth.py b/tests/test_auth.py\n"
        "--- a/tests/test_auth.py\n"
        "+++ b/tests/test_auth.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )

    patch_artifact = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        run_id=latest_run.id,
        type="git_diff",
        uri="workspace://patches/auth.patch",
        version=1,
        extra_metadata={"content": patch},
    )
    pr_artifact = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        run_id=latest_run.id,
        type="pull_request",
        uri="https://github.com/acme/example/pull/42",
        version=1,
        extra_metadata={"number": 42},
    )
    older_patch = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        run_id=older_run.id,
        type="git_diff",
        uri="workspace://patches/older.patch",
        version=1,
        extra_metadata={"content": patch},
    )
    session.add_all([patch_artifact, pr_artifact, older_patch])
    await session.flush()

    session.add(
        Approval(
            tenant_id=tenant_id,
            project_id=project.id,
            target_type="artifact",
            target_id=patch_artifact.id,
            status="APPROVED",
            decided_by="reviewer",
            decided_at=datetime.utcnow().isoformat(),
            comment="Looks safe",
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/mission-control/overview")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["work_intake"]
    assert data["work_intake"][0]["title"] == "Fix authentication test failure"
    assert "auth_service.py" in ",".join(data["work_intake"][0]["predicted_files"])
    assert data["recent_runs"][0]["run_id"] == str(latest_run.id)
    assert data["recent_runs"][0]["approval_status"] == "APPROVED"
    assert data["latest_change_impact"]["run_id"] == str(latest_run.id)
    assert "auth_service" in data["latest_change_impact"]["modules_impacted"]
    assert "tests/test_auth.py" in data["latest_change_impact"]["tests_impacted"]
    assert "GET /login" in data["latest_change_impact"]["api_impact"]
    assert data["previews_and_prs"]["repository_connected"] is True
    assert data["previews_and_prs"]["profile_configured"] is True
    assert data["previews_and_prs"]["preview_status"] == "READY"
    assert data["previews_and_prs"]["preview_url"] == "http://127.0.0.1:3100"
    assert data["previews_and_prs"]["frontend_url"] == "http://127.0.0.1:3100"
    assert data["previews_and_prs"]["backend_url"] == "http://127.0.0.1:8100"
    assert data["previews_and_prs"]["pull_request_url"] == "https://github.com/acme/example/pull/42"
    assert data["previews_and_prs"]["approval_status"] == "APPROVED"
    assert data["strategy_learning"][0]["label"] == "Minimal Patch"
    assert data["system_insights"]["total_runs"] == 2
    assert data["system_insights"]["successful_runs"] == 2
    assert data["system_insights"]["total_pull_requests"] == 1
