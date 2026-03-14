from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import types
import uuid
from pathlib import Path

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.api.v1 import routes
from app.db.base import Base
from app.db.models import (
    KnowledgeArtifact,
    KnowledgeEvent,
    KnowledgeProposal,
    KnowledgePublication,
    KnowledgeReview,
    Project,
    ProjectRepository,
)
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app
from app.services import knowledge_git, knowledge_service, repo_connector


pytest.importorskip("aiosqlite")


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "Agentic SDLC Tests")
    env.setdefault("GIT_AUTHOR_EMAIL", "tests@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "Agentic SDLC Tests")
    env.setdefault("GIT_COMMITTER_EMAIL", "tests@example.com")
    return env


def _auth_headers(tenant_id: uuid.UUID, user_id: str = "reviewer-1") -> dict[str, str]:
    return {
        "X-Tenant-Id": str(tenant_id),
        "X-User-Id": user_id,
    }


def _query_with_project(project_id: uuid.UUID) -> str:
    return f"?project_id={project_id}"


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


def _seed_remote_repo(tmp_path: Path, name: str) -> Path:
    seed = tmp_path / f"{name}-seed"
    remote = tmp_path / f"{name}-origin.git"
    seed.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-b", "main"], cwd=seed)
    (seed / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git(["add", "README.md"], cwd=seed)
    _run_git(["commit", "-m", "init"], cwd=seed)
    _run_git(["init", "--bare", str(remote)])
    _run_git(["remote", "add", "origin", str(remote)], cwd=seed)
    _run_git(["push", "-u", "origin", "main"], cwd=seed)
    return remote


def _commit_to_remote(remote: Path, rel_path: str, content: str, message: str) -> str:
    worktree = remote.parent / f"work-{uuid.uuid4().hex[:8]}"
    _run_git(["clone", str(remote), str(worktree)])
    file_path = worktree / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    _run_git(["add", rel_path], cwd=worktree)
    _run_git(["commit", "-m", message], cwd=worktree)
    _run_git(["push", "origin", "main"], cwd=worktree)
    return _run_git(["rev-parse", "HEAD"], cwd=worktree)


class DummyGitHubAdapter:
    def verify_signature(self, body: bytes, signature_header: str | None) -> bool:
        mac = hmac.new(os.getenv("GITHUB_WEBHOOK_SECRET", "supersecret").encode(), msg=body, digestmod=hashlib.sha256)
        return signature_header == f"sha256={mac.hexdigest()}"

    def get_pr_files(self, *_args, **_kwargs):
        return {"added": [], "modified": [], "removed": [], "all_files": []}

    def post_pr_comment(self, *_args, **_kwargs):
        return "ok"

    def assert_org_allowed(self, org_login: str) -> None:
        return None


@pytest.fixture
async def db_session(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'knowledge.db'}", future=True)
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

    default_tenant_id = uuid.uuid4()

    async def override_get_tenant_context(request: Request):
        tenant_header = request.headers.get("X-Tenant-Id")
        user_header = request.headers.get("X-User-Id")
        tenant_id = uuid.UUID(tenant_header) if tenant_header else default_tenant_id
        return TenantContext(
            tenant_id=tenant_id,
            user_id=user_header or "reviewer-1",
            role=None,
            enforcement=False,
        )

    settings_stub = types.SimpleNamespace(
        workspace_base_dir=str(tmp_path / "workspaces"),
        workspace_repo_source=None,
        git_author_name="Agentic SDLC Tests",
        git_author_email="tests@example.com",
        runtime_git_auth_mode="auto",
    )
    monkeypatch.setattr(repo_connector, "get_settings", lambda: settings_stub)
    monkeypatch.setattr(knowledge_git, "get_settings", lambda: settings_stub)

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_tenant_context] = override_get_tenant_context
    session: AsyncSession = session_factory()
    try:
        yield session, default_tenant_id, tmp_path
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_tenant_context, None)
        await session.close()
        await engine.dispose()


async def _create_project_repo(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    remote: Path,
    name: str,
    repo_full_name: str,
) -> tuple[Project, ProjectRepository]:
    project = Project(name=name, tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    repo = ProjectRepository(
        project_id=project.id,
        tenant_id=tenant_id,
        provider="github",
        repo_url=str(remote),
        repo_full_name=repo_full_name,
        default_branch="main",
    )
    session.add(repo)
    await session.commit()
    await session.refresh(project)
    return project, repo


async def _manual_sync(
    client: AsyncClient,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: str = "reviewer-1",
) -> dict:
    response = await client.post(
        "/api/v1/knowledge/events/manual-sync",
        json={"project_id": str(project_id)},
        headers=_auth_headers(tenant_id, user_id=user_id),
    )
    assert response.status_code == 202, response.text
    return response.json()


async def _inbox_items(client: AsyncClient, *, tenant_id: uuid.UUID, project_id: uuid.UUID) -> list[dict]:
    response = await client.get(
        f"/api/v1/knowledge/inbox{_query_with_project(project_id)}",
        headers=_auth_headers(tenant_id),
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def _artifact_items(client: AsyncClient, *, tenant_id: uuid.UUID, project_id: uuid.UUID) -> list[dict]:
    response = await client.get(
        f"/api/v1/knowledge/artifacts{_query_with_project(project_id)}",
        headers=_auth_headers(tenant_id),
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _proposal_id_for_artifact(items: list[dict], artifact_type: str) -> str:
    for item in items:
        if item["artifact_type"] == artifact_type:
            return str(item["proposal_id"])
    raise AssertionError(f"Expected proposal for artifact_type={artifact_type}")


async def _proposal_ids_for_event(
    session: AsyncSession,
    *,
    event_id: str | uuid.UUID,
    artifact_type: str | None = None,
) -> list[str]:
    stmt = select(KnowledgeProposal).where(KnowledgeProposal.knowledge_event_id == uuid.UUID(str(event_id)))
    if artifact_type is not None:
        stmt = stmt.where(KnowledgeProposal.artifact_type == artifact_type)
    rows = (await session.execute(stmt.order_by(KnowledgeProposal.created_at.asc()))).scalars().all()
    return [str(row.id) for row in rows]


async def _proposal_row(session: AsyncSession, proposal_id: str | uuid.UUID) -> KnowledgeProposal:
    proposal = await session.get(KnowledgeProposal, uuid.UUID(str(proposal_id)))
    assert proposal is not None
    return proposal


@pytest.mark.anyio
async def test_manual_sync_generates_proposals_and_publish_flow(db_session):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path, "basic")
    _commit_to_remote(remote, "README.md", "hello\nknowledge update\n", "docs: expand onboarding")
    project, _repo = await _create_project_repo(
        session,
        tenant_id=tenant_id,
        remote=remote,
        name="Knowledge Project",
        repo_full_name="example/repo-basic",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sync_data = await _manual_sync(client, tenant_id=tenant_id, project_id=project.id)
        assert sync_data["inline_processed"] is True
        event_id = sync_data["event"]["id"]

        inbox_items = await _inbox_items(client, tenant_id=tenant_id, project_id=project.id)
        assert len(inbox_items) >= 1

        for item in inbox_items:
            approve_resp = await client.post(
                f"/api/v1/knowledge/proposals/{item['proposal_id']}/approve{_query_with_project(project.id)}",
                json={"review_notes": "verified"},
                headers=_auth_headers(tenant_id),
            )
            assert approve_resp.status_code == 200, approve_resp.text

        event_resp = await client.get(
            f"/api/v1/knowledge/events/{event_id}{_query_with_project(project.id)}",
            headers=_auth_headers(tenant_id),
        )
        assert event_resp.status_code == 200
        assert event_resp.json()["status"] == "published"

        artifact_items = await _artifact_items(client, tenant_id=tenant_id, project_id=project.id)
        assert len(artifact_items) >= 1

    artifact_count = (
        await session.execute(
            select(func.count()).select_from(KnowledgeArtifact).where(KnowledgeArtifact.project_id == project.id)
        )
    ).scalar_one()
    assert artifact_count >= 1


@pytest.mark.anyio
async def test_push_webhook_is_idempotent(db_session, monkeypatch):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path, "webhook")
    commit_sha = _commit_to_remote(remote, "apps/api/app/main.py", 'print("noop")\n', "feat: change runtime")
    project, _repo = await _create_project_repo(
        session,
        tenant_id=tenant_id,
        remote=remote,
        name="Webhook Project",
        repo_full_name="example/repo-webhook",
    )

    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "supersecret")
    dummy = DummyGitHubAdapter()
    monkeypatch.setattr(routes, "github_adapter", dummy)

    payload = {
        "ref": "refs/heads/main",
        "before": "0" * 40,
        "after": commit_sha,
        "repository": {"full_name": "example/repo-webhook"},
        "head_commit": {"message": "feat: change runtime"},
    }
    body = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(b"supersecret", msg=body, digestmod=hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/v1/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "delivery-1",
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/json",
            },
        )
        second = await client.post(
            "/api/v1/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "delivery-1",
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/json",
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["knowledge_events_created"] == 1
    assert second.json()["knowledge_events_created"] == 0

    count = (
        await session.execute(
            select(func.count()).select_from(KnowledgeEvent).where(KnowledgeEvent.project_id == project.id)
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.anyio
async def test_manual_sync_schema_change_generates_db_note(db_session):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path, "schema")
    _commit_to_remote(
        remote,
        "apps/api/alembic/versions/20260314_extra_table.py",
        "revision = 'x'\n",
        "feat: add migration",
    )
    project, _repo = await _create_project_repo(
        session,
        tenant_id=tenant_id,
        remote=remote,
        name="Schema Project",
        repo_full_name="example/repo-schema",
    )

    result = await knowledge_service.trigger_manual_sync(
        session,
        tenant_id=tenant_id,
        project_id=project.id,
        triggered_by="reviewer-1",
    )

    assert result.proposals_created >= 1
    proposal_types = (
        await session.execute(
            select(KnowledgeProposal.artifact_type).where(KnowledgeProposal.project_id == project.id)
        )
    ).scalars().all()
    assert "db_note" in proposal_types


@pytest.mark.anyio
async def test_manual_sync_is_idempotent_for_same_commit(db_session):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path, "dedupe")
    _commit_to_remote(remote, "apps/api/app/main.py", 'print("v1")\n', "feat: add runtime hook")
    project, _repo = await _create_project_repo(
        session,
        tenant_id=tenant_id,
        remote=remote,
        name="Manual Sync Project",
        repo_full_name="example/repo-dedupe",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _manual_sync(client, tenant_id=tenant_id, project_id=project.id)
        second = await _manual_sync(client, tenant_id=tenant_id, project_id=project.id)

    assert first["event"]["id"] == second["event"]["id"]
    event_count = (
        await session.execute(
            select(func.count()).select_from(KnowledgeEvent).where(KnowledgeEvent.project_id == project.id)
        )
    ).scalar_one()
    proposal_count = (
        await session.execute(
            select(func.count()).select_from(KnowledgeProposal).where(KnowledgeProposal.project_id == project.id)
        )
    ).scalar_one()
    assert event_count == 1
    assert proposal_count >= 1


@pytest.mark.anyio
async def test_project_scope_blocks_cross_project_reads_and_writes(db_session):
    session, tenant_id, tmp_path = db_session
    remote_a = _seed_remote_repo(tmp_path, "scope-a")
    remote_b = _seed_remote_repo(tmp_path, "scope-b")
    _commit_to_remote(remote_b, "apps/api/app/main.py", 'print("b")\n', "feat: project b change")

    project_a, _repo_a = await _create_project_repo(
        session,
        tenant_id=tenant_id,
        remote=remote_a,
        name="Project A",
        repo_full_name="example/repo-scope-a",
    )
    project_b, _repo_b = await _create_project_repo(
        session,
        tenant_id=tenant_id,
        remote=remote_b,
        name="Project B",
        repo_full_name="example/repo-scope-b",
    )

    result_b = await knowledge_service.trigger_manual_sync(
        session,
        tenant_id=tenant_id,
        project_id=project_b.id,
        triggered_by="reviewer-1",
    )
    proposal_b = await session.scalar(
        select(KnowledgeProposal).where(KnowledgeProposal.knowledge_event_id == result_b.event.id)
    )
    artifact_b = await session.scalar(
        select(KnowledgeArtifact).where(KnowledgeArtifact.project_id == project_b.id)
    )
    assert proposal_b is not None
    assert artifact_b is not None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        inbox_a = await client.get(
            f"/api/v1/knowledge/inbox{_query_with_project(project_a.id)}",
            headers=_auth_headers(tenant_id),
        )
        proposals_a = await client.get(
            f"/api/v1/knowledge/proposals{_query_with_project(project_a.id)}",
            headers=_auth_headers(tenant_id),
        )
        artifacts_a = await client.get(
            f"/api/v1/knowledge/artifacts{_query_with_project(project_a.id)}",
            headers=_auth_headers(tenant_id),
        )

        assert inbox_a.status_code == 200
        assert proposals_a.status_code == 200
        assert artifacts_a.status_code == 200
        assert str(proposal_b.id) not in json.dumps(inbox_a.json())
        assert str(proposal_b.id) not in json.dumps(proposals_a.json())
        assert str(artifact_b.id) not in json.dumps(artifacts_a.json())

        wrong_scope_detail = await client.get(
            f"/api/v1/knowledge/proposals/{proposal_b.id}{_query_with_project(project_a.id)}",
            headers=_auth_headers(tenant_id),
        )
        wrong_scope_artifact = await client.get(
            f"/api/v1/knowledge/artifacts/{artifact_b.id}{_query_with_project(project_a.id)}",
            headers=_auth_headers(tenant_id),
        )
        wrong_scope_event = await client.get(
            f"/api/v1/knowledge/events/{result_b.event.id}{_query_with_project(project_a.id)}",
            headers=_auth_headers(tenant_id),
        )
        wrong_scope_approve = await client.post(
            f"/api/v1/knowledge/proposals/{proposal_b.id}/approve{_query_with_project(project_a.id)}",
            json={"review_notes": "should fail"},
            headers=_auth_headers(tenant_id),
        )

    assert wrong_scope_detail.status_code == 404
    assert wrong_scope_artifact.status_code == 404
    assert wrong_scope_event.status_code == 404
    assert wrong_scope_approve.status_code == 404


@pytest.mark.anyio
async def test_reviewer_identity_comes_from_authenticated_user(db_session):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path, "reviewer")
    _commit_to_remote(remote, "apps/api/app/main.py", 'print("review")\n', "feat: reviewer flow")
    project, _repo = await _create_project_repo(
        session,
        tenant_id=tenant_id,
        remote=remote,
        name="Reviewer Project",
        repo_full_name="example/repo-reviewer",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sync_data = await _manual_sync(client, tenant_id=tenant_id, project_id=project.id)
        proposal_id = (await _proposal_ids_for_event(session, event_id=sync_data["event"]["id"]))[0]
        response = await client.post(
            f"/api/v1/knowledge/proposals/{proposal_id}/approve{_query_with_project(project.id)}",
            json={"review_notes": "verified", "reviewer_user_id": "spoofed-user"},
            headers=_auth_headers(tenant_id, user_id="actual-reviewer"),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reviews"][0]["reviewer_user_id"] == "actual-reviewer"
    assert body["publication"]["published_by"] == "actual-reviewer"

    review = await session.scalar(select(KnowledgeReview).where(KnowledgeReview.proposal_id == uuid.UUID(proposal_id)))
    assert review is not None
    assert review.reviewer_user_id == "actual-reviewer"


@pytest.mark.anyio
async def test_repeated_approve_is_idempotent_and_terminal_actions_are_blocked(db_session):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path, "approve-state")
    _commit_to_remote(remote, "apps/api/app/main.py", 'print("approve")\n', "feat: state machine")
    project, _repo = await _create_project_repo(
        session,
        tenant_id=tenant_id,
        remote=remote,
        name="Approve Project",
        repo_full_name="example/repo-approve",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sync_data = await _manual_sync(client, tenant_id=tenant_id, project_id=project.id)
        proposal_id = (await _proposal_ids_for_event(session, event_id=sync_data["event"]["id"]))[0]

        first = await client.post(
            f"/api/v1/knowledge/proposals/{proposal_id}/approve{_query_with_project(project.id)}",
            json={"review_notes": "first approval"},
            headers=_auth_headers(tenant_id),
        )
        second = await client.post(
            f"/api/v1/knowledge/proposals/{proposal_id}/approve{_query_with_project(project.id)}",
            json={"review_notes": "retry approval"},
            headers=_auth_headers(tenant_id),
        )
        reject_after_publish = await client.post(
            f"/api/v1/knowledge/proposals/{proposal_id}/reject{_query_with_project(project.id)}",
            json={"review_notes": "invalid reject"},
            headers=_auth_headers(tenant_id),
        )
        defer_after_publish = await client.post(
            f"/api/v1/knowledge/proposals/{proposal_id}/defer{_query_with_project(project.id)}",
            json={"review_notes": "invalid defer"},
            headers=_auth_headers(tenant_id),
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert reject_after_publish.status_code == 409
    assert defer_after_publish.status_code == 409

    proposal = await _proposal_row(session, proposal_id)
    publication_count = (
        await session.execute(
            select(func.count()).select_from(KnowledgePublication).where(KnowledgePublication.proposal_id == proposal.id)
        )
    ).scalar_one()
    artifact = await session.get(KnowledgeArtifact, proposal.artifact_id)
    assert artifact is not None
    assert proposal.review_status == "published"
    assert publication_count == 1
    assert artifact.current_version == 1


@pytest.mark.anyio
async def test_reject_and_defer_validate_terminal_state_machine(db_session):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path, "reject-defer")
    _commit_to_remote(remote, "apps/api/app/main.py", 'print("one")\n', "feat: first change")
    project, _repo = await _create_project_repo(
        session,
        tenant_id=tenant_id,
        remote=remote,
        name="Reject Defer Project",
        repo_full_name="example/repo-reject-defer",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_sync = await _manual_sync(client, tenant_id=tenant_id, project_id=project.id)
        first_proposal_id = (await _proposal_ids_for_event(session, event_id=first_sync["event"]["id"]))[0]

        reject = await client.post(
            f"/api/v1/knowledge/proposals/{first_proposal_id}/reject{_query_with_project(project.id)}",
            json={"review_notes": "reject"},
            headers=_auth_headers(tenant_id),
        )
        reject_again = await client.post(
            f"/api/v1/knowledge/proposals/{first_proposal_id}/reject{_query_with_project(project.id)}",
            json={"review_notes": "reject again"},
            headers=_auth_headers(tenant_id),
        )
        approve_after_reject = await client.post(
            f"/api/v1/knowledge/proposals/{first_proposal_id}/approve{_query_with_project(project.id)}",
            json={"review_notes": "should fail"},
            headers=_auth_headers(tenant_id),
        )

        _commit_to_remote(remote, "apps/api/app/other.py", 'print("two")\n', "feat: second change")
        second_sync = await _manual_sync(client, tenant_id=tenant_id, project_id=project.id)
        second_proposal_id = (await _proposal_ids_for_event(session, event_id=second_sync["event"]["id"]))[0]

        defer = await client.post(
            f"/api/v1/knowledge/proposals/{second_proposal_id}/defer{_query_with_project(project.id)}",
            json={"review_notes": "defer"},
            headers=_auth_headers(tenant_id),
        )
        defer_again = await client.post(
            f"/api/v1/knowledge/proposals/{second_proposal_id}/defer{_query_with_project(project.id)}",
            json={"review_notes": "defer again"},
            headers=_auth_headers(tenant_id),
        )
        reject_after_defer = await client.post(
            f"/api/v1/knowledge/proposals/{second_proposal_id}/reject{_query_with_project(project.id)}",
            json={"review_notes": "should fail"},
            headers=_auth_headers(tenant_id),
        )

    assert reject.status_code == 200
    assert reject_again.status_code == 409
    assert approve_after_reject.status_code == 409
    assert defer.status_code == 200
    assert defer_again.status_code == 409
    assert reject_after_defer.status_code == 409


@pytest.mark.anyio
async def test_stale_proposal_is_superseded_and_cannot_overwrite_newer_publication(db_session):
    session, tenant_id, tmp_path = db_session
    remote = _seed_remote_repo(tmp_path, "stale")
    _commit_to_remote(remote, "apps/api/app/main.py", 'print("first")\n', "feat: first change")
    project, _repo = await _create_project_repo(
        session,
        tenant_id=tenant_id,
        remote=remote,
        name="Stale Project",
        repo_full_name="example/repo-stale",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_sync = await _manual_sync(client, tenant_id=tenant_id, project_id=project.id)
        first_changelog_id = (await _proposal_ids_for_event(
            session,
            event_id=first_sync["event"]["id"],
            artifact_type="changelog",
        ))[0]

        _commit_to_remote(remote, "apps/api/app/worker.py", 'print("second")\n', "feat: second change")
        second_sync = await _manual_sync(client, tenant_id=tenant_id, project_id=project.id)
        second_changelog_id = (await _proposal_ids_for_event(
            session,
            event_id=second_sync["event"]["id"],
            artifact_type="changelog",
        ))[0]

        approve_newer = await client.post(
            f"/api/v1/knowledge/proposals/{second_changelog_id}/approve{_query_with_project(project.id)}",
            json={"review_notes": "publish newer"},
            headers=_auth_headers(tenant_id),
        )
        approve_stale = await client.post(
            f"/api/v1/knowledge/proposals/{first_changelog_id}/approve{_query_with_project(project.id)}",
            json={"review_notes": "publish stale"},
            headers=_auth_headers(tenant_id),
        )
        stale_detail = await client.get(
            f"/api/v1/knowledge/proposals/{first_changelog_id}{_query_with_project(project.id)}",
            headers=_auth_headers(tenant_id),
        )
        first_event = await client.get(
            f"/api/v1/knowledge/events/{first_sync['event']['id']}{_query_with_project(project.id)}",
            headers=_auth_headers(tenant_id),
        )
        second_event = await client.get(
            f"/api/v1/knowledge/events/{second_sync['event']['id']}{_query_with_project(project.id)}",
            headers=_auth_headers(tenant_id),
        )

    assert approve_newer.status_code == 200, approve_newer.text
    assert approve_stale.status_code == 409
    assert stale_detail.status_code == 200
    assert stale_detail.json()["review_status"] == "superseded"
    assert first_event.json()["status"] == "superseded"
    assert second_event.json()["status"] == "published"

    newer_proposal = await _proposal_row(session, second_changelog_id)
    stale_proposal = await _proposal_row(session, first_changelog_id)
    artifact = await session.get(KnowledgeArtifact, newer_proposal.artifact_id)
    assert artifact is not None
    assert stale_proposal.review_status == "superseded"
    assert artifact.current_version == 1
    assert artifact.canonical_content == approve_newer.json()["publication"]["published_content"]


@pytest.mark.anyio
async def test_event_status_tracks_rejected_deferred_and_published_mixes(db_session):
    session, tenant_id, tmp_path = db_session

    reject_remote = _seed_remote_repo(tmp_path, "status-reject")
    _commit_to_remote(reject_remote, "apps/api/app/main.py", 'print("reject")\n', "feat: reject change")
    reject_project, _ = await _create_project_repo(
        session,
        tenant_id=tenant_id,
        remote=reject_remote,
        name="Reject Status Project",
        repo_full_name="example/repo-status-reject",
    )

    defer_remote = _seed_remote_repo(tmp_path, "status-defer")
    _commit_to_remote(defer_remote, "apps/api/app/main.py", 'print("defer")\n', "feat: defer change")
    defer_project, _ = await _create_project_repo(
        session,
        tenant_id=tenant_id,
        remote=defer_remote,
        name="Defer Status Project",
        repo_full_name="example/repo-status-defer",
    )

    mixed_remote = _seed_remote_repo(tmp_path, "status-mixed")
    _commit_to_remote(
        mixed_remote,
        "apps/api/alembic/versions/20260314_extra_table.py",
        "revision = 'mixed'\n",
        "feat: mixed schema change",
    )
    mixed_project, _ = await _create_project_repo(
        session,
        tenant_id=tenant_id,
        remote=mixed_remote,
        name="Mixed Status Project",
        repo_full_name="example/repo-status-mixed",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reject_sync = await _manual_sync(client, tenant_id=tenant_id, project_id=reject_project.id)
        for proposal_id in await _proposal_ids_for_event(session, event_id=reject_sync["event"]["id"]):
            reject_resp = await client.post(
                f"/api/v1/knowledge/proposals/{proposal_id}/reject{_query_with_project(reject_project.id)}",
                json={"review_notes": "reject event"},
                headers=_auth_headers(tenant_id),
            )
            assert reject_resp.status_code == 200

        defer_sync = await _manual_sync(client, tenant_id=tenant_id, project_id=defer_project.id)
        for proposal_id in await _proposal_ids_for_event(session, event_id=defer_sync["event"]["id"]):
            defer_resp = await client.post(
                f"/api/v1/knowledge/proposals/{proposal_id}/defer{_query_with_project(defer_project.id)}",
                json={"review_notes": "defer event"},
                headers=_auth_headers(tenant_id),
            )
            assert defer_resp.status_code == 200

        mixed_sync = await _manual_sync(client, tenant_id=tenant_id, project_id=mixed_project.id)
        mixed_items = await _inbox_items(client, tenant_id=tenant_id, project_id=mixed_project.id)
        db_note_id = _proposal_id_for_artifact(mixed_items, "db_note")
        other_proposal_id = next(
            str(item["proposal_id"]) for item in mixed_items if str(item["proposal_id"]) != db_note_id
        )
        approve_mixed = await client.post(
            f"/api/v1/knowledge/proposals/{db_note_id}/approve{_query_with_project(mixed_project.id)}",
            json={"review_notes": "publish one"},
            headers=_auth_headers(tenant_id),
        )
        reject_other = await client.post(
            f"/api/v1/knowledge/proposals/{other_proposal_id}/reject{_query_with_project(mixed_project.id)}",
            json={"review_notes": "reject one"},
            headers=_auth_headers(tenant_id),
        )
        assert approve_mixed.status_code == 200
        assert reject_other.status_code == 200

        reject_event = await client.get(
            f"/api/v1/knowledge/events/{reject_sync['event']['id']}{_query_with_project(reject_project.id)}",
            headers=_auth_headers(tenant_id),
        )
        defer_event = await client.get(
            f"/api/v1/knowledge/events/{defer_sync['event']['id']}{_query_with_project(defer_project.id)}",
            headers=_auth_headers(tenant_id),
        )
        mixed_event = await client.get(
            f"/api/v1/knowledge/events/{mixed_sync['event']['id']}{_query_with_project(mixed_project.id)}",
            headers=_auth_headers(tenant_id),
        )

    assert reject_event.status_code == 200
    assert defer_event.status_code == 200
    assert mixed_event.status_code == 200
    assert reject_event.json()["status"] == "rejected"
    assert defer_event.json()["status"] == "deferred"
    assert mixed_event.json()["status"] == "published"
