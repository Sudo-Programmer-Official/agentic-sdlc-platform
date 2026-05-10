from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIJobRun, ProjectBlueprint, ProjectGenesisRun, ProjectTopologySnapshot, Run


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 2)


def _fingerprint_topology(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return "none"
    material = {
        "blueprint_key": payload.get("blueprint_key"),
        "directories": payload.get("directories"),
        "modules": payload.get("modules"),
        "contracts": payload.get("contracts"),
        "stack_preset_key": payload.get("stack_preset_key"),
        "deployment_profile": payload.get("deployment_profile"),
    }
    digest = hashlib.sha1(str(material).encode("utf-8")).hexdigest()
    return digest


async def build_governance_kpis(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> dict[str, Any]:
    blueprint = await session.scalar(
        select(ProjectBlueprint).where(ProjectBlueprint.tenant_id == tenant_id, ProjectBlueprint.project_id == project_id)
    )
    genesis_runs = (
        await session.execute(
            select(ProjectGenesisRun).where(
                ProjectGenesisRun.tenant_id == tenant_id,
                ProjectGenesisRun.project_id == project_id,
            )
        )
    ).scalars().all()
    snapshots = (
        await session.execute(
            select(ProjectTopologySnapshot).where(
                ProjectTopologySnapshot.tenant_id == tenant_id,
                ProjectTopologySnapshot.project_id == project_id,
            )
        )
    ).scalars().all()
    runs = (
        await session.execute(
            select(Run).where(
                Run.tenant_id == tenant_id,
                Run.project_id == project_id,
            )
        )
    ).scalars().all()
    ai_jobs = (
        await session.execute(
            select(AIJobRun).where(
                AIJobRun.tenant_id == tenant_id,
                AIJobRun.project_id == project_id,
            )
        )
    ).scalars().all()

    genesis_completed = sum(1 for row in genesis_runs if str(row.status).upper() == "COMPLETED")
    genesis_success_rate = _pct(genesis_completed, len(genesis_runs))

    fingerprints = Counter(_fingerprint_topology(row.topology_json if isinstance(row.topology_json, dict) else None) for row in snapshots)
    deterministic_replay_match = _pct(max(fingerprints.values()) if fingerprints else 0, len(snapshots))

    non_genesis_feature_runs = 0
    for run in runs:
        summary = run.summary if isinstance(run.summary, dict) else {}
        source = str(summary.get("task_source") or "").strip().lower()
        run_kind = str(summary.get("run_kind") or "").strip().lower()
        if source == "genesis" or run_kind in {"genesis", "genesis_setup", "setup"}:
            continue
        non_genesis_feature_runs += 1
    has_any_genesis = len(genesis_runs) > 0
    feature_runs_without_genesis = non_genesis_feature_runs if not has_any_genesis else 0

    context_pack_jobs = 0
    loaded_total = 0
    selected_total = 0
    for job in ai_jobs:
        details = job.details_json if isinstance(job.details_json, dict) else {}
        context_pack = details.get("context_pack")
        if isinstance(context_pack, dict):
            context_pack_jobs += 1
            metadata = context_pack.get("metadata") if isinstance(context_pack.get("metadata"), dict) else {}
            loaded_total += int(metadata.get("context_loaded_count") or 0)
            selected_total += int(metadata.get("context_selected_count") or 0)
    context_pack_usage = _pct(context_pack_jobs, len(ai_jobs))
    context_efficiency_ratio = round((selected_total / loaded_total), 4) if loaded_total > 0 else 0.0

    return {
        "project_id": str(project_id),
        "blueprint_present": blueprint is not None,
        "genesis_success_rate": genesis_success_rate,
        "deterministic_replay_match": deterministic_replay_match,
        "feature_runs_without_genesis": feature_runs_without_genesis,
        "context_pack_usage": context_pack_usage,
        "context_efficiency_ratio": context_efficiency_ratio,
        "context_loaded_count": loaded_total,
        "context_selected_count": selected_total,
        "sample_sizes": {
            "genesis_runs": len(genesis_runs),
            "topology_snapshots": len(snapshots),
            "feature_runs": non_genesis_feature_runs,
            "ai_jobs": len(ai_jobs),
        },
    }
