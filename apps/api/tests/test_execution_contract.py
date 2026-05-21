from app.runtime.execution_contract import ExecutionBudgetLedger, ExecutionContract, build_execution_contract


def test_build_execution_contract_merges_scope_validation_and_command_prefixes():
    contract = build_execution_contract(
        run_summary={
            "goal": "Implement homepage hero",
            "target_files": ["apps/web/src/App.vue"],
            "expected_files": ["apps/web/src/App.vue", "apps/web/src/styles.css"],
            "edit_budget": {
                "mode": "minimal_patch",
                "max_files": 2,
                "hard_max_files": 4,
            },
        },
        architecture_profile={
            "protected_paths": ["apps/api/app/db/models"],
            "safe_paths": ["apps/web/src"],
            "summary": {"assumptions_used": ["repo layout inferred from preview profile"]},
            "validation_recipe_index": {"frontend_validation": {"paths": ["apps/web"]}},
            "command_index": {
                "frontend_build": {
                    "command": "npm -C apps/web run build",
                    "kind": "build",
                    "paths": ["apps/web"],
                },
                "frontend_test": {
                    "command": "npm -C apps/web run test",
                    "kind": "test",
                    "paths": ["apps/web"],
                },
                "frontend_lint": {
                    "command": "npm -C apps/web run lint",
                    "kind": "lint",
                    "paths": ["apps/web"],
                }
            },
        },
        plan_snapshot={
            "expected_files": ["apps/web/src/App.vue"],
            "validation_steps": ["Run tests", "Review diff"],
            "success_criteria": ["Frontend build passes"],
            "risk_level": "LOW",
        },
    )

    assert contract.goal == "Implement homepage hero"
    assert contract.target_files == ["apps/web/src/App.vue"]
    assert contract.allowed_files == ["apps/web/src/App.vue", "apps/web/src/styles.css"]
    assert contract.protected_paths == ["apps/api/app/db/models"]
    assert contract.safe_paths == ["apps/web/src"]
    assert contract.validation_steps == ["Run tests", "Review diff"]
    assert contract.validation_recipes == ["frontend_validation"]
    assert contract.build_command == "npm -C apps/web run build"
    assert contract.test_command == "npm -C apps/web run test"
    assert contract.lint_command == "npm -C apps/web run lint"
    assert contract.file_budget == 2
    assert contract.hard_file_budget == 4
    assert contract.validation_state == "PENDING"
    assert contract.retry_state == "IDLE"
    assert "git" in contract.allowed_command_prefixes
    assert "npm" in contract.allowed_command_prefixes


def test_execution_contract_coerces_legacy_state_aliases():
    contract = ExecutionContract.from_dict(
        {
            "lifecycle_state": "completed",
            "validation_state": "queued",
            "retry_state": "scheduled",
            "budget": {"max_tokens": 2_000},
        }
    )

    assert contract is not None
    assert contract.lifecycle_state == "SUCCESS"
    assert contract.validation_state == "PENDING"
    assert contract.retry_state == "PENDING"


def test_execution_budget_ledger_constrains_when_remaining_budget_is_low():
    ledger = ExecutionBudgetLedger(max_tokens=2_000, used_input_tokens=700, used_output_tokens=500)
    ledger.refresh()

    assert ledger.used_tokens == 1_200
    assert ledger.remaining_tokens == 800
    assert ledger.budget_mode in {"CONSTRAINED", "BLOCKED"}
    assert ledger.model_tier_cap in {"tier_economy", "tier_none"}
    assert ledger.completion_token_cap <= 400


def test_execution_budget_ledger_blocks_when_remaining_budget_is_exhausted():
    ledger = ExecutionBudgetLedger(max_tokens=700, used_input_tokens=300, used_output_tokens=200)
    ledger.refresh()

    assert ledger.remaining_tokens == 200
    assert ledger.budget_mode == "BLOCKED"
    assert ledger.model_tier_cap == "tier_none"
    assert ledger.completion_token_cap == 0


def test_execution_budget_ledger_allows_recovery_reserve_after_main_cost_is_exhausted():
    ledger = ExecutionBudgetLedger(
        max_tokens=20_000,
        max_cost_cents=30.0,
        used_cost_cents=31.0,
        recovery_reserve_cost_cents=12.0,
    )

    ledger.refresh(recovery_mode=True)

    assert ledger.active_budget_partition == "recovery"
    assert ledger.remaining_cost_cents == 11.0
    assert ledger.remaining_recovery_cost_cents == 12.0
    assert ledger.budget_mode == "NORMAL"


def test_execution_budget_ledger_blocks_when_recovery_reserve_is_exhausted():
    ledger = ExecutionBudgetLedger(
        max_tokens=20_000,
        max_cost_cents=30.0,
        used_cost_cents=42.2,
        recovery_reserve_cost_cents=12.0,
        used_recovery_cost_cents=11.7,
    )

    ledger.refresh(recovery_mode=True)

    assert ledger.budget_mode == "BLOCKED"
    assert ledger.escalation_reason == "recovery_budget_exhausted"
    assert ledger.completion_token_cap == 0


def test_execution_budget_ledger_falls_back_to_main_budget_when_recovery_reserve_is_exhausted():
    ledger = ExecutionBudgetLedger(
        max_tokens=20_000,
        max_cost_cents=40.0,
        used_cost_cents=34.0,
        recovery_reserve_cost_cents=12.0,
        used_recovery_cost_cents=11.7,
    )

    ledger.refresh(recovery_mode=True)

    assert ledger.active_budget_partition == "main_fallback"
    assert ledger.remaining_cost_cents == 6.0
    assert ledger.budget_mode in {"NORMAL", "CONSTRAINED"}


def test_build_execution_contract_scales_run_cost_budget_with_ai_backed_steps():
    contract = build_execution_contract(
        run_summary={"goal": "Polish the landing page"},
        architecture_profile=None,
        plan_snapshot={
            "steps": [
                {"work_item_type": "PLAN_DAG"},
                {"work_item_type": "CODE_FRONTEND"},
                {"work_item_type": "WRITE_TESTS"},
                {"work_item_type": "RUN_TESTS"},
                {"work_item_type": "REVIEW_DIFF"},
                {"work_item_type": "REVIEW_INTEGRATION"},
            ]
        },
    )

    assert contract.budget.max_cost_cents >= 40.0


def test_build_execution_contract_merges_project_contract_assumptions():
    contract = build_execution_contract(
        run_summary={
            "goal": "Apply design system update",
            "project_contract": {
                "assumptions_used": ["Branch strategy: run_branch_then_pr", "Default branch: main"],
            },
        },
        architecture_profile={
            "summary": {"assumptions_used": ["Repository: acme/example"]},
        },
        plan_snapshot=None,
    )

    assert "Repository: acme/example" in contract.assumptions_used
    assert "Branch strategy: run_branch_then_pr" in contract.assumptions_used
    assert "Default branch: main" in contract.assumptions_used


def test_build_execution_contract_prefers_static_frontend_test_command():
    contract = build_execution_contract(
        run_summary={
            "goal": "Refine portfolio navigation",
            "target_files": ["index.html", "styles.css"],
        },
        architecture_profile={
            "command_index": {
                "static_frontend_test": {
                    "command": "python3 -m pytest -q test_index_html.py",
                    "kind": "test",
                    "paths": ["."],
                },
                "repo_tests": {
                    "command": "python3 -m pytest -q",
                    "kind": "test",
                    "paths": ["."],
                },
            }
        },
        plan_snapshot=None,
    )

    assert contract.test_command == "python3 -m pytest -q test_index_html.py"


def test_build_execution_contract_applies_project_intent_risk_and_preview_defaults():
    contract = build_execution_contract(
        run_summary={
            "goal": "Ship onboarding flow",
            "project_intent": {
                "setup_experience": "recommended",
                "architecture_mode": "guided",
                "repo_layout": "monorepo",
                "frontend_stack": "vue_vite",
                "backend_stack": "fastapi",
                "capabilities": ["auth", "crm_sync"],
            },
        },
        architecture_profile={},
        plan_snapshot={"risk_level": "HIGH"},
    )

    assert contract.risk_level == "LOW"
    assert contract.preview_command == "npm -C apps/web run build"
    assert "Setup experience: recommended" in contract.assumptions_used
    assert "Architecture mode: guided" in contract.assumptions_used


def test_build_execution_contract_raises_risk_for_manual_intent_mode():
    contract = build_execution_contract(
        run_summary={
            "goal": "Patch mature production API",
            "project_intent": {
                "setup_experience": "advanced",
                "architecture_mode": "manual",
                "repo_layout": "monorepo",
                "frontend_stack": "nextjs",
                "backend_stack": "nestjs",
            },
        },
        architecture_profile={},
        plan_snapshot={"risk_level": "LOW"},
    )

    assert contract.risk_level == "MEDIUM"
