from __future__ import annotations

from dataclasses import dataclass

from app.services.ai_policy import contains_sensitive_paths


_SAFE_FRONTEND_SUFFIXES = (".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".vue")


@dataclass(frozen=True)
class MutationGovernanceDecision:
    requires_confirmation: bool
    mutation_class: str
    reason: str


def _is_safe_frontend_path(path: str) -> bool:
    lowered = path.strip().lower()
    return lowered.endswith(_SAFE_FRONTEND_SUFFIXES)


def evaluate_mutation_governance(
    *,
    work_item_type: str,
    target_files: list[str],
    changed_files: list[str],
    operator_confirmation_required: bool,
    repository_state: str | None = None,
) -> MutationGovernanceDecision:
    if not operator_confirmation_required:
        return MutationGovernanceDecision(
            requires_confirmation=False,
            mutation_class="SAFE_BY_VERIFIER",
            reason="verifier_did_not_require_confirmation",
        )

    normalized_targets = [path.strip() for path in target_files if isinstance(path, str) and path.strip()]
    normalized_changed = [path.strip() for path in changed_files if isinstance(path, str) and path.strip()]
    scope_files = normalized_changed or normalized_targets

    safe_bootstrap_frontend_mutation = (
        work_item_type == "CODE_FRONTEND"
        and 0 < len(normalized_targets) <= 2
        and all(_is_safe_frontend_path(path) for path in normalized_targets)
        and not contains_sensitive_paths(scope_files)
    )
    if safe_bootstrap_frontend_mutation:
        return MutationGovernanceDecision(
            requires_confirmation=False,
            mutation_class="SAFE_UI_SCAFFOLD",
            reason="safe_bootstrap_frontend_mutation",
        )

    normalized_state = (repository_state or "").strip().upper()
    safe_bootstrap_backend_mutation = (
        normalized_state in {"GENESIS", "EARLY_BUILD"}
        and work_item_type in {"GENERATE_ROUTE", "GENERATE_SERVICE", "GENERATE_REPOSITORY", "GENERATE_CAPABILITY_BINDING", "CODE_BACKEND"}
        and 0 < len(scope_files) <= 2
        and not contains_sensitive_paths(scope_files)
    )
    if safe_bootstrap_backend_mutation:
        return MutationGovernanceDecision(
            requires_confirmation=False,
            mutation_class="SAFE_BACKEND_SCAFFOLD",
            reason="safe_bootstrap_backend_mutation",
        )

    if contains_sensitive_paths(scope_files):
        return MutationGovernanceDecision(
            requires_confirmation=True,
            mutation_class="INFRA_OR_SENSITIVE_MUTATION",
            reason="sensitive_path_scope",
        )

    return MutationGovernanceDecision(
        requires_confirmation=True,
        mutation_class="STRUCTURAL_OR_BROAD_MUTATION",
        reason="operator_confirmation_required_by_verifier",
    )
