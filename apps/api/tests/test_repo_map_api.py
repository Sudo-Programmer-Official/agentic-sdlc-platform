from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Project, ProjectRepository, Run
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'repo-map-api.db'}", future=True)
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
        yield session, tenant_id, tmp_path
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_tenant_context, None)
        await session.close()
        await engine.dispose()


def _seed_repo_tree(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "src/components").mkdir(parents=True, exist_ok=True)
    (repo_root / "src/views").mkdir(parents=True, exist_ok=True)
    (repo_root / "src/services").mkdir(parents=True, exist_ok=True)
    (repo_root / "src/tests").mkdir(parents=True, exist_ok=True)
    (repo_root / "src/components/LoginButton.vue").write_text(
        "<template><button class='primary'>Login</button></template>\n"
        "<script setup lang='ts'>\n"
        "const buttonLabel = 'Login'\n"
        "</script>\n",
        encoding="utf-8",
    )
    (repo_root / "src/views/LoginPage.vue").write_text(
        "<template><LoginButton /></template>\n"
        "<script setup lang='ts'>\n"
        "import LoginButton from '../components/LoginButton.vue'\n"
        "const title = 'Login'\n"
        "</script>\n",
        encoding="utf-8",
    )
    (repo_root / "src/services/authService.ts").write_text(
        "export async function login() { return true }\nexport function logout() {}\n",
        encoding="utf-8",
    )
    (repo_root / "src/tests/LoginButton.test.ts").write_text(
        "import LoginButton from '../components/LoginButton.vue'\n"
        "describe('LoginButton', () => {\n"
        "  it('renders login label', () => expect(LoginButton).toBeTruthy())\n"
        "})\n",
        encoding="utf-8",
    )
    return repo_root


@pytest.mark.anyio
async def test_repo_map_endpoint_indexes_workspace_repo(db_session):
    session, tenant_id, tmp_path = db_session
    repo_root = _seed_repo_tree(tmp_path)

    project = Project(name="Repo map project", tenant_id=tenant_id)
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
        response = await client.get(f"/api/v1/projects/{project.id}/repo-map")

    assert response.status_code == 200
    data = response.json()
    assert data["source_type"] == "workspace"
    assert data["repo_full_name"] == "acme/plancraft"
    assert data["total_files"] >= 3
    assert data["test_links"] >= 1
    assert data["snapshot_indexed_at"]
    assert any(file["path"] == "src/components/LoginButton.vue" for file in data["files"])


@pytest.mark.anyio
async def test_repo_map_search_endpoint_returns_relevant_files(db_session):
    session, tenant_id, tmp_path = db_session
    repo_root = _seed_repo_tree(tmp_path)

    project = Project(name="Repo search project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
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
        response = await client.get(f"/api/v1/projects/{project.id}/repo-map/search", params={"q": "login button"})

    assert response.status_code == 200
    data = response.json()
    assert data["matches"]
    assert data["matches"][0]["path"] in {"src/components/LoginButton.vue", "src/views/LoginPage.vue"}
    assert data["matches"][0]["score"] > 0


@pytest.mark.anyio
async def test_repo_map_refresh_reindexes_updated_symbols(db_session):
    session, tenant_id, tmp_path = db_session
    repo_root = _seed_repo_tree(tmp_path)

    project = Project(name="Repo refresh project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
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
        first = await client.get(f"/api/v1/projects/{project.id}/repo-map/symbols", params={"q": "LoginButton"})
        assert first.status_code == 200

        (repo_root / "src/components/LoginButton.vue").write_text(
            "<template><button class='primary'>Login</button></template>\n"
            "<script setup lang='ts'>\n"
            "const buttonLabel = 'Continue'\n"
            "const LoginCta = 'Continue'\n"
            "</script>\n",
            encoding="utf-8",
        )
        refreshed = await client.post(f"/api/v1/projects/{project.id}/repo-map/refresh")
        assert refreshed.status_code == 200

        symbol_search = await client.get(f"/api/v1/projects/{project.id}/repo-map/symbols", params={"q": "LoginCta"})

    assert symbol_search.status_code == 200
    data = symbol_search.json()
    assert data["matches"]
    assert data["matches"][0]["name"] == "LoginCta"
    assert data["matches"][0]["path"] == "src/components/LoginButton.vue"


@pytest.mark.anyio
async def test_repo_map_symbol_search_returns_indexed_symbols(db_session):
    session, tenant_id, tmp_path = db_session
    repo_root = _seed_repo_tree(tmp_path)

    project = Project(name="Repo symbol project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
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
        response = await client.get(f"/api/v1/projects/{project.id}/repo-map/symbols", params={"q": "LoginButton"})

    assert response.status_code == 200
    data = response.json()
    assert data["matches"]
    assert data["matches"][0]["name"] == "LoginButton"
    assert data["matches"][0]["path"] == "src/components/LoginButton.vue"
    assert data["total_symbols"] >= 3


@pytest.mark.anyio
async def test_repo_map_impact_returns_dependents_and_related_tests(db_session):
    session, tenant_id, tmp_path = db_session
    repo_root = _seed_repo_tree(tmp_path)

    project = Project(name="Repo impact project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
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
        response = await client.get(
            f"/api/v1/projects/{project.id}/repo-map/impact",
            params={"file": "src/components/LoginButton.vue", "depth": 1},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["primary_files"][0]["path"] == "src/components/LoginButton.vue"
    dependent_paths = {item["path"] for item in data["dependent_files"]}
    related_test_paths = {item["path"] for item in data["related_tests"]}
    assert "src/views/LoginPage.vue" in dependent_paths
    assert "src/tests/LoginButton.test.ts" in related_test_paths
