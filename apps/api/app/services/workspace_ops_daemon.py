from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import (
    AdminAuditLog,
    Project,
    ProjectDeployment,
    Run,
    Workspace,
    WorkspaceAnomalySnapshot,
    WorkspaceUsageDaily,
)
from app.db.session import SessionLocal

log = logging.getLogger("app.workspace_ops")


def _compute_anomaly_flags(daily: list[dict[str, int]]) -> tuple[bool, bool, str | None, str | None]:
    if len(daily) < 4:
        return False, False, None, None
    midpoint = max(1, len(daily) // 2)
    prior = daily[:midpoint]
    recent = daily[midpoint:]
    prior_tokens = sum((row.get("input_tokens") or 0) + (row.get("output_tokens") or 0) for row in prior)
    recent_tokens = sum((row.get("input_tokens") or 0) + (row.get("output_tokens") or 0) for row in recent)
    prior_runs = max(1, sum(row.get("runs_count") or 0 for row in prior))
    recent_runs = max(1, sum(row.get("runs_count") or 0 for row in recent))
    prior_recoveries = sum(row.get("recoveries_count") or 0 for row in prior)
    recent_recoveries = sum(row.get("recoveries_count") or 0 for row in recent)
    prior_recovery_rate = prior_recoveries / prior_runs
    recent_recovery_rate = recent_recoveries / recent_runs
    burn_ratio_value = (recent_tokens / prior_tokens) if prior_tokens > 0 else (2.0 if recent_tokens > 0 else 1.0)
    failure_ratio_value = (
        (recent_recovery_rate / prior_recovery_rate)
        if prior_recovery_rate > 0
        else (2.0 if recent_recovery_rate > 0 else 1.0)
    )
    burn_spike = recent_tokens > prior_tokens * 1.5 and recent_tokens - prior_tokens > 1000
    failure_spike = recent_recovery_rate > prior_recovery_rate * 1.5 and recent_recoveries >= 2
    return burn_spike, failure_spike, f"{burn_ratio_value:.2f}", f"{failure_ratio_value:.2f}"


async def _materialize_workspace_usage_and_anomalies_once(*, window_days: int) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    today = datetime.now(timezone.utc).date()

    async with SessionLocal() as session:
        workspaces = (await session.execute(select(Workspace).order_by(Workspace.created_at.asc()))).scalars().all()
        failure_count = 0
        for workspace in workspaces:
            try:
                project_ids = (
                    await session.execute(
                        select(Project.id).where(
                            Project.tenant_id == workspace.tenant_id,
                            Project.workspace_id == workspace.id,
                        )
                    )
                ).scalars().all()

                run_rows = []
                deployment_rows = []
                if project_ids:
                    run_rows = (
                        await session.execute(
                            select(Run.created_at, Run.summary)
                            .where(
                                Run.tenant_id == workspace.tenant_id,
                                Run.project_id.in_(project_ids),
                                Run.created_at >= since,
                            )
                        )
                    ).all()
                    deployment_rows = (
                        await session.execute(
                            select(ProjectDeployment.created_at)
                            .where(
                                ProjectDeployment.tenant_id == workspace.tenant_id,
                                ProjectDeployment.project_id.in_(project_ids),
                                ProjectDeployment.created_at >= since,
                            )
                        )
                    ).all()

                token_by_day: dict[str, dict[str, int]] = {}
                runs_by_day: dict[str, int] = {}
                deployments_by_day: dict[str, int] = {}
                recoveries_by_day: dict[str, int] = {}
                daily: list[dict[str, int]] = []
                totals = {
                    "runs_count": 0,
                    "recoveries_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_cost_cents": 0,
                }

                for row in run_rows:
                    day = row.created_at.date().isoformat()
                    runs_by_day[day] = runs_by_day.get(day, 0) + 1
                    summary = row.summary if isinstance(row.summary, dict) else {}
                    usage = summary.get("usage") if isinstance(summary.get("usage"), dict) else {}
                    bucket = token_by_day.setdefault(day, {"input_tokens": 0, "output_tokens": 0, "total_cost_cents": 0})
                    bucket["input_tokens"] += int(usage.get("input_tokens") or 0)
                    bucket["output_tokens"] += int(usage.get("output_tokens") or 0)
                    bucket["total_cost_cents"] += int(round(float(usage.get("actual_cost_cents") or 0)))
                    if summary.get("resume_state") or summary.get("last_resume_checkpoint_id") or summary.get("recovery"):
                        recoveries_by_day[day] = recoveries_by_day.get(day, 0) + 1

                for row in deployment_rows:
                    day = row.created_at.date().isoformat()
                    deployments_by_day[day] = deployments_by_day.get(day, 0) + 1

                for offset in range(window_days - 1, -1, -1):
                    day = (datetime.now(timezone.utc) - timedelta(days=offset)).date().isoformat()
                    usage_bucket = token_by_day.get(day, {"input_tokens": 0, "output_tokens": 0, "total_cost_cents": 0})
                    row = {
                        "runs_count": runs_by_day.get(day, 0),
                        "deployments_count": deployments_by_day.get(day, 0),
                        "recoveries_count": recoveries_by_day.get(day, 0),
                        "input_tokens": usage_bucket["input_tokens"],
                        "output_tokens": usage_bucket["output_tokens"],
                        "total_cost_cents": usage_bucket["total_cost_cents"],
                    }
                    daily.append(row)
                    totals["runs_count"] += row["runs_count"]
                    totals["recoveries_count"] += row["recoveries_count"]
                    totals["input_tokens"] += row["input_tokens"]
                    totals["output_tokens"] += row["output_tokens"]
                    totals["total_cost_cents"] += row["total_cost_cents"]

                    usage_date = datetime.fromisoformat(day).date()
                    usage_row = await session.scalar(
                        select(WorkspaceUsageDaily).where(
                            WorkspaceUsageDaily.workspace_id == workspace.id,
                            WorkspaceUsageDaily.tenant_id == workspace.tenant_id,
                            WorkspaceUsageDaily.usage_date == usage_date,
                        )
                    )
                    if usage_row is None:
                        usage_row = WorkspaceUsageDaily(
                            tenant_id=workspace.tenant_id,
                            workspace_id=workspace.id,
                            usage_date=usage_date,
                        )
                        session.add(usage_row)
                    usage_row.runs_count = row["runs_count"]
                    usage_row.deployments_count = row["deployments_count"]
                    usage_row.recoveries_count = row["recoveries_count"]
                    usage_row.input_tokens = row["input_tokens"]
                    usage_row.output_tokens = row["output_tokens"]
                    usage_row.total_cost_cents = row["total_cost_cents"]

                burn_spike, failure_spike, burn_ratio, failure_ratio = _compute_anomaly_flags(daily)
                snapshot = await session.scalar(
                    select(WorkspaceAnomalySnapshot).where(
                        WorkspaceAnomalySnapshot.tenant_id == workspace.tenant_id,
                        WorkspaceAnomalySnapshot.workspace_id == workspace.id,
                        WorkspaceAnomalySnapshot.window_days == window_days,
                        WorkspaceAnomalySnapshot.snapshot_date == today,
                    )
                )
                if snapshot is None:
                    snapshot = WorkspaceAnomalySnapshot(
                        tenant_id=workspace.tenant_id,
                        workspace_id=workspace.id,
                        window_days=window_days,
                        snapshot_date=today,
                    )
                    session.add(snapshot)
                snapshot.runs_count = totals["runs_count"]
                snapshot.recoveries_count = totals["recoveries_count"]
                snapshot.total_tokens = totals["input_tokens"] + totals["output_tokens"]
                snapshot.total_cost_cents = totals["total_cost_cents"]
                snapshot.burn_spike = burn_spike
                snapshot.failure_spike = failure_spike
                snapshot.burn_ratio = burn_ratio
                snapshot.failure_ratio = failure_ratio
                await session.commit()
            except Exception:
                await session.rollback()
                failure_count += 1
                session.add(
                    AdminAuditLog(
                        admin_user_id="system-daemon",
                        target_workspace_id=workspace.id,
                        action="workspace_ops.workspace_error",
                        extra_metadata={"window_days": window_days},
                    )
                )
                await session.commit()
                log.exception("Workspace ops materialization failed workspace_id=%s", workspace.id)
        session.add(
            AdminAuditLog(
                admin_user_id="system-daemon",
                action="workspace_ops.cycle",
                extra_metadata={
                    "window_days": window_days,
                    "workspaces_processed": len(workspaces),
                    "workspace_failures": failure_count,
                },
            )
        )
        await session.commit()


async def run_workspace_ops_daemon(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    interval = max(300, int(settings.workspace_ops_daemon_interval_seconds))
    window_days = max(7, min(90, int(settings.workspace_ops_window_days)))
    while not stop_event.is_set():
        try:
            await _materialize_workspace_usage_and_anomalies_once(window_days=window_days)
        except Exception:
            log.exception("Workspace ops daemon cycle failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


async def shutdown_workspace_ops(task: asyncio.Task | None, stop_event: asyncio.Event | None) -> None:
    if stop_event is not None:
        stop_event.set()
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
