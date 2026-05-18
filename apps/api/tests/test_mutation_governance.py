from app.runtime.mutation_governance import evaluate_mutation_governance


def test_mutation_governance_allows_safe_bootstrap_backend_mutation():
    decision = evaluate_mutation_governance(
        work_item_type="GENERATE_ROUTE",
        target_files=["app.py"],
        changed_files=["app.py"],
        operator_confirmation_required=True,
        repository_state="GENESIS",
    )
    assert decision.requires_confirmation is False
    assert decision.reason == "safe_bootstrap_backend_mutation"


def test_mutation_governance_blocks_sensitive_bootstrap_backend_mutation():
    decision = evaluate_mutation_governance(
        work_item_type="GENERATE_ROUTE",
        target_files=["apps/api/app/schemas/auth_tokens.py"],
        changed_files=["apps/api/app/schemas/auth_tokens.py"],
        operator_confirmation_required=True,
        repository_state="GENESIS",
    )
    assert decision.requires_confirmation is True
    assert decision.reason == "sensitive_path_scope"


def test_mutation_governance_blocks_non_bootstrap_backend_mutation():
    decision = evaluate_mutation_governance(
        work_item_type="GENERATE_ROUTE",
        target_files=["app.py"],
        changed_files=["app.py"],
        operator_confirmation_required=True,
        repository_state="ACTIVE_PRODUCT",
    )
    assert decision.requires_confirmation is True
    assert decision.reason == "operator_confirmation_required_by_verifier"
