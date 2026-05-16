from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    DeploymentProfile,
    DeploymentProviderConnector,
    EnvironmentSyncStatus,
    EnvironmentValidationResult,
    Project,
    ProjectDeployment,
    ProjectEnvironmentVariable,
    ProjectPreviewProfile,
)
from app.services.secret_vault import resolve_vault_secret


@dataclass
class ReadinessIssue:
    category: str
    message: str


def _normalized_env(value: str | None) -> str:
    env = str(value or "PREVIEW").strip().upper()
    return env if env in {"PREVIEW", "STAGING", "PRODUCTION"} else "PREVIEW"


def _is_success_status(value: str | None) -> bool:
    return str(value or "").strip().upper() in {"READY", "DEPLOYED", "SUCCESS", "COMPLETED", "HEALTHY", "SYNCED", "PASS"}


def _clamp_score(score: float) -> int:
    return max(0, min(100, int(round(score))))


async def compute_deployment_readiness(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    environment: str | None,
) -> dict:
    target_env = _normalized_env(environment)

    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
    if not project:
        raise ValueError("Project not found")

    env_vars = (
        await session.execute(
            select(ProjectEnvironmentVariable).where(
                ProjectEnvironmentVariable.tenant_id == tenant_id,
                ProjectEnvironmentVariable.project_id == project_id,
                ProjectEnvironmentVariable.environment == target_env,
            )
        )
    ).scalars().all()
    required_vars = [row for row in env_vars if bool(row.required)]
    missing_required = [
        row.var_key
        for row in required_vars
        if not bool((row.vault_ref or "").strip() or (row.plain_value or "").strip())
    ]

    validations = (
        await session.execute(
            select(EnvironmentValidationResult).where(
                EnvironmentValidationResult.tenant_id == tenant_id,
                EnvironmentValidationResult.project_id == project_id,
                EnvironmentValidationResult.environment == target_env,
            )
        )
    ).scalars().all()
    latest_validation_by_key: dict[str, EnvironmentValidationResult] = {}
    for row in validations:
        existing = latest_validation_by_key.get(row.check_key)
        if existing is None or row.checked_at > existing.checked_at:
            latest_validation_by_key[row.check_key] = row

    failed_validation_checks = [
        key
        for key in [row.var_key for row in required_vars]
        if key in latest_validation_by_key and str(latest_validation_by_key[key].status or "").lower() != "pass"
    ]
    missing_validation_checks = [key for key in [row.var_key for row in required_vars] if key not in latest_validation_by_key]

    deployment_profile = await session.scalar(
        select(DeploymentProfile).where(
            DeploymentProfile.tenant_id == tenant_id,
            DeploymentProfile.project_id == project_id,
            DeploymentProfile.environment == target_env,
        )
    )
    provider = str(deployment_profile.provider or "").strip().lower() if deployment_profile else ""

    connector = None
    connector_token_ok = False
    if provider:
        connector = await session.scalar(
            select(DeploymentProviderConnector).where(
                DeploymentProviderConnector.tenant_id == tenant_id,
                DeploymentProviderConnector.provider == provider,
            )
        )
        connector_token_ok = bool(connector and connector.vault_ref and resolve_vault_secret(connector.vault_ref))

    sync_status = None
    if provider:
        sync_status = await session.scalar(
            select(EnvironmentSyncStatus).where(
                EnvironmentSyncStatus.tenant_id == tenant_id,
                EnvironmentSyncStatus.project_id == project_id,
                EnvironmentSyncStatus.environment == target_env,
                EnvironmentSyncStatus.provider == provider,
            )
        )

    preview_profile = await session.scalar(
        select(ProjectPreviewProfile).where(
            ProjectPreviewProfile.tenant_id == tenant_id,
            ProjectPreviewProfile.project_id == project_id,
        )
    )

    deployments = (
        await session.execute(
            select(ProjectDeployment).where(
                ProjectDeployment.tenant_id == tenant_id,
                ProjectDeployment.project_id == project_id,
            )
        )
    ).scalars().all()
    env_deployments = [row for row in deployments if str(row.environment or "").upper() == target_env]
    confidence_values = [float(row.deployment_confidence_score or 0.0) for row in env_deployments]
    confidence_score = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0

    has_rollback_path = any(
        _is_success_status(row.status) and bool((row.deployment_url or "").strip())
        for row in deployments
    )

    blockers: list[ReadinessIssue] = []
    warnings: list[ReadinessIssue] = []
    recommended_actions: list[str] = []

    if not deployment_profile:
        blockers.append(ReadinessIssue("DEPLOYMENT", f"{target_env} deployment profile not configured"))
        recommended_actions.append(f"Configure {target_env} deployment profile")
    else:
        if not (deployment_profile.build_command or "").strip() and str(deployment_profile.deployment_strategy or "") != "static_frontend":
            blockers.append(ReadinessIssue("APPLICATION", "Build contract missing (build command not configured)"))
            recommended_actions.append("Configure build command in deployment profile")
        if not (deployment_profile.healthcheck_path or "").strip():
            if target_env == "PRODUCTION":
                blockers.append(ReadinessIssue("OBSERVABILITY", "Health check path missing in deployment profile"))
            else:
                warnings.append(ReadinessIssue("OBSERVABILITY", "Health check path missing in deployment profile"))

    if missing_required:
        for key in missing_required:
            blockers.append(ReadinessIssue("APPLICATION", f"{key} missing"))
        recommended_actions.append("Add missing required environment variables")

    if not provider:
        blockers.append(ReadinessIssue("INFRASTRUCTURE", "Deployment provider not configured"))
        recommended_actions.append("Select a deployment provider")
    elif connector is None:
        blockers.append(ReadinessIssue("INFRASTRUCTURE", f"{provider} connector missing"))
        recommended_actions.append(f"Connect {provider.title()} provider")
    elif not connector_token_ok:
        blockers.append(ReadinessIssue("SECURITY", f"{provider} connector secret invalid or missing"))
        recommended_actions.append(f"Rotate {provider.title()} connector secret")

    if target_env == "PRODUCTION":
        if failed_validation_checks:
            for check in failed_validation_checks:
                blockers.append(ReadinessIssue("APPLICATION", f"Validation failed for {check}"))
            recommended_actions.append("Resolve validation failures and rerun validation")
        if missing_validation_checks:
            blockers.append(ReadinessIssue("APPLICATION", "Validation evidence missing for required variables"))
            recommended_actions.append("Run environment validation")
        if not sync_status or not _is_success_status(sync_status.status) or bool(sync_status.drift_detected):
            blockers.append(ReadinessIssue("DEPLOYMENT", "Provider sync not healthy"))
            recommended_actions.append("Run provider sync and resolve drift")
        if not has_rollback_path:
            blockers.append(ReadinessIssue("DEPLOYMENT", "Rollback path not available"))
            recommended_actions.append("Complete at least one healthy deployment before production promotion")
        if confidence_score < 0.8:
            blockers.append(ReadinessIssue("DEPLOYMENT", "Deployment confidence below threshold (0.80)"))
            recommended_actions.append("Stabilize deployments before production promotion")
    else:
        if failed_validation_checks:
            warnings.append(ReadinessIssue("APPLICATION", f"Validation failed for {', '.join(failed_validation_checks[:3])}"))
        if not sync_status or not _is_success_status(sync_status.status) or bool(sync_status.drift_detected):
            warnings.append(ReadinessIssue("DEPLOYMENT", "Provider sync not healthy yet"))
        if not has_rollback_path:
            warnings.append(ReadinessIssue("DEPLOYMENT", "Rollback path not available yet"))
        if confidence_score < 0.65:
            warnings.append(ReadinessIssue("DEPLOYMENT", "Deployment confidence is low for preview"))

    # Shared rollout clarity signals.
    if preview_profile and target_env == "PRODUCTION":
        if not (preview_profile.frontend_healthcheck_path or "").strip() and not (preview_profile.backend_healthcheck_path or "").strip():
            warnings.append(ReadinessIssue("OBSERVABILITY", "Preview profile health checks not configured"))

    base = 100.0
    base -= 18.0 * len(blockers)
    base -= 6.0 * len(warnings)
    if confidence_score > 0:
        base = (base * 0.7) + (min(1.0, confidence_score) * 100.0 * 0.3)
    score_pct = _clamp_score(base)

    preview_blockers = [
        issue for issue in blockers if issue.category in {"APPLICATION", "INFRASTRUCTURE", "SECURITY", "DEPLOYMENT"}
    ]
    safe_to_preview = len(preview_blockers) == 0 if target_env == "PREVIEW" else len(preview_blockers) == 0
    safe_to_production = target_env == "PRODUCTION" and len(blockers) == 0

    category_map: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"blockers": [], "warnings": []})
    for issue in blockers:
        category_map[issue.category]["blockers"].append(issue.message)
    for issue in warnings:
        category_map[issue.category]["warnings"].append(issue.message)

    return {
        "project_id": project_id,
        "environment": target_env,
        "score_pct": score_pct,
        "safe_to_preview": bool(safe_to_preview),
        "safe_to_production": bool(safe_to_production),
        "blockers": [issue.message for issue in blockers],
        "warnings": [issue.message for issue in warnings],
        "recommended_actions": list(dict.fromkeys(recommended_actions))[:8],
        "confidence_score": round(confidence_score, 4),
        "categories": dict(category_map),
        "evidence": {
            "required_vars_total": len(required_vars),
            "required_vars_missing": len(missing_required),
            "validation_failed": len(failed_validation_checks),
            "validation_missing": len(missing_validation_checks),
            "provider": provider or None,
            "connector_configured": bool(connector),
            "connector_secret_ok": bool(connector_token_ok),
            "sync_status": str(sync_status.status) if sync_status else None,
            "sync_drift_detected": bool(sync_status.drift_detected) if sync_status else None,
            "rollback_path_available": bool(has_rollback_path),
            "healthcheck_ready": bool(deployment_profile and (deployment_profile.healthcheck_path or "").strip()),
        },
    }
