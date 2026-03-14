"""Best-effort staging validation harness for the knowledge hardening pass.

This script is intentionally retained for reruns after shared-environment
alignment. It is useful for staging verification, but it is not yet treated as
a stable green-check gate because the shared environment still has unrelated
schema drift and the full Postgres concurrency pass has not completed cleanly.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import types
import uuid
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import routes
from app.db.models import (
    KnowledgeArtifact,
    KnowledgeEvent,
    KnowledgeProposal,
    KnowledgePublication,
    Project,
    ProjectRepository,
)
from app.db.session import SessionLocal
from app.main import app
from app.services import knowledge_git, repo_connector


class ValidationError(RuntimeError):
    pass


class DummyGitHubAdapter:
    def verify_signature(self, body: bytes, signature_header: str | None) -> bool:
        secret = os.getenv("GITHUB_WEBHOOK_SECRET", "supersecret").encode()
        mac = hmac.new(secret, msg=body, digestmod=hashlib.sha256)
        return signature_header == f"sha256={mac.hexdigest()}"

    def get_pr_files(self, *_args, **_kwargs):
        return {"added": [], "modified": [], "removed": [], "all_files": []}

    def post_pr_comment(self, *_args, **_kwargs):
        return "ok"

    def assert_org_allowed(self, _org_login: str) -> None:
        return None


@dataclass
class ValidationContext:
    tenant_id: uuid.UUID = field(default_factory=uuid.uuid4)
    reviewer_user_id: str = field(default_factory=lambda: f"knowledge-reviewer-{uuid.uuid4().hex[:8]}")
    workspace_dir: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="knowledge-live-workspace-")))
    remote_dir: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="knowledge-live-remote-")))
    project_ids: list[uuid.UUID] = field(default_factory=list)

    def headers(self, *, user_id: str | None = None) -> dict[str, str]:
        return {
            "X-Tenant-Id": str(self.tenant_id),
            "X-User-Id": user_id or self.reviewer_user_id,
        }


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "Agentic SDLC Validation")
    env.setdefault("GIT_AUTHOR_EMAIL", "validation@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "Agentic SDLC Validation")
    env.setdefault("GIT_COMMITTER_EMAIL", "validation@example.com")
    return env


def _run_git(args: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        env=_git_env(),
        check=False,
    )
    if result.returncode != 0:
        raise ValidationError(result.stderr or result.stdout or f"git {' '.join(args)} failed")
    return (result.stdout or "").strip()


def _seed_remote_repo(base_dir: Path, name: str) -> Path:
    seed = base_dir / f"{name}-seed"
    remote = base_dir / f"{name}-origin.git"
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


async def _create_project_repo(
    session: AsyncSession,
    *,
    ctx: ValidationContext,
    remote: Path,
    name: str,
    repo_full_name: str,
) -> tuple[Project, ProjectRepository]:
    project = Project(name=name, tenant_id=ctx.tenant_id)
    session.add(project)
    await session.flush()
    repository = ProjectRepository(
        project_id=project.id,
        tenant_id=ctx.tenant_id,
        provider="github",
        repo_url=str(remote),
        repo_full_name=repo_full_name,
        default_branch="main",
        created_by=ctx.reviewer_user_id,
    )
    session.add(repository)
    await session.commit()
    await session.refresh(project)
    ctx.project_ids.append(project.id)
    return project, repository


async def _manual_sync(
    client: AsyncClient,
    *,
    ctx: ValidationContext,
    project_id: uuid.UUID,
    user_id: str | None = None,
) -> dict:
    response = await client.post(
        "/api/v1/knowledge/events/manual-sync",
        json={"project_id": str(project_id)},
        headers=ctx.headers(user_id=user_id),
    )
    if response.status_code != 202:
        raise ValidationError(f"manual sync failed: {response.status_code} {response.text}")
    return response.json()


async def _wait_for_proposals(
    session: AsyncSession,
    *,
    event_id: uuid.UUID,
    timeout_seconds: float = 20.0,
) -> list[KnowledgeProposal]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        proposals = (
            await session.execute(
                select(KnowledgeProposal)
                .where(KnowledgeProposal.knowledge_event_id == event_id)
                .order_by(KnowledgeProposal.created_at.asc())
            )
        ).scalars().all()
        if proposals:
            return proposals
        event = await session.get(KnowledgeEvent, event_id)
        if event and event.status == "failed":
            raise ValidationError(f"event {event_id} failed analysis: {event.error_message}")
        if asyncio.get_running_loop().time() >= deadline:
            raise ValidationError(f"timed out waiting for proposals for event {event_id}")
        await session.rollback()
        await asyncio.sleep(0.2)


async def _proposal_ids_for_event(
    session: AsyncSession,
    *,
    event_id: uuid.UUID,
    artifact_type: str | None = None,
) -> list[uuid.UUID]:
    stmt = select(KnowledgeProposal).where(KnowledgeProposal.knowledge_event_id == event_id)
    if artifact_type:
        stmt = stmt.where(KnowledgeProposal.artifact_type == artifact_type)
    rows = (await session.execute(stmt.order_by(KnowledgeProposal.created_at.asc()))).scalars().all()
    return [row.id for row in rows]


async def _single_proposal_id(
    session: AsyncSession,
    *,
    event_id: uuid.UUID,
    artifact_type: str | None = None,
) -> uuid.UUID:
    ids = await _proposal_ids_for_event(session, event_id=event_id, artifact_type=artifact_type)
    if not ids:
        suffix = f" artifact_type={artifact_type}" if artifact_type else ""
        raise ValidationError(f"no proposal found for event {event_id}{suffix}")
    return ids[0]


async def _expect_count(
    session: AsyncSession,
    *,
    model,
    where_clause,
) -> int:
    return (await session.execute(select(func.count()).select_from(model).where(where_clause))).scalar_one()


async def validate_migration_assumptions(session: AsyncSession) -> None:
    project_count = (await session.execute(text("select count(*) from projects"))).scalar_one()
    repo_count = (await session.execute(text("select count(*) from project_repositories"))).scalar_one()
    event_count = (await session.execute(text("select count(*) from knowledge_events"))).scalar_one()
    proposal_count = (await session.execute(text("select count(*) from knowledge_proposals"))).scalar_one()
    publication_count = (await session.execute(text("select count(*) from knowledge_publications"))).scalar_one()
    columns = (
        await session.execute(
            text(
                """
                select column_name
                from information_schema.columns
                where table_name = 'knowledge_proposals'
                  and column_name in ('base_artifact_version', 'base_artifact_hash')
                order by column_name
                """
            )
        )
    ).scalars().all()
    constraint = (
        await session.execute(
            text(
                """
                select conname
                from pg_constraint
                where conname = 'uq_knowledge_publications_proposal_id'
                """
            )
        )
    ).scalar_one_or_none()
    if columns != ["base_artifact_hash", "base_artifact_version"]:
        raise ValidationError(f"knowledge proposal hardening columns missing: {columns}")
    if constraint != "uq_knowledge_publications_proposal_id":
        raise ValidationError("knowledge publication uniqueness constraint missing")
    if project_count <= 0:
        raise ValidationError("expected at least one existing project record to remain readable")
    print(
        json.dumps(
            {
                "step": "migration",
                "project_count": project_count,
                "repo_count": repo_count,
                "knowledge_event_count": event_count,
                "knowledge_proposal_count": proposal_count,
                "knowledge_publication_count": publication_count,
                "note": "shared database had no pre-existing knowledge rows before validation fixture creation",
            }
        )
    )


async def validate_scoping_and_reviewer_identity(
    session: AsyncSession,
    client: AsyncClient,
    *,
    ctx: ValidationContext,
) -> None:
    remote_a = _seed_remote_repo(ctx.remote_dir, "scope-a")
    remote_b = _seed_remote_repo(ctx.remote_dir, "scope-b")
    _commit_to_remote(remote_b, "apps/api/app/main.py", 'print("scope-b")\n', "feat: scope b")
    project_a, _repo_a = await _create_project_repo(
        session,
        ctx=ctx,
        remote=remote_a,
        name="Knowledge Scope A",
        repo_full_name=f"validation/{uuid.uuid4().hex[:8]}-scope-a",
    )
    project_b, _repo_b = await _create_project_repo(
        session,
        ctx=ctx,
        remote=remote_b,
        name="Knowledge Scope B",
        repo_full_name=f"validation/{uuid.uuid4().hex[:8]}-scope-b",
    )

    sync_b = await _manual_sync(client, ctx=ctx, project_id=project_b.id)
    event_b_id = uuid.UUID(sync_b["event"]["id"])
    proposals_b = await _wait_for_proposals(session, event_id=event_b_id)
    proposal_b = proposals_b[0]
    artifact_b = await session.get(KnowledgeArtifact, proposal_b.artifact_id)
    if artifact_b is None:
        raise ValidationError("expected a scoped artifact for project B")

    missing_project = await client.get("/api/v1/knowledge/inbox", headers=ctx.headers())
    wrong_inbox = await client.get(
        f"/api/v1/knowledge/inbox?project_id={project_a.id}",
        headers=ctx.headers(),
    )
    wrong_proposals = await client.get(
        f"/api/v1/knowledge/proposals?project_id={project_a.id}",
        headers=ctx.headers(),
    )
    wrong_artifacts = await client.get(
        f"/api/v1/knowledge/artifacts?project_id={project_a.id}",
        headers=ctx.headers(),
    )
    wrong_detail = await client.get(
        f"/api/v1/knowledge/proposals/{proposal_b.id}?project_id={project_a.id}",
        headers=ctx.headers(),
    )
    wrong_event = await client.get(
        f"/api/v1/knowledge/events/{event_b_id}?project_id={project_a.id}",
        headers=ctx.headers(),
    )
    wrong_artifact = await client.get(
        f"/api/v1/knowledge/artifacts/{artifact_b.id}?project_id={project_a.id}",
        headers=ctx.headers(),
    )
    wrong_approve = await client.post(
        f"/api/v1/knowledge/proposals/{proposal_b.id}/approve?project_id={project_a.id}",
        json={"review_notes": "should fail"},
        headers=ctx.headers(),
    )
    spoofed = await client.post(
        f"/api/v1/knowledge/proposals/{proposal_b.id}/approve?project_id={project_b.id}",
        json={"review_notes": "verified", "reviewer_user_id": "spoofed-user"},
        headers=ctx.headers(user_id="actual-reviewer"),
    )
    if missing_project.status_code != 422:
        raise ValidationError(f"omitted project_id leaked or passed unexpectedly: {missing_project.status_code}")
    if wrong_inbox.status_code != 200 or str(proposal_b.id) in wrong_inbox.text:
        raise ValidationError("cross-project inbox read was not blocked")
    if wrong_proposals.status_code != 200 or str(proposal_b.id) in wrong_proposals.text:
        raise ValidationError("cross-project proposal list leaked data")
    if wrong_artifacts.status_code != 200 or str(artifact_b.id) in wrong_artifacts.text:
        raise ValidationError("cross-project artifact list leaked data")
    if wrong_detail.status_code != 404 or wrong_event.status_code != 404 or wrong_artifact.status_code != 404:
        raise ValidationError("project-scoped detail lookup was not blocked")
    if wrong_approve.status_code != 404:
        raise ValidationError("cross-project approve did not return 404")
    if spoofed.status_code != 200:
        raise ValidationError(f"reviewer validation approve failed: {spoofed.status_code} {spoofed.text}")
    body = spoofed.json()
    if body["reviews"][0]["reviewer_user_id"] != "actual-reviewer":
        raise ValidationError("reviewer identity was not taken from authenticated context")
    if body["publication"]["published_by"] != "actual-reviewer":
        raise ValidationError("publication reviewer identity was spoofable")
    print(json.dumps({"step": "scoping", "proposal_id": str(proposal_b.id), "artifact_id": str(artifact_b.id)}))


async def _concurrent_approve(
    *,
    ctx: ValidationContext,
    project_id: uuid.UUID,
    proposal_id: uuid.UUID,
) -> list[int]:
    async def approve_once() -> int:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://validation") as client:
            response = await client.post(
                f"/api/v1/knowledge/proposals/{proposal_id}/approve?project_id={project_id}",
                json={"review_notes": "retry approval"},
                headers=ctx.headers(),
            )
            return response.status_code

    return list(await asyncio.gather(approve_once(), approve_once()))


async def validate_state_machine_and_concurrency(
    session: AsyncSession,
    client: AsyncClient,
    *,
    ctx: ValidationContext,
) -> None:
    approve_remote = _seed_remote_repo(ctx.remote_dir, "approve")
    _commit_to_remote(approve_remote, "apps/api/app/main.py", 'print("approve")\n', "feat: approve")
    approve_project, _ = await _create_project_repo(
        session,
        ctx=ctx,
        remote=approve_remote,
        name="Knowledge Approve",
        repo_full_name=f"validation/{uuid.uuid4().hex[:8]}-approve",
    )
    approve_sync = await _manual_sync(client, ctx=ctx, project_id=approve_project.id)
    approve_event_id = uuid.UUID(approve_sync["event"]["id"])
    approve_proposal_id = await _single_proposal_id(session, event_id=approve_event_id)
    statuses = await _concurrent_approve(ctx=ctx, project_id=approve_project.id, proposal_id=approve_proposal_id)
    await session.rollback()
    proposal = await session.get(KnowledgeProposal, approve_proposal_id)
    if proposal is None or proposal.artifact_id is None:
        raise ValidationError("approved proposal missing after concurrent approval")
    publication_count = await _expect_count(
        session,
        model=KnowledgePublication,
        where_clause=KnowledgePublication.proposal_id == proposal.id,
    )
    artifact = await session.get(KnowledgeArtifact, proposal.artifact_id)
    if statuses != [200, 200]:
        raise ValidationError(f"concurrent approval did not remain idempotent: {statuses}")
    if proposal.review_status != "published" or publication_count != 1 or artifact is None or artifact.current_version != 1:
        raise ValidationError("concurrent approval created duplicate publication/version state")

    reject_remote = _seed_remote_repo(ctx.remote_dir, "reject")
    _commit_to_remote(reject_remote, "apps/api/app/reject.py", 'print("reject")\n', "feat: reject")
    reject_project, _ = await _create_project_repo(
        session,
        ctx=ctx,
        remote=reject_remote,
        name="Knowledge Reject",
        repo_full_name=f"validation/{uuid.uuid4().hex[:8]}-reject",
    )
    reject_sync = await _manual_sync(client, ctx=ctx, project_id=reject_project.id)
    reject_proposal_id = await _single_proposal_id(session, event_id=uuid.UUID(reject_sync["event"]["id"]))
    reject_once = await client.post(
        f"/api/v1/knowledge/proposals/{reject_proposal_id}/reject?project_id={reject_project.id}",
        json={"review_notes": "reject"},
        headers=ctx.headers(),
    )
    reject_again = await client.post(
        f"/api/v1/knowledge/proposals/{reject_proposal_id}/reject?project_id={reject_project.id}",
        json={"review_notes": "reject again"},
        headers=ctx.headers(),
    )
    approve_after_reject = await client.post(
        f"/api/v1/knowledge/proposals/{reject_proposal_id}/approve?project_id={reject_project.id}",
        json={"review_notes": "invalid"},
        headers=ctx.headers(),
    )
    if [reject_once.status_code, reject_again.status_code, approve_after_reject.status_code] != [200, 409, 409]:
        raise ValidationError("reject terminal state machine validation failed")

    defer_remote = _seed_remote_repo(ctx.remote_dir, "defer")
    _commit_to_remote(defer_remote, "apps/api/app/defer.py", 'print("defer")\n', "feat: defer")
    defer_project, _ = await _create_project_repo(
        session,
        ctx=ctx,
        remote=defer_remote,
        name="Knowledge Defer",
        repo_full_name=f"validation/{uuid.uuid4().hex[:8]}-defer",
    )
    defer_sync = await _manual_sync(client, ctx=ctx, project_id=defer_project.id)
    defer_proposal_id = await _single_proposal_id(session, event_id=uuid.UUID(defer_sync["event"]["id"]))
    defer_once = await client.post(
        f"/api/v1/knowledge/proposals/{defer_proposal_id}/defer?project_id={defer_project.id}",
        json={"review_notes": "defer"},
        headers=ctx.headers(),
    )
    defer_again = await client.post(
        f"/api/v1/knowledge/proposals/{defer_proposal_id}/defer?project_id={defer_project.id}",
        json={"review_notes": "defer again"},
        headers=ctx.headers(),
    )
    reject_after_defer = await client.post(
        f"/api/v1/knowledge/proposals/{defer_proposal_id}/reject?project_id={defer_project.id}",
        json={"review_notes": "invalid"},
        headers=ctx.headers(),
    )
    if [defer_once.status_code, defer_again.status_code, reject_after_defer.status_code] != [200, 409, 409]:
        raise ValidationError("defer terminal state machine validation failed")

    stale_remote = _seed_remote_repo(ctx.remote_dir, "stale")
    _commit_to_remote(stale_remote, "apps/api/app/first.py", 'print("first")\n', "feat: first")
    stale_project, _ = await _create_project_repo(
        session,
        ctx=ctx,
        remote=stale_remote,
        name="Knowledge Stale",
        repo_full_name=f"validation/{uuid.uuid4().hex[:8]}-stale",
    )
    first_sync = await _manual_sync(client, ctx=ctx, project_id=stale_project.id)
    first_event_id = uuid.UUID(first_sync["event"]["id"])
    first_proposal_id = await _single_proposal_id(session, event_id=first_event_id, artifact_type="changelog")
    _commit_to_remote(stale_remote, "apps/api/app/second.py", 'print("second")\n', "feat: second")
    second_sync = await _manual_sync(client, ctx=ctx, project_id=stale_project.id)
    second_event_id = uuid.UUID(second_sync["event"]["id"])
    second_proposal_id = await _single_proposal_id(session, event_id=second_event_id, artifact_type="changelog")
    approve_newer = await client.post(
        f"/api/v1/knowledge/proposals/{second_proposal_id}/approve?project_id={stale_project.id}",
        json={"review_notes": "publish newer"},
        headers=ctx.headers(),
    )
    approve_stale = await client.post(
        f"/api/v1/knowledge/proposals/{first_proposal_id}/approve?project_id={stale_project.id}",
        json={"review_notes": "publish stale"},
        headers=ctx.headers(),
    )
    stale_detail = await client.get(
        f"/api/v1/knowledge/proposals/{first_proposal_id}?project_id={stale_project.id}",
        headers=ctx.headers(),
    )
    first_event = await client.get(
        f"/api/v1/knowledge/events/{first_event_id}?project_id={stale_project.id}",
        headers=ctx.headers(),
    )
    second_event = await client.get(
        f"/api/v1/knowledge/events/{second_event_id}?project_id={stale_project.id}",
        headers=ctx.headers(),
    )
    if approve_newer.status_code != 200 or approve_stale.status_code != 409:
        raise ValidationError("stale publish protection failed")
    if stale_detail.json()["review_status"] != "superseded":
        raise ValidationError("stale proposal did not become superseded")
    if first_event.json()["status"] != "superseded" or second_event.json()["status"] != "published":
        raise ValidationError("event status did not reflect stale/published lifecycle")
    print(
        json.dumps(
            {
                "step": "state_machine",
                "concurrent_approve_statuses": statuses,
                "published_proposal_id": str(approve_proposal_id),
                "stale_proposal_id": str(first_proposal_id),
            }
        )
    )


async def validate_webhook_and_manual_sync(
    session: AsyncSession,
    client: AsyncClient,
    *,
    ctx: ValidationContext,
) -> None:
    webhook_remote = _seed_remote_repo(ctx.remote_dir, "webhook")
    commit_sha = _commit_to_remote(webhook_remote, "apps/api/app/main.py", 'print("webhook")\n', "feat: webhook")
    repo_full_name = f"validation/{uuid.uuid4().hex[:8]}-webhook"
    webhook_project, _ = await _create_project_repo(
        session,
        ctx=ctx,
        remote=webhook_remote,
        name="Knowledge Webhook",
        repo_full_name=repo_full_name,
    )
    payload = {
        "ref": "refs/heads/main",
        "before": "0" * 40,
        "after": commit_sha,
        "repository": {"full_name": repo_full_name},
        "head_commit": {"message": "feat: webhook"},
    }
    body = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(b"supersecret", msg=body, digestmod=hashlib.sha256).hexdigest()
    first = await client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "validation-delivery",
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json",
        },
    )
    second = await client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "validation-delivery",
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json",
        },
    )
    if first.status_code != 200 or second.status_code != 200:
        raise ValidationError("webhook replay requests did not succeed")
    if first.json().get("knowledge_events_created") != 1 or second.json().get("knowledge_events_created") != 0:
        raise ValidationError("webhook replay was not idempotent at the API layer")
    webhook_event_count = await _expect_count(
        session,
        model=KnowledgeEvent,
        where_clause=KnowledgeEvent.project_id == webhook_project.id,
    )
    if webhook_event_count != 1:
        raise ValidationError(f"webhook replay created duplicate events: {webhook_event_count}")

    manual_remote = _seed_remote_repo(ctx.remote_dir, "manual")
    _commit_to_remote(manual_remote, "apps/api/app/manual.py", 'print("manual")\n', "feat: manual")
    manual_project, _ = await _create_project_repo(
        session,
        ctx=ctx,
        remote=manual_remote,
        name="Knowledge Manual",
        repo_full_name=f"validation/{uuid.uuid4().hex[:8]}-manual",
    )
    manual_first = await _manual_sync(client, ctx=ctx, project_id=manual_project.id)
    manual_second = await _manual_sync(client, ctx=ctx, project_id=manual_project.id)
    if manual_first["event"]["id"] != manual_second["event"]["id"]:
        raise ValidationError("manual sync did not reuse the same event for the same commit")
    manual_event_count = await _expect_count(
        session,
        model=KnowledgeEvent,
        where_clause=KnowledgeEvent.project_id == manual_project.id,
    )
    if manual_event_count != 1:
        raise ValidationError(f"manual sync created duplicate events: {manual_event_count}")

    mixed_remote = _seed_remote_repo(ctx.remote_dir, "mixed")
    mixed_commit = _commit_to_remote(mixed_remote, "apps/api/app/mixed.py", 'print("mixed")\n', "feat: mixed")
    mixed_repo_full_name = f"validation/{uuid.uuid4().hex[:8]}-mixed"
    mixed_project, _ = await _create_project_repo(
        session,
        ctx=ctx,
        remote=mixed_remote,
        name="Knowledge Mixed",
        repo_full_name=mixed_repo_full_name,
    )
    mixed_payload = {
        "ref": "refs/heads/main",
        "before": "0" * 40,
        "after": mixed_commit,
        "repository": {"full_name": mixed_repo_full_name},
        "head_commit": {"message": "feat: mixed"},
    }
    mixed_body = json.dumps(mixed_payload).encode("utf-8")
    mixed_signature = "sha256=" + hmac.new(b"supersecret", msg=mixed_body, digestmod=hashlib.sha256).hexdigest()
    mixed_webhook = await client.post(
        "/api/v1/webhooks/github",
        content=mixed_body,
        headers={
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "validation-mixed-delivery",
            "X-Hub-Signature-256": mixed_signature,
            "Content-Type": "application/json",
        },
    )
    if mixed_webhook.status_code != 200:
        raise ValidationError(f"mixed webhook failed: {mixed_webhook.status_code} {mixed_webhook.text}")
    await asyncio.sleep(0.5)
    mixed_manual = await _manual_sync(client, ctx=ctx, project_id=mixed_project.id)
    await asyncio.sleep(0.5)
    mixed_event_count = await _expect_count(
        session,
        model=KnowledgeEvent,
        where_clause=KnowledgeEvent.project_id == mixed_project.id,
    )
    mixed_proposal_count = await _expect_count(
        session,
        model=KnowledgeProposal,
        where_clause=KnowledgeProposal.project_id == mixed_project.id,
    )
    if mixed_event_count != 1:
        raise ValidationError(
            f"mixed webhook + manual sync created duplicate events for same commit: {mixed_event_count} "
            f"(manual_sync_event={mixed_manual['event']['id']})"
        )
    if mixed_proposal_count <= 0:
        raise ValidationError("mixed webhook + manual sync did not produce any proposals")
    print(
        json.dumps(
            {
                "step": "webhook_manual",
                "webhook_event_count": webhook_event_count,
                "manual_event_count": manual_event_count,
                "mixed_event_count": mixed_event_count,
                "mixed_proposal_count": mixed_proposal_count,
            }
        )
    )


async def cleanup_validation_fixture(session: AsyncSession, *, ctx: ValidationContext) -> None:
    if ctx.project_ids:
        await session.execute(delete(Project).where(Project.id.in_(ctx.project_ids)))
    await session.commit()


async def main() -> None:
    ctx = ValidationContext()
    settings_stub = types.SimpleNamespace(
        workspace_base_dir=str(ctx.workspace_dir),
        workspace_repo_source=None,
        git_author_name="Agentic SDLC Validation",
        git_author_email="validation@example.com",
        runtime_git_auth_mode="auto",
    )
    original_repo_get_settings = repo_connector.get_settings
    original_knowledge_get_settings = knowledge_git.get_settings
    original_github_adapter = routes.github_adapter
    os.environ["GITHUB_WEBHOOK_SECRET"] = "supersecret"
    repo_connector.get_settings = lambda: settings_stub
    knowledge_git.get_settings = lambda: settings_stub
    routes.github_adapter = DummyGitHubAdapter()
    try:
        async with SessionLocal() as session:
            try:
                await validate_migration_assumptions(session)
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://validation") as client:
                    await validate_scoping_and_reviewer_identity(session, client, ctx=ctx)
                    await validate_state_machine_and_concurrency(session, client, ctx=ctx)
                    await validate_webhook_and_manual_sync(session, client, ctx=ctx)
            finally:
                await cleanup_validation_fixture(session, ctx=ctx)
    finally:
        repo_connector.get_settings = original_repo_get_settings
        knowledge_git.get_settings = original_knowledge_get_settings
        routes.github_adapter = original_github_adapter


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ValidationError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        raise SystemExit(1) from exc
