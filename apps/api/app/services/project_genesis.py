from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Document,
    Project,
    ProjectBlueprint,
    ProjectGenesisRun,
    ProjectTopologySnapshot,
    StackPreset,
    Task,
)
from app.services.architecture_profile_service import bootstrap_architecture_profile
from app.services.foundation_readiness import build_foundation_readiness
from app.services.project_contract_service import bootstrap_project_contract

BLUEPRINT_KEY_FULLSTACK = "fullstack_monorepo"

DEFAULT_STACK_PRESETS: list[dict[str, Any]] = [
    {
        "key": "vue_fastapi",
        "label": "Vue + FastAPI",
        "runtime": "fullstack",
        "config_json": {
            "frontend": {"framework": "vue", "path": "apps/web"},
            "backend": {"framework": "fastapi", "path": "apps/api"},
            "packages": ["ui", "shared", "config", "types"],
            "ci": "github_actions",
            "deployment": "local_preview",
        },
    },
    {
        "key": "react_node",
        "label": "React + Node",
        "runtime": "fullstack",
        "config_json": {
            "frontend": {"framework": "react", "path": "apps/web"},
            "backend": {"framework": "node", "path": "apps/api"},
            "packages": ["ui", "shared", "config", "types"],
            "ci": "github_actions",
            "deployment": "local_preview",
        },
    },
    {
        "key": "static_html",
        "label": "Static HTML",
        "runtime": "frontend_only",
        "config_json": {
            "frontend": {"framework": "html", "path": "apps/web"},
            "backend": None,
            "packages": ["ui", "config", "types"],
            "ci": "github_actions",
            "deployment": "static_preview",
        },
    },
]


def _topology_template() -> dict[str, Any]:
    return {
        "blueprint_key": BLUEPRINT_KEY_FULLSTACK,
        "directories": [
            "apps/web",
            "apps/api",
            "packages/ui",
            "packages/shared",
            "packages/config",
            "packages/types",
            "infra",
            "docs",
            "requirements",
            "contracts",
        ],
        "modules": [
            "apps/web",
            "apps/api",
            "packages/ui",
            "packages/shared",
        ],
        "contracts": [
            "contracts/project_contract.json",
            "contracts/execution_contract.json",
            "requirements/requirements_graph.md",
        ],
    }


def _genesis_tasks(blueprint_key: str) -> list[dict[str, str]]:
    prefix = f"Genesis ({blueprint_key})"
    return [
        {"title": "initialize monorepo", "description": f"{prefix}: scaffold deterministic monorepo topology."},
        {"title": "initialize frontend", "description": f"{prefix}: initialize frontend app baseline."},
        {"title": "initialize backend", "description": f"{prefix}: initialize backend service baseline."},
        {"title": "initialize contracts", "description": f"{prefix}: initialize project + execution contracts."},
        {"title": "initialize requirements", "description": f"{prefix}: initialize requirements memory and starter graph."},
        {"title": "initialize CI", "description": f"{prefix}: initialize CI template and verification hooks."},
        {
            "title": "initialize deployment profile",
            "description": f"{prefix}: configure deployment profile and preview alignment.",
        },
        {"title": "validate foundation", "description": f"{prefix}: validate readiness before feature execution."},
        {"title": "initialize telemetry", "description": f"{prefix}: configure telemetry baselines and observability."},
    ]


async def ensure_stack_presets(session: AsyncSession, *, tenant_id: uuid.UUID, created_by: str | None = None) -> list[StackPreset]:
    rows = (
        await session.execute(
            select(StackPreset).where(StackPreset.tenant_id == tenant_id).order_by(StackPreset.key.asc())
        )
    ).scalars().all()
    by_key = {row.key: row for row in rows}
    changed = False
    for preset in DEFAULT_STACK_PRESETS:
        if preset["key"] in by_key:
            continue
        row = StackPreset(
            tenant_id=tenant_id,
            key=preset["key"],
            label=preset["label"],
            runtime=preset["runtime"],
            config_json=preset["config_json"],
            created_by=created_by,
        )
        session.add(row)
        rows.append(row)
        changed = True
    if changed:
        await session.flush()
    rows.sort(key=lambda item: item.key)
    return rows


async def get_project_blueprint(session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID) -> ProjectBlueprint | None:
    return await session.scalar(
        select(ProjectBlueprint)
        .where(ProjectBlueprint.tenant_id == tenant_id, ProjectBlueprint.project_id == project_id)
        .order_by(ProjectBlueprint.created_at.desc())
    )


async def get_latest_topology_snapshot(
    session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID
) -> ProjectTopologySnapshot | None:
    return await session.scalar(
        select(ProjectTopologySnapshot)
        .where(ProjectTopologySnapshot.tenant_id == tenant_id, ProjectTopologySnapshot.project_id == project_id)
        .order_by(ProjectTopologySnapshot.version.desc(), ProjectTopologySnapshot.created_at.desc())
    )


async def get_latest_genesis_run(session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID) -> ProjectGenesisRun | None:
    return await session.scalar(
        select(ProjectGenesisRun)
        .where(ProjectGenesisRun.tenant_id == tenant_id, ProjectGenesisRun.project_id == project_id)
        .order_by(ProjectGenesisRun.created_at.desc())
    )


async def run_project_genesis(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    blueprint_key: str,
    stack_preset_key: str,
    deployment_profile: str,
    readiness_enforced: bool,
    created_by: str | None,
) -> tuple[ProjectBlueprint, ProjectTopologySnapshot, ProjectGenesisRun]:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
    if project is None:
        raise ValueError("Project not found")

    presets = await ensure_stack_presets(session, tenant_id=tenant_id, created_by=created_by)
    preset_keys = {preset.key for preset in presets}
    if stack_preset_key not in preset_keys:
        raise ValueError("Unknown stack preset")
    if blueprint_key != BLUEPRINT_KEY_FULLSTACK:
        raise ValueError("Unsupported blueprint key")

    topology = _topology_template()
    topology["stack_preset_key"] = stack_preset_key
    topology["deployment_profile"] = deployment_profile

    blueprint = await get_project_blueprint(session, tenant_id=tenant_id, project_id=project_id)
    if blueprint is None:
        blueprint = ProjectBlueprint(
            tenant_id=tenant_id,
            project_id=project_id,
            blueprint_key=blueprint_key,
            stack_preset_key=stack_preset_key,
            deployment_profile=deployment_profile,
            architecture=BLUEPRINT_KEY_FULLSTACK,
            status="ACTIVE",
            readiness_enforced=readiness_enforced,
            generated_modules=topology["modules"],
            generated_contracts=topology["contracts"],
            metadata_json={"topology_version": 1, "generated_from": "deterministic_template"},
            created_by=created_by,
        )
        session.add(blueprint)
        await session.flush()
    else:
        blueprint.blueprint_key = blueprint_key
        blueprint.stack_preset_key = stack_preset_key
        blueprint.deployment_profile = deployment_profile
        blueprint.status = "ACTIVE"
        blueprint.readiness_enforced = readiness_enforced
        blueprint.generated_modules = topology["modules"]
        blueprint.generated_contracts = topology["contracts"]
        blueprint.metadata_json = {
            **(blueprint.metadata_json if isinstance(blueprint.metadata_json, dict) else {}),
            "topology_version": (blueprint.metadata_json or {}).get("topology_version", 1),
            "generated_from": "deterministic_template",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        session.add(blueprint)
        await session.flush()

    latest_snapshot = await get_latest_topology_snapshot(session, tenant_id=tenant_id, project_id=project_id)
    next_version = 1 if latest_snapshot is None else int(latest_snapshot.version) + 1
    snapshot = ProjectTopologySnapshot(
        tenant_id=tenant_id,
        project_id=project_id,
        blueprint_id=blueprint.id,
        version=next_version,
        topology_json=topology,
        summary="Deterministic topology scaffolded for genesis initialization.",
        created_by=created_by,
    )
    session.add(snapshot)
    await session.flush()

    task_ids: list[str] = []
    for item in _genesis_tasks(blueprint_key):
        task = Task(
            tenant_id=tenant_id,
            project_id=project_id,
            title=item["title"],
            description=item["description"],
            category="setup",
            stage="PLAN",
            status="PENDING",
            source="genesis",
            source_type="genesis_setup",
            requirement_id="genesis.foundation",
            derived_from_requirement_ids=["genesis.foundation"],
            created_by=created_by,
            provenance={
                "genesis": True,
                "blueprint_id": str(blueprint.id),
                "snapshot_id": str(snapshot.id),
                "deterministic": True,
            },
            result_payload={
                "expected_directories": topology["directories"],
                "generated_modules": topology["modules"],
                "generated_contracts": topology["contracts"],
            },
        )
        session.add(task)
        await session.flush()
        task_ids.append(str(task.id))

    existing_prd = await session.scalar(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.project_id == project_id,
            Document.type.in_(["prd", "requirements"]),
        )
    )
    if existing_prd is None:
        starter = Document(
            tenant_id=tenant_id,
            project_id=project_id,
            type="prd",
            title="Genesis Requirements Seed",
            body=(
                "# Genesis Requirements\n\n"
                "- Establish deterministic monorepo baseline.\n"
                "- Enforce foundation readiness before feature runs.\n"
                "- Track setup tasks and lineage in Mission Control.\n"
            ),
            source="genesis",
            created_by=created_by,
            version=1,
        )
        session.add(starter)
        await session.flush()

    await bootstrap_architecture_profile(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        refresh_repo_map_requested=False,
        created_by=created_by,
    )
    await bootstrap_project_contract(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        created_by=created_by,
    )
    readiness = await build_foundation_readiness(session, tenant_id=tenant_id, project_id=project_id)

    genesis_run = ProjectGenesisRun(
        tenant_id=tenant_id,
        project_id=project_id,
        blueprint_id=blueprint.id,
        status="COMPLETED",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        created_task_ids=task_ids,
        validation=readiness,
        summary="Genesis initialization completed with deterministic topology and setup tasks.",
        created_by=created_by,
    )
    session.add(genesis_run)
    await session.flush()

    return blueprint, snapshot, genesis_run
