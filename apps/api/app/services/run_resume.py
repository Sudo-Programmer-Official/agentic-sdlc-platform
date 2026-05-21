from __future__ import annotations

import hashlib
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, RunCheckpoint, WorkItem
from app.runtime.execution_contract import sync_run_execution_contract_state
from app.services.event_log import record_event
from app.services.repo_connector import get_project_repository
from app.services.workspace_supervisor import ensure_run_workspace
from app.services.work_item_state import is_blocking_failure

DEFAULT_RESUME_VERSION = 1
MAX_RESUME_CHECKPOINTS = 12
SAFE_CHECKPOINT_KINDS = {"baseline", "safe"}
REQUEUEABLE_STATUSES = {"RUNNING", "CLAIMED", "QUEUED", "CANCELED"}
RESUME_MODES = {
    "legacy_auto",
    "retry_failed_step",
    "resume_downstream",
    "replay_with_repair",
    "replay_exact",
    "rollback_and_resume",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summary_payload(run: Run) -> dict[str, Any]:
    return dict(run.summary or {})


def _repo_dir(run: Run) -> Path | None:
    if not run.repo_path:
        return None
    path = Path(run.repo_path)
    if not path.exists():
        return None
    return path


def _workspace_root(run: Run) -> Path | None:
    if not run.workspace_root:
        return None
    path = Path(run.workspace_root)
    if not path.exists():
        return None
    return path


def _checkpoint_dir(run: Run) -> Path | None:
    root = _workspace_root(run)
    if root is None:
        return None
    path = root / "context" / "checkpoints"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_git(repo_dir: Path, args: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_dir),
        input=input_bytes,
        capture_output=True,
        check=False,
    )


def _porcelain_dirty_files(output: str) -> list[str]:
    files: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path.startswith('"') and path.endswith('"') and len(path) >= 2:
            path = path[1:-1]
        if path and path not in files:
            files.append(path)
    return files


def _normalize_checkpoint(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    checkpoint_id = value.get("checkpoint_id")
    if not isinstance(checkpoint_id, str) or not checkpoint_id.strip():
        return None
    return {
        "checkpoint_id": checkpoint_id.strip(),
        "kind": str(value.get("kind") or "safe").strip().lower(),
        "created_at": value.get("created_at"),
        "work_item_id": value.get("work_item_id"),
        "work_item_type": value.get("work_item_type"),
        "work_item_status": value.get("work_item_status"),
        "dirty_files": [item for item in value.get("dirty_files") or [] if isinstance(item, str)],
        "dirty_file_count": int(value.get("dirty_file_count") or 0),
        "patch_path": value.get("patch_path") if isinstance(value.get("patch_path"), str) else None,
        "patch_uri": value.get("patch_uri") if isinstance(value.get("patch_uri"), str) else None,
        "storage_mode": str(value.get("storage_mode") or "metadata_only").strip().lower(),
        "patch_bytes": int(value.get("patch_bytes") or 0),
        "patch_sha256": value.get("patch_sha256") if isinstance(value.get("patch_sha256"), str) else None,
    }


def _checkpoint_from_record(record: RunCheckpoint) -> dict[str, Any]:
    return {
        "checkpoint_id": record.checkpoint_id,
        "kind": (record.kind or "safe").strip().lower(),
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "work_item_id": str(record.work_item_id) if record.work_item_id is not None else None,
        "work_item_type": record.work_item_type,
        "work_item_status": record.work_item_status,
        "dirty_files": [item for item in record.dirty_files if isinstance(item, str)],
        "dirty_file_count": int(record.dirty_file_count or 0),
        "patch_path": record.workspace_patch_path,
        "patch_uri": record.workspace_patch_uri,
        "storage_mode": (record.storage_mode or "metadata_only").strip().lower(),
        "patch_bytes": int(record.patch_bytes or 0),
        "patch_sha256": record.patch_sha256,
    }


async def _load_checkpoint_records(session: AsyncSession, run: Run) -> list[RunCheckpoint]:
    if not hasattr(session, "execute"):
        return []
    result = await session.execute(
        select(RunCheckpoint)
        .where(RunCheckpoint.run_id == run.id)
        .order_by(RunCheckpoint.created_at.asc(), RunCheckpoint.id.asc())
    )
    return result.scalars().all()


def _checkpoint_blob(record: RunCheckpoint | None) -> bytes | None:
    if record is None or record.patch_blob is None:
        return None
    return bytes(record.patch_blob)


def _record_by_checkpoint_id(records: list[RunCheckpoint]) -> dict[str, RunCheckpoint]:
    return {record.checkpoint_id: record for record in records if isinstance(record.checkpoint_id, str) and record.checkpoint_id}


def _merged_checkpoints(summary: dict[str, Any], records: list[RunCheckpoint]) -> list[dict[str, Any]]:
    if records:
        return [_checkpoint_from_record(record) for record in records]
    return _resume_checkpoints(summary)


def _resume_checkpoints(summary: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(summary.get("resume_checkpoints"), list):
        return []
    checkpoints: list[dict[str, Any]] = []
    for raw in summary.get("resume_checkpoints") or []:
        normalized = _normalize_checkpoint(raw)
        if normalized is not None:
            checkpoints.append(normalized)
    return checkpoints


def _latest_safe_checkpoint(checkpoints: list[dict[str, Any]]) -> dict[str, Any] | None:
    for checkpoint in reversed(checkpoints):
        if checkpoint.get("kind") in SAFE_CHECKPOINT_KINDS:
            return checkpoint
    return None


def _failed_error(item: WorkItem | None) -> str | None:
    if item is None:
        return None
    if item.last_error:
        return item.last_error
    result = item.result if isinstance(item.result, dict) else {}
    for key in ("message", "stderr", "stdout"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _sync_summary_checkpoints(summary: dict[str, Any], checkpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trimmed = checkpoints[-MAX_RESUME_CHECKPOINTS:]
    summary["resume_checkpoints"] = trimmed
    return trimmed


async def _ensure_resume_workspace(session: AsyncSession, run: Run) -> bool:
    repo_dir = _repo_dir(run)
    if repo_dir is not None and (repo_dir / ".git").exists():
        return False

    project_repo = await get_project_repository(session, project_id=run.project_id, tenant_id=run.tenant_id)
    if project_repo is None:
        raise RuntimeError(
            "Workspace repository is unavailable for resume and no project repository is configured."
        )

    await ensure_run_workspace(
        session,
        run,
        require_repo=True,
        repo_url=project_repo.repo_url,
        repo_branch=project_repo.default_branch,
        repo_provider=project_repo.provider,
        repo_full_name=project_repo.repo_full_name,
        repo_installation_id=project_repo.installation_id,
        repo_auth_strategy=project_repo.auth_strategy,
        prefer_local_source=False,
    )
    if run.workspace_status == "ERROR":
        raise RuntimeError(run.workspace_error or "Workspace repository could not be rehydrated for resume.")

    refreshed_repo_dir = _repo_dir(run)
    if refreshed_repo_dir is None or not (refreshed_repo_dir / ".git").exists():
        raise RuntimeError("Workspace repository could not be rehydrated for resume.")
    return True


async def capture_run_checkpoint(
    session: AsyncSession,
    run: Run,
    *,
    work_item: WorkItem | None = None,
    checkpoint_kind: str = "safe",
) -> dict[str, Any]:
    summary = _summary_payload(run)
    records = await _load_checkpoint_records(session, run)
    checkpoints = _merged_checkpoints(summary, records)
    repo_dir = _repo_dir(run)
    checkpoint_path = _checkpoint_dir(run)
    dirty_files: list[str] = []
    patch_path: str | None = None
    patch_uri: str | None = None
    patch_blob: bytes | None = None

    if repo_dir is not None and (repo_dir / ".git").exists():
        status_result = _run_git(repo_dir, ["status", "--porcelain"])
        if status_result.returncode == 0:
            dirty_files = _porcelain_dirty_files(status_result.stdout.decode("utf-8", errors="ignore"))

        diff_result = _run_git(repo_dir, ["diff", "--binary", "--no-ext-diff", "HEAD", "--"])
        if diff_result.returncode == 0 and diff_result.stdout:
            patch_blob = bytes(diff_result.stdout)
            if checkpoint_path is not None:
                token = work_item.id.hex[:8] if work_item is not None else "baseline"
                patch_file = checkpoint_path / f"{len(checkpoints) + 1:02d}-{token}.patch"
                patch_file.write_bytes(patch_blob)
                patch_path = str(patch_file)
                if checkpoint_path.parent.parent.exists():
                    relative = patch_file.relative_to(checkpoint_path.parent.parent)
                    patch_uri = f"workspace://context/{relative.as_posix()}"

    patch_sha256 = hashlib.sha256(patch_blob).hexdigest() if patch_blob else None
    patch_bytes = len(patch_blob or b"")
    if patch_blob and patch_path:
        storage_mode = "database+workspace"
    elif patch_blob:
        storage_mode = "database"
    else:
        storage_mode = "metadata_only"
    checkpoint = {
        "checkpoint_id": f"chk-{uuid.uuid4().hex[:12]}",
        "kind": checkpoint_kind.strip().lower() or "safe",
        "created_at": _now_iso(),
        "work_item_id": str(work_item.id) if work_item is not None else None,
        "work_item_type": work_item.type if work_item is not None else None,
        "work_item_status": work_item.status if work_item is not None else None,
        "dirty_files": dirty_files,
        "dirty_file_count": len(dirty_files),
        "patch_path": patch_path,
        "patch_uri": patch_uri,
        "storage_mode": storage_mode,
        "patch_bytes": patch_bytes,
        "patch_sha256": patch_sha256,
    }
    session.add(
        RunCheckpoint(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            run_id=run.id,
            work_item_id=work_item.id if work_item is not None else None,
            checkpoint_id=checkpoint["checkpoint_id"],
            kind=checkpoint["kind"],
            work_item_type=work_item.type if work_item is not None else None,
            work_item_status=work_item.status if work_item is not None else None,
            storage_mode=storage_mode,
            dirty_files=dirty_files,
            dirty_file_count=len(dirty_files),
            patch_blob=patch_blob,
            patch_sha256=patch_sha256,
            patch_bytes=patch_bytes,
            workspace_patch_path=patch_path,
            workspace_patch_uri=patch_uri,
        )
    )
    checkpoints.append(checkpoint)
    _sync_summary_checkpoints(summary, checkpoints)
    run.summary = summary
    session.add(run)
    await session.flush()
    return checkpoint


async def sync_run_resume_state(
    session: AsyncSession,
    run: Run,
    *,
    failed_work_item: WorkItem | None = None,
) -> dict[str, Any]:
    work_items = (
        await session.execute(
            select(WorkItem).where(WorkItem.run_id == run.id).order_by(WorkItem.created_at.asc(), WorkItem.id.asc())
        )
    ).scalars().all()
    summary = _summary_payload(run)
    previous_state = summary.get("resume_state") if isinstance(summary.get("resume_state"), dict) else {}
    checkpoint_records = await _load_checkpoint_records(session, run)
    checkpoints = _merged_checkpoints(summary, checkpoint_records)
    checkpoints = _sync_summary_checkpoints(summary, checkpoints)
    latest_safe = _latest_safe_checkpoint(checkpoints)
    active_items = [item for item in work_items if item.status in {"RUNNING", "CLAIMED"}]
    queued_items = [item for item in work_items if item.status == "QUEUED"]
    canceled_items = [item for item in work_items if item.status == "CANCELED"]
    blocking_failed_items = [item for item in work_items if is_blocking_failure(item)]
    completed_count = sum(1 for item in work_items if item.status in {"DONE", "SKIPPED"})

    if failed_work_item is None:
        failed_work_item = next(
            (
                item
                for item in reversed(work_items)
                if item.status == "FAILED" and is_blocking_failure(item)
            ),
            None,
        )

    if run.status == "PAUSED":
        # Paused runs should be resumable when the workspace is healthy and no item is actively executing.
        can_resume = run.workspace_status != "ERROR" and not active_items
    else:
        can_resume = (
            run.status in {"FAILED", "CANCELED"}
            and run.workspace_status != "ERROR"
            and not active_items
            and latest_safe is not None
        )
    blocked_reason = None
    if run.status not in {"FAILED", "CANCELED", "PAUSED"}:
        blocked_reason = "run_not_terminal"
    elif run.workspace_status == "ERROR":
        blocked_reason = "workspace_error"
    elif active_items:
        blocked_reason = "active_work_items_present"
    elif run.status in {"FAILED", "CANCELED"} and latest_safe is None:
        blocked_reason = "no_safe_checkpoint"

    resume_state = {
        **previous_state,
        "version": DEFAULT_RESUME_VERSION,
        "can_resume": can_resume,
        "resume_blocked_reason": blocked_reason,
        "run_status": run.status,
        "workspace_status": run.workspace_status,
        "last_safe_checkpoint_id": latest_safe.get("checkpoint_id") if latest_safe else None,
        "last_safe_checkpoint_at": latest_safe.get("created_at") if latest_safe else None,
        "last_safe_checkpoint_patch_path": latest_safe.get("patch_path") if latest_safe else None,
        "last_safe_checkpoint_dirty_files": latest_safe.get("dirty_files") if latest_safe else [],
        "last_safe_checkpoint_storage_mode": latest_safe.get("storage_mode") if latest_safe else None,
        "last_safe_checkpoint_patch_bytes": latest_safe.get("patch_bytes") if latest_safe else 0,
        "checkpoint_count": len(checkpoints),
        "durable_checkpoint_count": len(checkpoint_records),
        "active_work_item_ids": [str(item.id) for item in active_items],
        "queued_work_item_ids": [str(item.id) for item in queued_items],
        "blocking_failed_work_item_ids": [str(item.id) for item in blocking_failed_items],
        "canceled_work_item_ids": [str(item.id) for item in canceled_items],
        "completed_work_item_count": completed_count,
        "failed_work_item_id": str(failed_work_item.id) if failed_work_item is not None else None,
        "failed_work_item_type": failed_work_item.type if failed_work_item is not None else None,
        "failed_error": _failed_error(failed_work_item),
        "resume_count": int(previous_state.get("resume_count") or 0),
        "last_synced_at": _now_iso(),
    }
    summary["resume_state"] = resume_state
    run.summary = summary
    session.add(run)
    await session.flush()
    return resume_state


def _restore_workspace_to_checkpoint(
    run: Run,
    checkpoint: dict[str, Any],
    *,
    patch_blob: bytes | None = None,
) -> str:
    repo_dir = _repo_dir(run)
    if repo_dir is None or not (repo_dir / ".git").exists():
        raise RuntimeError("Workspace repository is unavailable for checkpoint restore")

    reset_result = _run_git(repo_dir, ["reset", "--hard", "HEAD"])
    if reset_result.returncode != 0:
        raise RuntimeError(reset_result.stderr.decode("utf-8", errors="ignore").strip() or "git reset failed")

    clean_result = _run_git(repo_dir, ["clean", "-fd"])
    if clean_result.returncode != 0:
        raise RuntimeError(clean_result.stderr.decode("utf-8", errors="ignore").strip() or "git clean failed")

    patch_bytes = patch_blob
    restore_source = "clean_head"
    expected_patch = int(checkpoint.get("patch_bytes") or 0) > 0 or bool(checkpoint.get("patch_sha256"))
    patch_path = checkpoint.get("patch_path")
    if patch_bytes is None and isinstance(patch_path, str) and patch_path.strip():
        patch_file = Path(patch_path)
        if patch_file.exists():
            patch_bytes = patch_file.read_bytes()
            restore_source = "workspace_patch"
    if patch_bytes is None and expected_patch:
        raise RuntimeError("resume checkpoint payload is unavailable")
    if patch_bytes is not None:
        if restore_source == "clean_head":
            restore_source = "database_patch"
        apply_result = _run_git(
            repo_dir,
            ["apply", "--binary", "--whitespace=nowarn", "-"],
            input_bytes=patch_bytes,
        )
        if apply_result.returncode != 0:
            error = apply_result.stderr.decode("utf-8", errors="ignore").strip()
            if not error:
                error = apply_result.stdout.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(error or "git apply failed while restoring checkpoint")
    return restore_source


async def prepare_run_for_resume(
    session: AsyncSession,
    run: Run,
    *,
    actor_type: str = "USER",
    actor_id: str | None = None,
    mode: str = "legacy_auto",
    failed_work_item_id: str | None = None,
    repair_strategy: str | None = None,
    checkpoint_id: str | None = None,
) -> Run:
    mode = str(mode or "legacy_auto").strip().lower()
    if mode not in RESUME_MODES:
        raise ValueError("Unsupported resume mode")
    if run.status not in {"FAILED", "CANCELED", "PAUSED"}:
        raise ValueError("Only failed, canceled, or paused runs can be resumed")

    resume_state = await sync_run_resume_state(session, run)
    if not resume_state.get("can_resume"):
        raise ValueError(str(resume_state.get("resume_blocked_reason") or "Run cannot be resumed"))

    summary = _summary_payload(run)
    checkpoint_records = await _load_checkpoint_records(session, run)
    checkpoints = _merged_checkpoints(summary, checkpoint_records)
    checkpoint = _latest_safe_checkpoint(checkpoints)
    if checkpoint_id:
        requested = str(checkpoint_id).strip()
        checkpoint = next((item for item in checkpoints if str(item.get("checkpoint_id") or "") == requested), None)
        if checkpoint is None:
            raise ValueError("Requested resume checkpoint was not found")
    durable_checkpoint = (
        _record_by_checkpoint_id(checkpoint_records).get(str(checkpoint.get("checkpoint_id") or ""))
        if checkpoint is not None
        else None
    )

    work_items = (
        await session.execute(
            select(WorkItem).where(WorkItem.run_id == run.id).order_by(WorkItem.created_at.asc(), WorkItem.id.asc())
        )
    ).scalars().all()
    by_id = {str(item.id): item for item in work_items}
    if any(item.status in {"RUNNING", "CLAIMED"} for item in work_items):
        raise ValueError("Run still has active work items")

    workspace_rehydrated = False
    restore_source = "paused_continue"
    if run.status in {"FAILED", "CANCELED"} or mode == "rollback_and_resume":
        if checkpoint is None:
            raise ValueError("No safe checkpoint available for resume")
        workspace_rehydrated = await _ensure_resume_workspace(session, run)
        restore_source = _restore_workspace_to_checkpoint(run, checkpoint, patch_blob=_checkpoint_blob(durable_checkpoint))

    failed_blocking = [item for item in work_items if item.status == "FAILED" and is_blocking_failure(item)]
    target_failed: WorkItem | None = None
    if failed_work_item_id:
        target_failed = by_id.get(str(failed_work_item_id).strip())
        if target_failed is None:
            raise ValueError("Requested failed work item was not found")
    elif failed_blocking:
        target_failed = failed_blocking[-1]

    downstream_ids: set[str] = set()
    if target_failed is not None:
        from app.db.models import WorkItemEdge
        edge_rows = (
            await session.execute(
                select(WorkItemEdge.from_work_item_id, WorkItemEdge.to_work_item_id).where(WorkItemEdge.run_id == run.id)
            )
        ).all()
        graph: dict[str, list[str]] = {}
        for src, dst in edge_rows:
            graph.setdefault(str(src), []).append(str(dst))
        queue = [str(target_failed.id)]
        seen = set(queue)
        while queue:
            node = queue.pop(0)
            for child in graph.get(node, []):
                if child in seen:
                    continue
                seen.add(child)
                downstream_ids.add(child)
                queue.append(child)

    requeued_ids: list[str] = []
    for item in work_items:
        should_requeue = item.status in REQUEUEABLE_STATUSES or (item.status == "FAILED" and is_blocking_failure(item))
        if run.status == "PAUSED" and item.status in {"RUNNING", "CLAIMED"}:
            should_requeue = True
        if mode == "retry_failed_step":
            should_requeue = target_failed is not None and str(item.id) == str(target_failed.id)
        elif mode == "resume_downstream":
            should_requeue = str(item.id) in downstream_ids and item.status in {"CANCELED", "QUEUED", "FAILED"}
        elif mode == "replay_with_repair":
            should_requeue = target_failed is not None and str(item.id) == str(target_failed.id)
        elif mode == "replay_exact":
            should_requeue = target_failed is not None and str(item.id) == str(target_failed.id)
        elif mode == "rollback_and_resume":
            should_requeue = item.status in REQUEUEABLE_STATUSES or (item.status == "FAILED" and is_blocking_failure(item))
        if not should_requeue:
            continue
        item.status = "QUEUED"
        item.assigned_agent_id = None
        item.lease_expires_at = None
        item.started_at = None
        item.finished_at = None
        item.last_error = None
        item.result = {}
        if mode == "replay_with_repair" and target_failed is not None and str(item.id) == str(target_failed.id):
            payload = dict(item.payload or {})
            payload["recovery_action"] = "resume_repair_continue"
            if repair_strategy:
                payload["recovery_strategy"] = str(repair_strategy).strip().lower()
                payload["recovery_reason"] = "manual_repair_injection"
            item.payload = payload
        elif mode == "replay_exact" and target_failed is not None and str(item.id) == str(target_failed.id):
            payload = dict(item.payload or {})
            payload["recovery_action"] = "resume_replay_exact"
            payload["resume_replay_exact"] = True
            item.payload = payload
        session.add(item)
        requeued_ids.append(str(item.id))

    previous = run.status
    summary = _summary_payload(run)
    previous_state = summary.get("resume_state") if isinstance(summary.get("resume_state"), dict) else {}
    history = summary.get("resume_history") if isinstance(summary.get("resume_history"), list) else []
    history.append(
        {
            "resumed_at": _now_iso(),
            "previous_status": previous,
            "resume_mode": mode,
            "checkpoint_id": checkpoint.get("checkpoint_id") if checkpoint else None,
            "requeued_work_item_ids": requeued_ids,
            "checkpoint_storage_mode": checkpoint.get("storage_mode") if checkpoint else None,
            "restore_source": restore_source,
            "workspace_rehydrated": workspace_rehydrated,
            "failed_work_item_id": str(target_failed.id) if target_failed is not None else None,
            "repair_strategy": str(repair_strategy).strip().lower() if repair_strategy else None,
            "downstream_reuse_ratio": round(
                (
                    (sum(1 for item in work_items if item.status in {"DONE", "SKIPPED"}))
                    / max(1, len(work_items))
                ),
                4,
            ),
        }
    )
    summary["resume_history"] = history[-10:]
    summary["resume_state"] = {
        **previous_state,
        "resume_count": int(previous_state.get("resume_count") or 0) + 1,
        "last_resume_at": _now_iso(),
        "last_resume_mode": mode,
        "last_resume_checkpoint_id": checkpoint.get("checkpoint_id") if checkpoint else None,
        "last_resume_restore_source": restore_source,
        "last_resume_workspace_rehydrated": workspace_rehydrated,
        "last_resume_failed_work_item_id": str(target_failed.id) if target_failed is not None else None,
        "last_resume_repair_strategy": str(repair_strategy).strip().lower() if repair_strategy else None,
        "last_resume_requeued_count": len(requeued_ids),
    }
    run.status = "QUEUED"
    run.finished_at = None
    run.summary = summary
    session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_RESUME_PREPARED",
        actor_type=actor_type,
        actor_id=actor_id,
        tenant_id=run.tenant_id,
        payload={
            "previous": previous,
            "new": "QUEUED",
            "resume_mode": mode,
            "checkpoint_id": checkpoint.get("checkpoint_id") if checkpoint else None,
            "requeued_work_item_ids": requeued_ids,
            "checkpoint_storage_mode": checkpoint.get("storage_mode") if checkpoint else None,
            "restore_source": restore_source,
            "workspace_rehydrated": workspace_rehydrated,
            "failed_work_item_id": str(target_failed.id) if target_failed is not None else None,
            "repair_strategy": str(repair_strategy).strip().lower() if repair_strategy else None,
        },
    )
    await sync_run_execution_contract_state(session, run)
    await sync_run_resume_state(session, run)
    await session.flush()
    return run
