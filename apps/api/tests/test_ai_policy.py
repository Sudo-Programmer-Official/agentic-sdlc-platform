import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Artifact, Project
from app.services.ai_policy import AIJobManager, AIJobRequest, contains_sensitive_paths


def test_planner_routes_to_standard_tier_without_auto_retries():
    manager = AIJobManager()
    policy = manager.route_job(
        AIJobRequest(
            workflow_type="interactive_planning",
            role="planner",
            task_type="planning",
            ambiguity_level="high",
            risk_level="medium",
            tenant_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            user_triggered=True,
        )
    )

    assert policy.max_model_tier == "tier_premium"
    assert policy.selected_model_tier == "tier_standard"
    assert policy.max_retries == 0
    assert policy.max_context_tokens == 10_000
    assert policy.budget_cents == 8.0
    assert manager.resolve_model_name(policy.selected_model_tier) == "gpt-4.1-mini"


def test_background_docs_job_stays_deterministic_under_economy_cap():
    manager = AIJobManager()
    policy = manager.route_job(
        AIJobRequest(
            workflow_type="docs_verification",
            role="documenter",
            task_type="docs_proposal",
            ambiguity_level="low",
            risk_level="low",
            tenant_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            background_job=True,
            deterministic_preferred=True,
        )
    )

    assert policy.max_model_tier == "tier_economy"
    assert policy.selected_model_tier == "tier_none"
    assert policy.max_context_tokens == 4_000
    assert policy.budget_cents == 2.0


def test_sensitive_paths_force_human_review():
    changed_files = ["apps/api/app/api/v1/knowledge.py", "apps/api/alembic/versions/20260314_0009_ai_control.py"]
    manager = AIJobManager()
    policy = manager.route_job(
        AIJobRequest(
            workflow_type="repo_implementation_task",
            role="coder",
            task_type="implementation",
            ambiguity_level="medium",
            risk_level="high",
            tenant_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            changed_files=changed_files,
        )
    )

    assert contains_sensitive_paths(changed_files) is True
    assert policy.max_model_tier == "tier_premium"
    assert policy.selected_model_tier == "tier_standard"
    assert policy.requires_human_review is True


def test_repo_implementation_routes_standard_tier_to_mini_with_single_retry():
    manager = AIJobManager()
    policy = manager.route_job(
        AIJobRequest(
            workflow_type="repo_implementation_task",
            role="coder",
            task_type="implementation",
            ambiguity_level="medium",
            risk_level="medium",
            tenant_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
        )
    )

    assert policy.selected_model_tier == "tier_standard"
    assert policy.max_retries == 1
    assert manager.resolve_model_name(policy.selected_model_tier) == "gpt-4.1-mini"


def test_frontend_implementation_allows_premium_escalation():
    manager = AIJobManager()
    policy = manager.route_job(
        AIJobRequest(
            workflow_type="repo_implementation_task",
            role="coder",
            task_type="implementation",
            ambiguity_level="medium",
            risk_level="medium",
            tenant_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            surface="frontend",
        )
    )

    assert policy.selected_model_tier == "tier_standard"
    assert policy.max_model_tier == "tier_premium"
    assert policy.max_retries == 1


def test_fix_failure_routes_to_mini_first_with_premium_escalation_available():
    manager = AIJobManager()
    policy = manager.route_job(
        AIJobRequest(
            workflow_type="repo_implementation_task",
            role="coder",
            task_type="bugfix",
            ambiguity_level="medium",
            risk_level="medium",
            tenant_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            tests_failed=True,
        )
    )

    assert policy.selected_model_tier == "tier_standard"
    assert policy.max_model_tier == "tier_premium"
    assert policy.max_retries == 1


def test_write_tests_routes_to_mini_first_with_premium_escalation_available():
    manager = AIJobManager()
    policy = manager.route_job(
        AIJobRequest(
            workflow_type="repo_implementation_task",
            role="coder",
            task_type="testing",
            ambiguity_level="medium",
            risk_level="medium",
            tenant_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
        )
    )

    assert policy.selected_model_tier == "tier_standard"
    assert policy.max_model_tier == "tier_premium"
    assert policy.max_retries == 1


def test_high_risk_reviewer_job_does_not_force_human_review():
    manager = AIJobManager()
    policy = manager.route_job(
        AIJobRequest(
            workflow_type="pr_review",
            role="reviewer",
            task_type="review",
            ambiguity_level="high",
            risk_level="high",
            tenant_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            changed_files=["apps/api/app/api/v1/knowledge.py", "apps/api/alembic/versions/20260314_0009_ai_control.py"],
        )
    )

    assert policy.max_model_tier == "tier_premium"
    assert policy.selected_model_tier == "tier_premium"
    assert policy.requires_human_review is False


def test_medium_risk_reviewer_job_can_escalate_to_premium():
    manager = AIJobManager()
    policy = manager.route_job(
        AIJobRequest(
            workflow_type="pr_review",
            role="reviewer",
            task_type="review",
            ambiguity_level="medium",
            risk_level="medium",
            tenant_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            changed_files=["index.html"],
        )
    )

    assert policy.selected_model_tier == "tier_standard"
    assert policy.max_model_tier == "tier_premium"
    assert policy.max_retries == 1


@pytest.mark.anyio
async def test_context_pack_injects_external_reference_and_is_replay_consistent(tmp_path, monkeypatch):
    monkeypatch.setenv("EXTERNAL_REFERENCE_MAX_CONTEXT_CHARS", "1200")
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ai_policy_refs.db'}", future=True)
    session_factory = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        session.add(Project(id=project_id, tenant_id=tenant_id, name="P"))
        session.add(
            Artifact(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                type="external_reference",
                uri="https://example.com/ref",
                extra_metadata={"label": "Ref", "summary": "Use bounded retries and explicit escalation."},
            )
        )
        await session.commit()
    manager = AIJobManager(session_factory=session_factory)
    request = AIJobRequest(
        workflow_type="repo_implementation_task",
        role="coder",
        task_type="implementation",
        ambiguity_level="medium",
        risk_level="medium",
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=run_id,
        metadata={"requirement_id": "FR-001"},
    )
    first = await manager.load_context_pack(request)
    second = await manager.load_context_pack(request)
    assert "external_references" in first.fragments
    assert "context_ranking" in first.fragments
    assert "bounded retries" in first.fragments["external_references"]
    assert "avg_relevance" in first.fragments["context_ranking"]
    assert first.pack_hash == second.pack_hash
    await engine.dispose()
