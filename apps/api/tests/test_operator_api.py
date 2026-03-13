import uuid
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Artifact, Project, ProjectRepository, Run, RunEvent, WorkItem
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'operator-api.db'}", future=True)
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
async def test_operator_project_status_is_grounded(db_session):
    session, tenant_id = db_session
    project = Project(name="Operator project", description="summary", tenant_id=tenant_id, status="PLAN")
    session.add(project)
    await session.commit()
    await session.refresh(project)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ai/operator",
            json={"project_id": str(project.id), "message": "What is going on in this project?", "context": {}},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "project_status"
    assert "Facts:" in data["answer"]
    assert data["grounding_tools"] == ["get_current_project"]
    assert data["tool_results"]["get_current_project"]["name"] == "Operator project"
    assert any(ref["path"] == f"/projects/{project.id}/run" for ref in data["references"])
    assert any(action["type"] == "open_project" for action in data["actions"])


@pytest.mark.anyio
async def test_operator_explains_latest_run_failure(db_session):
    session, tenant_id = db_session
    project = Project(name="Failure project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="FAILED",
        executor="codex",
        started_at=datetime.utcnow() - timedelta(minutes=3),
        finished_at=datetime.utcnow() - timedelta(minutes=2),
    )
    session.add(run)
    await session.flush()
    session.add(
        RunEvent(
            tenant_id=tenant_id,
            project_id=project.id,
            run_id=run.id,
            event_type="WORK_ITEM_FAILED",
            actor_type="SYSTEM",
            message="auth.test.js failed with session validation error",
            payload={"failure_class": "test_failure"},
        )
    )
    session.add(
        WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="RUN_TESTS",
            key="RUN_TESTS",
            status="FAILED",
            priority=10,
            executor="test",
            payload={"title": "Run auth tests"},
            result={"stderr": "session validation error"},
            last_error="session validation error",
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ai/operator",
            json={"project_id": str(project.id), "message": "Why did the latest run fail?", "context": {}},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "run_debug"
    assert "Primary error" in data["answer"]
    assert "session validation error" in data["answer"]
    assert data["grounding_tools"] == ["get_latest_run"]
    assert any(action["type"] == "open_run_replay" for action in data["actions"])


@pytest.mark.anyio
async def test_operator_explains_latest_patch_artifact(db_session):
    session, tenant_id = db_session
    project = Project(name="Artifact project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    run = Run(project_id=project.id, tenant_id=tenant_id, status="COMPLETED", executor="codex")
    session.add(run)
    await session.flush()
    artifact = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        run_id=run.id,
        type="git_diff",
        uri="memory://patch.diff",
        version=1,
        extra_metadata={
            "content": """diff --git a/auth_service.py b/auth_service.py
index 1111111..2222222 100644
--- a/auth_service.py
+++ b/auth_service.py
@@ -1,1 +1,2 @@
-print('old')
+print('new')
+print('extra')
"""
        },
    )
    session.add(artifact)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ai/operator",
            json={"project_id": str(project.id), "message": "Explain the latest patch", "context": {}},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "artifact_explain"
    assert "Changed files" in data["answer"]
    assert data["grounding_tools"] == ["explain_artifact"]
    assert any(ref["type"] == "artifact" for ref in data["references"])


@pytest.mark.anyio
async def test_operator_compares_last_two_runs(db_session):
    session, tenant_id = db_session
    project = Project(name="Compare project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    base = datetime.utcnow() - timedelta(minutes=10)
    newer = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        started_at=base + timedelta(minutes=5),
        finished_at=base + timedelta(minutes=7),
        summary={"pull_request_url": "https://github.com/acme/example/pull/11"},
    )
    older = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="FAILED",
        executor="codex",
        started_at=base,
        finished_at=base + timedelta(minutes=4),
    )
    session.add_all([newer, older])
    await session.flush()

    session.add_all(
        [
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=newer.id,
                type="RUN_TESTS",
                key="RUN_TESTS",
                status="DONE",
                priority=10,
                executor="test",
                payload={"title": "Run tests"},
                result={"stdout": "passed"},
            ),
            WorkItem(
                project_id=project.id,
                tenant_id=tenant_id,
                run_id=older.id,
                type="RUN_TESTS",
                key="RUN_TESTS",
                status="FAILED",
                priority=10,
                executor="test",
                payload={"title": "Run tests"},
                result={"stderr": "failed"},
                last_error="failed",
            ),
            Artifact(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=newer.id,
                type="pull_request",
                uri="https://github.com/acme/example/pull/11",
                version=1,
                extra_metadata={"number": 11},
            ),
        ]
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ai/operator",
            json={"project_id": str(project.id), "message": "Compare the last two runs", "context": {}},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "run_comparison"
    assert "Facts:" in data["answer"]
    assert data["grounding_tools"] == ["compare_runs"]
    assert any(action["type"] == "open_run_compare" for action in data["actions"])


@pytest.mark.anyio
async def test_operator_reports_workspace_status(db_session):
    session, tenant_id = db_session
    project = Project(name="Workspace project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="RUNNING",
        executor="codex",
        workspace_status="READY",
        workspace_root="/tmp/workspaces/run-1",
        repo_path="/tmp/workspaces/run-1/repo",
        branch_name="feature/operator",
    )
    session.add(run)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ai/operator",
            json={
                "project_id": str(project.id),
                "message": "Show workspace status",
                "context": {"run_id": str(run.id)},
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "workspace_status"
    assert data["grounding_tools"] == ["get_workspace_status"]
    assert data["tool_results"]["get_workspace_status"]["workspace_status"] == "READY"
    assert any(action["type"] == "open_run_replay" for action in data["actions"])


@pytest.mark.anyio
async def test_operator_reports_project_health(db_session):
    session, tenant_id = db_session
    project = Project(name="Health project", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ai/operator",
            json={"project_id": str(project.id), "message": "Show project health", "context": {}},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "project_health"
    assert data["grounding_tools"] == ["get_project_health"]
    assert "No major structural issues" in data["answer"]


@pytest.mark.anyio
async def test_operator_can_search_repo_map(db_session, tmp_path):
    session, tenant_id = db_session
    repo_root = tmp_path / "repo"
    (repo_root / "src/components").mkdir(parents=True, exist_ok=True)
    (repo_root / "src/views").mkdir(parents=True, exist_ok=True)
    (repo_root / "src/components/LoginButton.vue").write_text("<button>Login</button>\n", encoding="utf-8")
    (repo_root / "src/views/LoginPage.vue").write_text("<template><LoginButton /></template>\n", encoding="utf-8")
    (repo_root / "src/services").mkdir(parents=True, exist_ok=True)
    (repo_root / "src/services/authService.ts").write_text("export function login() {}\n", encoding="utf-8")

    project = Project(name="Repo search", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="https://github.com/acme/plancraft.git",
            repo_full_name="acme/plancraft",
            default_branch="main",
        )
    )
    session.add(
        Run(
            project_id=project.id,
            tenant_id=tenant_id,
            status="COMPLETED",
            executor="codex",
            repo_path=str(repo_root),
            workspace_status="SEEDED",
            branch_name="main",
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ai/operator",
            json={"project_id": str(project.id), "message": "Find the login component", "context": {}},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "repo_context"
    assert data["grounding_tools"] == ["search_repo_map"]
    assert data["tool_results"]["search_repo_map"]["matches"][0]["path"] in {
        "src/components/LoginButton.vue",
        "src/views/LoginPage.vue",
    }
    assert any(ref["type"] == "file" for ref in data["references"])


@pytest.mark.anyio
async def test_operator_handles_unknown_requests_gracefully(db_session):
    session, tenant_id = db_session
    project = Project(name="Unknown project", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ai/operator",
            json={"project_id": str(project.id), "message": "Can you deploy this to production?", "context": {}},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "unknown"
    assert data["status"] == "unsupported"
    assert "I can help with project status" in data["answer"]
