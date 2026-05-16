from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import httpx

from app.db.models import ProjectDeployment


@dataclass
class DeploymentExecutorResult:
    ok: bool
    next_status: str
    error_message: str | None = None


class DeploymentProviderExecutor(Protocol):
    async def validate(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult: ...
    async def provision(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult: ...
    async def deploy(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult: ...
    async def health_check(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult: ...
    async def rollback(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult: ...
    async def fetch_logs(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult: ...


class BootstrapLinkExecutor:
    async def validate(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult:
        repository_url = str(metadata.get("repository_url") or "").strip()
        if deployment.target == "user_app" and not repository_url:
            return DeploymentExecutorResult(False, "FAILED_VALIDATION", "Missing repository URL for deployment target user_app.")
        return DeploymentExecutorResult(True, "PROVISIONING")

    async def provision(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult:
        return DeploymentExecutorResult(
            False,
            "MANUAL_ACTION_REQUIRED",
            "Complete provider import flow, then retry deployment to continue automated verification.",
        )

    async def deploy(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult:
        return DeploymentExecutorResult(False, "MANUAL_ACTION_REQUIRED", "Deployment requires provider handoff completion.")

    async def health_check(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult:
        return DeploymentExecutorResult(False, "MANUAL_ACTION_REQUIRED", "Health verification blocked until managed deployment is connected.")

    async def rollback(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult:
        return DeploymentExecutorResult(False, "MANUAL_ACTION_REQUIRED", "Rollback unavailable in bootstrap-link mode.")

    async def fetch_logs(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult:
        return DeploymentExecutorResult(True, deployment.status)


class ManagedApiExecutor:
    async def _trigger_deploy_hook(self, hook_url: str, payload: dict) -> tuple[bool, dict, str | None]:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.post(hook_url, json=payload)
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            if response.status_code >= 400:
                return False, data if isinstance(data, dict) else {}, f"Provider returned {response.status_code}"
            return True, data if isinstance(data, dict) else {}, None
        except Exception as exc:  # pragma: no cover - network
            return False, {}, str(exc)

    async def _trigger_vercel_api(self, token: str, payload: dict) -> tuple[bool, dict, str | None]:
        try:
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.post("https://api.vercel.com/v13/deployments", headers=headers, json=payload)
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            if response.status_code >= 400:
                return False, data if isinstance(data, dict) else {}, f"Vercel API returned {response.status_code}"
            return True, data if isinstance(data, dict) else {}, None
        except Exception as exc:  # pragma: no cover
            return False, {}, str(exc)

    async def _trigger_render_api(self, token: str, service_id: str) -> tuple[bool, dict, str | None]:
        try:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            url = f"https://api.render.com/v1/services/{service_id}/deploys"
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.post(url, headers=headers, json={"clearCache": "do_not_clear"})
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            if response.status_code >= 400:
                return False, data if isinstance(data, dict) else {}, f"Render API returned {response.status_code}"
            return True, data if isinstance(data, dict) else {}, None
        except Exception as exc:  # pragma: no cover
            return False, {}, str(exc)

    async def validate(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult:
        repository_url = str(metadata.get("repository_url") or "").strip()
        if deployment.target == "user_app" and not repository_url:
            return DeploymentExecutorResult(False, "FAILED_VALIDATION", "Missing repository URL for managed deployment.")
        provider = str(deployment.provider or "").lower()
        token = str(metadata.get("_provider_token") or "").strip()
        if not token:
            return DeploymentExecutorResult(
                False,
                "MANUAL_ACTION_REQUIRED",
                "Missing provider connector secret for managed deployment.",
            )
        return DeploymentExecutorResult(True, "PROVISIONING")

    async def provision(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult:
        return DeploymentExecutorResult(True, "BUILDING")

    async def deploy(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult:
        provider = str(deployment.provider or "").lower()
        if provider not in {"vercel", "render"}:
            return DeploymentExecutorResult(False, "MANUAL_ACTION_REQUIRED", f"Provider {provider} not supported yet.")
        token = str(metadata.get("_provider_token") or "").strip()
        if not token:
            return DeploymentExecutorResult(False, "MANUAL_ACTION_REQUIRED", "Missing provider connector secret for deployment.")

        branch = metadata.get("branch_name") or "main"
        ok = False
        data: dict = {}
        error: str | None = None
        if provider == "vercel":
            repo = str(metadata.get("repository_full_name") or "").strip()
            project_name = str(metadata.get("repository_full_name") or f"project-{deployment.project_id}").split("/")[-1]
            payload = {
                "name": project_name,
                "target": "production" if str(deployment.environment).upper() == "PRODUCTION" else "preview",
                "gitSource": {
                    "type": "github",
                    "repo": repo,
                    "ref": branch,
                },
                "meta": {
                    "agentic_deployment_id": str(deployment.id),
                },
            }
            ok, data, error = await self._trigger_vercel_api(token, payload)
        elif provider == "render":
            service_id = str(metadata.get("render_service_id") or "").strip()
            if not service_id:
                return DeploymentExecutorResult(False, "MANUAL_ACTION_REQUIRED", "Missing render_service_id for managed deployment.")
            ok, data, error = await self._trigger_render_api(token, service_id)

        if not ok:
            return DeploymentExecutorResult(False, "MANUAL_ACTION_REQUIRED", error or "Provider API orchestration failed.")
        external_id = str(data.get("id") or data.get("deploymentId") or data.get("job", {}).get("id") or "").strip()
        possible_url = str(data.get("url") or data.get("deploy_url") or data.get("deploymentUrl") or "").strip()
        if external_id:
            deployment.external_deployment_id = external_id
        if possible_url:
            if possible_url.startswith("http://") or possible_url.startswith("https://"):
                deployment.deployment_url = possible_url
            elif provider == "vercel":
                deployment.deployment_url = f"https://{possible_url.lstrip('/')}"
        metadata["provider_triggered_at"] = datetime.now(timezone.utc).isoformat()
        scrubbed = {k: v for k, v in metadata.items() if not str(k).startswith("_")}
        deployment.extra_metadata = scrubbed
        return DeploymentExecutorResult(True, "HEALTH_CHECKING")

    async def health_check(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult:
        return DeploymentExecutorResult(True, "READY")

    async def rollback(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult:
        return DeploymentExecutorResult(True, "MANUAL_ACTION_REQUIRED")

    async def fetch_logs(self, deployment: ProjectDeployment, metadata: dict) -> DeploymentExecutorResult:
        return DeploymentExecutorResult(True, deployment.status)


def resolve_deployment_executor(deployment: ProjectDeployment, metadata: dict) -> DeploymentProviderExecutor:
    integration_mode = str(metadata.get("integration_mode") or "bootstrap_link").lower()
    if integration_mode == "managed_api":
        return ManagedApiExecutor()
    return BootstrapLinkExecutor()
