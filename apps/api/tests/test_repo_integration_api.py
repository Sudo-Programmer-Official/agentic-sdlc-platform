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
from app.db.models import Artifact, Project, ProjectRepository, Run, WorkItem, WorkItemEdge
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app
from app.services import pr_service, repo_connector, run_delivery, run_replay, workspace_supervisor


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


def _create_empty_remote_repo(tmp_path: Path) -> Path:
    remote = tmp_path / "empty-origin.git"
    _run_git(["init", "--bare", str(remote)])
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
        runtime_git_auth_mode="auto",
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
                "auth_strategy": "public_https",
            },
        )
        fetch_resp = await client.get(f"/api/v1/projects/{project.id}/repo")

    assert create_resp.status_code == 200
    assert create_resp.json()["repo_full_name"] == "example/repo"
    assert create_resp.json()["provider"] == "github"
    assert create_resp.json()["auth_strategy"] == "public_https"
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
async def test_repo_preflight_uses_saved_auth_strategy(db_session, monkeypatch):
    session, tenant_id, tmp_path = db_session
    project = Project(name="Repo project", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    remote = _seed_remote_repo(tmp_path)
    calls = []

    def fake_preflight(**kwargs):
        calls.append(kwargs)
        return repo_connector.RepoPreflightResult(
            ok=True,
            provider=kwargs["provider"],
            auth_strategy=kwargs["auth_strategy"],
            auth_mode="plain",
            credential_strategy="anonymous_https",
            selection_reason="test",
            transport_url=kwargs["repo_url"],
            repo_url=kwargs["repo_url"],
            default_branch=kwargs["default_branch"],
            installation_id=kwargs["installation_id"],
            git_binary="/usr/bin/git",
        )

    monkeypatch.setattr(persistence, "preflight_repo_access", fake_preflight)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            f"/api/v1/projects/{project.id}/connect-repo",
            json={
                "provider": "github",
                "repo_url": str(remote),
                "repo_full_name": "example/repo",
                "default_branch": "main",
                "auth_strategy": "public_https",
            },
        )
        preflight_resp = await client.post(
            f"/api/v1/projects/{project.id}/repo/preflight",
            json={"clone": True},
        )

    assert create_resp.status_code == 200
    assert preflight_resp.status_code == 200
    assert preflight_resp.json()["ok"] is True
    assert calls[0]["auth_strategy"] == "public_https"
    assert calls[0]["repo_url"] == str(remote)


@pytest.mark.anyio
async def test_repo_bootstrap_initializes_empty_remote(db_session):
    session, tenant_id, tmp_path = db_session
    project = Project(name="Bootstrap project", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    remote = _create_empty_remote_repo(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bootstrap_resp = await client.post(
            f"/api/v1/projects/{project.id}/repo/bootstrap",
            json={
                "provider": "github",
                "repo_url": str(remote),
                "default_branch": "main",
                "auth_strategy": "public_https",
                "readme_title": "Bootstrap project",
            },
        )
        preflight_resp = await client.post(
            f"/api/v1/projects/{project.id}/repo/preflight",
            json={
                "provider": "github",
                "repo_url": str(remote),
                "default_branch": "main",
                "auth_strategy": "public_https",
                "clone": True,
            },
        )

    assert bootstrap_resp.status_code == 200
    assert bootstrap_resp.json()["ok"] is True
    assert bootstrap_resp.json()["created"] is True
    assert bootstrap_resp.json()["commit_sha"]
    assert preflight_resp.status_code == 200
    assert preflight_resp.json()["ok"] is True


@pytest.mark.anyio
async def test_github_connect_info_and_installation_repositories(db_session, monkeypatch):
    _session, _tenant_id, _tmp_path = db_session

    class DummyGitHubAdapter:
        def list_installation_repositories(self, installation_id: int):
            assert installation_id == 4242
            return [
                {
                    "id": 1,
                    "name": "agentic-sdlc-platform",
                    "full_name": "sudo-programmer-official/agentic-sdlc-platform",
                    "clone_url": "https://github.com/sudo-programmer-official/agentic-sdlc-platform.git",
                    "ssh_url": "git@github.com:sudo-programmer-official/agentic-sdlc-platform.git",
                    "html_url": "https://github.com/sudo-programmer-official/agentic-sdlc-platform",
                    "default_branch": "main",
                    "private": True,
                    "owner_login": "sudo-programmer-official",
                }
            ]

    monkeypatch.setattr(persistence, "github_adapter", DummyGitHubAdapter())
    monkeypatch.setattr(persistence.settings, "github_app_slug", "agentic-sdlc")
    monkeypatch.setattr(persistence.settings, "github_allowed_org", "sudo-programmer-official")
    monkeypatch.setattr(persistence.settings, "runtime_git_auth_mode", "auto")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        connect_resp = await client.get("/api/v1/integrations/github/connect")
        repos_resp = await client.get("/api/v1/integrations/github/installations/4242/repositories")

    assert connect_resp.status_code == 200
    assert connect_resp.json() == {
        "enabled": True,
        "app_slug": "agentic-sdlc",
        "allowed_org": "sudo-programmer-official",
        "install_url": "https://github.com/apps/agentic-sdlc/installations/new",
        "runtime_git_auth_mode": "auto",
    }
    assert repos_resp.status_code == 200
    assert repos_resp.json()[0]["full_name"] == "sudo-programmer-official/agentic-sdlc-platform"


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
            installation_id=4242,
            auth_strategy="ssh",
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
async def test_publish_run_branch_if_ready_commits_and_pushes_workspace_changes(db_session):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path)

    workspace_root = tmp_path / "workspaces" / "proj" / "publish-run"
    repo_path = workspace_root / "repo"
    _run_git(["clone", str(remote), str(repo_path)])
    _run_git(["checkout", "-b", "run/publish-test"], cwd=repo_path)
    (repo_path / "docs").mkdir(parents=True, exist_ok=True)
    (repo_path / "docs" / "publish-test.md").write_text("hello publish\n", encoding="utf-8")

    project = Project(name="Publish project", tenant_id=tenant_id)
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
            installation_id=4242,
            auth_strategy="ssh",
        )
    )
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        workspace_root=str(workspace_root),
        repo_path=str(repo_path),
        branch_name="run/publish-test",
        workspace_status="SEEDED",
        summary={"goal": "Publish docs smoke file"},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    result = await run_delivery.publish_run_branch_if_ready(session, run=run)

    assert result is not None
    assert result["branch_name"] == "run/publish-test"
    assert result["created_commit"] is True
    assert _run_git(["status", "--short"], cwd=repo_path) == ""

    updated_run = await session.get(Run, run.id)
    assert updated_run is not None
    await session.refresh(updated_run)
    assert updated_run.summary["remote_branch_pushed"] is True
    assert updated_run.summary["remote_branch_created_commit"] is True

    show_ref = _run_git(["--git-dir", str(remote), "show-ref", "--verify", "refs/heads/run/publish-test"])
    assert show_ref


@pytest.mark.anyio
async def test_publish_run_branch_if_ready_pushes_clean_branch_without_new_commit(db_session):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path)

    workspace_root = tmp_path / "workspaces" / "proj" / "publish-clean-run"
    repo_path = workspace_root / "repo"
    _run_git(["clone", str(remote), str(repo_path)])
    _run_git(["checkout", "-b", "run/publish-clean"], cwd=repo_path)
    head_before = _run_git(["rev-parse", "HEAD"], cwd=repo_path)

    project = Project(name="Publish clean branch project", tenant_id=tenant_id)
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
            installation_id=4242,
        )
    )
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        workspace_root=str(workspace_root),
        repo_path=str(repo_path),
        branch_name="run/publish-clean",
        workspace_status="SEEDED",
        summary={"goal": "Publish clean branch"},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    result = await run_delivery.publish_run_branch_if_ready(session, run=run)

    assert result is not None
    assert result["branch_name"] == "run/publish-clean"
    assert result["created_commit"] is False
    assert result["commit_sha"] == head_before

    updated_run = await session.get(Run, run.id)
    assert updated_run is not None
    await session.refresh(updated_run)
    assert updated_run.summary["remote_branch_pushed"] is True
    assert updated_run.summary["remote_branch_created_commit"] is False

    show_ref = _run_git(["--git-dir", str(remote), "show-ref", "--verify", "refs/heads/run/publish-clean"])
    assert show_ref.endswith("refs/heads/run/publish-clean")


@pytest.mark.anyio
async def test_publish_run_branch_persists_successful_fallback_strategy(db_session, monkeypatch):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path)

    workspace_root = tmp_path / "workspaces" / "proj" / "publish-fallback-run"
    repo_path = workspace_root / "repo"
    _run_git(["clone", str(remote), str(repo_path)])
    _run_git(["checkout", "-b", "run/publish-fallback"], cwd=repo_path)
    (repo_path / "README.md").write_text("hello fallback\n", encoding="utf-8")

    project = Project(name="Publish fallback strategy project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    repo_record = ProjectRepository(
        project_id=project.id,
        tenant_id=tenant_id,
        provider="github",
        repo_url=str(remote),
        repo_full_name="example/repo",
        default_branch="main",
        auth_strategy="runtime_default",
    )
    session.add(repo_record)
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        workspace_root=str(workspace_root),
        repo_path=str(repo_path),
        branch_name="run/publish-fallback",
        workspace_status="SEEDED",
        summary={"goal": "Publish fallback strategy"},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    real_push_branch = run_delivery.push_branch
    seen_strategies: list[str] = []

    def _push_with_first_failure(*args, **kwargs):
        strategy = kwargs.get("auth_strategy")
        seen_strategies.append(str(strategy))
        if strategy == "runtime_default":
            raise RuntimeError("simulated runtime_default auth failure")
        return real_push_branch(*args, **kwargs)

    monkeypatch.setattr(run_delivery, "github_app_runtime_configured", lambda: True)
    monkeypatch.setattr(run_delivery, "push_branch", _push_with_first_failure)

    result = await run_delivery.publish_run_branch_if_ready(session, run=run)
    assert result is not None
    assert seen_strategies[0] == "runtime_default"
    assert "ssh" in seen_strategies or "public_https" in seen_strategies or "github_app" in seen_strategies

    updated_repo = await session.get(ProjectRepository, repo_record.id)
    assert updated_repo is not None
    assert updated_repo.auth_strategy != "runtime_default"


@pytest.mark.anyio
async def test_publish_run_branch_skips_github_app_paths_when_runtime_unconfigured(db_session, monkeypatch):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path)

    workspace_root = tmp_path / "workspaces" / "proj" / "publish-skip-app-run"
    repo_path = workspace_root / "repo"
    _run_git(["clone", str(remote), str(repo_path)])
    _run_git(["checkout", "-b", "run/publish-skip-app"], cwd=repo_path)
    (repo_path / "README.md").write_text("hello skip app\n", encoding="utf-8")

    project = Project(name="Publish skip app fallback project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    repo_record = ProjectRepository(
        project_id=project.id,
        tenant_id=tenant_id,
        provider="github",
        repo_url=str(remote),
        repo_full_name="example/repo",
        default_branch="main",
        auth_strategy="runtime_default",
    )
    session.add(repo_record)
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        workspace_root=str(workspace_root),
        repo_path=str(repo_path),
        branch_name="run/publish-skip-app",
        workspace_status="SEEDED",
        summary={"goal": "Publish skip app fallback strategy"},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(run_delivery, "github_app_runtime_configured", lambda: False)

    seen_strategies: list[str] = []
    real_push_branch = run_delivery.push_branch

    def _recorded_push(*args, **kwargs):
        seen_strategies.append(str(kwargs.get("auth_strategy")))
        return real_push_branch(*args, **kwargs)

    monkeypatch.setattr(run_delivery, "push_branch", _recorded_push)

    result = await run_delivery.publish_run_branch_if_ready(session, run=run)

    assert result is not None
    assert "runtime_default" not in seen_strategies
    assert "github_app" not in seen_strategies
    assert seen_strategies[0] in {"ssh", "public_https"}


@pytest.mark.anyio
async def test_feedback_fork_materializes_branch_before_publish(db_session):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path)

    source_workspace_root = tmp_path / "workspaces" / "proj" / "source-run"
    source_repo_path = source_workspace_root / "repo"
    _run_git(["clone", str(remote), str(source_repo_path)])
    _run_git(["checkout", "-b", "run/9054455f"], cwd=source_repo_path)
    (source_repo_path / "index.html").write_text("<!doctype html><html><body>base</body></html>\n", encoding="utf-8")
    _run_git(["add", "index.html"], cwd=source_repo_path)
    _run_git(["commit", "-m", "base run"], cwd=source_repo_path)
    _run_git(["push", "-u", "origin", "run/9054455f"], cwd=source_repo_path)

    project = Project(name="Feedback fork project", tenant_id=tenant_id)
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
            installation_id=4242,
        )
    )
    source_run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        workspace_root=str(source_workspace_root),
        repo_path=str(source_repo_path),
        branch_name="run/9054455f",
        workspace_status="SEEDED",
        summary={"goal": "Base portfolio run"},
    )
    session.add(source_run)
    await session.commit()
    await session.refresh(source_run)

    forked_run = await run_replay.fork_run(
        session,
        source_run=source_run,
        executor="codex",
        branch_name="run/9054455f-minimal-patch",
        summary_overrides={"feedback_text": "Move footer to bottom of viewport"},
        start_now=False,
    )

    forked_repo_path = Path(forked_run.repo_path)
    assert _run_git(["branch", "--show-current"], cwd=forked_repo_path) == "run/9054455f-minimal-patch"

    (forked_repo_path / "index.html").write_text(
        "<!doctype html><html><body><footer>moved</footer></body></html>\n",
        encoding="utf-8",
    )
    result = await run_delivery.publish_run_branch_if_ready(session, run=forked_run)

    assert result is not None
    assert result["branch_name"] == "run/9054455f-minimal-patch"
    show_ref = _run_git(
        ["--git-dir", str(remote), "show-ref", "--verify", "refs/heads/run/9054455f-minimal-patch"]
    )
    assert show_ref.endswith("refs/heads/run/9054455f-minimal-patch")


@pytest.mark.anyio
async def test_fork_run_excludes_recovery_items_and_recomputes_dependencies(db_session):
    session, tenant_id, _tmp_path = db_session
    project = Project(name="Fork pruning project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    source_run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="FAILED",
        executor="codex",
        summary={"goal": "stabilize homepage"},
    )
    session.add(source_run)
    await session.flush()

    plan = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=source_run.id,
        type="PLAN_DAG",
        key="PLAN_DAG",
        status="FAILED",
        executor="codex",
        priority=1,
        depends_on_count=0,
        payload={},
        result={},
    )
    code = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=source_run.id,
        type="CODE_FRONTEND",
        key="CODE_FRONTEND",
        status="QUEUED",
        executor="codex",
        priority=2,
        depends_on_count=1,
        payload={},
        result={},
    )
    fix = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=source_run.id,
        type="FIX_TEST_FAILURE",
        key="FIX_TEST_FAILURE_1",
        status="QUEUED",
        executor="codex",
        priority=9,
        depends_on_count=0,
        payload={"failed_work_item_id": "abc"},
        result={},
    )
    session.add_all([plan, code, fix])
    await session.flush()
    session.add(
        WorkItemEdge(
            tenant_id=tenant_id,
            run_id=source_run.id,
            from_work_item_id=plan.id,
            to_work_item_id=code.id,
        )
    )
    await session.commit()

    forked_run = await run_replay.fork_run(
        session,
        source_run=source_run,
        executor="codex",
        start_now=False,
    )

    items = (
        await session.execute(select(WorkItem).where(WorkItem.run_id == forked_run.id).order_by(WorkItem.created_at.asc()))
    ).scalars().all()
    assert [item.type for item in items] == ["PLAN_DAG", "CODE_FRONTEND"]
    assert all(item.status == "QUEUED" for item in items)

    cloned_plan = next(item for item in items if item.type == "PLAN_DAG")
    cloned_code = next(item for item in items if item.type == "CODE_FRONTEND")
    assert cloned_plan.depends_on_count == 0
    assert cloned_code.depends_on_count == 1


@pytest.mark.anyio
async def test_fork_run_clears_inherited_degraded_summary_flags(db_session):
    session, tenant_id, _tmp_path = db_session
    project = Project(name="Fork degraded summary reset", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    source_run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        summary={
            "goal": "stale degraded summary should not propagate",
            "degraded_completion": True,
            "degraded_reason": "stalled_no_progress",
            "degraded_at": "2026-05-12T00:00:00Z",
            "goal_state": "CONCLUDED_UNRESOLVABLE",
            "stall_recovery_attempts": 4,
        },
    )
    session.add(source_run)
    await session.flush()

    plan = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=source_run.id,
        type="PLAN_DAG",
        key="PLAN_DAG",
        status="DONE",
        executor="codex",
        priority=1,
        depends_on_count=0,
        payload={},
        result={},
    )
    session.add(plan)
    await session.commit()

    forked_run = await run_replay.fork_run(
        session,
        source_run=source_run,
        executor="codex",
        start_now=False,
    )

    assert isinstance(forked_run.summary, dict)
    assert forked_run.summary.get("forked_from_run_id") == str(source_run.id)
    assert "degraded_completion" not in forked_run.summary
    assert "degraded_reason" not in forked_run.summary
    assert "degraded_at" not in forked_run.summary
    assert "goal_state" not in forked_run.summary
    assert "stall_recovery_attempts" not in forked_run.summary


@pytest.mark.anyio
async def test_fork_run_clears_inherited_preview_summary(db_session):
    session, tenant_id, _tmp_path = db_session
    project = Project(name="Fork preview summary reset", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    source_run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        summary={
            "goal": "stale preview summary should not propagate",
            "preview": {
                "status": "FAILED",
                "preview_url": "http://127.0.0.1:62305",
                "frontend": {
                    "url": "http://127.0.0.1:62305",
                    "log_path": "/private/tmp/old-run/logs/preview/frontend-preview.log",
                },
                "verification_note": "stale preview verifier note",
            },
        },
    )
    session.add(source_run)
    await session.flush()

    plan = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=source_run.id,
        type="PLAN_DAG",
        key="PLAN_DAG",
        status="DONE",
        executor="codex",
        priority=1,
        depends_on_count=0,
        payload={},
        result={},
    )
    session.add(plan)
    await session.commit()

    forked_run = await run_replay.fork_run(
        session,
        source_run=source_run,
        executor="codex",
        start_now=False,
    )

    assert isinstance(forked_run.summary, dict)
    assert forked_run.summary.get("forked_from_run_id") == str(source_run.id)
    assert "preview" not in forked_run.summary


@pytest.mark.anyio
async def test_fork_run_repairs_workspace_and_preserves_test_strategy_payload(db_session):
    session, tenant_id, tmp_path = db_session
    source_workspace_root = tmp_path / "workspaces" / "fork-consistency" / "source-run"
    source_repo_path = source_workspace_root / "repo"
    (source_repo_path / "apps" / "web" / "src").mkdir(parents=True, exist_ok=True)
    (source_repo_path / "apps" / "web" / "src" / "main.ts").write_text("console.log('boot')\n", encoding="utf-8")
    # Intentionally missing apps/web/package.json + vite.config.ts + index.html

    project = Project(name="Fork workspace consistency project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    source_run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        workspace_root=str(source_workspace_root),
        repo_path=str(source_repo_path),
        workspace_status="SEEDED",
        summary={"goal": "fork consistency"},
    )
    session.add(source_run)
    await session.flush()

    write_tests = WorkItem(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=source_run.id,
        type="WRITE_TESTS",
        key="WRITE_TESTS",
        status="DONE",
        executor="codex",
        priority=5,
        depends_on_count=0,
        payload={"target_files": ["apps/web/src/components/landing/tests/TestimonialsSection.spec.ts"]},
        result={},
    )
    session.add(write_tests)
    await session.commit()

    forked_run = await run_replay.fork_run(
        session,
        source_run=source_run,
        executor="codex",
        start_now=False,
    )

    assert isinstance(forked_run.summary, dict)
    assert forked_run.summary.get("replay_workspace_repaired") is True
    repaired = forked_run.summary.get("replay_workspace_repairs")
    assert isinstance(repaired, list)
    assert "apps/web/package.json" in repaired
    assert "apps/web/vite.config.ts" in repaired
    assert "apps/web/index.html" in repaired

    forked_repo = Path(forked_run.repo_path or "")
    assert (forked_repo / "apps" / "web" / "package.json").exists()
    assert (forked_repo / "apps" / "web" / "vite.config.ts").exists()
    assert (forked_repo / "apps" / "web" / "index.html").exists()

    cloned_write_tests = await session.scalar(
        select(WorkItem).where(WorkItem.run_id == forked_run.id, WorkItem.key == "WRITE_TESTS")
    )
    assert cloned_write_tests is not None
    assert isinstance(cloned_write_tests.payload, dict)
    assert cloned_write_tests.payload.get("package_affinity") == "apps/web"
    assert cloned_write_tests.payload.get("test_strategy") == "vitest"
    assert cloned_write_tests.payload.get("framework_router") == "frontend_vite_vitest"

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
            installation_id=4242,
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

    def _push_local_branch(
        repo_dir: Path,
        branch_name: str,
        *,
        provider: str,
        repo_url: str,
        repo_full_name: str | None = None,
        installation_id: int | None = None,
        auth_strategy: str | None = None,
    ):
        assert provider == "github"
        assert repo_full_name == "example/repo"
        assert installation_id == 4242
        assert auth_strategy == "ssh"
        origin_url = _run_git(["remote", "get-url", "origin"], cwd=repo_dir)
        assert origin_url == str(remote)
        assert repo_url == str(remote)
        _run_git(["push", "-u", "origin", branch_name], cwd=repo_dir)

    monkeypatch.setattr(pr_service, "push_branch", _push_local_branch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        blocked = await client.post(
            f"/api/v1/runs/{run.id}/create-pr",
            json={
                "artifact_id": str(artifact.id),
                "title": "Fix auth README",
                "body": "Automated fix",
                "branch_name": "run/fix-auth",
            },
        )
        assert blocked.status_code == 409
        assert "approved" in blocked.json()["detail"].lower()

        approval_resp = await client.post(
            f"/api/v1/projects/{project.id}/approvals",
            json={
                "target_type": "artifact",
                "target_id": str(artifact.id),
                "status": "APPROVED",
                "decided_by": "ui-user",
                "comment": "Reviewed patch artifact",
            },
        )
        assert approval_resp.status_code == 201, approval_resp.text

        approvals_resp = await client.get(
            f"/api/v1/projects/{project.id}/approvals",
            params={"target_type": "artifact", "target_id": str(artifact.id)},
        )
        assert approvals_resp.status_code == 200
        assert approvals_resp.json()[0]["status"] == "APPROVED"

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


@pytest.mark.anyio
async def test_create_pr_from_artifact_uses_already_published_branch(db_session, monkeypatch):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path)

    workspace_root = tmp_path / "workspaces" / "proj" / "published-run"
    repo_path = workspace_root / "repo"
    _run_git(["clone", str(remote), str(repo_path)])
    _run_git(["checkout", "-b", "run/already-pushed"], cwd=repo_path)
    readme = repo_path / "README.md"
    readme.write_text("hello\nalready pushed\n", encoding="utf-8")
    diff = _run_git(["diff"], cwd=repo_path)
    _run_git(["add", "README.md"], cwd=repo_path)
    _run_git(["commit", "-m", "already pushed"], cwd=repo_path)
    pushed_sha = _run_git(["rev-parse", "HEAD"], cwd=repo_path)
    _run_git(["push", "-u", "origin", "run/already-pushed"], cwd=repo_path)

    project = Project(name="Already pushed PR project", tenant_id=tenant_id)
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
            installation_id=4242,
        )
    )
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        workspace_root=str(workspace_root),
        repo_path=str(repo_path),
        branch_name="run/already-pushed",
        workspace_status="SEEDED",
        summary={
            "remote_branch_pushed": True,
            "remote_branch_name": "run/already-pushed",
            "remote_branch_commit_sha": pushed_sha,
        },
    )
    session.add(run)
    await session.flush()
    artifact = Artifact(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="git_diff",
        uri="workspace://patches/already-pushed.patch",
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
                "html_url": f"https://github.com/{repo}/pull/34",
                "number": 34,
            }

    monkeypatch.setattr(pr_service, "get_vcs_adapter", lambda provider: DummyGitHubAdapter())

    def _unexpected_push(*_args, **_kwargs):
        raise AssertionError("push_branch should not be called for an already published branch")

    monkeypatch.setattr(pr_service, "push_branch", _unexpected_push)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        approval_resp = await client.post(
            f"/api/v1/projects/{project.id}/approvals",
            json={
                "target_type": "artifact",
                "target_id": str(artifact.id),
                "status": "APPROVED",
                "decided_by": "ui-user",
                "comment": "Reviewed patch artifact",
            },
        )
        assert approval_resp.status_code == 201, approval_resp.text

        response = await client.post(
            f"/api/v1/runs/{run.id}/create-pr",
            json={
                "artifact_id": str(artifact.id),
                "title": "Already pushed README",
                "body": "Automated fix",
                "branch_name": "run/already-pushed",
            },
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["pull_request_url"] == "https://github.com/example/repo/pull/34"
    assert data["commit_sha"] == pushed_sha


@pytest.mark.anyio
async def test_create_pr_returns_409_when_provider_reports_conflict(db_session, monkeypatch):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path)

    workspace_root = tmp_path / "workspaces" / "proj" / "pr-conflict"
    repo_path = workspace_root / "repo"
    patch_dir = workspace_root / "patches"
    patch_dir.mkdir(parents=True, exist_ok=True)
    _run_git(["clone", str(remote), str(repo_path)])
    _run_git(["checkout", "-b", "run/pr-conflict"], cwd=repo_path)
    readme = repo_path / "README.md"
    readme.write_text("hello\nconflict\n", encoding="utf-8")
    diff = _run_git(["diff"], cwd=repo_path)
    _run_git(["add", "README.md"], cwd=repo_path)
    _run_git(["commit", "-m", "conflict prep"], cwd=repo_path)
    _run_git(["push", "-u", "origin", "run/pr-conflict"], cwd=repo_path)
    patch_path = patch_dir / "conflict.patch"
    patch_path.write_text(diff, encoding="utf-8")

    project = Project(name="PR conflict project", tenant_id=tenant_id)
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
            installation_id=4242,
        )
    )
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        workspace_root=str(workspace_root),
        repo_path=str(repo_path),
        branch_name="run/pr-conflict",
        workspace_status="SEEDED",
        summary={
            "remote_branch_pushed": True,
            "remote_branch_name": "run/pr-conflict",
        },
    )
    session.add(run)
    await session.flush()
    artifact = Artifact(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="git_diff",
        uri="workspace://patches/conflict.patch",
        version=1,
        extra_metadata={"content": diff},
    )
    session.add(artifact)
    await session.commit()

    class DummyGitHubAdapter:
        def create_pull_request(self, repo: str, title: str, body: str, head: str, base: str, installation_id=None):
            raise ValueError("A pull request already exists for run/pr-conflict")

    monkeypatch.setattr(pr_service, "get_vcs_adapter", lambda provider: DummyGitHubAdapter())
    monkeypatch.setattr(pr_service, "push_branch", lambda *args, **kwargs: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        approval_resp = await client.post(
            f"/api/v1/projects/{project.id}/approvals",
            json={
                "target_type": "artifact",
                "target_id": str(artifact.id),
                "status": "APPROVED",
                "decided_by": "ui-user",
                "comment": "Reviewed patch artifact",
            },
        )
        assert approval_resp.status_code == 201, approval_resp.text

        response = await client.post(
            f"/api/v1/runs/{run.id}/create-pr",
            json={
                "artifact_id": str(artifact.id),
                "title": "Conflict case",
                "body": "Automated fix",
                "branch_name": "run/pr-conflict",
            },
        )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_create_pr_returns_400_when_github_installation_missing(db_session, monkeypatch):
    session, tenant_id, _tmp_path = db_session
    project = Project(name="Missing installation project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="https://github.com/example/repo.git",
            repo_full_name="example/repo",
            default_branch="main",
            installation_id=None,
            auth_strategy="ssh",
        )
    )
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/missing-install",
    )
    session.add(run)
    await session.commit()

    class DummyGitHubAdapter:
        def create_pull_request(self, *args, **kwargs):
            raise AssertionError("create_pull_request should not be called when installation is missing")

    monkeypatch.setattr(pr_service, "get_vcs_adapter", lambda provider: DummyGitHubAdapter())
    monkeypatch.setattr(pr_service, "get_default_installation_id", lambda provider: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/runs/{run.id}/create-pr",
            json={"branch_name": "run/missing-install"},
        )

    assert response.status_code == 400
    assert "installation" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_approval_auto_queues_paused_run_for_resume(db_session):
    session, tenant_id, _tmp_path = db_session
    project = Project(name="Approval auto resume project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="PAUSED",
        executor="codex",
        summary={"goal_state": "NEEDS_HUMAN_INPUT", "recovery_pause": {"reason": "requires_approval"}},
    )
    session.add(run)
    await session.flush()
    artifact = Artifact(
        project_id=project.id,
        tenant_id=tenant_id,
        run_id=run.id,
        type="git_diff",
        uri="workspace://patches/needs-approval.patch",
        version=1,
    )
    session.add(artifact)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        approval_resp = await client.post(
            f"/api/v1/projects/{project.id}/approvals",
            json={
                "target_type": "artifact",
                "target_id": str(artifact.id),
                "status": "APPROVED",
                "decided_by": "demo-user",
                "comment": "Approved for demo flow",
            },
        )
    assert approval_resp.status_code == 201, approval_resp.text

    await session.refresh(run)
    assert run.status == "QUEUED"
    summary = run.summary or {}
    assert summary.get("auto_resumed_after_approval") is True
    assert "recovery_pause" not in summary
