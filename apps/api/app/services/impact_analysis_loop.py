from __future__ import annotations

from typing import Any


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def predict_pre_execution_impact(
    *,
    run_summary: dict[str, Any] | None,
    architecture_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    summary = run_summary if isinstance(run_summary, dict) else {}
    profile = architecture_profile if isinstance(architecture_profile, dict) else {}

    predicted_files = (
        _coerce_string_list(summary.get("target_files"))
        or _coerce_string_list(summary.get("expected_files"))
        or _coerce_string_list(summary.get("files"))
    )
    predicted_validations = _coerce_string_list(profile.get("validation_recipes"))
    if not predicted_validations:
        predicted_validations = ["run_tests"]

    risk = "LOW"
    if len(predicted_files) >= 5:
        risk = "HIGH"
    elif len(predicted_files) >= 2:
        risk = "MEDIUM"

    historical_instability_hints: list[str] = []
    if summary.get("task_source") == "genesis":
        historical_instability_hints.append("genesis_bootstrap_surface")

    confidence = 0.85 if predicted_files else 0.35
    if len(predicted_files) >= 5:
        confidence = 0.72

    return {
        "predicted_files": predicted_files,
        "predicted_validations": predicted_validations,
        "predicted_risk": risk,
        "historical_instability_hints": historical_instability_hints,
        "confidence": confidence,
    }


def score_impact_prediction(
    *,
    prediction: dict[str, Any] | None,
    actual_files_changed: list[str] | None,
    run_status: str | None,
    recovery_count: int = 0,
) -> dict[str, Any]:
    predicted_files = set(_coerce_string_list((prediction or {}).get("predicted_files")))
    actual_files = set(_coerce_string_list(actual_files_changed))
    overlap = predicted_files & actual_files

    precision = (len(overlap) / len(predicted_files)) if predicted_files else 0.0
    recall = (len(overlap) / len(actual_files)) if actual_files else 0.0

    regression_signals = []
    if str(run_status or "").upper() == "FAILED":
        regression_signals.append("run_failed")
    if recovery_count > 0:
        regression_signals.append("recovery_invoked")

    return {
        "predicted_files": sorted(predicted_files),
        "actual_files_changed": sorted(actual_files),
        "overlap_files": sorted(overlap),
        "precision": round(precision * 100.0, 2),
        "recall": round(recall * 100.0, 2),
        "recovery_count": recovery_count,
        "regression_signals": regression_signals,
    }
