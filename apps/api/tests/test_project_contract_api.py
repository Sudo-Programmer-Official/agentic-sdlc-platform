import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Project, ProjectRepository
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'project-contract.db'}", future=True)
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
async def test_project_contract_bootstrap_and_summary_endpoints(db_session):
    session, tenant_id = db_session
    project = Project(name="Contract bootstrap project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="https://github.com/acme/contract-ui.git",
            repo_full_name="acme/contract-ui",
            default_branch="main",
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bootstrap = await client.post(
            f"/api/v1/projects/{project.id}/project-contract/bootstrap",
            json={"created_by": "ui-user"},
        )
        assert bootstrap.status_code == 200, bootstrap.text
        body = bootstrap.json()
        assert body["source"] == "BOOTSTRAP"
        assert body["derived_json"]["enforcement"]["enabled"] is True
        assert "brand-primary" in body["derived_json"]["brand_tokens"]

        summary_response = await client.get(f"/api/v1/projects/{project.id}/project-contract/summary")
        assert summary_response.status_code == 200, summary_response.text
        summary = summary_response.json()
        assert summary["profile_exists"] is True
        assert summary["enforcement_enabled"] is True
        assert summary["enforcement_mode"] == "warn"
        assert summary["brand_token_count"] >= 1
        assert "disallow_inline_styles" in summary["active_rules"]

        project_summary_response = await client.get(f"/api/v1/projects/{project.id}/summary")
        assert project_summary_response.status_code == 200, project_summary_response.text
        project_summary = project_summary_response.json()
        assert project_summary["project_contract"]["profile_exists"] is True
        assert project_summary["project_contract"]["rule_count"] >= 1


@pytest.mark.anyio
async def test_project_contract_patch_updates_rules_and_derivation(db_session):
    session, tenant_id = db_session
    project = Project(name="Patch contract project", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bootstrap = await client.post(
            f"/api/v1/projects/{project.id}/project-contract/bootstrap",
            json={"created_by": "ui-user"},
        )
        assert bootstrap.status_code == 200, bootstrap.text
        version_before = bootstrap.json()["version"]

        patch_response = await client.patch(
            f"/api/v1/projects/{project.id}/project-contract",
            json={
                "summary": "Apply stricter UI token rules",
                "sections": {
                    "enforcement": {
                        "enabled": True,
                        "mode": "strict",
                        "enforce_color_tokens": True,
                        "allowed_hex_values": ["#2563eb"],
                    },
                    "design_system": {
                        "rules": {
                            "disallow_inline_styles": True,
                        }
                    },
                },
                "updated_by": "ui-user",
            },
        )
        assert patch_response.status_code == 200, patch_response.text
        patched = patch_response.json()
        assert patched["version"] == version_before + 1
        assert patched["summary"] == "Apply stricter UI token rules"
        assert patched["derived_json"]["enforcement"]["enforce_color_tokens"] is True
        assert patched["derived_json"]["enforcement"]["mode"] == "strict"
        assert patched["derived_json"]["enforcement"]["allowed_hex_values"] == ["#2563eb"]


@pytest.mark.anyio
async def test_design_contract_get_and_put_endpoints(db_session):
    session, tenant_id = db_session
    project = Project(name="Design contract project", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        fetched = await client.get(f"/api/v1/projects/{project.id}/design-contract")
        assert fetched.status_code == 200, fetched.text
        baseline = fetched.json()
        assert baseline["identity"]["name"] == "Design contract project"
        assert baseline["typography"]["heading_font"] == "Inter"
        assert baseline["experience_blueprint"] == "premium_saas"
        assert isinstance(baseline["token_registry"], dict)

        put_response = await client.put(
            f"/api/v1/projects/{project.id}/design-contract",
            json={
                "experience_blueprint": "enterprise_operational",
                "identity": {
                    "name": "Prompt2PR",
                    "tone": "operational_enterprise",
                    "personality": "confident_governed_clear",
                },
                "tokens": {
                    "primary": "#2563eb",
                    "surface": "#0f172a",
                    "accent": "#7c3aed",
                    "success": "#22c55e",
                },
                "typography": {
                    "heading_font": "Sora",
                    "body_font": "Inter",
                    "radius_scale": "soft",
                    "density": "comfortable",
                },
                "components": {
                    "buttons": {"style": "glass", "radius": "xl", "shadow": "soft"},
                    "registry": ["HeroSection", "DashboardShell", "MetricCard"],
                },
                "token_registry": {
                    "colors": {"primary": "#2563eb", "accent": "#7c3aed"},
                    "spacing": {"sm": "0.5rem", "md": "1rem"},
                    "radius": {"md": "0.5rem"},
                    "motion": {"base": "200ms"},
                    "elevation": {"md": "shadow"},
                },
                "allowed_components": ["HeroSection", "DashboardShell", "MetricCard"],
                "layout": {
                    "spacing": "airy",
                    "container_width": "wide",
                    "visual_weight": "balanced",
                    "hero_style": "immersive",
                },
                "updated_by": "ui-user",
            },
        )
        assert put_response.status_code == 200, put_response.text
        body = put_response.json()
        assert body["contract_json"]["design_contract"]["experience_blueprint"] == "enterprise_operational"
        assert body["contract_json"]["design_contract"]["identity"]["tone"] == "operational_enterprise"
        assert body["contract_json"]["design_contract"]["tokens"]["accent"] == "#7c3aed"
        assert body["contract_json"]["design_contract"]["token_registry"]["colors"]["accent"] == "#7c3aed"
        assert body["contract_json"]["design_contract"]["allowed_components"] == ["HeroSection", "DashboardShell", "MetricCard"]

        fetched_after = await client.get(f"/api/v1/projects/{project.id}/design-contract")
        assert fetched_after.status_code == 200, fetched_after.text
        updated = fetched_after.json()
        assert updated["experience_blueprint"] == "enterprise_operational"
        assert updated["identity"]["name"] == "Prompt2PR"
        assert updated["typography"]["heading_font"] == "Sora"
        assert updated["layout"]["hero_style"] == "immersive"
