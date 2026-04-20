import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Project, ProjectPreviewProfile, ProjectRepository, RepoFile
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'architecture-profile.db'}", future=True)
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
async def test_architecture_profile_bootstrap_and_summary_endpoints(db_session):
    session, tenant_id = db_session
    project = Project(name="External repo project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/external-monorepo.git",
            repo_full_name="acme/external-monorepo",
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
            frontend_build_command="npm -C apps/web run build",
            backend_build_command="python3 -m pytest -q apps/api/tests",
        )
    )
    session.add_all(
        [
            RepoFile(
                tenant_id=tenant_id,
                project_id=project.id,
                path="apps/web/package.json",
                language="json",
                kind="config",
                summary="frontend package",
            ),
            RepoFile(
                tenant_id=tenant_id,
                project_id=project.id,
                path="apps/web/src/views/Home.vue",
                language="vue",
                kind="page_view",
                summary="homepage view",
            ),
            RepoFile(
                tenant_id=tenant_id,
                project_id=project.id,
                path="apps/api/pyproject.toml",
                language="toml",
                kind="config",
                summary="api config",
            ),
            RepoFile(
                tenant_id=tenant_id,
                project_id=project.id,
                path="apps/api/app/db/models/user.py",
                language="python",
                kind="backend_module",
                summary="db model",
            ),
            RepoFile(
                tenant_id=tenant_id,
                project_id=project.id,
                path="infra/docker-compose.yml",
                language="yaml",
                kind="config",
                summary="infra compose",
            ),
        ]
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bootstrap_response = await client.post(
            f"/api/v1/projects/{project.id}/architecture-profile/bootstrap",
            json={"refresh_repo_map": False, "created_by": "ui-user"},
        )
        assert bootstrap_response.status_code == 200, bootstrap_response.text
        bootstrap = bootstrap_response.json()
        packages = bootstrap["profile_json"]["repo_layout"]["packages"]
        assert any(item["name"] == "apps/web" for item in packages)
        assert any(item["name"] == "apps/api" for item in packages)
        assert "apps/api/app/db/models" in bootstrap["derived_json"]["protected_zone_index"]

        summary_response = await client.get(f"/api/v1/projects/{project.id}/architecture-profile/summary")
        assert summary_response.status_code == 200, summary_response.text
        summary = summary_response.json()
        assert summary["profile_exists"] is True
        assert summary["monorepo"] is True
        assert summary["package_count"] >= 2
        assert "frontend_build" in summary["commands"]
        assert "apps/api/app/db/models" in summary["protected_zones"]

        project_summary_response = await client.get(f"/api/v1/projects/{project.id}/summary")
        assert project_summary_response.status_code == 200, project_summary_response.text
        project_summary = project_summary_response.json()
        assert project_summary["architecture_profile"]["profile_exists"] is True
        assert project_summary["architecture_profile"]["repo_full_name"] == "acme/external-monorepo"


@pytest.mark.anyio
async def test_architecture_profile_patch_merges_sections_and_rederives(db_session):
    session, tenant_id = db_session
    project = Project(name="Patchable architecture", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="https://github.com/acme/patchable.git",
            repo_full_name="acme/patchable",
            default_branch="main",
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bootstrap_response = await client.post(
            f"/api/v1/projects/{project.id}/architecture-profile/bootstrap",
            json={"created_by": "ui-user"},
        )
        assert bootstrap_response.status_code == 200, bootstrap_response.text
        version_before = bootstrap_response.json()["version"]

        patch_response = await client.patch(
            f"/api/v1/projects/{project.id}/architecture-profile",
            json={
                "summary": "Manual contract for bounded frontend execution.",
                "sections": {
                    "safe_refactor_zones": ["apps/web/src/views"],
                    "do_not_touch_zones": [{"path": "apps/web/src/admin", "reason": "approval required"}],
                },
                "updated_by": "ui-user",
            },
        )
        assert patch_response.status_code == 200, patch_response.text
        patched = patch_response.json()
        assert patched["version"] == version_before + 1
        assert patched["summary"] == "Manual contract for bounded frontend execution."
        assert patched["derived_json"]["safe_zone_index"]["apps/web/src/views"]["editable"] is True
        assert patched["derived_json"]["protected_zone_index"]["apps/web/src/admin"]["approval_required"] is True
