import uuid

from app.services.ai_policy import AIJobManager, AIJobRequest, contains_sensitive_paths


def test_planner_routes_to_premium_with_interactive_defaults():
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
    assert policy.selected_model_tier == "tier_premium"
    assert policy.max_retries == 1
    assert policy.max_context_tokens == 20_000
    assert policy.budget_cents == 25.0


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
    assert policy.max_model_tier == "tier_standard"
    assert policy.requires_human_review is True
