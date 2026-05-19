import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Project, ProjectBlueprint, ProjectPreviewProfile, ProjectRepository, RepoFile
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
        assert "repo_intelligence" in summary["derived_from"]
        assert summary["derivation_confidence"] in {"MEDIUM", "HIGH"}

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


@pytest.mark.anyio
async def test_architecture_profile_derive_normalizes_integrations_and_environment_assumptions(db_session):
    session, tenant_id = db_session
    project = Project(name="Derive normalize", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="https://github.com/acme/normalize.git",
            repo_full_name="acme/normalize",
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
                path="apps/api/pyproject.toml",
                language="toml",
                kind="config",
                summary="api config",
            ),
        ]
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bootstrap_response = await client.post(
            f"/api/v1/projects/{project.id}/architecture-profile/bootstrap",
            json={"created_by": "ui-user"},
        )
        assert bootstrap_response.status_code == 200, bootstrap_response.text

        patch_response = await client.patch(
            f"/api/v1/projects/{project.id}/architecture-profile",
            json={
                "sections": {
                    "integrations": [
                        {"name": "repository", "provider": None, "repo_full_name": None, "default_branch": None},
                        {"name": "repository", "provider": "github", "repo_full_name": "acme/normalize", "default_branch": "main"},
                    ],
                    "environment_assumptions": {
                        "repo_connected": False,
                        "preview_profile_configured": False,
                        "frontend_root": None,
                        "backend_root": None,
                    },
                },
                "updated_by": "ui-user",
            },
        )
        assert patch_response.status_code == 200, patch_response.text

        derive_response = await client.post(
            f"/api/v1/projects/{project.id}/architecture-profile/derive",
            json={"updated_by": "ui-user"},
        )
        assert derive_response.status_code == 200, derive_response.text
        payload = derive_response.json()
        integrations = payload["profile_json"]["integrations"]
        assert len(integrations) == 2
        assert integrations[0]["name"] == "repository"
        assert integrations[0]["provider"] == "github"
        assert integrations[0]["repo_full_name"] == "acme/normalize"
        assert integrations[1]["name"] == "preview"
        assert integrations[1]["frontend_root"] == "apps/web"
        assert integrations[1]["backend_root"] == "apps/api"
        assumptions = payload["profile_json"]["environment_assumptions"]
        assert assumptions["repo_connected"] is True
        assert assumptions["preview_profile_configured"] is True
        assert assumptions["frontend_root"] == "apps/web"
        assert assumptions["backend_root"] == "apps/api"
        diagnostics = payload["profile_json"]["contract_diagnostics"]
        assert diagnostics["warnings"] == []


@pytest.mark.anyio
async def test_architecture_profile_fix_drift_preview_and_apply(db_session):
    session, tenant_id = db_session
    project = Project(name="Fix drift project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="https://github.com/acme/fix-drift.git",
            repo_full_name="acme/fix-drift",
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
                "sections": {
                    "integrations": [
                        {"name": "repository", "provider": None, "repo_full_name": None, "default_branch": None},
                        {"name": "repository", "provider": "github", "repo_full_name": "acme/fix-drift", "default_branch": "main"},
                    ],
                },
                "updated_by": "ui-user",
            },
        )
        assert patch_response.status_code == 200, patch_response.text

        preview_response = await client.post(
            f"/api/v1/projects/{project.id}/architecture-profile/fix-drift",
        )
        assert preview_response.status_code == 200, preview_response.text
        preview_payload = preview_response.json()
        assert preview_payload["changed"] is True
        assert preview_payload["diagnostics"]["severity"] in {"LOW", "MEDIUM"}
        assert preview_payload["patch"]["integrations"][0]["name"] == "repository"

        apply_response = await client.post(
            f"/api/v1/projects/{project.id}/architecture-profile/fix-drift/apply",
            json={"updated_by": "ui-user"},
        )
        assert apply_response.status_code == 200, apply_response.text
        apply_payload = apply_response.json()
        assert apply_payload["applied"] is True
        assert apply_payload["profile"]["version"] == version_before + 2
        assert apply_payload["profile"]["profile_json"]["contract_diagnostics"]["warnings"] == []


@pytest.mark.anyio
async def test_architecture_profile_fix_drift_apply_and_pr_requires_repo(db_session):
    session, tenant_id = db_session
    project = Project(name="Fix drift no repo", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bootstrap_response = await client.post(
            f"/api/v1/projects/{project.id}/architecture-profile/bootstrap",
            json={"created_by": "ui-user"},
        )
        assert bootstrap_response.status_code == 200, bootstrap_response.text

        response = await client.post(
            f"/api/v1/projects/{project.id}/architecture-profile/fix-drift/apply-and-pr",
            json={"updated_by": "ui-user"},
        )
        assert response.status_code == 400, response.text
        assert "repository is not connected" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_architecture_profile_fix_drift_apply_and_pr_success_with_mock(db_session, monkeypatch):
    session, tenant_id = db_session
    project = Project(name="Fix drift with mock PR", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bootstrap_response = await client.post(
            f"/api/v1/projects/{project.id}/architecture-profile/bootstrap",
            json={"created_by": "ui-user"},
        )
        assert bootstrap_response.status_code == 200, bootstrap_response.text

        from app.api.v1 import architecture_profile as architecture_profile_router

        async def _mock_apply_and_pr(*args, **kwargs):
            profile = SimpleNamespace(**bootstrap_response.json())
            return {
                "applied": True,
                "branch_name": "chore/fix-architecture-drift-12345678",
                "pr_url": "https://github.com/acme/repo/pull/42",
                "pr_number": 42,
                "diagnostics": {"warnings": [], "violations": [], "fixes": [], "severity": "LOW"},
                "changed_files": ["contracts/project_contract.json"],
                "profile": profile,
            }

        monkeypatch.setattr(
            architecture_profile_router,
            "apply_architecture_drift_fix_and_open_pr",
            _mock_apply_and_pr,
        )

        response = await client.post(
            f"/api/v1/projects/{project.id}/architecture-profile/fix-drift/apply-and-pr",
            json={"updated_by": "ui-user"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["applied"] is True
        assert payload["pr_number"] == 42
        assert payload["branch_name"].startswith("chore/fix-architecture-drift-")
        assert "contracts/project_contract.json" in payload["changed_files"]

@pytest.mark.anyio
async def test_architecture_profile_bootstrap_includes_blueprint_sections_when_present(db_session):
    session, tenant_id = db_session
    project = Project(name="Blueprint aware architecture", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectBlueprint(
            tenant_id=tenant_id,
            project_id=project.id,
            blueprint_key="fullstack_monorepo",
            stack_preset_key="vue_fastapi",
            deployment_profile="local_preview",
            architecture="fullstack_monorepo",
            status="ACTIVE",
            readiness_enforced=True,
            generated_modules=["apps/web", "apps/api"],
            generated_contracts=["contracts/project_contract.json"],
            metadata_json={
                "stack": {"frontend": "vue", "backend": "fastapi", "database": "postgres"},
                "environment": {"logical": ["PREVIEW", "STAGING", "PRODUCTION"], "runtime": {"STAGING": "local_docker"}},
                "governance": {"level": "governed", "bounded_execution": True},
            },
            created_by="ui-user",
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bootstrap_response = await client.post(
            f"/api/v1/projects/{project.id}/architecture-profile/bootstrap",
            json={"created_by": "ui-user"},
        )
        assert bootstrap_response.status_code == 200, bootstrap_response.text
        payload = bootstrap_response.json()
        assert payload["profile_json"]["blueprint_key"] == "fullstack_monorepo"
        assert payload["profile_json"]["architecture_blueprint"]["style"] == "fullstack_monorepo"
        assert payload["profile_json"]["deployment_blueprint"]["profile"] == "local_preview"
        assert payload["profile_json"]["environment_blueprint"]["logical"] == ["PREVIEW", "STAGING", "PRODUCTION"]
        assert payload["profile_json"]["governance_blueprint"]["level"] == "governed"


@pytest.mark.anyio
async def test_create_project_auto_provisions_starter_blueprint_and_architecture(db_session):
    _session, _tenant_id = db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post(
            "/api/v1/projects",
            json={
                "name": "Auto starter project",
                "description": "auto provision check",
            },
        )
        assert create_response.status_code == 201, create_response.text
        project_id = create_response.json()["id"]

        blueprint_response = await client.get(f"/api/v1/projects/{project_id}/blueprint")
        assert blueprint_response.status_code == 200, blueprint_response.text
        blueprint = blueprint_response.json()
        assert blueprint is not None
        assert blueprint["blueprint_key"] == "fullstack_monorepo"
        assert blueprint["stack_preset_key"] == "vue_fastapi"

        summary_response = await client.get(f"/api/v1/projects/{project_id}/architecture-profile/summary")
        assert summary_response.status_code == 200, summary_response.text
        summary = summary_response.json()
        assert summary["profile_exists"] is True
        assert summary["derived_ready"] is True
        assert summary["package_count"] >= 2
        assert summary["command_coverage_count"] >= 1
        assert summary["validation_recipe_count"] >= 1
