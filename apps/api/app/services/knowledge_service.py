from __future__ import annotations

import asyncio
import difflib
import fnmatch
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Artifact,
    KnowledgeArtifact,
    KnowledgeChange,
    KnowledgeEvent,
    KnowledgeFileMapping,
    KnowledgeProposal,
    KnowledgePublication,
    KnowledgeReview,
    Project,
    ProjectRepository,
    Run,
)
from app.db.session import SessionLocal
from app.schemas.knowledge import (
    KnowledgeArtifactDetailOut,
    KnowledgeArtifactListResponse,
    KnowledgeArtifactHistoryItemOut,
    KnowledgeArtifactSummaryOut,
    KnowledgeChangeOut,
    KnowledgeEventDetailOut,
    KnowledgeEventSummaryOut,
    KnowledgeInboxItemOut,
    KnowledgeInboxResponse,
    KnowledgeProposalListResponse,
    KnowledgeProposalDetailOut,
    KnowledgeProposalSummaryOut,
    KnowledgePublicationOut,
    KnowledgeReviewOut,
    KnowledgeSearchHookListResponse,
    KnowledgeSearchHookOut,
    KnowledgeTriggerResponse,
)
from app.services.knowledge_git import current_head, diff_snapshot, ensure_analysis_repo, fetch_origin, previous_commit
from app.services.repo_connector import get_project_repository
from app.services.run_summary_builder import upsert_run_summary
from app.services.ai_policy import AIJobManager, AIJobRequest


logger = logging.getLogger("app.knowledge")
ai_job_manager = AIJobManager()

EMPTY_CONTENT_HASH = hashlib.sha256(b"").hexdigest()
PROPOSAL_PENDING = "pending"
PROPOSAL_DEFERRED = "deferred"
PROPOSAL_APPROVED = "approved"
PROPOSAL_REJECTED = "rejected"
PROPOSAL_SUPERSEDED = "superseded"
PROPOSAL_PUBLISHED = "published"
PROPOSAL_TERMINAL_STATUSES = {
    PROPOSAL_DEFERRED,
    PROPOSAL_REJECTED,
    PROPOSAL_SUPERSEDED,
    PROPOSAL_PUBLISHED,
}
PROPOSAL_OPEN_STATUSES = {
    PROPOSAL_PENDING,
    PROPOSAL_APPROVED,
}

LOW_SIGNAL_DOC_EXTENSIONS = (".md", ".mdx", ".rst", ".txt")
TEST_PATH_TOKENS = ("test", "tests", "__tests__", "spec", ".spec.", ".test.", "fixtures/")
SCHEMA_PATH_TOKENS = ("migration", "migrations", "schema", "schemas", "alembic", ".sql")
INFRA_PATH_TOKENS = ("infra/", "deploy", "docker", "compose", "k8s", "helm", "terraform", ".github/workflows")
API_PATH_TOKENS = ("api/", "router", "routes", "controller", "openapi", "graphql")
ONBOARDING_PATH_TOKENS = ("README", ".env", "package.json", "pyproject.toml", "requirements", "setup", "vite.config")
CONFIG_PATH_TOKENS = ("package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", ".toml", ".ini", ".yaml", ".yml", ".env")

SECTION_BY_ARTIFACT = {
    "changelog": "Entries",
    "release_note": "Entries",
    "module_doc": "Recent Verified Updates",
    "architecture_note": "Recent Verified Updates",
    "runbook": "Recent Verified Updates",
    "adr": "Recent Verified Updates",
    "onboarding_note": "Recent Verified Updates",
    "api_note": "Recent Verified Updates",
    "db_note": "Recent Verified Updates",
}

TITLE_BY_ARTIFACT = {
    "changelog": "Project Changelog",
    "module_doc": "Module Documentation",
    "architecture_note": "Architecture Notes",
    "runbook": "Operations Runbook",
    "adr": "Architecture Decision Record",
    "release_note": "Release Notes",
    "onboarding_note": "Developer Onboarding Notes",
    "api_note": "API Surface Notes",
    "db_note": "Database Notes",
}


@dataclass(frozen=True)
class EventSnapshot:
    title: str
    body: str
    branch_name: str | None
    commit_sha: str | None
    base_ref: str | None
    changed_files: list[str]
    diff_text: str
    commit_messages: list[str]
    pr_number: int | None = None


@dataclass(frozen=True)
class ChangeSignals:
    change_type: str
    summary: str
    technical_summary: str
    business_summary: str
    risk_level: str
    confidence_score: float
    impacts_runtime: bool
    impacts_api: bool
    impacts_schema: bool
    impacts_docs: bool
    impacts_architecture: bool
    impacts_onboarding: bool
    impacted_files: list[str]
    impacted_modules: list[str]
    probable_artifacts: list[dict[str, Any]]
    docs_only: bool
    test_only: bool


@dataclass(frozen=True)
class ArtifactSuggestion:
    artifact_type: str
    artifact_key: str
    artifact_title: str
    proposal_type: str
    target_section: str | None
    rationale: str
    confidence_score: float


class KnowledgeServiceError(Exception):
    """Base exception for knowledge subsystem failures."""


class KnowledgeNotFoundError(KnowledgeServiceError):
    """Raised when a scoped object cannot be found."""


class KnowledgeConflictError(KnowledgeServiceError):
    """Raised when a lifecycle action conflicts with current state."""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _content_hash(content: str | None) -> str:
    payload = (content or "").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    compact = "-".join(part for part in cleaned.split("-") if part)
    return compact or "default"


def _safe_title(event: KnowledgeEvent, snapshot: EventSnapshot) -> str:
    title = (event.title or snapshot.title or "").strip()
    if title:
        return title
    if snapshot.commit_sha:
        return f"{event.source_type} update {snapshot.commit_sha[:8]}"
    return f"{event.source_type} update"


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = (value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _looks_like_docs_path(path: str) -> bool:
    lowered = path.lower()
    return lowered.startswith("docs/") or any(token in path for token in ("README", "CHANGELOG")) or lowered.endswith(
        LOW_SIGNAL_DOC_EXTENSIONS
    )


def _looks_like_test_path(path: str) -> bool:
    lowered = path.lower()
    return any(token in lowered for token in TEST_PATH_TOKENS)


def _has_tokens(path: str, tokens: tuple[str, ...]) -> bool:
    lowered = path.lower()
    return any(token in lowered for token in tokens)


def _derive_modules(paths: list[str]) -> list[str]:
    modules: list[str] = []
    for path in paths:
        parts = [part for part in path.split("/") if part]
        if not parts:
            continue
        if len(parts) >= 2 and parts[0] in {"apps", "core", "agent", "docs", "infra"}:
            modules.append("/".join(parts[:2]))
        else:
            modules.append(parts[0])
    return _unique_strings(modules)[:4]


def _change_type_from_paths(paths: list[str], title: str, body: str) -> str:
    joined_text = f"{title} {body}".lower()
    docs_only = bool(paths) and all(_looks_like_docs_path(path) for path in paths)
    test_only = bool(paths) and all(_looks_like_test_path(path) for path in paths)
    if any(_has_tokens(path, SCHEMA_PATH_TOKENS) for path in paths):
        return "schema"
    if docs_only:
        return "docs"
    if test_only:
        return "test"
    if any(_has_tokens(path, INFRA_PATH_TOKENS) for path in paths):
        return "infra"
    if any(_has_tokens(path, API_PATH_TOKENS) for path in paths):
        return "api"
    if any(_has_tokens(path, CONFIG_PATH_TOKENS) for path in paths):
        return "config"
    if any(token in joined_text for token in ("bug", "fix", "hotfix", "repair")):
        return "bugfix"
    if any(token in joined_text for token in ("refactor", "cleanup", "rename", "reorganize")):
        return "refactor"
    if any(token in joined_text for token in ("feature", "feat", "implement", "add", "introduce")):
        return "feature"
    if len(paths) >= 6:
        return "refactor"
    return "unknown"


def _impact_flags(paths: list[str], modules: list[str]) -> dict[str, bool]:
    docs_only = bool(paths) and all(_looks_like_docs_path(path) for path in paths)
    test_only = bool(paths) and all(_looks_like_test_path(path) for path in paths)
    impacts_schema = any(_has_tokens(path, SCHEMA_PATH_TOKENS) for path in paths)
    impacts_api = any(_has_tokens(path, API_PATH_TOKENS) for path in paths)
    impacts_onboarding = any(any(token in path for token in ONBOARDING_PATH_TOKENS) for path in paths)
    impacts_architecture = impacts_schema or any(_has_tokens(path, INFRA_PATH_TOKENS) for path in paths) or len(modules) >= 3
    impacts_runtime = bool(paths) and not docs_only and not test_only
    impacts_docs = docs_only or impacts_api or impacts_schema or impacts_onboarding or impacts_architecture or any(
        _has_tokens(path, CONFIG_PATH_TOKENS) for path in paths
    )
    return {
        "docs_only": docs_only,
        "test_only": test_only,
        "impacts_runtime": impacts_runtime,
        "impacts_api": impacts_api,
        "impacts_schema": impacts_schema,
        "impacts_docs": impacts_docs,
        "impacts_architecture": impacts_architecture,
        "impacts_onboarding": impacts_onboarding,
    }


def _risk_level(change_type: str, flags: dict[str, bool], changed_files: int) -> str:
    if flags["impacts_schema"] or (flags["impacts_api"] and changed_files >= 3) or flags["impacts_architecture"]:
        return "high"
    if change_type in {"feature", "api", "infra", "config", "bugfix"} or flags["impacts_runtime"] or changed_files >= 4:
        return "medium"
    return "low"


def _confidence_score(change_type: str, flags: dict[str, bool], title: str, body: str, changed_files: int) -> float:
    score = 0.45
    title_text = f"{title} {body}".lower()
    if change_type in {"docs", "test", "schema", "infra", "api", "config"}:
        score += 0.18
    if change_type == "unknown":
        score -= 0.08
    if change_type in {"bugfix", "feature", "refactor"} and change_type.replace("fix", "") in title_text:
        score += 0.1
    if flags["impacts_schema"] or flags["impacts_api"] or flags["impacts_architecture"]:
        score += 0.08
    if changed_files >= 5:
        score += 0.04
    return round(max(0.25, min(score, 0.95)), 2)


def _plain_summary(title: str, change_type: str, modules: list[str], paths: list[str]) -> str:
    module_text = ", ".join(modules[:3]) if modules else "the repository"
    file_count = len(paths)
    return f"{title} touched {file_count} file(s) and mainly affects {module_text}; classified as {change_type}."


def _technical_summary(change_type: str, paths: list[str], flags: dict[str, bool], commit_messages: list[str]) -> str:
    signals: list[str] = [f"Primary classification: {change_type}."]
    if paths:
        signals.append(f"Changed files: {', '.join(paths[:8])}.")
    if commit_messages:
        signals.append(f"Commit messages: {' | '.join(commit_messages[:4])}.")
    impact_tokens = [
        name.replace("impacts_", "")
        for name, enabled in flags.items()
        if name.startswith("impacts_") and enabled
    ]
    if impact_tokens:
        signals.append(f"Impact signals: {', '.join(impact_tokens)}.")
    return " ".join(signals)


def _business_summary(change_type: str, flags: dict[str, bool], modules: list[str]) -> str:
    if flags["impacts_schema"]:
        return "Database-facing behavior changed, so verified DB notes should be refreshed before the change is treated as official project knowledge."
    if flags["impacts_api"]:
        return "External or internal API expectations likely changed; reviewers should confirm the official API guidance stays accurate."
    if flags["impacts_onboarding"]:
        return "Developer onboarding material may now be stale and should be re-verified."
    if change_type == "infra":
        return "Operational behavior changed, so the runbook should be verified before operators depend on it."
    if modules:
        return f"Module knowledge for {', '.join(modules[:2])} may now be stale and should be re-verified."
    return "Project knowledge may now be stale and should be reviewed before publication."


def _artifact_target_title(artifact_type: str, artifact_key: str, module_name: str | None = None) -> str:
    if artifact_type == "module_doc" and module_name:
        return f"{module_name} Module Documentation"
    if artifact_type == "module_doc":
        return f"{artifact_key.replace('-', ' ').title()} Module Documentation"
    return TITLE_BY_ARTIFACT.get(artifact_type, artifact_key.replace("-", " ").title())


def _artifact_rationale(artifact_type: str, paths: list[str], change_type: str) -> str:
    focus = ", ".join(paths[:5]) if paths else "the repository diff"
    return f"{artifact_type} is suggested because the {change_type} touches {focus}, which can stale official engineering knowledge."


def _default_artifact_suggestions(change: ChangeSignals, mappings: list[KnowledgeFileMapping]) -> list[ArtifactSuggestion]:
    suggestions: list[ArtifactSuggestion] = []
    seen: set[tuple[str, str]] = set()

    def add(artifact_type: str, artifact_key: str, *, module_name: str | None = None, confidence_boost: float = 0.0) -> None:
        key = (artifact_type, artifact_key)
        if key in seen:
            return
        seen.add(key)
        suggestions.append(
            ArtifactSuggestion(
                artifact_type=artifact_type,
                artifact_key=artifact_key,
                artifact_title=_artifact_target_title(artifact_type, artifact_key, module_name),
                proposal_type="append",
                target_section=SECTION_BY_ARTIFACT.get(artifact_type),
                rationale=_artifact_rationale(artifact_type, change.impacted_files, change.change_type),
                confidence_score=round(min(change.confidence_score + confidence_boost, 0.99), 2),
            )
        )

    for mapping in mappings:
        add(mapping.artifact_type, mapping.artifact_key, module_name=mapping.module_name, confidence_boost=0.05)

    if change.docs_only:
        add("changelog", "project-changelog")
        if change.impacts_onboarding:
            add("onboarding_note", "developer-onboarding")
        return suggestions

    if change.test_only and change.risk_level == "low" and len(change.impacted_files) <= 2:
        return suggestions

    add("changelog", "project-changelog")
    for module_name in change.impacted_modules[:2]:
        add("module_doc", _slugify(module_name), module_name=module_name)
    if change.impacts_api:
        add("api_note", "api-surface")
    if change.impacts_schema:
        add("db_note", "database")
    if change.impacts_architecture:
        add("architecture_note", "system-architecture")
    if change.impacts_onboarding:
        add("onboarding_note", "developer-onboarding")
    if change.change_type in {"infra", "config"}:
        add("runbook", "operations")
    if any("package" in path or "lock" in path or "build" in path for path in change.impacted_files):
        add("release_note", "release")
    return suggestions


def _replace_section(content: str, section_title: str, new_body: str) -> str:
    lines = content.splitlines()
    target_prefix = f"## {section_title}".strip()
    start_index: int | None = None
    end_index = len(lines)
    for idx, line in enumerate(lines):
        if line.strip() == target_prefix:
            start_index = idx
            continue
        if start_index is not None and idx > start_index and line.startswith("## "):
            end_index = idx
            break
    if start_index is None:
        return content.rstrip() + f"\n\n## {section_title}\n\n{new_body.strip()}\n"
    new_lines = lines[: start_index + 1] + ["", *new_body.strip().splitlines(), ""] + lines[end_index:]
    return "\n".join(new_lines).strip() + "\n"


def _seed_artifact_content(artifact_type: str, artifact_title: str, target_section: str | None) -> str:
    base = f"# {artifact_title}\n"
    if target_section:
        return base + f"\n## {target_section}\n\n"
    return base + "\n"


def _proposal_body(suggestion: ArtifactSuggestion, event: KnowledgeEvent, snapshot: EventSnapshot, change: ChangeSignals) -> str:
    title = _safe_title(event, snapshot)
    changed_files = "\n".join(f"- `{path}`" for path in change.impacted_files[:8]) or "- None"
    impacted_modules = ", ".join(change.impacted_modules) or "repository-wide"
    return (
        f"### {title}\n\n"
        f"- Source: `{event.source_type}`\n"
        f"- Change type: `{change.change_type}`\n"
        f"- Risk: `{change.risk_level}`\n"
        f"- Confidence: `{change.confidence_score}`\n"
        f"- Impacted modules: {impacted_modules}\n\n"
        f"{change.summary}\n\n"
        f"{change.technical_summary}\n\n"
        f"{change.business_summary}\n\n"
        f"Changed files:\n{changed_files}\n"
    )


def _merge_generated_content(
    *,
    artifact: KnowledgeArtifact,
    suggestion: ArtifactSuggestion,
    event: KnowledgeEvent,
    snapshot: EventSnapshot,
    change: ChangeSignals,
) -> tuple[str, str]:
    current_content = artifact.canonical_content or ""
    body = _proposal_body(suggestion, event, snapshot, change)
    if not current_content.strip():
        seeded = _seed_artifact_content(suggestion.artifact_type, suggestion.artifact_title, suggestion.target_section)
        if suggestion.target_section:
            generated = _replace_section(seeded, suggestion.target_section, body)
        else:
            generated = seeded.rstrip() + "\n\n" + body.strip() + "\n"
        return "create", generated
    if suggestion.target_section:
        return "append", _replace_section(current_content, suggestion.target_section, current_content_section_append(current_content, suggestion.target_section, body))
    return "append", current_content.rstrip() + "\n\n" + body.strip() + "\n"


def current_content_section_append(current_content: str, section_title: str, new_body: str) -> str:
    lines = current_content.splitlines()
    target_prefix = f"## {section_title}".strip()
    in_target = False
    section_lines: list[str] = []
    for line in lines:
        if line.strip() == target_prefix:
            in_target = True
            continue
        if in_target and line.startswith("## "):
            break
        if in_target:
            section_lines.append(line)
    existing = "\n".join(section_lines).strip()
    if not existing:
        return new_body.strip()
    return existing.rstrip() + "\n\n" + new_body.strip()


def _build_diff_preview(current_content: str, generated_content: str) -> str:
    diff_lines = difflib.unified_diff(
        current_content.splitlines(),
        generated_content.splitlines(),
        fromfile="official",
        tofile="proposed",
        lineterm="",
    )
    return "\n".join(diff_lines)


def _artifact_search_text(artifact: KnowledgeArtifact) -> str:
    return f"{artifact.title}\n{artifact.artifact_type}\n{artifact.artifact_key}\n{artifact.canonical_content}".strip()


async def _find_project_repo_by_full_name(
    session: AsyncSession, repo_full_name: str
) -> list[ProjectRepository]:
    result = await session.execute(
        select(ProjectRepository).where(
            ProjectRepository.provider == "github",
            ProjectRepository.repo_full_name == repo_full_name,
        )
    )
    return result.scalars().all()


async def _get_project_scope(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> Project:
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.tenant_id == tenant_id,
            Project.deleted_at.is_(None),
        )
    )
    if project is None:
        raise KnowledgeNotFoundError("knowledge project not found")
    return project


async def _get_repository_scope(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    repository_id: uuid.UUID,
) -> ProjectRepository:
    repository = await session.scalar(
        select(ProjectRepository).where(
            ProjectRepository.id == repository_id,
            ProjectRepository.project_id == project_id,
            ProjectRepository.tenant_id == tenant_id,
        )
    )
    if repository is None:
        raise KnowledgeNotFoundError("knowledge repository not found")
    return repository


async def _get_scoped_proposal(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    proposal_id: uuid.UUID,
    for_update: bool = False,
) -> KnowledgeProposal:
    stmt = select(KnowledgeProposal).where(
        KnowledgeProposal.id == proposal_id,
        KnowledgeProposal.project_id == project_id,
        KnowledgeProposal.tenant_id == tenant_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    proposal = await session.scalar(stmt)
    if proposal is None:
        raise KnowledgeNotFoundError("knowledge proposal not found")
    return proposal


async def _get_scoped_artifact(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    artifact_id: uuid.UUID,
    for_update: bool = False,
) -> KnowledgeArtifact:
    stmt = select(KnowledgeArtifact).where(
        KnowledgeArtifact.id == artifact_id,
        KnowledgeArtifact.project_id == project_id,
        KnowledgeArtifact.tenant_id == tenant_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    artifact = await session.scalar(stmt)
    if artifact is None:
        raise KnowledgeNotFoundError("knowledge artifact not found")
    return artifact


async def _get_scoped_event(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    event_id: uuid.UUID,
) -> KnowledgeEvent:
    event = await session.scalar(
        select(KnowledgeEvent).where(
            KnowledgeEvent.id == event_id,
            KnowledgeEvent.project_id == project_id,
            KnowledgeEvent.tenant_id == tenant_id,
        )
    )
    if event is None:
        raise KnowledgeNotFoundError("knowledge event not found")
    return event


async def _matched_mappings(
    session: AsyncSession, *, repository_id: uuid.UUID, paths: list[str]
) -> list[KnowledgeFileMapping]:
    result = await session.execute(
        select(KnowledgeFileMapping)
        .where(KnowledgeFileMapping.repository_id == repository_id)
        .order_by(KnowledgeFileMapping.priority.asc(), KnowledgeFileMapping.created_at.asc())
    )
    rows = result.scalars().all()
    matched: list[KnowledgeFileMapping] = []
    for row in rows:
        if any(fnmatch.fnmatch(path, row.file_path_pattern) for path in paths):
            matched.append(row)
    return matched


async def _get_or_create_artifact(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    repository_id: uuid.UUID,
    suggestion: ArtifactSuggestion,
) -> KnowledgeArtifact:
    artifact = await session.scalar(
        select(KnowledgeArtifact).where(
            KnowledgeArtifact.project_id == project_id,
            KnowledgeArtifact.repository_id == repository_id,
            KnowledgeArtifact.artifact_type == suggestion.artifact_type,
            KnowledgeArtifact.artifact_key == suggestion.artifact_key,
        )
    )
    if artifact is not None:
        return artifact
    artifact = KnowledgeArtifact(
        tenant_id=tenant_id,
        project_id=project_id,
        repository_id=repository_id,
        artifact_type=suggestion.artifact_type,
        artifact_key=suggestion.artifact_key,
        title=suggestion.artifact_title,
        canonical_content="",
        current_version=0,
        status="active",
    )
    session.add(artifact)
    await session.flush()
    return artifact


async def _load_event_snapshot(session: AsyncSession, event: KnowledgeEvent, repo: ProjectRepository) -> EventSnapshot:
    payload = event.raw_payload_json or {}
    if event.source_type == "push":
        repo_dir = ensure_analysis_repo(repo, branch_name=event.branch_name or repo.default_branch)
        fetch_origin(repo, repo_dir)
        after_ref = event.commit_sha or payload.get("after") or current_head(repo_dir, "HEAD")
        before_ref = payload.get("before")
        if before_ref and set(before_ref) == {"0"}:
            before_ref = None
        if not after_ref:
            raise ValueError("push event is missing an after commit")
        diff = diff_snapshot(repo_dir, base_ref=before_ref, head_ref=after_ref)
        title = (payload.get("head_commit") or {}).get("message") or (diff.commit_messages[0] if diff.commit_messages else "")
        return EventSnapshot(
            title=title.splitlines()[0] if title else f"Push to {event.branch_name or repo.default_branch}",
            body="",
            branch_name=event.branch_name,
            commit_sha=after_ref,
            base_ref=before_ref,
            changed_files=diff.changed_files,
            diff_text=diff.diff_text,
            commit_messages=diff.commit_messages,
        )
    if event.source_type == "pr_merged":
        repo_dir = ensure_analysis_repo(repo, branch_name=repo.default_branch)
        fetch_origin(repo, repo_dir)
        pull_request = payload.get("pull_request") or {}
        merge_ref = event.commit_sha or pull_request.get("merge_commit_sha") or pull_request.get("head", {}).get("sha")
        base_ref = pull_request.get("base", {}).get("sha")
        if not merge_ref:
            raise ValueError("merged PR event is missing a merge commit")
        diff = diff_snapshot(repo_dir, base_ref=base_ref, head_ref=merge_ref)
        return EventSnapshot(
            title=pull_request.get("title") or f"Merged PR #{event.pr_number}",
            body=pull_request.get("body") or "",
            branch_name=pull_request.get("base", {}).get("ref") or repo.default_branch,
            commit_sha=merge_ref,
            base_ref=base_ref,
            changed_files=diff.changed_files,
            diff_text=diff.diff_text,
            commit_messages=diff.commit_messages,
            pr_number=event.pr_number,
        )
    if event.source_type == "manual_sync":
        repo_dir = ensure_analysis_repo(repo, branch_name=event.branch_name or repo.default_branch)
        fetch_origin(repo, repo_dir)
        head_ref = event.commit_sha or payload.get("head_ref") or current_head(repo_dir, "HEAD")
        base_ref = payload.get("base_ref")
        if not head_ref:
            raise ValueError("manual sync could not resolve repository head")
        diff = diff_snapshot(repo_dir, base_ref=base_ref, head_ref=head_ref)
        return EventSnapshot(
            title=event.title or f"Manual knowledge sync for {event.branch_name or repo.default_branch}",
            body=payload.get("notes") or "",
            branch_name=event.branch_name,
            commit_sha=head_ref,
            base_ref=base_ref,
            changed_files=diff.changed_files,
            diff_text=diff.diff_text,
            commit_messages=diff.commit_messages,
        )
    if event.source_type == "agent_run":
        run_id = payload.get("run_id")
        if not run_id:
            raise ValueError("agent run event is missing run_id")
        run = await session.get(Run, uuid.UUID(str(run_id)))
        if run is None:
            raise ValueError("agent run not found")
        await upsert_run_summary(session, run.id)
        artifacts = (
            await session.execute(
                select(Artifact).where(
                    Artifact.run_id == run.id,
                    Artifact.tenant_id == run.tenant_id,
                    Artifact.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        changed_files = _unique_strings([value for value in (payload.get("changed_files") or []) if isinstance(value, str)])
        diff_texts: list[str] = []
        for artifact in artifacts:
            if artifact.type != "git_diff":
                continue
            metadata = artifact.extra_metadata or {}
            content = metadata.get("content")
            if isinstance(content, str) and content.strip():
                diff_texts.append(content)
            elif artifact.uri.startswith("workspace://patches/") and run.workspace_root:
                patch_path = Path(run.workspace_root) / "patches" / artifact.uri.removeprefix("workspace://patches/")
                if patch_path.exists():
                    diff_texts.append(patch_path.read_text(encoding="utf-8"))
        summary = run.summary or {}
        return EventSnapshot(
            title=event.title or summary.get("goal") or f"Agent run {run.id}",
            body=summary.get("fork_notes") or "",
            branch_name=run.branch_name,
            commit_sha=summary.get("pull_request_commit_sha") or event.commit_sha,
            base_ref=None,
            changed_files=changed_files,
            diff_text="\n".join(diff_texts),
            commit_messages=[summary.get("goal")] if isinstance(summary.get("goal"), str) else [],
        )
    raise ValueError(f"Unsupported knowledge event source: {event.source_type}")


async def _analyze_snapshot(
    session: AsyncSession,
    *,
    event: KnowledgeEvent,
    repo: ProjectRepository,
    snapshot: EventSnapshot,
) -> ChangeSignals:
    changed_files = _unique_strings(snapshot.changed_files)
    modules = _derive_modules(changed_files)
    mappings = await _matched_mappings(session, repository_id=repo.id, paths=changed_files)
    modules = _unique_strings(
        [mapping.module_name for mapping in mappings if mapping.module_name] + modules
    )
    change_type = _change_type_from_paths(changed_files, snapshot.title, snapshot.body)
    flags = _impact_flags(changed_files, modules)
    risk_level = _risk_level(change_type, flags, len(changed_files))
    confidence = _confidence_score(change_type, flags, snapshot.title, snapshot.body, len(changed_files))
    provisional = ChangeSignals(
        change_type=change_type,
        summary=_plain_summary(_safe_title(event, snapshot), change_type, modules, changed_files),
        technical_summary=_technical_summary(change_type, changed_files, flags, snapshot.commit_messages),
        business_summary=_business_summary(change_type, flags, modules),
        risk_level=risk_level,
        confidence_score=confidence,
        impacts_runtime=flags["impacts_runtime"],
        impacts_api=flags["impacts_api"],
        impacts_schema=flags["impacts_schema"],
        impacts_docs=flags["impacts_docs"],
        impacts_architecture=flags["impacts_architecture"],
        impacts_onboarding=flags["impacts_onboarding"],
        impacted_files=changed_files,
        impacted_modules=modules,
        probable_artifacts=[],
        docs_only=flags["docs_only"],
        test_only=flags["test_only"],
    )
    suggestions = _default_artifact_suggestions(provisional, mappings)
    probable_artifacts = [
        {
            "artifact_type": suggestion.artifact_type,
            "artifact_key": suggestion.artifact_key,
            "artifact_title": suggestion.artifact_title,
            "proposal_type": suggestion.proposal_type,
            "target_section": suggestion.target_section,
            "confidence_score": suggestion.confidence_score,
        }
        for suggestion in suggestions
    ]
    return ChangeSignals(
        probable_artifacts=probable_artifacts,
        **{field: getattr(provisional, field) for field in provisional.__dataclass_fields__ if field != "probable_artifacts"},
    )


async def _store_change(session: AsyncSession, event_id: uuid.UUID, change: ChangeSignals) -> KnowledgeChange:
    existing = await session.scalar(
        select(KnowledgeChange).where(KnowledgeChange.knowledge_event_id == event_id)
    )
    if existing is not None:
        existing.change_type = change.change_type
        existing.summary = change.summary
        existing.technical_summary = change.technical_summary
        existing.business_summary = change.business_summary
        existing.risk_level = change.risk_level
        existing.confidence_score = change.confidence_score
        existing.impacts_runtime = change.impacts_runtime
        existing.impacts_api = change.impacts_api
        existing.impacts_schema = change.impacts_schema
        existing.impacts_docs = change.impacts_docs
        existing.impacts_architecture = change.impacts_architecture
        existing.impacts_onboarding = change.impacts_onboarding
        existing.impacted_files = change.impacted_files
        existing.impacted_modules = change.impacted_modules
        existing.probable_artifacts = change.probable_artifacts
        session.add(existing)
        await session.flush()
        return existing
    row = KnowledgeChange(
        knowledge_event_id=event_id,
        change_type=change.change_type,
        summary=change.summary,
        technical_summary=change.technical_summary,
        business_summary=change.business_summary,
        risk_level=change.risk_level,
        confidence_score=change.confidence_score,
        impacts_runtime=change.impacts_runtime,
        impacts_api=change.impacts_api,
        impacts_schema=change.impacts_schema,
        impacts_docs=change.impacts_docs,
        impacts_architecture=change.impacts_architecture,
        impacts_onboarding=change.impacts_onboarding,
        impacted_files=change.impacted_files,
        impacted_modules=change.impacted_modules,
        probable_artifacts=change.probable_artifacts,
    )
    session.add(row)
    await session.flush()
    return row


def _artifact_suggestions_from_change(change: ChangeSignals) -> list[ArtifactSuggestion]:
    suggestions: list[ArtifactSuggestion] = []
    for item in change.probable_artifacts:
        suggestions.append(
            ArtifactSuggestion(
                artifact_type=str(item.get("artifact_type")),
                artifact_key=str(item.get("artifact_key")),
                artifact_title=str(item.get("artifact_title")),
                proposal_type=str(item.get("proposal_type") or "append"),
                target_section=item.get("target_section"),
                rationale=_artifact_rationale(str(item.get("artifact_type")), change.impacted_files, change.change_type),
                confidence_score=float(item.get("confidence_score") or change.confidence_score),
            )
        )
    return suggestions


async def analyze_event_now(session: AsyncSession, event_id: uuid.UUID) -> int:
    event = await session.get(KnowledgeEvent, event_id)
    if event is None:
        raise ValueError("knowledge event not found")
    if event.status in {"proposed", "reviewed", "approved", "rejected", "published"}:
        return (
            await session.execute(select(func.count()).where(KnowledgeProposal.knowledge_event_id == event_id))
        ).scalar_one()

    repo = await session.get(ProjectRepository, event.repository_id)
    if repo is None:
        event.status = "failed"
        event.error_message = "project repository not found"
        session.add(event)
        await session.flush()
        return 0

    try:
        logger.info("knowledge event %s analysis started", event.id)
        snapshot = await _load_event_snapshot(session, event, repo)
        if snapshot.commit_sha and not event.commit_sha:
            event.commit_sha = snapshot.commit_sha
        if snapshot.branch_name and not event.branch_name:
            event.branch_name = snapshot.branch_name
        if snapshot.pr_number and not event.pr_number:
            event.pr_number = snapshot.pr_number
        change = await _analyze_snapshot(session, event=event, repo=repo, snapshot=snapshot)
        await _store_change(session, event.id, change)
        await ai_job_manager.record_deterministic_job(
            AIJobRequest(
                workflow_type="docs_verification",
                role="classifier",
                task_type="classification",
                ambiguity_level="medium" if change.confidence_score < 0.8 else "low",
                risk_level=change.risk_level,
                tenant_id=event.tenant_id,
                project_id=event.project_id,
                repository_id=event.repository_id,
                knowledge_event_id=event.id,
                changed_files=change.impacted_files,
                background_job=event.source_type in {"push", "pr_merged", "agent_run"},
                deterministic_preferred=True,
                confidence_score=change.confidence_score,
                metadata={"source_type": event.source_type},
            ),
            filters_used=["diff_narrowing", "module_ownership_lookup", "docs_target_lookup"],
            context_sections={
                "event_title": _safe_title(event, snapshot),
                "changed_files": "\n".join(change.impacted_files[:8]),
                "impacted_modules": ", ".join(change.impacted_modules[:6]),
                "technical_summary": change.technical_summary,
            },
            confidence_score=change.confidence_score,
            session=session,
        )
        event.analyzed_at = _now_utc()
        event.status = "analyzed"
        event.error_message = None
        session.add(event)
        await session.flush()

        suggestions = _artifact_suggestions_from_change(change)
        proposal_count = 0
        for suggestion in suggestions:
            artifact = await _get_or_create_artifact(
                session,
                tenant_id=event.tenant_id,
                project_id=event.project_id,
                repository_id=event.repository_id,
                suggestion=suggestion,
            )
            existing = await session.scalar(
                select(KnowledgeProposal).where(
                    KnowledgeProposal.knowledge_event_id == event.id,
                    KnowledgeProposal.artifact_type == suggestion.artifact_type,
                    KnowledgeProposal.artifact_key == suggestion.artifact_key,
                )
            )
            proposal_type, generated_content = _merge_generated_content(
                artifact=artifact,
                suggestion=suggestion,
                event=event,
                snapshot=snapshot,
                change=change,
            )
            diff_preview = _build_diff_preview(artifact.canonical_content or "", generated_content)
            if existing is None:
                proposal = KnowledgeProposal(
                    tenant_id=event.tenant_id,
                    project_id=event.project_id,
                    repository_id=event.repository_id,
                    knowledge_event_id=event.id,
                    artifact_id=artifact.id,
                    proposal_type=proposal_type,
                    artifact_type=suggestion.artifact_type,
                    artifact_key=suggestion.artifact_key,
                    artifact_title=suggestion.artifact_title,
                    target_section=suggestion.target_section,
                    generated_content=generated_content,
                    diff_preview=diff_preview,
                    rationale=suggestion.rationale,
                    base_artifact_version=artifact.current_version,
                    base_artifact_hash=_content_hash(artifact.canonical_content),
                    confidence_score=suggestion.confidence_score,
                    review_status=PROPOSAL_PENDING,
                    created_by_agent="knowledge-engine",
                )
                session.add(proposal)
            else:
                existing.proposal_type = proposal_type
                existing.target_section = suggestion.target_section
                existing.generated_content = generated_content
                existing.diff_preview = diff_preview
                existing.rationale = suggestion.rationale
                existing.base_artifact_version = artifact.current_version
                existing.base_artifact_hash = _content_hash(artifact.canonical_content)
                existing.confidence_score = suggestion.confidence_score
                if existing.review_status not in PROPOSAL_TERMINAL_STATUSES:
                    existing.review_status = PROPOSAL_PENDING
                session.add(existing)
            proposal_count += 1

        event.status = "proposed" if proposal_count else "analyzed"
        session.add(event)
        await session.flush()
        await ai_job_manager.record_deterministic_job(
            AIJobRequest(
                workflow_type="docs_verification",
                role="documenter",
                task_type="docs_proposal",
                ambiguity_level="medium" if change.impacts_architecture else "low",
                risk_level=change.risk_level,
                tenant_id=event.tenant_id,
                project_id=event.project_id,
                repository_id=event.repository_id,
                knowledge_event_id=event.id,
                changed_files=change.impacted_files,
                background_job=event.source_type in {"push", "pr_merged", "agent_run"},
                deterministic_preferred=True,
                confidence_score=change.confidence_score,
                metadata={"proposal_count": proposal_count, "source_type": event.source_type},
            ),
            filters_used=["artifact_target_lookup", "template_merge", "diff_preview_generation"],
            context_sections={
                "summary": change.summary,
                "business_summary": change.business_summary,
                "proposal_targets": ", ".join(
                    f"{suggestion.artifact_type}:{suggestion.artifact_key}" for suggestion in suggestions[:8]
                ),
            },
            status="awaiting_review" if proposal_count else "completed",
            approval_state="pending" if proposal_count else "not_required",
            confidence_score=change.confidence_score,
            details={"proposal_count": proposal_count},
            session=session,
        )
        logger.info("knowledge event %s analysis finished proposals=%s", event.id, proposal_count)
        return proposal_count
    except Exception as exc:
        logger.exception("knowledge event %s analysis failed", event.id)
        event.status = "failed"
        event.error_message = str(exc)
        session.add(event)
        await session.flush()
        raise


async def _analyze_event_in_new_session(event_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        try:
            await analyze_event_now(session, event_id)
            await session.commit()
        except Exception:
            await session.rollback()


async def maybe_enqueue_analysis(session: AsyncSession, event_id: uuid.UUID, *, prefer_async: bool = True) -> tuple[bool, bool, int]:
    bind = session.get_bind()
    if prefer_async and bind is not None and bind.dialect.name != "sqlite":
        asyncio.create_task(_analyze_event_in_new_session(event_id))
        return True, False, 0
    proposals_created = await analyze_event_now(session, event_id)
    await session.commit()
    return False, True, proposals_created


async def create_knowledge_event(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    repository_id: uuid.UUID,
    source_type: str,
    source_external_id: str | None = None,
    delivery_key: str | None = None,
    branch_name: str | None = None,
    commit_sha: str | None = None,
    pr_number: int | None = None,
    title: str | None = None,
    raw_payload_json: dict[str, Any] | None = None,
    triggered_by: str | None = None,
) -> tuple[KnowledgeEvent, bool]:
    if delivery_key:
        existing = await session.scalar(
            select(KnowledgeEvent).where(
                KnowledgeEvent.repository_id == repository_id,
                KnowledgeEvent.delivery_key == delivery_key,
            )
        )
        if existing is not None:
            return existing, False
    if source_external_id:
        existing = await session.scalar(
            select(KnowledgeEvent).where(
                KnowledgeEvent.repository_id == repository_id,
                KnowledgeEvent.source_type == source_type,
                KnowledgeEvent.source_external_id == source_external_id,
            )
        )
        if existing is not None:
            return existing, False
    event = KnowledgeEvent(
        tenant_id=tenant_id,
        project_id=project_id,
        repository_id=repository_id,
        source_type=source_type,
        source_external_id=source_external_id,
        delivery_key=delivery_key,
        branch_name=branch_name,
        commit_sha=commit_sha,
        pr_number=pr_number,
        title=title,
        raw_payload_json=raw_payload_json,
        triggered_by=triggered_by,
        status="detected",
    )
    session.add(event)
    await session.flush()
    return event, True


async def _proposal_count_for_event(session: AsyncSession, event_id: uuid.UUID) -> int:
    return (
        await session.execute(select(func.count()).where(KnowledgeProposal.knowledge_event_id == event_id))
    ).scalar_one()


async def trigger_manual_sync(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    triggered_by: str,
    title: str | None = None,
    branch_name: str | None = None,
    commit_sha: str | None = None,
    prefer_async: bool = False,
) -> KnowledgeTriggerResponse:
    repo = await get_project_repository(session, project_id=project_id, tenant_id=tenant_id)
    if repo is None:
        raise ValueError("Project repository is not connected")
    repo_dir = ensure_analysis_repo(repo, branch_name=branch_name or repo.default_branch)
    fetch_origin(repo, repo_dir)
    head_ref = commit_sha or current_head(repo_dir, "HEAD")
    if not head_ref:
        raise ValueError("Unable to resolve repository head for manual sync")
    latest_event_commit = await session.scalar(
        select(KnowledgeEvent.commit_sha)
        .where(
            KnowledgeEvent.repository_id == repo.id,
            KnowledgeEvent.project_id == project_id,
            KnowledgeEvent.commit_sha.is_not(None),
        )
        .order_by(KnowledgeEvent.detected_at.desc())
    )
    base_ref = latest_event_commit if latest_event_commit and latest_event_commit != head_ref else previous_commit(repo_dir, head_ref)
    scoped_branch = branch_name or repo.default_branch
    manual_dedupe_key = f"manual_sync:{project_id}:{repo.id}:{scoped_branch}:{head_ref}"
    event, _created = await create_knowledge_event(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        repository_id=repo.id,
        source_type="manual_sync",
        source_external_id=manual_dedupe_key,
        delivery_key=manual_dedupe_key,
        branch_name=scoped_branch,
        commit_sha=head_ref,
        title=title or f"Manual knowledge sync for {repo.repo_full_name or repo.repo_url}",
        raw_payload_json={"base_ref": base_ref, "head_ref": head_ref},
        triggered_by=triggered_by,
    )
    if not _created:
        proposal_count = await _proposal_count_for_event(session, event.id)
        await session.refresh(event)
        return KnowledgeTriggerResponse(
            event=_event_out(event, repo),
            proposals_created=proposal_count,
            queued=False,
            inline_processed=False,
        )
    await session.commit()
    queued, inline_processed, proposals_created = await maybe_enqueue_analysis(
        session,
        event.id,
        prefer_async=prefer_async,
    )
    await session.refresh(event)
    return KnowledgeTriggerResponse(
        event=_event_out(event, repo),
        proposals_created=proposals_created,
        queued=queued,
        inline_processed=inline_processed,
    )


async def ingest_github_push_events(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    delivery_id: str | None,
) -> list[KnowledgeEvent]:
    repo_full_name = (payload.get("repository") or {}).get("full_name")
    if not repo_full_name:
        return []
    repositories = await _find_project_repo_by_full_name(session, repo_full_name)
    created_events: list[KnowledgeEvent] = []
    for repo in repositories:
        event, created = await create_knowledge_event(
            session,
            tenant_id=repo.tenant_id,
            project_id=repo.project_id,
            repository_id=repo.id,
            source_type="push",
            source_external_id=payload.get("after"),
            delivery_key=f"github:{delivery_id}" if delivery_id else None,
            branch_name=(payload.get("ref") or "").removeprefix("refs/heads/") or repo.default_branch,
            commit_sha=payload.get("after"),
            title=((payload.get("head_commit") or {}).get("message") or "GitHub push").splitlines()[0],
            raw_payload_json=payload,
            triggered_by="github",
        )
        if created:
            created_events.append(event)
    await session.commit()
    return created_events


async def ingest_github_pr_merged_events(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    delivery_id: str | None,
) -> list[KnowledgeEvent]:
    repo_full_name = (payload.get("repository") or {}).get("full_name")
    pull_request = payload.get("pull_request") or {}
    if not repo_full_name or not pull_request.get("merged"):
        return []
    repositories = await _find_project_repo_by_full_name(session, repo_full_name)
    created_events: list[KnowledgeEvent] = []
    pr_number = pull_request.get("number") or payload.get("number")
    merge_commit_sha = pull_request.get("merge_commit_sha")
    for repo in repositories:
        event, created = await create_knowledge_event(
            session,
            tenant_id=repo.tenant_id,
            project_id=repo.project_id,
            repository_id=repo.id,
            source_type="pr_merged",
            source_external_id=f"pr:{pr_number}:{merge_commit_sha or pull_request.get('head', {}).get('sha')}",
            delivery_key=f"github:{delivery_id}" if delivery_id else None,
            branch_name=pull_request.get("base", {}).get("ref") or repo.default_branch,
            commit_sha=merge_commit_sha,
            pr_number=pr_number,
            title=pull_request.get("title") or f"Merged PR #{pr_number}",
            raw_payload_json=payload,
            triggered_by="github",
        )
        if created:
            created_events.append(event)
    await session.commit()
    return created_events


async def ingest_agent_run_event(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    actor_id: str | None = None,
) -> KnowledgeEvent | None:
    run = await session.get(Run, run_id)
    if run is None:
        return None
    repo = await get_project_repository(session, project_id=run.project_id, tenant_id=run.tenant_id)
    if repo is None:
        return None
    summary = await upsert_run_summary(session, run.id)
    changed_files = list(summary.changed_files) if summary and summary.changed_files else []
    if not changed_files:
        artifacts = (
            await session.execute(
                select(Artifact).where(Artifact.run_id == run.id, Artifact.tenant_id == run.tenant_id)
            )
        ).scalars().all()
        if not any(artifact.type == "git_diff" for artifact in artifacts):
            return None
    event, created = await create_knowledge_event(
        session,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        repository_id=repo.id,
        source_type="agent_run",
        source_external_id=f"run:{run.id}",
        branch_name=run.branch_name,
        commit_sha=(run.summary or {}).get("pull_request_commit_sha"),
        title=(run.summary or {}).get("goal") or f"Agent run {run.id}",
        raw_payload_json={
            "run_id": str(run.id),
            "executor": run.executor,
            "changed_files": changed_files,
        },
        triggered_by=actor_id or "system",
    )
    if not created:
        return event
    await analyze_event_now(session, event.id)
    return event


async def refresh_event_status(session: AsyncSession, event_id: uuid.UUID) -> None:
    event = await session.get(KnowledgeEvent, event_id)
    if event is None:
        return
    proposals = (
        await session.execute(select(KnowledgeProposal).where(KnowledgeProposal.knowledge_event_id == event_id))
    ).scalars().all()
    if not proposals:
        event.status = "analyzed"
        session.add(event)
        await session.flush()
        return
    proposal_statuses = [proposal.review_status for proposal in proposals]
    publications = (
        await session.execute(
            select(KnowledgePublication).join(
                KnowledgeProposal, KnowledgePublication.proposal_id == KnowledgeProposal.id
            ).where(KnowledgeProposal.knowledge_event_id == event_id)
        )
    ).scalars().all()
    if publications or any(status == PROPOSAL_PUBLISHED for status in proposal_statuses):
        event.status = "published"
    elif all(status == PROPOSAL_REJECTED for status in proposal_statuses):
        event.status = "rejected"
    elif all(status == PROPOSAL_SUPERSEDED for status in proposal_statuses):
        event.status = "superseded"
    elif all(status == PROPOSAL_DEFERRED for status in proposal_statuses):
        event.status = "deferred"
    elif all(status == PROPOSAL_PENDING for status in proposal_statuses):
        event.status = "proposed"
    elif any(status == PROPOSAL_APPROVED for status in proposal_statuses):
        event.status = "approved"
    elif any(status == PROPOSAL_PENDING for status in proposal_statuses):
        event.status = "reviewed"
    else:
        event.status = "reviewed"
    session.add(event)
    await session.flush()


async def _publish_proposal(
    session: AsyncSession,
    *,
    proposal: KnowledgeProposal,
    artifact: KnowledgeArtifact,
    content: str,
    reviewer_user_id: str,
    publication_mode: str,
) -> KnowledgePublication:
    existing = await session.scalar(select(KnowledgePublication).where(KnowledgePublication.proposal_id == proposal.id))
    if existing is not None:
        return existing
    artifact.canonical_content = content
    artifact.current_version += 1
    artifact.last_verified_at = _now_utc()
    artifact.last_verified_by = reviewer_user_id
    session.add(artifact)
    await session.flush()
    publication = KnowledgePublication(
        proposal_id=proposal.id,
        artifact_id=artifact.id,
        artifact_version=artifact.current_version,
        published_content=content,
        publication_mode=publication_mode,
        published_by=reviewer_user_id,
    )
    session.add(publication)
    await session.flush()
    return publication


def _proposal_state_error(current_status: str, attempted_action: str) -> KnowledgeConflictError:
    return KnowledgeConflictError(
        f"knowledge proposal cannot transition from {current_status} via {attempted_action}"
    )


async def _get_proposal_publication(session: AsyncSession, proposal_id: uuid.UUID) -> KnowledgePublication | None:
    return await session.scalar(select(KnowledgePublication).where(KnowledgePublication.proposal_id == proposal_id))


async def _record_review(
    session: AsyncSession,
    *,
    proposal: KnowledgeProposal,
    reviewer_user_id: str,
    action: str,
    review_notes: str | None = None,
    edited_content: str | None = None,
) -> KnowledgeReview:
    review = KnowledgeReview(
        proposal_id=proposal.id,
        reviewer_user_id=reviewer_user_id,
        action=action,
        review_notes=review_notes,
        edited_content=edited_content,
    )
    session.add(review)
    await session.flush()
    return review


async def _supersede_proposal(
    session: AsyncSession,
    *,
    proposal: KnowledgeProposal,
    actor_user_id: str,
    reason: str,
) -> None:
    if proposal.review_status in PROPOSAL_TERMINAL_STATUSES:
        return
    proposal.review_status = PROPOSAL_SUPERSEDED
    session.add(proposal)
    await _record_review(
        session,
        proposal=proposal,
        reviewer_user_id=actor_user_id,
        action="superseded",
        review_notes=reason,
    )
    await session.flush()


async def _supersede_stale_proposals_for_artifact(
    session: AsyncSession,
    *,
    artifact: KnowledgeArtifact,
    exclude_proposal_id: uuid.UUID,
    actor_user_id: str,
) -> None:
    current_hash = _content_hash(artifact.canonical_content)
    proposals = (
        await session.execute(
            select(KnowledgeProposal).where(
                KnowledgeProposal.artifact_id == artifact.id,
                KnowledgeProposal.id != exclude_proposal_id,
                KnowledgeProposal.review_status.in_(tuple(PROPOSAL_OPEN_STATUSES)),
            )
        )
    ).scalars().all()
    affected_event_ids: set[uuid.UUID] = set()
    for proposal in proposals:
        if (
            proposal.base_artifact_version == artifact.current_version
            and proposal.base_artifact_hash == current_hash
        ):
            continue
        await _supersede_proposal(
            session,
            proposal=proposal,
            actor_user_id=actor_user_id,
            reason="Superseded because a newer verified publication changed the target artifact.",
        )
        affected_event_ids.add(proposal.knowledge_event_id)
    for event_id in affected_event_ids:
        await refresh_event_status(session, event_id)


def _is_stale_against_artifact(proposal: KnowledgeProposal, artifact: KnowledgeArtifact) -> bool:
    return (
        proposal.base_artifact_version != artifact.current_version
        or proposal.base_artifact_hash != _content_hash(artifact.canonical_content)
    )


async def approve_proposal(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    proposal_id: uuid.UUID,
    reviewer_user_id: str,
    review_notes: str | None = None,
    edited_content: str | None = None,
) -> KnowledgeProposalDetailOut:
    await _get_project_scope(session, tenant_id=tenant_id, project_id=project_id)
    proposal = await _get_scoped_proposal(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.artifact_id is None:
        raise KnowledgeConflictError("knowledge proposal is missing a target artifact")
    artifact = await _get_scoped_artifact(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        artifact_id=proposal.artifact_id,
        for_update=True,
    )
    publication = await _get_proposal_publication(session, proposal.id)
    if proposal.review_status == PROPOSAL_PUBLISHED or publication is not None:
        if proposal.review_status != PROPOSAL_PUBLISHED:
            proposal.review_status = PROPOSAL_PUBLISHED
            session.add(proposal)
            await refresh_event_status(session, proposal.knowledge_event_id)
            await session.commit()
        return await get_proposal_detail(session, tenant_id=tenant_id, project_id=project_id, proposal_id=proposal_id)
    if proposal.review_status == PROPOSAL_SUPERSEDED:
        raise _proposal_state_error(proposal.review_status, "approve")
    if proposal.review_status in {PROPOSAL_REJECTED, PROPOSAL_DEFERRED}:
        raise _proposal_state_error(proposal.review_status, "approve")
    if proposal.review_status not in {PROPOSAL_PENDING, PROPOSAL_APPROVED}:
        raise _proposal_state_error(proposal.review_status, "approve")
    if _is_stale_against_artifact(proposal, artifact):
        await _supersede_proposal(
            session,
            proposal=proposal,
            actor_user_id=reviewer_user_id,
            reason="Approval blocked because the target artifact changed after this draft was generated.",
        )
        await refresh_event_status(session, proposal.knowledge_event_id)
        await session.commit()
        raise KnowledgeConflictError("knowledge proposal is stale and must be regenerated before publication")

    action = "edit_and_approve" if edited_content is not None else "approve"
    if proposal.review_status == PROPOSAL_PENDING:
        await _record_review(
            session,
            proposal=proposal,
            reviewer_user_id=reviewer_user_id,
            action=action,
            review_notes=review_notes,
            edited_content=edited_content,
        )
    content = edited_content if edited_content is not None else proposal.generated_content
    proposal.review_status = PROPOSAL_APPROVED
    session.add(proposal)
    await session.flush()
    publication = await _publish_proposal(
        session,
        proposal=proposal,
        artifact=artifact,
        content=content,
        reviewer_user_id=reviewer_user_id,
        publication_mode="edited_publish" if edited_content is not None else "approved_publish",
    )
    proposal.review_status = PROPOSAL_PUBLISHED
    session.add(proposal)
    await session.flush()
    await _supersede_stale_proposals_for_artifact(
        session,
        artifact=artifact,
        exclude_proposal_id=proposal.id,
        actor_user_id=reviewer_user_id,
    )
    await refresh_event_status(session, proposal.knowledge_event_id)
    await ai_job_manager.sync_knowledge_review_state(
        proposal.knowledge_event_id,
        approval_state="approved",
        reviewer_user_id=reviewer_user_id,
        session=session,
    )
    await session.commit()
    return await get_proposal_detail(session, tenant_id=tenant_id, project_id=project_id, proposal_id=proposal_id)


async def reject_proposal(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    proposal_id: uuid.UUID,
    reviewer_user_id: str,
    review_notes: str | None = None,
) -> KnowledgeProposalDetailOut:
    await _get_project_scope(session, tenant_id=tenant_id, project_id=project_id)
    proposal = await _get_scoped_proposal(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.review_status != PROPOSAL_PENDING:
        raise _proposal_state_error(proposal.review_status, "reject")
    await _record_review(
        session,
        proposal=proposal,
        reviewer_user_id=reviewer_user_id,
        action="reject",
        review_notes=review_notes,
    )
    proposal.review_status = PROPOSAL_REJECTED
    session.add(proposal)
    await session.flush()
    await refresh_event_status(session, proposal.knowledge_event_id)
    await ai_job_manager.sync_knowledge_review_state(
        proposal.knowledge_event_id,
        approval_state="rejected",
        reviewer_user_id=reviewer_user_id,
        session=session,
    )
    await session.commit()
    return await get_proposal_detail(session, tenant_id=tenant_id, project_id=project_id, proposal_id=proposal_id)


async def defer_proposal(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    proposal_id: uuid.UUID,
    reviewer_user_id: str,
    review_notes: str | None = None,
) -> KnowledgeProposalDetailOut:
    await _get_project_scope(session, tenant_id=tenant_id, project_id=project_id)
    proposal = await _get_scoped_proposal(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.review_status != PROPOSAL_PENDING:
        raise _proposal_state_error(proposal.review_status, "defer")
    await _record_review(
        session,
        proposal=proposal,
        reviewer_user_id=reviewer_user_id,
        action="defer",
        review_notes=review_notes,
    )
    proposal.review_status = PROPOSAL_DEFERRED
    session.add(proposal)
    await session.flush()
    await refresh_event_status(session, proposal.knowledge_event_id)
    await ai_job_manager.sync_knowledge_review_state(
        proposal.knowledge_event_id,
        approval_state="deferred",
        reviewer_user_id=reviewer_user_id,
        session=session,
    )
    await session.commit()
    return await get_proposal_detail(session, tenant_id=tenant_id, project_id=project_id, proposal_id=proposal_id)


def _event_out(event: KnowledgeEvent, repo: ProjectRepository | None = None) -> KnowledgeEventSummaryOut:
    return KnowledgeEventSummaryOut(
        id=event.id,
        project_id=event.project_id,
        repository_id=event.repository_id,
        repo_full_name=repo.repo_full_name if repo else None,
        source_type=event.source_type,
        source_external_id=event.source_external_id,
        branch_name=event.branch_name,
        commit_sha=event.commit_sha,
        pr_number=event.pr_number,
        title=event.title,
        triggered_by=event.triggered_by,
        detected_at=event.detected_at,
        analyzed_at=event.analyzed_at,
        status=event.status,
    )


def _change_out(change: KnowledgeChange | None) -> KnowledgeChangeOut | None:
    if change is None:
        return None
    return KnowledgeChangeOut(
        id=change.id,
        change_type=change.change_type,
        summary=change.summary,
        technical_summary=change.technical_summary,
        business_summary=change.business_summary,
        risk_level=change.risk_level,
        confidence_score=change.confidence_score,
        impacts_runtime=change.impacts_runtime,
        impacts_api=change.impacts_api,
        impacts_schema=change.impacts_schema,
        impacts_docs=change.impacts_docs,
        impacts_architecture=change.impacts_architecture,
        impacts_onboarding=change.impacts_onboarding,
        impacted_files=[value for value in change.impacted_files if isinstance(value, str)],
        impacted_modules=[value for value in change.impacted_modules if isinstance(value, str)],
        probable_artifacts=[value for value in change.probable_artifacts if isinstance(value, dict)],
        created_at=change.created_at,
    )


def _proposal_out(proposal: KnowledgeProposal) -> KnowledgeProposalSummaryOut:
    return KnowledgeProposalSummaryOut(
        id=proposal.id,
        knowledge_event_id=proposal.knowledge_event_id,
        artifact_id=proposal.artifact_id,
        proposal_type=proposal.proposal_type,
        artifact_type=proposal.artifact_type,
        artifact_key=proposal.artifact_key,
        artifact_title=proposal.artifact_title,
        target_section=proposal.target_section,
        confidence_score=proposal.confidence_score,
        review_status=proposal.review_status,
        created_by_agent=proposal.created_by_agent,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )


def _review_out(review: KnowledgeReview) -> KnowledgeReviewOut:
    return KnowledgeReviewOut(
        id=review.id,
        proposal_id=review.proposal_id,
        reviewer_user_id=review.reviewer_user_id,
        action=review.action,
        review_notes=review.review_notes,
        edited_content=review.edited_content,
        created_at=review.created_at,
    )


def _publication_out(publication: KnowledgePublication | None) -> KnowledgePublicationOut | None:
    if publication is None:
        return None
    return KnowledgePublicationOut(
        id=publication.id,
        proposal_id=publication.proposal_id,
        artifact_id=publication.artifact_id,
        artifact_version=publication.artifact_version,
        published_content=publication.published_content,
        publication_mode=publication.publication_mode,
        published_by=publication.published_by,
        published_at=publication.published_at,
    )


def _artifact_out(artifact: KnowledgeArtifact, repo: ProjectRepository | None = None) -> KnowledgeArtifactSummaryOut:
    return KnowledgeArtifactSummaryOut(
        id=artifact.id,
        project_id=artifact.project_id,
        repository_id=artifact.repository_id,
        repo_full_name=repo.repo_full_name if repo else None,
        artifact_type=artifact.artifact_type,
        artifact_key=artifact.artifact_key,
        title=artifact.title,
        canonical_content=artifact.canonical_content,
        current_version=artifact.current_version,
        last_verified_at=artifact.last_verified_at,
        last_verified_by=artifact.last_verified_by,
        status=artifact.status,
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
    )


def _apply_project_filters(
    stmt: Select[Any],
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    repository_id: uuid.UUID | None = None,
) -> Select[Any]:
    stmt = stmt.where(
        KnowledgeProposal.tenant_id == tenant_id,
        KnowledgeProposal.project_id == project_id,
    )
    if repository_id is not None:
        stmt = stmt.where(KnowledgeProposal.repository_id == repository_id)
    return stmt


async def list_inbox(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    repository_id: uuid.UUID | None = None,
    review_status: str | None = None,
    change_type: str | None = None,
    artifact_type: str | None = None,
    risk_level: str | None = None,
) -> KnowledgeInboxResponse:
    await _get_project_scope(session, tenant_id=tenant_id, project_id=project_id)
    if repository_id is not None:
        await _get_repository_scope(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            repository_id=repository_id,
        )
    stmt = (
        select(KnowledgeProposal, KnowledgeEvent, ProjectRepository, KnowledgeChange)
        .join(KnowledgeEvent, KnowledgeProposal.knowledge_event_id == KnowledgeEvent.id)
        .join(ProjectRepository, KnowledgeProposal.repository_id == ProjectRepository.id)
        .outerjoin(KnowledgeChange, KnowledgeChange.knowledge_event_id == KnowledgeEvent.id)
        .order_by(KnowledgeProposal.created_at.desc())
    )
    stmt = _apply_project_filters(stmt, tenant_id=tenant_id, project_id=project_id, repository_id=repository_id)
    stmt = stmt.where(KnowledgeProposal.review_status == (review_status or PROPOSAL_PENDING))
    if change_type:
        stmt = stmt.where(KnowledgeChange.change_type == change_type)
    if artifact_type:
        stmt = stmt.where(KnowledgeProposal.artifact_type == artifact_type)
    if risk_level:
        stmt = stmt.where(KnowledgeChange.risk_level == risk_level)
    rows = (await session.execute(stmt)).all()
    items = [
        KnowledgeInboxItemOut(
            proposal_id=proposal.id,
            event_id=event.id,
            artifact_id=proposal.artifact_id,
            project_id=proposal.project_id,
            repository_id=proposal.repository_id,
            repo_full_name=repo.repo_full_name,
            event_title=event.title,
            source_type=event.source_type,
            impacted_modules=[value for value in (change.impacted_modules if change else []) if isinstance(value, str)],
            proposal_target=proposal.artifact_title,
            artifact_type=proposal.artifact_type,
            change_type=change.change_type if change else "unknown",
            confidence_score=proposal.confidence_score,
            risk_level=change.risk_level if change else "medium",
            created_at=proposal.created_at,
            review_status=proposal.review_status,
            detected_at=event.detected_at,
        )
        for proposal, event, repo, change in rows
    ]
    return KnowledgeInboxResponse(items=items, total=len(items))


async def list_proposals(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    repository_id: uuid.UUID | None = None,
    review_status: str | None = None,
) -> KnowledgeProposalListResponse:
    await _get_project_scope(session, tenant_id=tenant_id, project_id=project_id)
    if repository_id is not None:
        await _get_repository_scope(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            repository_id=repository_id,
        )
    stmt = (
        select(KnowledgeProposal)
        .where(
            KnowledgeProposal.tenant_id == tenant_id,
            KnowledgeProposal.project_id == project_id,
        )
        .order_by(KnowledgeProposal.created_at.desc())
    )
    if repository_id is not None:
        stmt = stmt.where(KnowledgeProposal.repository_id == repository_id)
    if review_status:
        stmt = stmt.where(KnowledgeProposal.review_status == review_status)
    rows = (await session.execute(stmt)).scalars().all()
    items = [_proposal_out(row) for row in rows]
    return KnowledgeProposalListResponse(items=items, total=len(items))


async def get_proposal_detail(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    proposal_id: uuid.UUID,
) -> KnowledgeProposalDetailOut:
    await _get_project_scope(session, tenant_id=tenant_id, project_id=project_id)
    proposal = await _get_scoped_proposal(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        proposal_id=proposal_id,
    )
    event = await _get_scoped_event(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        event_id=proposal.knowledge_event_id,
    )
    repo = await _get_repository_scope(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        repository_id=proposal.repository_id,
    )
    change = await session.scalar(select(KnowledgeChange).where(KnowledgeChange.knowledge_event_id == proposal.knowledge_event_id))
    artifact = (
        await _get_scoped_artifact(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            artifact_id=proposal.artifact_id,
        )
        if proposal.artifact_id
        else None
    )
    reviews = (
        await session.execute(
            select(KnowledgeReview).where(KnowledgeReview.proposal_id == proposal_id).order_by(KnowledgeReview.created_at.asc())
        )
    ).scalars().all()
    publication = await _get_proposal_publication(session, proposal_id)
    return KnowledgeProposalDetailOut(
        **_proposal_out(proposal).model_dump(),
        event=_event_out(event, repo),
        change=_change_out(change),
        current_canonical_content=artifact.canonical_content if artifact else "",
        generated_content=proposal.generated_content,
        diff_preview=proposal.diff_preview,
        rationale=proposal.rationale,
        reviews=[_review_out(review) for review in reviews],
        publication=_publication_out(publication),
        raw_payload_json=event.raw_payload_json if event else None,
    )


async def list_artifacts(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    repository_id: uuid.UUID | None = None,
    query: str | None = None,
    include_drafts: bool = False,
) -> KnowledgeArtifactListResponse:
    await _get_project_scope(session, tenant_id=tenant_id, project_id=project_id)
    if repository_id is not None:
        await _get_repository_scope(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            repository_id=repository_id,
        )
    stmt = (
        select(KnowledgeArtifact, ProjectRepository)
        .join(ProjectRepository, KnowledgeArtifact.repository_id == ProjectRepository.id)
        .where(
            KnowledgeArtifact.tenant_id == tenant_id,
            KnowledgeArtifact.project_id == project_id,
        )
        .order_by(KnowledgeArtifact.updated_at.desc())
    )
    if repository_id is not None:
        stmt = stmt.where(KnowledgeArtifact.repository_id == repository_id)
    if not include_drafts:
        stmt = stmt.where(KnowledgeArtifact.current_version > 0)
    if query:
        search = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(KnowledgeArtifact.title).like(search),
                func.lower(KnowledgeArtifact.canonical_content).like(search),
                func.lower(KnowledgeArtifact.artifact_key).like(search),
            )
        )
    rows = (await session.execute(stmt)).all()
    items = [_artifact_out(artifact, repo) for artifact, repo in rows]
    return KnowledgeArtifactListResponse(items=items, total=len(items))


async def get_artifact_detail(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    artifact_id: uuid.UUID,
) -> KnowledgeArtifactDetailOut:
    await _get_project_scope(session, tenant_id=tenant_id, project_id=project_id)
    artifact = await _get_scoped_artifact(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        artifact_id=artifact_id,
    )
    repo = await _get_repository_scope(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        repository_id=artifact.repository_id,
    )
    proposals = (
        await session.execute(
            select(KnowledgeProposal)
            .where(
                KnowledgeProposal.artifact_id == artifact_id,
                KnowledgeProposal.project_id == project_id,
                KnowledgeProposal.tenant_id == tenant_id,
            )
            .order_by(KnowledgeProposal.created_at.desc())
        )
    ).scalars().all()
    history: list[KnowledgeArtifactHistoryItemOut] = []
    for proposal in proposals:
        reviews = (
            await session.execute(
                select(KnowledgeReview).where(KnowledgeReview.proposal_id == proposal.id).order_by(KnowledgeReview.created_at.asc())
            )
        ).scalars().all()
        publication = await _get_proposal_publication(session, proposal.id)
        history.append(
            KnowledgeArtifactHistoryItemOut(
                proposal=_proposal_out(proposal),
                reviews=[_review_out(review) for review in reviews],
                publication=_publication_out(publication),
            )
        )
    return KnowledgeArtifactDetailOut(**_artifact_out(artifact, repo).model_dump(), history=history)


async def get_event_detail(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    event_id: uuid.UUID,
) -> KnowledgeEventDetailOut:
    await _get_project_scope(session, tenant_id=tenant_id, project_id=project_id)
    event = await _get_scoped_event(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        event_id=event_id,
    )
    repo = await _get_repository_scope(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        repository_id=event.repository_id,
    )
    change = await session.scalar(select(KnowledgeChange).where(KnowledgeChange.knowledge_event_id == event_id))
    proposals = (
        await session.execute(
            select(KnowledgeProposal)
            .where(
                KnowledgeProposal.knowledge_event_id == event_id,
                KnowledgeProposal.project_id == project_id,
                KnowledgeProposal.tenant_id == tenant_id,
            )
            .order_by(KnowledgeProposal.created_at.asc())
        )
    ).scalars().all()
    return KnowledgeEventDetailOut(
        **_event_out(event, repo).model_dump(),
        raw_payload_json=event.raw_payload_json,
        change=_change_out(change),
        proposals=[_proposal_out(proposal) for proposal in proposals],
    )


async def list_search_hooks(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> KnowledgeSearchHookListResponse:
    await _get_project_scope(session, tenant_id=tenant_id, project_id=project_id)
    stmt = (
        select(KnowledgeArtifact)
        .where(
            KnowledgeArtifact.tenant_id == tenant_id,
            KnowledgeArtifact.project_id == project_id,
            KnowledgeArtifact.current_version > 0,
        )
        .order_by(KnowledgeArtifact.updated_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    items = [
        KnowledgeSearchHookOut(
            artifact_id=row.id,
            artifact_key=row.artifact_key,
            title=row.title,
            search_text=_artifact_search_text(row),
        )
        for row in rows
    ]
    return KnowledgeSearchHookListResponse(items=items, total=len(items))
