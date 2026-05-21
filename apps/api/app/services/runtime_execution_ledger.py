from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CostLedger, PatchLedger, RecoveryLedger, Run, RunLedger, StageLedger, WorkItem
from app.services.execution_intelligence import capture_post_run_estimation_outcome


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _duration_ms(started_at: datetime | None, finished_at: datetime | None) -> int | None:
    if started_at is None or finished_at is None:
        return None
    return max(0, int((finished_at - started_at).total_seconds() * 1000))


def _patch_metrics_from_payload(payload: dict[str, Any]) -> tuple[int, int, int]:
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    files_touched = len([item for item in files if isinstance(item, str)])
    lines_added = _as_int(payload.get("lines_added"))
    lines_removed = _as_int(payload.get("lines_removed"))
    return files_touched, lines_added, lines_removed


def _targeting_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    targeting_evidence = payload.get("targeting_evidence") if isinstance(payload.get("targeting_evidence"), dict) else {}
    selected_existing = targeting_evidence.get("selected_existing_files") if isinstance(targeting_evidence.get("selected_existing_files"), list) else []
    reason_map = (
        targeting_evidence.get("selected_existing_reason_map")
        if isinstance(targeting_evidence.get("selected_existing_reason_map"), dict)
        else {}
    )
    top_ranked = targeting_evidence.get("top_ranked_candidates") if isinstance(targeting_evidence.get("top_ranked_candidates"), list) else []
    neighbor_files = targeting_evidence.get("neighbor_files") if isinstance(targeting_evidence.get("neighbor_files"), list) else []
    target_files = payload.get("target_files") if isinstance(payload.get("target_files"), list) else []
    explicit_target_count = len([item for item in target_files if isinstance(item, str)])
    existing_target_count = len([item for item in selected_existing if isinstance(item, str)])
    reuse_ratio = 0.0 if explicit_target_count <= 0 else round(min(1.0, existing_target_count / max(1, explicit_target_count)), 4)
    primary_selected = next((item for item in selected_existing if isinstance(item, str)), None)
    primary_reasons = (
        reason_map.get(primary_selected)
        if primary_selected is not None and isinstance(reason_map.get(primary_selected), list)
        else []
    )
    ranked_scores = [
        float(item.get("score"))
        for item in top_ranked
        if isinstance(item, dict) and isinstance(item.get("score"), (int, float))
    ]
    primary_target_score = ranked_scores[0] if ranked_scores else None
    runner_up_target_score = ranked_scores[1] if len(ranked_scores) > 1 else None
    targeting_confidence_delta = (
        round(primary_target_score - runner_up_target_score, 4)
        if primary_target_score is not None and runner_up_target_score is not None
        else None
    )
    targeting_confidence_label = None
    if targeting_confidence_delta is not None:
        if targeting_confidence_delta >= 4:
            targeting_confidence_label = "decisive"
        elif targeting_confidence_delta >= 2:
            targeting_confidence_label = "moderate"
        else:
            targeting_confidence_label = "close"
    return {
        "targeting_strategy": str(payload.get("targeting_strategy") or "") or None,
        "target_file_count": explicit_target_count,
        "selected_existing_files_count": existing_target_count,
        "neighbor_files_count": len([item for item in neighbor_files if isinstance(item, str)]),
        "component_reuse_preferred": bool(payload.get("component_reuse_preferred")),
        "module_reuse_preferred": bool(payload.get("module_reuse_preferred")),
        "reuse_ratio": reuse_ratio,
        "primary_targeting_reasons": [str(item) for item in primary_reasons if isinstance(item, str)],
        "primary_target_score": primary_target_score,
        "runner_up_target_score": runner_up_target_score,
        "targeting_confidence_delta": targeting_confidence_delta,
        "targeting_confidence_label": targeting_confidence_label,
        "selected_existing_reason_map": {
            str(path): [str(item) for item in reasons if isinstance(item, str)]
            for path, reasons in reason_map.items()
            if isinstance(path, str) and isinstance(reasons, list)
        },
        "top_ranked_candidates": [
            item for item in top_ranked
            if isinstance(item, dict)
        ][:5],
    }


async def _load_work_item(session: AsyncSession, work_item_id: uuid.UUID | None) -> WorkItem | None:
    if work_item_id is None:
        return None
    return await session.get(WorkItem, work_item_id)


async def project_runtime_ledger_from_event(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    work_item_id: uuid.UUID | None,
    event_type: str,
    payload: dict[str, Any] | None,
) -> None:
    event_payload = payload if isinstance(payload, dict) else {}
    work_item = await _load_work_item(session, work_item_id)
    stage_name = work_item.type if work_item is not None else "RUN"

    if event_type in {"WORK_ITEM_CLAIMED", "WORK_ITEM_RETRIED"}:
        session.add(
            StageLedger(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                work_item_id=work_item_id,
                stage_name=stage_name,
                lifecycle_state="CLAIMED" if event_type == "WORK_ITEM_CLAIMED" else "RETRIED",
                started_at=work_item.started_at if work_item else None,
                retries=work_item.attempt if work_item else 0,
                recovery_count=_as_int((work_item.result or {}).get("recovery_attempts")) if work_item else 0,
                payload=event_payload,
            )
        )
    elif event_type in {"WORK_ITEM_DONE", "WORK_ITEM_FAILED", "WORK_ITEM_SKIPPED"} and work_item is not None:
        files_touched, lines_added, lines_removed = _patch_metrics_from_payload(work_item.result or {})
        targeting_meta = _targeting_metrics(work_item.payload or {})
        lifecycle_state = "DONE" if event_type == "WORK_ITEM_DONE" else "FAILED" if event_type == "WORK_ITEM_FAILED" else "SKIPPED"
        session.add(
            StageLedger(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                work_item_id=work_item_id,
                stage_name=stage_name,
                lifecycle_state=lifecycle_state,
                started_at=work_item.started_at,
                finished_at=work_item.finished_at,
                duration_ms=_duration_ms(work_item.started_at, work_item.finished_at),
                retries=work_item.attempt,
                recovery_count=_as_int((work_item.result or {}).get("recovery_attempts")),
                model_tier=str((work_item.result or {}).get("selected_model_tier") or "") or None,
                files_touched=files_touched,
                lines_added=lines_added,
                lines_removed=lines_removed,
                package_affinity=str((work_item.payload or {}).get("package_affinity") or "") or None,
                layer_affinity=str((work_item.payload or {}).get("layer_affinity") or "") or None,
                topology_zone=str((work_item.result or {}).get("execution_zone") or "") or None,
                architecture_compliance_score=_as_float((work_item.result or {}).get("architecture_compliance_score"), None),
                payload={**event_payload, **targeting_meta},
            )
        )
        prompt_tokens = _as_int((work_item.result or {}).get("input_tokens"))
        completion_tokens = _as_int((work_item.result or {}).get("output_tokens"))
        estimated_cost_cents = _as_float((work_item.result or {}).get("estimated_cost_cents"))
        if prompt_tokens or completion_tokens or estimated_cost_cents:
            session.add(
                CostLedger(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=run_id,
                    work_item_id=work_item_id,
                    stage_name=stage_name,
                    feature_key=str((work_item.payload or {}).get("feature_key") or "") or None,
                    capability_key=str((work_item.payload or {}).get("capability_key") or "") or None,
                    model_tier=str((work_item.result or {}).get("selected_model_tier") or "") or None,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    estimated_cost_cents=estimated_cost_cents,
                    wall_clock_ms=_duration_ms(work_item.started_at, work_item.finished_at),
                    execution_time_ms=_duration_ms(work_item.started_at, work_item.finished_at),
                    preview_cost_units=1 if stage_name == "PREVIEW_VALIDATE" else 0,
                    recovery_amplification_pct=_as_float((work_item.result or {}).get("recovery_amplification_pct")),
                    payload={**event_payload, **targeting_meta},
                )
            )
        if files_touched or lines_added or lines_removed:
            session.add(
                PatchLedger(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=run_id,
                    work_item_id=work_item_id,
                    stage_name=stage_name,
                    files_touched=files_touched,
                    lines_added=lines_added,
                    lines_removed=lines_removed,
                    patch_entropy=_as_float((work_item.result or {}).get("patch_entropy"), None),
                    monolith_risk=_as_float((work_item.result or {}).get("monolith_risk"), None),
                    drift_risk=_as_float((work_item.result or {}).get("drift_risk_score"), None),
                    package_affinity=str((work_item.payload or {}).get("package_affinity") or "") or None,
                    layer_affinity=str((work_item.payload or {}).get("layer_affinity") or "") or None,
                    topology_zone=str((work_item.result or {}).get("execution_zone") or "") or None,
                    architecture_compliance_score=_as_float((work_item.result or {}).get("architecture_compliance_score"), None),
                    risk_score=_as_float((work_item.result or {}).get("risk_score"), None),
                    payload={**event_payload, **targeting_meta},
                )
            )

    if event_type in {"WORK_ITEM_RECOVERY", "RUN_CONVERGENCE_STOPPED"}:
        session.add(
            RecoveryLedger(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                work_item_id=work_item_id,
                stage_name=stage_name if work_item else None,
                failure_type=str(event_payload.get("failure_class") or event_payload.get("failure_type") or "") or None,
                recovery_action=str(event_payload.get("recovery_action") or "") or None,
                replay_count=_as_int(event_payload.get("replay_count")),
                convergence_count=_as_int(event_payload.get("same_failure_signature_count")),
                no_progress_retry_count=_as_int(event_payload.get("no_progress_retry_count")),
                recovery_waste_cost_cents=_as_float(event_payload.get("recovery_waste_cost_cents")),
                payload=event_payload,
            )
        )

    if event_type in {"RUN_COMPLETED", "RUN_FAILED", "RUN_DEGRADED", "RUN_CANCELED"}:
        await append_run_aggregate_snapshot(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            event_type=event_type,
        )


async def append_run_aggregate_snapshot(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    event_type: str = "RUN_AGGREGATE_SNAPSHOT",
) -> None:
    await session.flush()
    run = await session.get(Run, run_id)
    if run is None:
        return
    total_cost = (
        await session.scalar(
            select(func.coalesce(func.sum(CostLedger.estimated_cost_cents), 0.0)).where(
                CostLedger.run_id == run_id,
                CostLedger.tenant_id == tenant_id,
            )
        )
    ) or 0.0
    total_duration = (
        await session.scalar(
            select(func.coalesce(func.sum(StageLedger.duration_ms), 0)).where(
                StageLedger.run_id == run_id,
                StageLedger.tenant_id == tenant_id,
            )
        )
    ) or 0
    recovery_events = (
        await session.scalar(select(func.count()).where(RecoveryLedger.run_id == run_id, RecoveryLedger.tenant_id == tenant_id))
    ) or 0
    preview_failures = (
        await session.scalar(
            select(func.count()).where(
                StageLedger.run_id == run_id,
                StageLedger.tenant_id == tenant_id,
                StageLedger.stage_name == "PREVIEW_VALIDATE",
                StageLedger.lifecycle_state == "FAILED",
            )
        )
    ) or 0
    drift_events = (
        await session.scalar(
            select(func.count()).where(
                PatchLedger.run_id == run_id,
                PatchLedger.tenant_id == tenant_id,
                PatchLedger.drift_risk.is_not(None),
                PatchLedger.drift_risk > 0.6,
            )
        )
    ) or 0
    recovery_cost = (
        await session.scalar(
            select(func.coalesce(func.sum(RecoveryLedger.recovery_waste_cost_cents), 0.0)).where(
                RecoveryLedger.run_id == run_id,
                RecoveryLedger.tenant_id == tenant_id,
            )
        )
    ) or 0.0
    overhead = 0.0 if total_cost <= 0 else round((recovery_cost / total_cost) * 100.0, 3)
    stage_rows = (
        await session.execute(select(StageLedger).where(StageLedger.run_id == run_id, StageLedger.tenant_id == tenant_id))
    ).scalars().all()
    patch_rows = (
        await session.execute(select(PatchLedger).where(PatchLedger.run_id == run_id, PatchLedger.tenant_id == tenant_id))
    ).scalars().all()
    targeted_stage_rows = [
        row for row in stage_rows
        if isinstance(row.payload, dict) and row.payload.get("targeting_strategy")
    ]
    targeted_count = len(targeted_stage_rows)
    component_reuse_count = sum(1 for row in targeted_stage_rows if bool((row.payload or {}).get("component_reuse_preferred")))
    module_reuse_count = sum(1 for row in targeted_stage_rows if bool((row.payload or {}).get("module_reuse_preferred")))
    avg_reuse_ratio = round(
        sum(float((row.payload or {}).get("reuse_ratio") or 0.0) for row in targeted_stage_rows) / max(1, targeted_count),
        4,
    ) if targeted_count else 0.0
    package_drift_count = sum(
        1
        for row in patch_rows
        if row.package_affinity and row.files_touched > 0 and (row.package_affinity not in {"apps/web", "apps/api", "frontend", "backend"})
    )
    monolith_risk_max = max((float(row.monolith_risk or 0.0) for row in patch_rows), default=0.0)
    confidence_deltas = [
        float((row.payload or {}).get("targeting_confidence_delta"))
        for row in targeted_stage_rows
        if isinstance((row.payload or {}).get("targeting_confidence_delta"), (int, float))
    ]
    avg_targeting_confidence_delta = round(
        sum(confidence_deltas) / max(1, len(confidence_deltas)),
        4,
    ) if confidence_deltas else 0.0
    decisive_targeting_count = sum(
        1 for row in targeted_stage_rows
        if str((row.payload or {}).get("targeting_confidence_label") or "") == "decisive"
    )
    moderate_targeting_count = sum(
        1 for row in targeted_stage_rows
        if str((row.payload or {}).get("targeting_confidence_label") or "") == "moderate"
    )
    close_targeting_count = sum(
        1 for row in targeted_stage_rows
        if str((row.payload or {}).get("targeting_confidence_label") or "") == "close"
    )
    preview_attempts = sum(1 for row in stage_rows if row.stage_name == "PREVIEW_VALIDATE")
    preview_successes = sum(1 for row in stage_rows if row.stage_name == "PREVIEW_VALIDATE" and row.lifecycle_state == "DONE")
    preview_continuity_score = round(preview_successes / max(1, preview_attempts), 4) if preview_attempts else 0.0
    row = RunLedger(
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=run_id,
        event_type=event_type,
        feature_key=str((run.summary or {}).get("feature_key") or "") if isinstance(run.summary, dict) else None,
        capability_key=str((run.summary or {}).get("capability_key") or "") if isinstance(run.summary, dict) else None,
        customer_key=str((run.summary or {}).get("customer_key") or "") if isinstance(run.summary, dict) else None,
        total_cost_cents=float(total_cost),
        total_duration_ms=int(total_duration),
        recovery_overhead_pct=overhead,
        preview_failures=int(preview_failures),
        drift_events=int(drift_events),
        payload={
            "recovery_event_count": int(recovery_events),
            "targeted_stage_count": targeted_count,
            "component_reuse_ratio": round(component_reuse_count / max(1, targeted_count), 4) if targeted_count else 0.0,
            "module_reuse_ratio": round(module_reuse_count / max(1, targeted_count), 4) if targeted_count else 0.0,
            "avg_reuse_ratio": avg_reuse_ratio,
            "package_drift_count": package_drift_count,
            "monolith_risk_max": round(monolith_risk_max, 4),
            "preview_continuity_score": preview_continuity_score,
            "avg_targeting_confidence_delta": avg_targeting_confidence_delta,
            "decisive_targeting_count": decisive_targeting_count,
            "moderate_targeting_count": moderate_targeting_count,
            "close_targeting_count": close_targeting_count,
        },
    )
    session.add(row)
    await session.flush()
    try:
        await capture_post_run_estimation_outcome(session, run=run, run_ledger=row)
    except ValueError:
        pass
