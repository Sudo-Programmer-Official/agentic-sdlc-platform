from __future__ import annotations

import asyncio
import logging
import random
from contextlib import suppress
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import DeploymentProviderConnector, ProjectDeployment
from app.db.session import SessionLocal
from app.services.deployment_executors import resolve_deployment_executor
from app.services.secret_vault import resolve_vault_secret
from app.services.activity_log import log_activity

log = logging.getLogger("app.deployment_runtime")

ACTIVE_STATES = {"QUEUED", "VALIDATING", "PROVISIONING", "BUILDING", "DEPLOYING", "HEALTH_CHECKING"}
ACTIVE_STATES |= {"ROLLBACK_PENDING", "ROLLBACK_RUNNING"}
RETRYABLE_STATES = {"FAILED_VALIDATION", "FAILED_BUILD", "FAILED_DEPLOY", "FAILED_HEALTH_CHECK", "MANUAL_ACTION_REQUIRED"}
TERMINAL_STATES = {"READY", *RETRYABLE_STATES}


async def _probe_url(url: str, timeout_seconds: int) -> tuple[bool, int | None, str | None, str | None]:
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            response = await client.get(url)
        return response.status_code < 500, response.status_code, None, response.text[:512]
    except Exception as exc:  # pragma: no cover - network path best-effort
        return False, None, str(exc), None


def _confidence(ok_root: bool, ok_health: bool, html_hint_ok: bool) -> float:
    score = 0.0
    if ok_root:
        score += 0.4
    if ok_health:
        score += 0.4
    if html_hint_ok:
        score += 0.2
    return round(max(0.0, min(1.0, score)), 3)


async def process_deployments_once() -> None:
    settings = get_settings()
    limit = max(1, int(settings.deployment_runtime_batch_size))
    timeout_seconds = max(2, int(settings.deployment_healthcheck_timeout_seconds))

    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ProjectDeployment)
                .where(ProjectDeployment.status.in_(ACTIVE_STATES))
                .order_by(ProjectDeployment.created_at.asc(), ProjectDeployment.id.asc())
                .limit(limit)
            )
        ).scalars().all()

        for deployment in rows:
            try:
                metadata = dict(deployment.extra_metadata or {})
                status = str(deployment.status or "").upper()
                connector_vault_ref = str(metadata.get("provider_connector_vault_ref") or "").strip()
                if connector_vault_ref:
                    token = resolve_vault_secret(connector_vault_ref)
                    if token:
                        metadata["_provider_token"] = token
                elif metadata.get("provider_connector_id"):
                    connector_id = str(metadata.get("provider_connector_id") or "").strip()
                    try:
                        connector = await session.scalar(
                            select(DeploymentProviderConnector).where(
                                DeploymentProviderConnector.id == connector_id,
                                DeploymentProviderConnector.tenant_id == deployment.tenant_id,
                            )
                        )
                    except Exception:
                        connector = None
                    if connector and connector.vault_ref:
                        token = resolve_vault_secret(connector.vault_ref)
                        if token:
                            metadata["_provider_token"] = token

                if status == "QUEUED":
                    deployment.status = "VALIDATING"
                    deployment.error_message = None
                    await log_activity(
                        session,
                        project_id=deployment.project_id,
                        entity_type="project_deployment",
                        entity_id=deployment.id,
                        action_type="deployment.transition",
                        event_type="DEPLOYMENT_STARTED",
                        metadata={"from": status, "to": deployment.status},
                    )
                    await session.commit()
                    continue

                if status == "ROLLBACK_PENDING":
                    deployment.status = "ROLLBACK_RUNNING"
                    await log_activity(
                        session,
                        project_id=deployment.project_id,
                        entity_type="project_deployment",
                        entity_id=deployment.id,
                        action_type="deployment.rollback.transition",
                        event_type="ROLLBACK_RUNNING",
                        metadata={"from": status, "to": deployment.status},
                    )
                    await session.commit()
                    continue

                if status == "ROLLBACK_RUNNING":
                    deployment.status = "ROLLBACK_SUCCEEDED"
                    deployment.error_message = None
                    await log_activity(
                        session,
                        project_id=deployment.project_id,
                        entity_type="project_deployment",
                        entity_id=deployment.id,
                        action_type="deployment.rollback.transition",
                        event_type="ROLLBACK_SUCCEEDED",
                        metadata={"from": status, "to": deployment.status},
                    )
                    await session.commit()
                    continue

                executor = resolve_deployment_executor(deployment, metadata)

                if status == "VALIDATING":
                    result = await executor.validate(deployment, metadata)
                    deployment.status = result.next_status
                    deployment.error_message = result.error_message
                    await log_activity(
                        session,
                        project_id=deployment.project_id,
                        entity_type="project_deployment",
                        entity_id=deployment.id,
                        action_type="deployment.validation",
                        event_type="DEPLOYMENT_VALIDATED" if result.ok else "DEPLOYMENT_DEGRADED_TO_MANUAL",
                        metadata={"from": status, "to": deployment.status, "error": result.error_message},
                    )
                    await session.commit()
                    continue

                if status == "PROVISIONING":
                    result = await executor.provision(deployment, metadata)
                    deployment.status = result.next_status
                    deployment.error_message = result.error_message
                    await log_activity(
                        session,
                        project_id=deployment.project_id,
                        entity_type="project_deployment",
                        entity_id=deployment.id,
                        action_type="deployment.provision",
                        event_type="PROVIDER_REQUEST_SENT" if result.ok else "DEPLOYMENT_DEGRADED_TO_MANUAL",
                        metadata={"from": status, "to": deployment.status, "error": result.error_message},
                    )
                    await session.commit()
                    continue

                if status == "BUILDING":
                    result = await executor.deploy(deployment, metadata)
                    deployment.status = "DEPLOYING" if result.next_status == "HEALTH_CHECKING" else result.next_status
                    deployment.error_message = result.error_message
                    await log_activity(
                        session,
                        project_id=deployment.project_id,
                        entity_type="project_deployment",
                        entity_id=deployment.id,
                        action_type="deployment.build",
                        event_type="BUILD_STARTED" if result.ok else "BUILD_FAILED",
                        metadata={"from": status, "to": deployment.status, "error": result.error_message},
                    )
                    await session.commit()
                    continue

                if status == "DEPLOYING":
                    deployment.status = "HEALTH_CHECKING"
                    await log_activity(
                        session,
                        project_id=deployment.project_id,
                        entity_type="project_deployment",
                        entity_id=deployment.id,
                        action_type="deployment.transition",
                        event_type="DEPLOYMENT_HEALTH_CHECKING",
                        metadata={"from": status, "to": deployment.status},
                    )
                    await session.commit()
                    continue

                if status == "HEALTH_CHECKING":
                    deployment_url = str(deployment.deployment_url or "").strip()
                    healthcheck_url = str(metadata.get("healthcheck_url") or deployment_url).strip()
                    if not deployment_url:
                        deployment.status = "FAILED_HEALTH_CHECK"
                        deployment.error_message = "Missing deployment URL for health verification."
                        await session.commit()
                        continue

                    retries = max(1, int(settings.deployment_healthcheck_max_retries))
                    ok_root = False
                    root_status = None
                    root_error = None
                    body_sample = None
                    for attempt in range(retries):
                        ok_root, root_status, root_error, body_sample = await _probe_url(deployment_url, timeout_seconds)
                        if ok_root:
                            break
                        await asyncio.sleep(min(2.0, 0.25 * (2**attempt) + random.uniform(0, 0.1)))
                    ok_health = True
                    health_status = None
                    health_error = None
                    if healthcheck_url and healthcheck_url != deployment_url:
                        for attempt in range(retries):
                            ok_health, health_status, health_error, _ = await _probe_url(healthcheck_url, timeout_seconds)
                            if ok_health:
                                break
                            await asyncio.sleep(min(2.0, 0.25 * (2**attempt) + random.uniform(0, 0.1)))

                    metadata["last_health_check_at"] = datetime.now(timezone.utc).isoformat()
                    metadata["last_health_root_status"] = root_status
                    metadata["last_health_endpoint_status"] = health_status
                    html_hint_ok = "<html" in str(body_sample or "").lower() if deployment.deployment_strategy == "static_frontend" else True
                    metadata["last_health_html_hint_ok"] = html_hint_ok
                    if root_error:
                        metadata["last_health_root_error"] = root_error
                    if health_error:
                        metadata["last_health_endpoint_error"] = health_error
                    deployment.extra_metadata = {k: v for k, v in metadata.items() if not str(k).startswith("_")}

                    deployment.deployment_confidence_score = _confidence(ok_root, ok_health, html_hint_ok)
                    if ok_root and ok_health and html_hint_ok:
                        deployment.status = "READY"
                        deployment.error_message = None
                        event = "DEPLOYMENT_READY"
                    else:
                        deployment.status = "FAILED_HEALTH_CHECK"
                        deployment.error_message = "Deployment failed runtime health checks."
                        event = "HEALTH_CHECK_RETRY"
                    await log_activity(
                        session,
                        project_id=deployment.project_id,
                        entity_type="project_deployment",
                        entity_id=deployment.id,
                        action_type="deployment.healthcheck",
                        event_type=event,
                        metadata={
                            "from": status,
                            "to": deployment.status,
                            "root_status": root_status,
                            "health_status": health_status,
                            "confidence": deployment.deployment_confidence_score,
                        },
                    )
                    await session.commit()
                    continue
            except Exception:
                await session.rollback()
                log.exception("Deployment runtime cycle failed deployment_id=%s", deployment.id)


async def run_deployment_runtime_daemon(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    interval = max(5, int(settings.deployment_runtime_interval_seconds))
    while not stop_event.is_set():
        try:
            await process_deployments_once()
        except Exception:
            log.exception("Deployment runtime daemon cycle failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


async def shutdown_deployment_runtime(task: asyncio.Task | None, stop_event: asyncio.Event | None) -> None:
    if stop_event is not None:
        stop_event.set()
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
