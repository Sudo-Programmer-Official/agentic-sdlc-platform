from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Run, WorkItem
from app.schemas.mission_control import (
    MissionControlExecutionCommand,
    MissionControlExecutionConsoleResponse,
    MissionControlExecutionEnvironment,
    MissionControlExecutionStep,
    MissionControlExecutionSummary,
)
from app.services.execution_contract_telemetry import build_execution_contract_telemetry
from app.services.runtime_env_diagnostics import collect_runtime_startup_diagnostics


def _safe_json_load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _humanize_work_item(work_item: WorkItem) -> str:
    payload = work_item.payload or {}
    for key in ("title", "goal", "label"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if work_item.key:
        return str(work_item.key)
    return str(work_item.type)


def _step_summary(work_item: WorkItem) -> str | None:
    result = work_item.result or {}
    for key in ("message", "stderr", "stdout"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            compact = " ".join(value.split())
            return compact[:220] + ("…" if len(compact) > 220 else "")
    if work_item.last_error:
        compact = " ".join(work_item.last_error.split())
        return compact[:220] + ("…" if len(compact) > 220 else "")
    return None


def _read_log_sections(log_path: str | None, limit: int = 3200) -> tuple[str | None, str | None]:
    if not log_path:
        return None, None
    path = Path(log_path)
    if not path.exists():
        return None, None
    try:
        body = path.read_text(encoding="utf-8")
    except OSError:
        return None, None
    separator = "\n\n--- STDERR ---\n"
    if separator in body:
        stdout, stderr = body.split(separator, 1)
    else:
        stdout, stderr = body, ""
    stdout = stdout[-limit:].strip() or None
    stderr = stderr[-limit:].strip() or None
    return stdout, stderr


def _load_command_records(audit_path: str | None) -> list[dict[str, Any]]:
    if not audit_path:
        return []
    path = Path(audit_path)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _merge_command_audit_records(
    records: list[dict[str, Any]],
    *,
    max_items: int = 8,
) -> list[MissionControlExecutionCommand]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for index, record in enumerate(records):
        command_id = str(record.get("command_id") or f"legacy-{index}")
        current = merged.get(command_id)
        if current is None:
            current = {
                "command_id": command_id,
                "label": record.get("label") or "workspace-command",
                "status": record.get("status") or "UNKNOWN",
                "command": list(record.get("command") or []),
                "cwd": str(record.get("cwd") or ""),
                "started_at": _parse_iso(record.get("started_at")),
                "finished_at": _parse_iso(record.get("finished_at")),
                "duration_ms": record.get("duration_ms"),
                "exit_code": record.get("exit_code"),
                "timed_out": bool(record.get("timed_out")),
                "blocked_reason": record.get("blocked_reason"),
                "log_path": record.get("log_path"),
            }
            merged[command_id] = current
            order.append(command_id)
        else:
            current["label"] = record.get("label") or current["label"]
            current["command"] = list(record.get("command") or current["command"])
            current["cwd"] = str(record.get("cwd") or current["cwd"])
            current["started_at"] = _parse_iso(record.get("started_at")) or current["started_at"]
            current["finished_at"] = _parse_iso(record.get("finished_at")) or current["finished_at"]
            current["duration_ms"] = record.get("duration_ms", current["duration_ms"])
            current["exit_code"] = record.get("exit_code", current["exit_code"])
            current["timed_out"] = bool(record.get("timed_out", current["timed_out"]))
            current["blocked_reason"] = record.get("blocked_reason") or current["blocked_reason"]
            current["log_path"] = record.get("log_path") or current["log_path"]
        current["status"] = record.get("status") or current["status"]

    def sort_key(item: dict[str, Any]) -> tuple[datetime, datetime]:
        started_at = item.get("started_at") or datetime.min
        finished_at = item.get("finished_at") or started_at
        return finished_at, started_at

    commands: list[MissionControlExecutionCommand] = []
    for command_id in sorted(order, key=lambda cid: sort_key(merged[cid]), reverse=True)[:max_items]:
        item = merged[command_id]
        stdout_tail, stderr_tail = _read_log_sections(item.get("log_path"))
        commands.append(
            MissionControlExecutionCommand(
                command_id=item["command_id"],
                label=str(item["label"]),
                status=str(item["status"]),
                command=[str(value) for value in item.get("command") or []],
                cwd=str(item.get("cwd") or ""),
                started_at=item.get("started_at"),
                finished_at=item.get("finished_at"),
                duration_ms=int(item["duration_ms"]) if isinstance(item.get("duration_ms"), int) else None,
                exit_code=int(item["exit_code"]) if isinstance(item.get("exit_code"), int) else None,
                timed_out=bool(item.get("timed_out")),
                blocked_reason=item.get("blocked_reason"),
                log_path=item.get("log_path"),
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            )
        )
    return commands


async def build_run_execution_console(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
) -> MissionControlExecutionConsoleResponse:
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id))
    if run is None:
        raise ValueError("Run not found")

    work_items = (
        await session.execute(
            select(WorkItem)
            .where(WorkItem.run_id == run_id, WorkItem.tenant_id == tenant_id)
            .order_by(WorkItem.created_at.asc(), WorkItem.id.asc())
        )
    ).scalars().all()

    manifest: dict[str, Any] = {}
    manifest_path: Path | None = None
    if run.workspace_root:
        candidate = Path(run.workspace_root) / "context" / "workspace.json"
        if candidate.exists():
            manifest_path = candidate
            manifest = _safe_json_load(candidate)
    settings = get_settings()
    runtime_diagnostics = collect_runtime_startup_diagnostics(settings.runtime_mode, settings.runtime_git_auth_mode)

    environment = MissionControlExecutionEnvironment(
        workspace_root=run.workspace_root,
        repo_path=run.repo_path,
        artifacts_path=str(manifest.get("artifacts_path") or ""),
        logs_path=str(manifest.get("logs_path") or ""),
        patches_path=str(manifest.get("patches_path") or ""),
        branch_name=run.branch_name,
        workspace_status=run.workspace_status,
        repo_seeded=bool(manifest.get("repo_seeded")),
        repo_url=manifest.get("repo_url"),
        repo_branch=manifest.get("repo_branch"),
        repo_auth_mode=manifest.get("repo_auth_mode"),
        simulation_mode=manifest.get("simulation_mode"),
        cleanup_policy=manifest.get("cleanup_policy"),
        command_audit_log=manifest.get("command_audit_log"),
        workspace_manifest_path=str(manifest_path) if manifest_path else None,
        allowed_command_prefixes=[
            str(value) for value in manifest.get("allowed_command_prefixes") or [] if isinstance(value, str)
        ],
        runtime_mode=runtime_diagnostics.runtime_mode,
        runtime_git_auth_mode=runtime_diagnostics.runtime_git_auth_mode,
        runtime_git_auth_status=runtime_diagnostics.runtime_git_auth_status,
        runtime_git_auth_ready=runtime_diagnostics.runtime_git_auth_ready,
        runtime_git_auth_missing=list(runtime_diagnostics.runtime_git_auth_missing),
        git_binary=runtime_diagnostics.git_binary,
        ssh_binary=runtime_diagnostics.ssh_binary,
        github_clone_auth_status=runtime_diagnostics.github_clone_auth_status,
        github_clone_auth_ready=runtime_diagnostics.github_clone_auth_ready,
        github_clone_auth_missing=list(runtime_diagnostics.github_clone_auth_missing),
        github_app_id_present=runtime_diagnostics.github_app_id_present,
        github_private_key_present=runtime_diagnostics.github_private_key_present,
        github_webhook_secret_present=runtime_diagnostics.github_webhook_secret_present,
    )

    commands = _merge_command_audit_records(_load_command_records(environment.command_audit_log))
    active_step = next((wi for wi in work_items if wi.status in {"RUNNING", "CLAIMED"}), None)
    queued_step = next((wi for wi in work_items if wi.status == "QUEUED"), None)
    current_step = active_step or queued_step

    recent_steps = sorted(
        work_items,
        key=lambda wi: (
            0
            if wi.status in {"RUNNING", "CLAIMED"}
            else 1
            if wi.status == "FAILED"
            else 2
            if wi.status in {"DONE", "SKIPPED"}
            else 3,
            wi.started_at or wi.finished_at or wi.updated_at or wi.created_at,
        ),
    )[:8]
    steps = [
        MissionControlExecutionStep(
            work_item_id=wi.id,
            title=_humanize_work_item(wi),
            type=wi.type,
            executor=wi.executor,
            status=wi.status,
            started_at=wi.started_at,
            finished_at=wi.finished_at,
            attempt=wi.attempt,
            summary=_step_summary(wi),
        )
        for wi in recent_steps
    ]

    last_updated_candidates = [run.updated_at]
    for command in commands:
        if command.finished_at:
            last_updated_candidates.append(command.finished_at)
        elif command.started_at:
            last_updated_candidates.append(command.started_at)

    summary = MissionControlExecutionSummary(
        run_id=run.id,
        run_status=run.status,
        workspace_status=run.workspace_status,
        current_step=_humanize_work_item(current_step) if current_step else None,
        current_executor=current_step.executor if current_step else None,
        active_command_count=sum(1 for command in commands if command.status == "RUNNING"),
        last_updated_at=max((value for value in last_updated_candidates if value is not None), default=None),
        execution_contract=build_execution_contract_telemetry(run.summary if isinstance(run.summary, dict) else None),
    )

    return MissionControlExecutionConsoleResponse(
        summary=summary,
        environment=environment,
        commands=commands,
        steps=steps,
    )
