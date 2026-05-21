from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.architecture_profile_service import bootstrap_architecture_profile, derive_architecture_profile
from app.services.project_genesis import run_project_genesis
from app.services.runtime_template_instantiation import (
    DEFAULT_TEMPLATE_KEY,
    DEFAULT_TEMPLATE_VERSION,
    instantiate_runtime_template,
)


@dataclass(frozen=True)
class RuntimeBootstrapResult:
    template_bootstrap_meta: dict[str, str | int] | None
    template_repo_root: str | None
    contract_derived: bool
    governance_ready: bool


async def bootstrap_project_runtime(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    starter_blueprint_enabled: bool,
    starter_blueprint_key: str,
    starter_stack_preset_key: str,
    starter_deployment_profile: str,
    project_intent: dict[str, Any] | None,
    actor_id: str | None,
) -> RuntimeBootstrapResult:
    template_bootstrap_meta: dict[str, str | int] | None = None
    template_repo_root: str | None = None
    contract_derived = False
    governance_ready = False

    if starter_blueprint_enabled:
        requested_template_key = str(
            ((project_intent or {}).get("template_key") if isinstance(project_intent, dict) else DEFAULT_TEMPLATE_KEY)
            or DEFAULT_TEMPLATE_KEY
        ).strip()
        requested_template_version = int(
            ((project_intent or {}).get("template_version") if isinstance(project_intent, dict) else DEFAULT_TEMPLATE_VERSION)
            or DEFAULT_TEMPLATE_VERSION
        )
        try:
            template_instantiation = instantiate_runtime_template(
                project_id=project_id,
                tenant_id=tenant_id,
                template_key=requested_template_key,
                template_version=requested_template_version,
            )
            template_bootstrap_meta = {
                "template_key": template_instantiation.template_key,
                "template_version": template_instantiation.template_version,
                "template_repo_root": str(template_instantiation.repo_root),
            }
            template_repo_root = str(template_instantiation.repo_root)
        except ValueError:
            template_bootstrap_meta = None
            template_repo_root = None

    if starter_blueprint_enabled:
        try:
            await run_project_genesis(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                blueprint_key=starter_blueprint_key,
                stack_preset_key=starter_stack_preset_key,
                deployment_profile=starter_deployment_profile,
                readiness_enforced=True,
                created_by=actor_id,
            )
            await bootstrap_architecture_profile(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                refresh_repo_map_requested=False,
                created_by=actor_id,
            )
            await derive_architecture_profile(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                refresh_repo_map_requested=False,
                bootstrap_if_missing=True,
                updated_by=actor_id,
            )
            contract_derived = True
            governance_ready = True
        except ValueError:
            # Keep project creation resilient even when starter bootstrap fails.
            pass

    return RuntimeBootstrapResult(
        template_bootstrap_meta=template_bootstrap_meta,
        template_repo_root=template_repo_root,
        contract_derived=contract_derived,
        governance_ready=governance_ready,
    )
