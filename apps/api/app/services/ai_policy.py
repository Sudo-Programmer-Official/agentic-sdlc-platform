from __future__ import annotations

import fnmatch
import math
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.models import (
    AIArtifactCache,
    AIJobRun,
    KnowledgeArtifact,
    KnowledgeFileMapping,
    Project,
    ProjectRepository,
    RepoFile,
    RepoSnapshot,
    RunSummary,
)
from app.db.session import SessionLocal


ModelTier = Literal["tier_premium", "tier_standard", "tier_economy", "tier_none"]
RiskLevel = Literal["low", "medium", "high"]
AmbiguityLevel = Literal["low", "medium", "high"]

TIER_ORDER: dict[str, int] = {
    "tier_none": 0,
    "tier_economy": 1,
    "tier_standard": 2,
    "tier_premium": 3,
}

SENSITIVE_PATH_TOKENS = (
    "schema",
    "migration",
    "migrations",
    "alembic",
    "/api/",
    "auth",
    "deploy",
    "infra",
    "docker",
    "terraform",
    ".github/workflows",
)

TRANSIENT_ERROR_TOKENS = ("timeout", "tempor", "connection", "network", "rate limit", "429")


class AIPolicyError(RuntimeError):
    def __init__(self, reason: str, next_action: str, *, job_id: uuid.UUID | None = None, details: dict[str, Any] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.next_action = next_action
        self.job_id = job_id
        self.details = details or {}


@dataclass(frozen=True)
class AIJobRequest:
    workflow_type: str
    role: str
    task_type: str
    ambiguity_level: AmbiguityLevel
    risk_level: RiskLevel
    tenant_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    repository_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    work_item_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    knowledge_event_id: uuid.UUID | None = None
    changed_files: list[str] = field(default_factory=list)
    background_job: bool = False
    user_triggered: bool = False
    deterministic_preferred: bool = False
    tests_failed: bool = False
    confidence_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AIJobPolicy:
    task_type: str
    ambiguity_level: AmbiguityLevel
    risk_level: RiskLevel
    max_model_tier: ModelTier
    selected_model_tier: ModelTier
    max_retries: int
    max_context_tokens: int
    budget_cents: float
    requires_human_review: bool


@dataclass(frozen=True)
class AICacheContext:
    fragments: dict[str, str]
    cache_hits: int
    cache_keys: list[str]


@dataclass(frozen=True)
class PreparedAIExecution:
    job_id: uuid.UUID
    policy: AIJobPolicy
    model_name: str | None
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_cents: float
    context_size: int
    cache_hit_count: int
    blocked: bool
    stop_reason: str | None
    next_action: str | None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _round_cost(value: float) -> float:
    return round(max(value, 0.0), 4)


def _compact_text(text: str, max_chars: int) -> str:
    cleaned = " ".join((text or "").split())
    if max_chars <= 0 or len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(0, max_chars - 3)].rstrip() + "..."


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def contains_sensitive_paths(paths: list[str]) -> bool:
    for path in paths:
        lowered = path.lower()
        if any(token in lowered for token in SENSITIVE_PATH_TOKENS):
            return True
    return False


def is_retryable_error(exc: Exception) -> bool:
    lowered = str(exc).lower()
    return any(token in lowered for token in TRANSIENT_ERROR_TOKENS)


def retry_error_kind(exc: Exception) -> str:
    lowered = str(exc).lower()
    if "rate" in lowered and "limit" in lowered:
        return "rate_limit"
    if "timeout" in lowered:
        return "timeout"
    if "network" in lowered or "connection" in lowered or "tempor" in lowered:
        return "transient_network_failure"
    return "model_error"


def _cap_tier(left: ModelTier, right: ModelTier) -> ModelTier:
    return left if TIER_ORDER[left] <= TIER_ORDER[right] else right


class AIJobManager:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None):
        self._session_factory = session_factory or SessionLocal
        self._settings = get_settings()

    @classmethod
    def from_session(cls, session: AsyncSession) -> "AIJobManager":
        bind = session.get_bind()
        return cls(
            async_sessionmaker(
                bind=bind,
                autoflush=False,
                expire_on_commit=False,
                class_=AsyncSession,
            )
        )

    @asynccontextmanager
    async def _session_scope(self, session: AsyncSession | None = None):
        if session is not None:
            yield session
            return
        async with self._session_factory() as owned:
            try:
                yield owned
                await owned.commit()
            except Exception:
                await owned.rollback()
                raise

    def route_job(self, request: AIJobRequest) -> AIJobPolicy:
        settings = self._settings
        role = request.role
        if role == "planner":
            max_tier: ModelTier = "tier_premium"
        elif role == "coder":
            max_tier = "tier_standard"
        elif role == "reviewer":
            max_tier = "tier_premium" if request.risk_level == "high" else "tier_standard"
        elif role in {"documenter", "classifier"}:
            max_tier = "tier_economy"
        else:
            max_tier = "tier_none"

        selected_tier: ModelTier = max_tier
        if request.deterministic_preferred and role in {"documenter", "classifier", "formatter"}:
            selected_tier = "tier_none"
        if role == "formatter":
            max_tier = "tier_none"
            selected_tier = "tier_none"

        if request.background_job and not (contains_sensitive_paths(request.changed_files) or request.tests_failed):
            max_tier = _cap_tier(max_tier, "tier_economy")
            selected_tier = _cap_tier(selected_tier, "tier_economy")

        if request.workflow_type == "interactive_planning":
            budget_cents = settings.ai_budget_premium_cents
            max_context_tokens = settings.ai_max_context_premium_tokens
        elif request.workflow_type == "repo_implementation_task":
            budget_cents = settings.ai_budget_standard_cents
            max_context_tokens = settings.ai_max_context_standard_tokens
        elif request.workflow_type in {"docs_verification", "docs_proposal"}:
            budget_cents = settings.ai_budget_economy_cents
            max_context_tokens = settings.ai_max_context_economy_tokens
        elif request.background_job:
            budget_cents = settings.ai_budget_background_cents
            max_context_tokens = settings.ai_max_context_economy_tokens
        else:
            budget_cents = {
                "tier_premium": settings.ai_budget_premium_cents,
                "tier_standard": settings.ai_budget_standard_cents,
                "tier_economy": settings.ai_budget_economy_cents,
                "tier_none": 0.0,
            }[max_tier]
            max_context_tokens = {
                "tier_premium": settings.ai_max_context_premium_tokens,
                "tier_standard": settings.ai_max_context_standard_tokens,
                "tier_economy": settings.ai_max_context_economy_tokens,
                "tier_none": settings.ai_max_context_economy_tokens,
            }[max_tier]

        max_retries = {
            "tier_premium": 1,
            "tier_standard": 2,
            "tier_economy": 1,
            "tier_none": 0,
        }[selected_tier]

        requires_human_review = (
            request.risk_level == "high"
            or contains_sensitive_paths(request.changed_files)
            or len(request.changed_files) > settings.ai_human_review_file_threshold
            or (
                request.confidence_score is not None
                and request.confidence_score < settings.ai_low_confidence_threshold
            )
        )

        return AIJobPolicy(
            task_type=request.task_type,
            ambiguity_level=request.ambiguity_level,
            risk_level=request.risk_level,
            max_model_tier=max_tier,
            selected_model_tier=selected_tier,
            max_retries=max_retries,
            max_context_tokens=max_context_tokens,
            budget_cents=budget_cents,
            requires_human_review=requires_human_review,
        )

    def resolve_model_name(self, tier: ModelTier) -> str | None:
        settings = self._settings
        if tier == "tier_premium":
            return settings.ai_tier_premium_model or settings.llm_model or settings.codex_model
        if tier == "tier_standard":
            return settings.ai_tier_standard_model or settings.codex_model or settings.llm_model
        if tier == "tier_economy":
            return settings.ai_tier_economy_model or settings.llm_model or settings.codex_model
        return None

    def default_completion_tokens(self, tier: ModelTier) -> int:
        settings = self._settings
        return {
            "tier_premium": settings.ai_default_completion_premium_tokens,
            "tier_standard": settings.ai_default_completion_standard_tokens,
            "tier_economy": settings.ai_default_completion_economy_tokens,
            "tier_none": 0,
        }[tier]

    def estimate_cost_cents(self, tier: ModelTier, input_tokens: int, output_tokens: int) -> float:
        settings = self._settings
        pricing = {
            "tier_premium": (
                settings.ai_tier_premium_input_cents_per_1k_tokens,
                settings.ai_tier_premium_output_cents_per_1k_tokens,
            ),
            "tier_standard": (
                settings.ai_tier_standard_input_cents_per_1k_tokens,
                settings.ai_tier_standard_output_cents_per_1k_tokens,
            ),
            "tier_economy": (
                settings.ai_tier_economy_input_cents_per_1k_tokens,
                settings.ai_tier_economy_output_cents_per_1k_tokens,
            ),
            "tier_none": (0.0, 0.0),
        }
        in_rate, out_rate = pricing[tier]
        return _round_cost((input_tokens / 1000.0) * in_rate + (output_tokens / 1000.0) * out_rate)

    async def load_cached_context_fragments(
        self,
        request: AIJobRequest,
        *,
        session: AsyncSession | None = None,
    ) -> AICacheContext:
        cache_hits = 0
        cache_keys: list[str] = []
        fragments: dict[str, str] = {}
        if not request.project_id:
            return AICacheContext(fragments=fragments, cache_hits=0, cache_keys=cache_keys)

        async with self._session_scope(session) as db:
            repo_summary = await self._load_or_compute_cache(
                db,
                request,
                cache_scope="repo_summary",
                cache_key="latest",
                source_revision="latest",
                builder=lambda inner: self._build_repo_summary(inner, request),
            )
            if repo_summary:
                fragments["repo_summary"] = str(repo_summary.get("text") or "")
                cache_hits += int(repo_summary.get("_cache_hit", 0))
                cache_keys.append("repo_summary")

            architecture = await self._load_or_compute_cache(
                db,
                request,
                cache_scope="architecture_summary",
                cache_key="official",
                source_revision="latest",
                builder=lambda inner: self._build_architecture_summary(inner, request),
            )
            if architecture:
                fragments["architecture_summary"] = str(architecture.get("text") or "")
                cache_hits += int(architecture.get("_cache_hit", 0))
                cache_keys.append("architecture_summary")

            conventions = await self._load_or_compute_cache(
                db,
                request,
                cache_scope="conventions",
                cache_key="repo_conventions",
                source_revision="latest",
                builder=lambda inner: self._build_conventions_summary(inner, request),
            )
            if conventions:
                fragments["conventions"] = str(conventions.get("text") or "")
                cache_hits += int(conventions.get("_cache_hit", 0))
                cache_keys.append("conventions")

            if request.changed_files:
                revision = sha1("\n".join(sorted(request.changed_files)).encode("utf-8")).hexdigest()[:16]
                module_map = await self._load_or_compute_cache(
                    db,
                    request,
                    cache_scope="module_map",
                    cache_key="changed_files",
                    source_revision=revision,
                    builder=lambda inner: self._build_module_map(inner, request),
                )
                if module_map:
                    fragments["module_map"] = str(module_map.get("text") or "")
                    cache_hits += int(module_map.get("_cache_hit", 0))
                    cache_keys.append("module_map")

                ownership = await self._load_or_compute_cache(
                    db,
                    request,
                    cache_scope="file_ownership",
                    cache_key="changed_files",
                    source_revision=revision,
                    builder=lambda inner: self._build_file_ownership(inner, request),
                )
                if ownership:
                    fragments["file_ownership"] = str(ownership.get("text") or "")
                    cache_hits += int(ownership.get("_cache_hit", 0))
                    cache_keys.append("file_ownership")

        return AICacheContext(fragments=fragments, cache_hits=cache_hits, cache_keys=cache_keys)

    async def prepare_job(
        self,
        request: AIJobRequest,
        *,
        system_prompt: str,
        user_prompt: str,
        filters_used: list[str],
        cache_hit_count: int = 0,
        completion_token_estimate: int | None = None,
        block_on_human_review: bool = False,
        session: AsyncSession | None = None,
    ) -> PreparedAIExecution:
        policy = self.route_job(request)
        input_tokens = estimate_tokens(system_prompt) + estimate_tokens(user_prompt)
        context_size = estimate_tokens(user_prompt)
        output_tokens = completion_token_estimate if completion_token_estimate is not None else self.default_completion_tokens(
            policy.selected_model_tier
        )
        estimated_cost = self.estimate_cost_cents(policy.selected_model_tier, input_tokens, output_tokens)
        stop_reason: str | None = None
        next_action: str | None = None
        blocked = False
        status = "ready"
        approval_state = "pending" if policy.requires_human_review else "not_required"

        if context_size > policy.max_context_tokens:
            stop_reason = "context_limit_exceeded"
            next_action = "Reduce the file set or send a narrower error trace."
            status = "stopped"
        elif estimated_cost > policy.budget_cents:
            stop_reason = "budget_exceeded"
            next_action = "Shrink context, split the task, or request approval before retrying."
            status = "stopped"
        elif policy.selected_model_tier != "tier_none" and self.resolve_model_name(policy.selected_model_tier) is None:
            stop_reason = "model_tier_unconfigured"
            next_action = "Configure the tier model mapping before executing this job."
            status = "stopped"
        elif block_on_human_review and policy.requires_human_review:
            stop_reason = "human_review_required"
            next_action = "Obtain approval or reduce risk before attempting autonomous execution."
            status = "blocked"
            blocked = True

        async with self._session_scope(session) as db:
            row = AIJobRun(
                tenant_id=request.tenant_id or uuid.UUID(int=0),
                project_id=request.project_id,
                repository_id=request.repository_id,
                run_id=request.run_id,
                work_item_id=request.work_item_id,
                document_id=request.document_id,
                knowledge_event_id=request.knowledge_event_id,
                workflow_type=request.workflow_type,
                role=request.role,
                task_type=policy.task_type,
                ambiguity_level=policy.ambiguity_level,
                risk_level=policy.risk_level,
                max_model_tier=policy.max_model_tier,
                selected_model_tier=policy.selected_model_tier,
                max_retries=policy.max_retries,
                max_context_tokens=policy.max_context_tokens,
                context_size=context_size,
                budget_cents=policy.budget_cents,
                estimated_cost_cents=estimated_cost,
                requires_human_review=policy.requires_human_review,
                approval_state=approval_state,
                status=status,
                stop_reason=stop_reason,
                next_action=next_action,
                confidence_score=request.confidence_score,
                cache_hit_count=cache_hit_count,
                details_json={
                    "filters_used": filters_used,
                    "metadata": request.metadata,
                },
                completed_at=_now_utc() if status == "stopped" else None,
            )
            db.add(row)
            await db.flush()
            return PreparedAIExecution(
                job_id=row.id,
                policy=policy,
                model_name=self.resolve_model_name(policy.selected_model_tier),
                estimated_input_tokens=input_tokens,
                estimated_output_tokens=output_tokens,
                estimated_cost_cents=estimated_cost,
                context_size=context_size,
                cache_hit_count=cache_hit_count,
                blocked=blocked,
                stop_reason=stop_reason,
                next_action=next_action,
            )

    async def record_attempt(self, job_id: uuid.UUID, *, session: AsyncSession | None = None) -> None:
        async with self._session_scope(session) as db:
            row = await db.get(AIJobRun, job_id)
            if row is None:
                return
            row.call_count += 1
            row.status = "running"
            db.add(row)
            await db.flush()

    async def record_retry(self, job_id: uuid.UUID, error_kind: str, *, session: AsyncSession | None = None) -> None:
        async with self._session_scope(session) as db:
            row = await db.get(AIJobRun, job_id)
            if row is None:
                return
            row.retry_count += 1
            row.error_kind = error_kind
            db.add(row)
            await db.flush()

    async def complete_job(
        self,
        job_id: uuid.UUID,
        *,
        input_tokens: int,
        output_tokens: int,
        confidence_score: float | None = None,
        details: dict[str, Any] | None = None,
        approval_state: str | None = None,
        status: str = "completed",
        session: AsyncSession | None = None,
    ) -> None:
        async with self._session_scope(session) as db:
            row = await db.get(AIJobRun, job_id)
            if row is None:
                return
            row.tokens_input = max(row.tokens_input, input_tokens)
            row.tokens_output = max(row.tokens_output, output_tokens)
            row.actual_cost_cents = self.estimate_cost_cents(
                row.selected_model_tier, row.tokens_input, row.tokens_output
            )
            row.confidence_score = confidence_score
            row.status = status
            row.approval_state = approval_state or row.approval_state
            row.error_kind = None if status == "completed" else row.error_kind
            row.completed_at = _now_utc()
            if details:
                row.details_json = {**(row.details_json or {}), **details}
            db.add(row)
            await db.flush()

    async def fail_job(
        self,
        job_id: uuid.UUID,
        *,
        reason: str,
        next_action: str,
        error_kind: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        details: dict[str, Any] | None = None,
        approval_state: str | None = None,
        status: str = "failed",
        session: AsyncSession | None = None,
    ) -> None:
        async with self._session_scope(session) as db:
            row = await db.get(AIJobRun, job_id)
            if row is None:
                return
            row.tokens_input = max(row.tokens_input, input_tokens)
            row.tokens_output = max(row.tokens_output, output_tokens)
            row.actual_cost_cents = self.estimate_cost_cents(
                row.selected_model_tier, row.tokens_input, row.tokens_output
            )
            row.status = status
            row.stop_reason = reason
            row.next_action = next_action
            row.error_kind = error_kind
            row.approval_state = approval_state or row.approval_state
            row.completed_at = _now_utc()
            if details:
                row.details_json = {**(row.details_json or {}), **details}
            db.add(row)
            await db.flush()

    async def record_deterministic_job(
        self,
        request: AIJobRequest,
        *,
        filters_used: list[str],
        context_sections: dict[str, str],
        status: str = "completed",
        approval_state: str = "not_required",
        confidence_score: float | None = None,
        details: dict[str, Any] | None = None,
        session: AsyncSession | None = None,
    ) -> uuid.UUID:
        policy = self.route_job(request)
        context_text = "\n".join(value for value in context_sections.values() if value)
        async with self._session_scope(session) as db:
            row = AIJobRun(
                tenant_id=request.tenant_id or uuid.UUID(int=0),
                project_id=request.project_id,
                repository_id=request.repository_id,
                run_id=request.run_id,
                work_item_id=request.work_item_id,
                document_id=request.document_id,
                knowledge_event_id=request.knowledge_event_id,
                workflow_type=request.workflow_type,
                role=request.role,
                task_type=policy.task_type,
                ambiguity_level=policy.ambiguity_level,
                risk_level=policy.risk_level,
                max_model_tier=policy.max_model_tier,
                selected_model_tier="tier_none",
                max_retries=0,
                max_context_tokens=policy.max_context_tokens,
                context_size=estimate_tokens(context_text),
                budget_cents=policy.budget_cents,
                estimated_cost_cents=0.0,
                actual_cost_cents=0.0,
                requires_human_review=policy.requires_human_review,
                approval_state=approval_state,
                status=status,
                confidence_score=confidence_score,
                cache_hit_count=0,
                details_json={
                    "filters_used": filters_used,
                    "context_sections": list(context_sections.keys()),
                    **(details or {}),
                },
                completed_at=_now_utc(),
            )
            db.add(row)
            await db.flush()
            return row.id

    async def sync_knowledge_review_state(
        self,
        knowledge_event_id: uuid.UUID,
        *,
        approval_state: str,
        reviewer_user_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        async with self._session_scope(session) as db:
            result = await db.execute(
                select(AIJobRun).where(AIJobRun.knowledge_event_id == knowledge_event_id).order_by(AIJobRun.created_at.desc())
            )
            rows = result.scalars().all()
            for row in rows:
                row.approval_state = approval_state
                if approval_state == "approved":
                    row.approved_at = _now_utc()
                    row.approved_by = reviewer_user_id
                    if row.status in {"awaiting_review", "blocked"}:
                        row.status = "completed"
                        row.completed_at = row.completed_at or _now_utc()
                elif approval_state in {"rejected", "deferred"}:
                    row.completed_at = row.completed_at or _now_utc()
                db.add(row)
            await db.flush()

    async def get_dashboard(
        self,
        *,
        project_id: uuid.UUID | None = None,
        repository_id: uuid.UUID | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        async with self._session_scope(session) as db:
            stmt = select(AIJobRun).order_by(AIJobRun.created_at.desc())
            if project_id:
                stmt = stmt.where(AIJobRun.project_id == project_id)
            if repository_id:
                stmt = stmt.where(AIJobRun.repository_id == repository_id)
            rows = (await db.execute(stmt)).scalars().all()

            project_names = {
                row.id: row.name
                for row in (
                    await db.execute(select(Project).where(Project.id.in_({item.project_id for item in rows if item.project_id})))
                ).scalars().all()
            } if rows else {}
            repo_names = {
                row.id: row.repo_full_name or row.repo_url
                for row in (
                    await db.execute(
                        select(ProjectRepository).where(
                            ProjectRepository.id.in_({item.repository_id for item in rows if item.repository_id})
                        )
                    )
                ).scalars().all()
            } if rows else {}

        def total_tokens(item: AIJobRun) -> int:
            return (item.tokens_input or 0) + (item.tokens_output or 0)

        def total_cost(item: AIJobRun) -> float:
            return item.actual_cost_cents or item.estimated_cost_cents or 0.0

        def approval_required(item: AIJobRun) -> bool:
            return (item.approval_state or "not_required") != "not_required"

        def rate(numerator: int, denominator: int) -> float:
            if denominator <= 0:
                return 0.0
            return round(numerator / denominator, 4)

        workflow_groups: dict[str, list[AIJobRun]] = {}
        tier_groups: dict[str, list[AIJobRun]] = {}
        project_groups: dict[str, list[AIJobRun]] = {}
        repo_groups: dict[str, list[AIJobRun]] = {}
        for row in rows:
            workflow_groups.setdefault(row.workflow_type, []).append(row)
            tier_groups.setdefault(row.selected_model_tier, []).append(row)
            if row.project_id:
                project_groups.setdefault(str(row.project_id), []).append(row)
            if row.repository_id:
                repo_groups.setdefault(str(row.repository_id), []).append(row)

        workflows = []
        for workflow_type, items in sorted(workflow_groups.items(), key=lambda pair: pair[0]):
            approvals_needed = sum(1 for item in items if approval_required(item))
            approvals_done = sum(1 for item in items if item.approval_state == "approved")
            workflows.append(
                {
                    "workflow_type": workflow_type,
                    "jobs": len(items),
                    "calls_per_run": round(sum(item.call_count for item in items) / len(items), 3),
                    "tokens_per_run": round(sum(total_tokens(item) for item in items) / len(items), 3),
                    "cost_per_run": round(sum(total_cost(item) for item in items) / len(items), 4),
                    "retry_count": sum(item.retry_count for item in items),
                    "average_context_size": round(sum(item.context_size for item in items) / len(items), 3),
                    "success_rate": rate(sum(1 for item in items if item.status == "completed"), len(items)),
                    "manual_escalation_rate": rate(sum(1 for item in items if item.requires_human_review), len(items)),
                    "approval_rate": rate(approvals_done, approvals_needed),
                }
            )

        spend_by_tier = [
            {
                "key": tier,
                "label": tier.replace("tier_", "").replace("_", " ").title(),
                "cost_cents": round(sum(total_cost(item) for item in items), 4),
                "job_count": len(items),
            }
            for tier, items in sorted(tier_groups.items(), key=lambda pair: TIER_ORDER.get(pair[0], 99), reverse=True)
        ]

        spend_by_project = [
            {
                "key": project_key,
                "label": project_names.get(uuid.UUID(project_key), project_key) if project_key else "Unknown project",
                "cost_cents": round(sum(total_cost(item) for item in items), 4),
                "job_count": len(items),
            }
            for project_key, items in sorted(
                project_groups.items(),
                key=lambda pair: sum(total_cost(item) for item in pair[1]),
                reverse=True,
            )
        ]

        spend_by_repository = [
            {
                "key": repo_key,
                "label": repo_names.get(uuid.UUID(repo_key), repo_key) if repo_key else "Unknown repository",
                "cost_cents": round(sum(total_cost(item) for item in items), 4),
                "job_count": len(items),
            }
            for repo_key, items in sorted(
                repo_groups.items(),
                key=lambda pair: sum(total_cost(item) for item in pair[1]),
                reverse=True,
            )
        ]

        recent_jobs = [
            {
                "id": item.id,
                "workflow_type": item.workflow_type,
                "role": item.role,
                "task_type": item.task_type,
                "selected_model_tier": item.selected_model_tier,
                "status": item.status,
                "approval_state": item.approval_state,
                "retry_count": item.retry_count,
                "context_size": item.context_size,
                "cost_cents": round(total_cost(item), 4),
                "confidence_score": item.confidence_score,
                "requires_human_review": item.requires_human_review,
                "stop_reason": item.stop_reason,
                "project_id": item.project_id,
                "repository_id": item.repository_id,
                "created_at": item.created_at,
                "completed_at": item.completed_at,
            }
            for item in rows[:12]
        ]

        top_retry_offenders = [
            {
                "id": item.id,
                "label": f"{item.workflow_type} · {item.role}",
                "workflow_type": item.workflow_type,
                "selected_model_tier": item.selected_model_tier,
                "retry_count": item.retry_count,
                "context_size": item.context_size,
                "cost_cents": round(total_cost(item), 4),
                "status": item.status,
                "created_at": item.created_at,
            }
            for item in sorted(rows, key=lambda row: (row.retry_count, total_cost(row)), reverse=True)[:8]
            if item.retry_count > 0
        ]

        largest_context_offenders = [
            {
                "id": item.id,
                "label": f"{item.workflow_type} · {item.role}",
                "workflow_type": item.workflow_type,
                "selected_model_tier": item.selected_model_tier,
                "retry_count": item.retry_count,
                "context_size": item.context_size,
                "cost_cents": round(total_cost(item), 4),
                "status": item.status,
                "created_at": item.created_at,
            }
            for item in sorted(rows, key=lambda row: (row.context_size, total_cost(row)), reverse=True)[:8]
        ]

        approvals_needed_total = sum(1 for item in rows if approval_required(item))
        approvals_done_total = sum(1 for item in rows if item.approval_state == "approved")
        successful_pr_jobs = [
            item for item in rows if item.workflow_type == "pr_review" and item.status == "completed"
        ]
        docs_jobs = [
            item for item in rows if item.workflow_type in {"docs_verification", "docs_proposal"} and item.status == "completed"
        ]

        return {
            "summary": {
                "total_jobs": len(rows),
                "calls_per_run": round(sum(item.call_count for item in rows) / len(rows), 3) if rows else 0.0,
                "tokens_per_run": round(sum(total_tokens(item) for item in rows) / len(rows), 3) if rows else 0.0,
                "cost_per_run": round(sum(total_cost(item) for item in rows) / len(rows), 4) if rows else 0.0,
                "retry_count": sum(item.retry_count for item in rows),
                "success_rate": rate(sum(1 for item in rows if item.status == "completed"), len(rows)),
                "manual_escalation_rate": rate(sum(1 for item in rows if item.requires_human_review), len(rows)),
                "approval_rate": rate(approvals_done_total, approvals_needed_total),
                "average_context_size": round(sum(item.context_size for item in rows) / len(rows), 3) if rows else 0.0,
                "total_cost_cents": round(sum(total_cost(item) for item in rows), 4),
                "average_cost_per_successful_pr": round(
                    sum(total_cost(item) for item in successful_pr_jobs) / len(successful_pr_jobs), 4
                )
                if successful_pr_jobs
                else 0.0,
                "average_cost_per_docs_proposal": round(
                    sum(total_cost(item) for item in docs_jobs) / len(docs_jobs), 4
                )
                if docs_jobs
                else 0.0,
            },
            "workflows": workflows,
            "spend_by_tier": spend_by_tier,
            "spend_by_project": spend_by_project,
            "spend_by_repository": spend_by_repository,
            "top_retry_offenders": top_retry_offenders,
            "largest_context_offenders": largest_context_offenders,
            "recent_jobs": recent_jobs,
        }

    async def _load_or_compute_cache(
        self,
        session: AsyncSession,
        request: AIJobRequest,
        *,
        cache_scope: str,
        cache_key: str,
        source_revision: str,
        builder,
    ) -> dict[str, Any] | None:
        stmt = select(AIArtifactCache).where(
            AIArtifactCache.tenant_id == (request.tenant_id or uuid.UUID(int=0)),
            AIArtifactCache.project_id == request.project_id,
            AIArtifactCache.repository_id == request.repository_id,
            AIArtifactCache.cache_scope == cache_scope,
            AIArtifactCache.cache_key == cache_key,
            AIArtifactCache.source_revision == source_revision,
        )
        existing = await session.scalar(stmt)
        if existing is not None:
            existing.hit_count += 1
            existing.last_accessed_at = _now_utc()
            session.add(existing)
            await session.flush()
            return {"_cache_hit": 1, **(existing.payload_json or {})}

        payload = await builder(session)
        if not payload:
            return None
        row = AIArtifactCache(
            tenant_id=request.tenant_id or uuid.UUID(int=0),
            project_id=request.project_id,
            repository_id=request.repository_id,
            cache_scope=cache_scope,
            cache_key=cache_key,
            source_revision=source_revision,
            payload_json=payload,
            hit_count=0,
            last_accessed_at=_now_utc(),
        )
        session.add(row)
        await session.flush()
        return {"_cache_hit": 0, **payload}

    async def _build_repo_summary(self, session: AsyncSession, request: AIJobRequest) -> dict[str, Any] | None:
        repo = await session.get(ProjectRepository, request.repository_id) if request.repository_id else None
        snapshot = await session.scalar(
            select(RepoSnapshot).where(RepoSnapshot.project_id == request.project_id).order_by(RepoSnapshot.indexed_at.desc())
        )
        latest_run = await session.scalar(
            select(RunSummary).where(RunSummary.project_id == request.project_id).order_by(RunSummary.created_at.desc())
        )
        parts: list[str] = []
        if repo is not None:
            parts.append(f"Repository: {repo.repo_full_name or repo.repo_url}.")
        if snapshot is not None:
            parts.append(
                f"Indexed snapshot: {snapshot.file_count} files, {snapshot.symbol_count} symbols, {snapshot.edge_count} edges."
            )
        if latest_run is not None:
            changed = ", ".join(latest_run.changed_files[:5]) if latest_run.changed_files else "no recent file list"
            parts.append(f"Latest run: {latest_run.status} via {latest_run.executor}; recent changed files: {changed}.")
        if not parts:
            return None
        return {"text": " ".join(parts)}

    async def _build_architecture_summary(self, session: AsyncSession, request: AIJobRequest) -> dict[str, Any] | None:
        stmt = (
            select(KnowledgeArtifact)
            .where(
                KnowledgeArtifact.project_id == request.project_id,
                KnowledgeArtifact.status == "active",
                KnowledgeArtifact.artifact_type.in_(["architecture_note", "adr", "api_note", "db_note"]),
            )
            .order_by(KnowledgeArtifact.updated_at.desc())
            .limit(3)
        )
        artifacts = (await session.execute(stmt)).scalars().all()
        if not artifacts:
            return None
        text = " ".join(
            f"{artifact.title}: {_compact_text(artifact.canonical_content or '', 320)}"
            for artifact in artifacts
            if artifact.canonical_content
        )
        if not text:
            return None
        return {"text": _compact_text(text, 1200)}

    async def _build_conventions_summary(self, session: AsyncSession, request: AIJobRequest) -> dict[str, Any] | None:
        stmt = (
            select(RepoFile)
            .where(
                RepoFile.project_id == request.project_id,
                RepoFile.path.in_(["pyproject.toml", "package.json", "requirements.txt", "README.md"]),
            )
            .order_by(RepoFile.path.asc())
        )
        files = (await session.execute(stmt)).scalars().all()
        if not files:
            return None
        text = "Conventions: " + " ".join(f"{item.path} -> {item.summary}" for item in files)
        return {"text": _compact_text(text, 1000)}

    async def _build_module_map(self, _session: AsyncSession, request: AIJobRequest) -> dict[str, Any] | None:
        modules: list[str] = []
        for path in request.changed_files:
            parts = [part for part in path.split("/") if part]
            if not parts:
                continue
            if len(parts) >= 2 and parts[0] in {"apps", "core", "agent", "docs", "infra"}:
                modules.append("/".join(parts[:2]))
            else:
                modules.append(parts[0])
        ordered: list[str] = []
        for item in modules:
            if item not in ordered:
                ordered.append(item)
        if not ordered:
            return None
        return {"text": f"Changed module map: {', '.join(ordered[:6])}."}

    async def _build_file_ownership(self, session: AsyncSession, request: AIJobRequest) -> dict[str, Any] | None:
        if not request.repository_id or not request.changed_files:
            return None
        rows = (
            await session.execute(
                select(KnowledgeFileMapping)
                .where(KnowledgeFileMapping.repository_id == request.repository_id)
                .order_by(KnowledgeFileMapping.priority.asc(), KnowledgeFileMapping.created_at.asc())
            )
        ).scalars().all()
        matches: list[str] = []
        for mapping in rows:
            if any(fnmatch.fnmatch(path, mapping.file_path_pattern) for path in request.changed_files):
                label = mapping.module_name or mapping.artifact_key
                if label not in matches:
                    matches.append(label)
        if not matches:
            return None
        return {"text": f"File ownership hints: {', '.join(matches[:6])}."}
