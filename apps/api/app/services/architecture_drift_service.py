from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DriftSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class DriftViolation:
    code: str
    message: str
    severity: DriftSeverity


def _first_package_by_kind(profile_json: dict[str, Any], kind: str) -> str | None:
    repo_layout = profile_json.get("repo_layout")
    if not isinstance(repo_layout, dict):
        return None
    packages = repo_layout.get("packages")
    if not isinstance(packages, list):
        return None
    for package in packages:
        if not isinstance(package, dict):
            continue
        if package.get("kind") != kind:
            continue
        name = package.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _coerce_integrations(profile_json: dict[str, Any]) -> list[dict[str, Any]]:
    raw = profile_json.get("integrations")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _richness(entry: dict[str, Any]) -> int:
    score = 0
    for value in entry.values():
        if isinstance(value, str) and value.strip():
            score += 1
        elif isinstance(value, bool):
            score += 1
    return score


def _canonical_integrations(profile_json: dict[str, Any]) -> list[dict[str, Any]]:
    integrations = _coerce_integrations(profile_json)
    by_name: dict[str, dict[str, Any]] = {}
    for item in integrations:
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        key = name.strip()
        prev = by_name.get(key)
        if prev is None or _richness(item) >= _richness(prev):
            by_name[key] = dict(item)

    repo = by_name.get("repository", {"name": "repository", "provider": None, "repo_full_name": None, "default_branch": None})
    preview = by_name.get("preview", {"name": "preview", "mode": None, "frontend_root": None, "backend_root": None})

    inferred_frontend = _first_package_by_kind(profile_json, "frontend")
    inferred_backend = _first_package_by_kind(profile_json, "backend")
    if not preview.get("frontend_root") and inferred_frontend:
        preview["frontend_root"] = inferred_frontend
    if not preview.get("backend_root") and inferred_backend:
        preview["backend_root"] = inferred_backend
    return [repo, preview]


def _canonical_environment_assumptions(profile_json: dict[str, Any], integrations: list[dict[str, Any]]) -> dict[str, Any]:
    assumptions = profile_json.get("environment_assumptions")
    current = dict(assumptions) if isinstance(assumptions, dict) else {}
    repo = next((item for item in integrations if item.get("name") == "repository"), {})
    preview = next((item for item in integrations if item.get("name") == "preview"), {})
    return {
        "repo_connected": bool(repo.get("provider")),
        "preview_profile_configured": bool(preview.get("mode")),
        "frontend_root": preview.get("frontend_root") or current.get("frontend_root") or _first_package_by_kind(profile_json, "frontend"),
        "backend_root": preview.get("backend_root") or current.get("backend_root") or _first_package_by_kind(profile_json, "backend"),
    }


def _canonical_release_flow(profile_json: dict[str, Any], integrations: list[dict[str, Any]]) -> dict[str, Any]:
    release = profile_json.get("release_flow")
    current = dict(release) if isinstance(release, dict) else {}
    repo = next((item for item in integrations if item.get("name") == "repository"), {})
    preview = next((item for item in integrations if item.get("name") == "preview"), {})
    return {
        **current,
        "default_branch": repo.get("default_branch") or current.get("default_branch") or "main",
        "preview_mode": preview.get("mode") if preview.get("mode") is not None else current.get("preview_mode"),
    }


def generate_canonical_contract_patch(profile_json: dict[str, Any]) -> dict[str, Any]:
    integrations = _canonical_integrations(profile_json)
    assumptions = _canonical_environment_assumptions(profile_json, integrations)
    release_flow = _canonical_release_flow(profile_json, integrations)
    return {
        "integrations": integrations,
        "environment_assumptions": assumptions,
        "release_flow": release_flow,
    }


def detect_architecture_drift(profile_json: dict[str, Any]) -> dict[str, Any]:
    patch = generate_canonical_contract_patch(profile_json)
    warnings: list[str] = []
    violations: list[DriftViolation] = []
    fixes: list[dict[str, Any]] = []

    existing_integrations = _coerce_integrations(profile_json)
    repo_entries = [item for item in existing_integrations if item.get("name") == "repository"]
    preview_entries = [item for item in existing_integrations if item.get("name") == "preview"]
    if len(repo_entries) > 1:
        warnings.append("Multiple repository integration entries detected.")
        violations.append(
            DriftViolation(
                code="duplicate_repository_integrations",
                message="More than one repository integration entry exists.",
                severity=DriftSeverity.MEDIUM,
            )
        )
    if len(preview_entries) > 1:
        warnings.append("Multiple preview integration entries detected.")
        violations.append(
            DriftViolation(
                code="duplicate_preview_integrations",
                message="More than one preview integration entry exists.",
                severity=DriftSeverity.MEDIUM,
            )
        )

    for key in ("integrations", "environment_assumptions", "release_flow"):
        current = profile_json.get(key)
        target = patch.get(key)
        if current != target:
            fixes.append({"field": key, "from": current, "to": target})

    severity = DriftSeverity.LOW
    if any(v.severity == DriftSeverity.CRITICAL for v in violations):
        severity = DriftSeverity.CRITICAL
    elif any(v.severity == DriftSeverity.HIGH for v in violations):
        severity = DriftSeverity.HIGH
    elif any(v.severity == DriftSeverity.MEDIUM for v in violations):
        severity = DriftSeverity.MEDIUM
    elif fixes:
        severity = DriftSeverity.LOW

    return {
        "warnings": warnings,
        "violations": [
            {"code": v.code, "message": v.message, "severity": v.severity.value}
            for v in violations
        ],
        "fixes": fixes,
        "severity": severity.value,
    }
