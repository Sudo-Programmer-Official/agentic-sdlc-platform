import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import AIArtifactCache, AIJobRun, Project, ProjectRepository, RepoFile, RepoSnapshot
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app
from app.services.ai_policy import AIJobManager, AIJobRequest


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ai-ops.db'}", future=True)
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
async def test_ai_ops_dashboard_reports_feature_surface_and_context_pack_metrics(db_session):
    session, tenant_id = db_session
    project = Project(name="AI Ops Project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    repository = ProjectRepository(
        tenant_id=tenant_id,
        project_id=project.id,
        repo_url="https://github.com/acme/platform",
        repo_full_name="acme/platform",
        default_branch="main",
    )
    session.add(repository)
    await session.flush()

    session.add_all(
        [
            AIJobRun(
                tenant_id=tenant_id,
                project_id=project.id,
                repository_id=repository.id,
                workflow_type="repo_implementation_task",
                feature_key="auth-login",
                surface="frontend",
                entrypoint="runtime.codex_executor",
                role="coder",
                task_type="implementation",
                ambiguity_level="medium",
                risk_level="medium",
                max_model_tier="tier_standard",
                selected_model_tier="tier_standard",
                context_size=240,
                call_count=1,
                tokens_input=120,
                tokens_output=24,
                estimated_cost_cents=1.1,
                actual_cost_cents=1.1,
                status="completed",
                details_json={"context_pack": {"key": "auth-login", "hash": "pack-auth", "pack_cache_hit": False}},
            ),
            AIJobRun(
                tenant_id=tenant_id,
                project_id=project.id,
                repository_id=repository.id,
                workflow_type="repo_implementation_task",
                feature_key="auth-login",
                surface="backend",
                entrypoint="runtime.codex_executor",
                role="coder",
                task_type="bugfix",
                ambiguity_level="medium",
                risk_level="medium",
                max_model_tier="tier_standard",
                selected_model_tier="tier_standard",
                context_size=180,
                call_count=2,
                retry_count=1,
                tokens_input=90,
                tokens_output=18,
                estimated_cost_cents=0.9,
                actual_cost_cents=0.9,
                status="completed",
                details_json={"context_pack": {"key": "auth-login", "hash": "pack-auth", "pack_cache_hit": True}},
            ),
        ]
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/ai/ops/dashboard?project_id={project.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["unique_context_packs"] == 1
    assert data["summary"]["context_pack_reuse_rate"] == 0.5
    assert data["spend_by_feature"][0]["key"] == "auth-login"
    assert data["spend_by_feature"][0]["job_count"] == 2
    assert data["spend_by_surface"][0]["key"] in {"frontend", "backend"}
    assert data["recent_jobs"][0]["feature_key"] == "auth-login"
    assert data["recent_jobs"][0]["entrypoint"] == "runtime.codex_executor"


@pytest.mark.anyio
async def test_load_context_pack_reuses_cached_pack(db_session):
    session, tenant_id = db_session
    project = Project(name="Context Pack Project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    repository = ProjectRepository(
        tenant_id=tenant_id,
        project_id=project.id,
        repo_url="https://github.com/acme/context-pack",
        repo_full_name="acme/context-pack",
        default_branch="main",
    )
    session.add(repository)
    session.add(
        RepoSnapshot(
            tenant_id=tenant_id,
            project_id=project.id,
            file_count=12,
            symbol_count=24,
            edge_count=6,
        )
    )
    session.add(
        RepoFile(
            tenant_id=tenant_id,
            project_id=project.id,
            path="README.md",
            kind="documentation",
            summary="Project README with setup and usage notes.",
            features=["setup"],
            size_bytes=120,
        )
    )
    await session.commit()

    manager = AIJobManager.from_session(session)
    request = AIJobRequest(
        workflow_type="repo_implementation_task",
        role="coder",
        task_type="implementation",
        ambiguity_level="medium",
        risk_level="medium",
        tenant_id=tenant_id,
        project_id=project.id,
        repository_id=repository.id,
        feature_key="auth-login",
        surface="frontend",
        entrypoint="runtime.codex_executor",
        changed_files=["apps/web/src/views/LoginView.vue"],
    )

    first = await manager.load_context_pack(request, session=session)
    second = await manager.load_context_pack(request, session=session)
    await session.commit()

    packs = (
        await session.execute(select(AIArtifactCache).where(AIArtifactCache.cache_scope == "context_pack"))
    ).scalars().all()

    assert first.pack_cache_hit is False
    assert second.pack_cache_hit is True
    assert first.pack_hash == second.pack_hash
    assert "feature_scope" in first.fragments
    assert any(key in first.fragments for key in {"repo_summary", "conventions"})
    assert len(packs) == 1
