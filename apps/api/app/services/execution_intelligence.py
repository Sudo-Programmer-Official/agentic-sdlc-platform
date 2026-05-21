from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CostLedger,
    EstimationFeatureSnapshot,
    EstimationOutcomeSnapshot,
    PatchLedger,
    RecoveryLedger,
    Run,
    RunLedger,
    StageLedger,
)
from app.schemas.execution_intelligence import (
    TrainingExampleFeaturesOut,
    TrainingExampleLabelsOut,
    TrainingExampleOut,
    TrainingExampleResponse,
)


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


async def capture_pre_run_estimation_features(
    session: AsyncSession,
    *,
    run: Run,
) -> EstimationFeatureSnapshot:
    existing = await session.scalar(
        select(EstimationFeatureSnapshot).where(
            EstimationFeatureSnapshot.run_id == run.id,
            EstimationFeatureSnapshot.tenant_id == run.tenant_id,
            EstimationFeatureSnapshot.snapshot_type == "PRE_RUN",
        )
    )
    if existing is not None:
        return existing

    summary = run.summary if isinstance(run.summary, dict) else {}
    impact = summary.get("impact_prediction") if isinstance(summary.get("impact_prediction"), dict) else {}
    expected_files = summary.get("expected_files") if isinstance(summary.get("expected_files"), list) else []
    expected_stages = summary.get("steps") if isinstance(summary.get("steps"), list) else []
    architecture = summary.get("architecture_profile") if isinstance(summary.get("architecture_profile"), dict) else {}
    stage_count = len([item for item in expected_stages if isinstance(item, dict) or isinstance(item, str)])
    backend_modules = architecture.get("backend_modules") if isinstance(architecture.get("backend_modules"), list) else []
    component_registry = architecture.get("component_registry") if isinstance(architecture.get("component_registry"), list) else []
    row = EstimationFeatureSnapshot(
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        run_id=run.id,
        snapshot_type="PRE_RUN",
        feature_key=str(summary.get("feature_key") or "") or None,
        capability_key=str(summary.get("capability_key") or "") or None,
        customer_key=str(summary.get("customer_key") or "") or None,
        repository_state=str(summary.get("repository_state") or "") or None,
        executor=run.executor,
        expected_stage_count=stage_count,
        expected_files_count=len([item for item in expected_files if isinstance(item, str)]),
        expected_components=len([item for item in component_registry if isinstance(item, str)]),
        expected_backend_modules=len([item for item in backend_modules if isinstance(item, str)]),
        predicted_risk=str(impact.get("risk_tier") or "") or None,
        predicted_cost_min_cents=_as_float(impact.get("estimated_cost_min_cents")),
        predicted_cost_max_cents=_as_float(impact.get("estimated_cost_max_cents")),
        predicted_duration_min_seconds=_as_float(impact.get("estimated_duration_min_seconds")),
        predicted_duration_max_seconds=_as_float(impact.get("estimated_duration_max_seconds")),
        payload={"impact_prediction": impact},
    )
    session.add(row)
    await session.flush()
    return row


async def capture_post_run_estimation_outcome(
    session: AsyncSession,
    *,
    run: Run,
    run_ledger: RunLedger | None,
) -> EstimationOutcomeSnapshot:
    if run.status not in {"COMPLETED", "FAILED", "CANCELED"}:
        # Degraded runs are normalized to COMPLETED/FAILED in runtime status before this write path.
        raise ValueError("outcome snapshots are terminal-state only")
    existing = await session.scalar(
        select(EstimationOutcomeSnapshot).where(
            EstimationOutcomeSnapshot.run_id == run.id,
            EstimationOutcomeSnapshot.tenant_id == run.tenant_id,
            EstimationOutcomeSnapshot.snapshot_type == "POST_RUN",
        )
    )
    if existing is not None:
        return existing

    recovery_events = (
        await session.scalar(select(func.count()).where(RecoveryLedger.run_id == run.id, RecoveryLedger.tenant_id == run.tenant_id))
    ) or 0
    retries = (
        await session.scalar(select(func.coalesce(func.sum(StageLedger.retries), 0)).where(StageLedger.run_id == run.id, StageLedger.tenant_id == run.tenant_id))
    ) or 0
    architecture_compliance = (
        await session.scalar(
            select(func.avg(PatchLedger.architecture_compliance_score)).where(
                PatchLedger.run_id == run.id,
                PatchLedger.tenant_id == run.tenant_id,
                PatchLedger.architecture_compliance_score.is_not(None),
            )
        )
    ) or None
    row = EstimationOutcomeSnapshot(
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        run_id=run.id,
        snapshot_type="POST_RUN",
        run_status=run.status,
        success=run.status == "COMPLETED",
        total_cost_cents=run_ledger.total_cost_cents if run_ledger is not None else 0.0,
        total_duration_ms=run_ledger.total_duration_ms if run_ledger is not None else 0,
        recovery_overhead_pct=run_ledger.recovery_overhead_pct if run_ledger is not None else 0.0,
        preview_failures=run_ledger.preview_failures if run_ledger is not None else 0,
        drift_events=run_ledger.drift_events if run_ledger is not None else 0,
        run_recovery_events=int(recovery_events),
        run_retries=int(retries),
        architecture_compliance_score=_as_float(architecture_compliance),
        payload={},
    )
    session.add(row)
    await session.flush()
    return row


async def build_training_examples(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int = 100,
) -> TrainingExampleResponse:
    outcome_rows = (
        await session.execute(
            select(EstimationOutcomeSnapshot)
            .where(
                EstimationOutcomeSnapshot.tenant_id == tenant_id,
                EstimationOutcomeSnapshot.project_id == project_id,
            )
            .order_by(EstimationOutcomeSnapshot.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    if not outcome_rows:
        return TrainingExampleResponse(items=[], total=0, limit=limit)

    run_ids = [row.run_id for row in outcome_rows]
    feature_rows = (
        await session.execute(
            select(EstimationFeatureSnapshot)
            .where(EstimationFeatureSnapshot.tenant_id == tenant_id, EstimationFeatureSnapshot.run_id.in_(run_ids))
            .order_by(EstimationFeatureSnapshot.created_at.desc())
        )
    ).scalars().all()
    features_by_run: dict[uuid.UUID, EstimationFeatureSnapshot] = {}
    for row in feature_rows:
        if row.run_id not in features_by_run:
            features_by_run[row.run_id] = row

    stage_agg = (
        await session.execute(
            select(
                StageLedger.run_id,
                func.count(StageLedger.id),
                func.coalesce(func.sum(StageLedger.files_touched), 0),
                func.coalesce(func.sum(StageLedger.lines_added), 0),
                func.coalesce(func.sum(StageLedger.lines_removed), 0),
            )
            .where(StageLedger.tenant_id == tenant_id, StageLedger.run_id.in_(run_ids))
            .group_by(StageLedger.run_id)
        )
    ).all()
    stage_by_run = {row[0]: row for row in stage_agg}

    cost_agg = (
        await session.execute(
            select(
                CostLedger.run_id,
                func.coalesce(func.sum(CostLedger.prompt_tokens), 0),
                func.coalesce(func.sum(CostLedger.completion_tokens), 0),
            )
            .where(CostLedger.tenant_id == tenant_id, CostLedger.run_id.in_(run_ids))
            .group_by(CostLedger.run_id)
        )
    ).all()
    cost_by_run = {row[0]: row for row in cost_agg}
    stage_meta = (
        await session.execute(
            select(
                StageLedger.run_id,
                func.max(StageLedger.package_affinity),
                func.max(StageLedger.layer_affinity),
                func.max(StageLedger.topology_zone),
                func.max(StageLedger.model_tier),
            )
            .where(StageLedger.tenant_id == tenant_id, StageLedger.run_id.in_(run_ids))
            .group_by(StageLedger.run_id)
        )
    ).all()
    stage_meta_by_run = {row[0]: row for row in stage_meta}

    items: list[TrainingExampleOut] = []
    for outcome in outcome_rows:
        feature = features_by_run.get(outcome.run_id)
        stage_row = stage_by_run.get(outcome.run_id)
        cost_row = cost_by_run.get(outcome.run_id)
        stage_meta_row = stage_meta_by_run.get(outcome.run_id)
        features = TrainingExampleFeaturesOut(
            task_type=feature.executor if feature else None,
            package_affinity=str(stage_meta_row[1]) if stage_meta_row and stage_meta_row[1] else None,
            layer_affinity=str(stage_meta_row[2]) if stage_meta_row and stage_meta_row[2] else None,
            topology_zone=str(stage_meta_row[3]) if stage_meta_row and stage_meta_row[3] else None,
            target_file_count=feature.expected_files_count if feature else 0,
            model_tier=str(stage_meta_row[4]) if stage_meta_row and stage_meta_row[4] else None,
            feature_key=feature.feature_key if feature else None,
            capability_key=feature.capability_key if feature else None,
            customer_key=feature.customer_key if feature else None,
            repository_state=feature.repository_state if feature else None,
            executor=feature.executor if feature else None,
            expected_stage_count=feature.expected_stage_count if feature else 0,
            expected_files_count=feature.expected_files_count if feature else 0,
            expected_components=feature.expected_components if feature else 0,
            expected_backend_modules=feature.expected_backend_modules if feature else 0,
            predicted_risk=feature.predicted_risk if feature else None,
            predicted_cost_min_cents=feature.predicted_cost_min_cents if feature else None,
            predicted_cost_max_cents=feature.predicted_cost_max_cents if feature else None,
            predicted_duration_min_seconds=feature.predicted_duration_min_seconds if feature else None,
            predicted_duration_max_seconds=feature.predicted_duration_max_seconds if feature else None,
        )
        labels = TrainingExampleLabelsOut(
            run_status=outcome.run_status,
            success=outcome.success,
            total_cost_cents=outcome.total_cost_cents,
            total_duration_ms=outcome.total_duration_ms,
            recovery_overhead_pct=outcome.recovery_overhead_pct,
            recovery_overhead=round(outcome.recovery_overhead_pct / 100.0, 6),
            preview_passed=outcome.preview_failures == 0,
            preview_failures=outcome.preview_failures,
            drift_events=outcome.drift_events,
            run_recovery_events=outcome.run_recovery_events,
            run_retries=outcome.run_retries,
            architecture_compliance_score=outcome.architecture_compliance_score,
        )
        items.append(
            TrainingExampleOut(
                run_id=outcome.run_id,
                project_id=outcome.project_id,
                features=features,
                labels=labels,
                stage_count=int(stage_row[1]) if stage_row else 0,
                total_prompt_tokens=int(cost_row[1]) if cost_row else 0,
                total_completion_tokens=int(cost_row[2]) if cost_row else 0,
                total_files_touched=int(stage_row[2]) if stage_row else 0,
                total_lines_added=int(stage_row[3]) if stage_row else 0,
                total_lines_removed=int(stage_row[4]) if stage_row else 0,
                created_at=outcome.created_at,
            )
        )
    return TrainingExampleResponse(items=items, total=len(items), limit=limit)
