from __future__ import annotations

import os
import subprocess
import types
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.api.v1 import persistence
from app.db.base import Base
from app.db.models import Artifact, Project, ProjectRepository, Run
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app
from app.services import pr_service, repo_connector, workspace_supervisor


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "Agentic SDLC Tests")
    env.setdefault("GIT_AUTHOR_EMAIL", "tests@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "Agentic SDLC Tests")
    env.setdefault("GIT_COMMITTER_EMAIL", "tests@example.com")
    return env


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        env=_git_env(),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return (result.stdout or "").strip()


def _seed_remote_repo(tmp_path: Path) -> Path:
    seed = tmp_path / "seed"
    remote = tmp_path / "origin.git"
    seed.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-b", "main"], cwd=seed)
    (seed / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git(["add", "README.md"], cwd=seed)
    _run_git(["commit", "-m", "init"], cwd=seed)
    _run_git(["init", "--bare", str(remote)])
    _run_git(["remote", "add", "origin", str(remote)], cwd=seed)
    _run_git(["push", "-u", "origin", "main"], cwd=seed)
    return remote


@pytest.fixture
async def db_session(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'repo-integration.db'}", future=True)
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

    settings_stub = types.SimpleNamespace(
        workspace_base_dir=str(tmp_path / "workspaces"),
        workspace_repo_source=None,
        git_author_name="Agentic SDLC Tests",
        git_author_email="tests@example.com",
    )
    monkeypatch.setattr(workspace_supervisor, "get_settings", lambda: settings_stub)
    monkeypatch.setattr(repo_connector, "get_settings", lambda: settings_stub)

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


@pytest.mark.anyio
async def test_connect_repo_upserts_project_repository(db_session):
    session, tenant_id, tmp_path = db_session
    project = Project(name="Repo project", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    remote = _seed_remote_repo(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            f"/api/v1/projects/{project.id}/connect-repo",
            json={
                "provider": "github",
                "repo_url": str(remote),
                "repo_full_name": "example/repo",
                "default_branch": "main",
            },
        )
        fetch_resp = await client.get(f"/api/v1/projects/{project.id}/repo")

    assert create_resp.status_code == 200
    assert create_resp.json()["repo_full_name"] == "example/repo"
    assert create_resp.json()["provider"] == "github"
    assert fetch_resp.status_code == 200
    assert fetch_resp.json()["repo_url"] == str(remote)


@pytest.mark.anyio
async def test_connect_repo_uses_provider_default_installation_id(db_session, monkeypatch):
    session, tenant_id, tmp_path = db_session
    project = Project(name="Repo project", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    remote = _seed_remote_repo(tmp_path)
    monkeypatch.setattr(repo_connector, "get_default_installation_id", lambda provider: 4242)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            f"/api/v1/projects/{project.id}/connect-repo",
            json={
                "provider": "github",
                "repo_url": str(remote),
                "repo_full_name": "example/repo",
                "default_branch": "main",
            },
        )

    assert create_resp.status_code == 200
    assert create_resp.json()["installation_id"] == 4242


@pytest.mark.anyio
async def test_create_run_seeds_workspace_from_connected_repo(db_session, monkeypatch):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path)

    project = Project(name="Workspace run", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url=str(remote),
            repo_full_name="example/repo",
            default_branch="main",
        )
    )
    await session.commit()
    await session.refresh(project)

    class DummyOrchestrator:
        def __init__(self, *_args, **_kwargs):
            pass

        async def start(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(persistence, "RunOrchestrator", DummyOrchestrator)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/projects/{project.id}/runs",
            json={"executor": "codex"},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["workspace_status"] == "SEEDED"
    assert Path(data["repo_path"]).joinpath(".git").exists()


@pytest.mark.anyio
async def test_create_pr_from_patch_artifact_creates_branch_and_pr_artifact(db_session, monkeypatch):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path)

    workspace_root = tmp_path / "workspaces" / "proj" / "run"
    repo_path = workspace_root / "repo"
    patch_dir = workspace_root / "patches"
    patch_dir.mkdir(parents=True, exist_ok=True)
    _run_git(["clone", str(remote), str(repo_path)])
    _run_git(["checkout", "-b", "run/fix-auth"], cwd=repo_path)
    readme = repo_path / "README.md"
    readme.write_text("hello\npatched\n", encoding="utf-8")
    diff = _run_git(["diff"], cwd=repo_path)
    _run_git(["reset", "--hard", "HEAD"], cwd=repo_path)
    patch_path = patch_dir / "fix.patch"
    patch_path.write_text(diff, encoding="utf-8")

    project = Project(name="PR project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url=str(remote),
            repo_full_name="example/repo",
            default_branch="main",
        )
    )
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        workspace_root=str(workspace_root),
        repo_path=str(repo_path),
        branch_name="run/fix-auth",
        workspace_status="SEEDED",
    )
    session.add(run)
    await session.flush()
    artifact = Artifact(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="git_diff",
        uri="workspace://patches/fix.patch",
        version=1,
        extra_metadata={"content": diff},
    )
    session.add(artifact)
    await session.commit()
    await session.refresh(run)
    await session.refresh(artifact)

    class DummyGitHubAdapter:
        def create_pull_request(self, repo: str, title: str, body: str, head: str, base: str, installation_id=None):
            return {
                "html_url": f"https://github.com/{repo}/pull/12",
                "number": 12,
            }

    monkeypatch.setattr(pr_service, "get_vcs_adapter", lambda provider: DummyGitHubAdapter())

    def _push_local_branch(repo_dir: Path, branch_name: str):
        origin_url = _run_git(["remote", "get-url", "origin"], cwd=repo_dir)
        assert origin_url == str(remote)
        _run_git(["push", "-u", "origin", branch_name], cwd=repo_dir)

    monkeypatch.setattr(pr_service, "push_branch", _push_local_branch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/runs/{run.id}/create-pr",
            json={
                "artifact_id": str(artifact.id),
                "title": "Fix auth README",
                "body": "Automated fix",
                "branch_name": "run/fix-auth",
            },
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["pull_request_url"] == "https://github.com/example/repo/pull/12"
    assert data["branch_name"] == "run/fix-auth"

    updated_run = await session.get(Run, run.id)
    assert updated_run is not None
    await session.refresh(updated_run)
    assert updated_run.summary["pull_request_number"] == 12

    pr_artifact = await session.scalar(
        select(Artifact).where(
            Artifact.run_id == run.id,
            Artifact.type == "pull_request",
        )
    )
    assert pr_artifact is not None
    assert pr_artifact.uri == "https://github.com/example/repo/pull/12"

    show_ref = _run_git(["--git-dir", str(remote), "show-ref", "--verify", "refs/heads/run/fix-auth"])
    assert show_ref
