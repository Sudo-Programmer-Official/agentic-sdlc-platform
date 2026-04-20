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
    assert ledger.budget_mode == "CONSTRAINED"
    assert ledger.model_tier_cap == "tier_economy"
    assert ledger.completion_token_cap == 400


def test_execution_budget_ledger_blocks_when_remaining_budget_is_exhausted():
    ledger = ExecutionBudgetLedger(max_tokens=700, used_input_tokens=300, used_output_tokens=200)
    ledger.refresh()

    assert ledger.remaining_tokens == 200
    assert ledger.budget_mode == "BLOCKED"
    assert ledger.model_tier_cap == "tier_none"
    assert ledger.completion_token_cap == 0
