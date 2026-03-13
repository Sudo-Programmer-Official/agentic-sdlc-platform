from __future__ import annotations

import json
import os
import shlex
import signal
import socket
import string
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import ProjectPreviewProfile, ProjectRepository, Run
from app.schemas.preview import RunPreviewOut, RunPreviewServiceRef
from app.services.workspace_commands import run_workspace_command_async


DEFAULT_PREVIEW_STATUS = "NOT_CONFIGURED"


@dataclass(frozen=True)
class _PreviewProcess:
    pid: int
    log_path: str
    url: str
    port: int


def _now() -> datetime:
    return datetime.now(UTC)


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _preview_summary(run: Run) -> dict[str, Any]:
    if isinstance(run.summary, dict):
        raw = run.summary.get("preview")
        if isinstance(raw, dict):
            return dict(raw)
    return {}


def _write_preview_summary(run: Run, preview: dict[str, Any]) -> None:
    summary = dict(run.summary or {})
    summary["preview"] = preview
    summary["preview_status"] = preview.get("status")
    preview_url = preview.get("preview_url")
    if isinstance(preview_url, str):
        summary["preview_url"] = preview_url
    run.summary = summary


def _workspace_path(run: Run) -> Path:
    if not run.workspace_root:
        raise ValueError("Run workspace is not available.")
    path = Path(run.workspace_root).expanduser().resolve()
    if not path.exists():
        raise ValueError("Run workspace does not exist.")
    return path


def _repo_root(run: Run) -> Path:
    if not run.repo_path:
        raise ValueError("Run repo path is not available.")
    path = Path(run.repo_path).expanduser().resolve()
    if not path.exists():
        raise ValueError("Run repo path does not exist.")
    return path


def _root_path(repo_root: Path, configured: str | None) -> Path:
    if not configured:
        return repo_root
    resolved = (repo_root / configured).resolve()
    if not resolved.exists():
        raise ValueError(f"Preview root does not exist: {configured}")
    return resolved


def _pick_port(preferred: int | None = None) -> int:
    if preferred:
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _expand_command(command: str, env: dict[str, str]) -> list[str]:
    expanded = string.Template(command).safe_substitute(env)
    parts = shlex.split(expanded)
    if not parts:
        raise ValueError("Preview command is empty.")
    return parts


def _service_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def _service_healthcheck(url: str, path: str | None) -> bool:
    target = f"{url}{path or '/'}"
    try:
        with urlopen(target, timeout=1.5) as response:  # noqa: S310
            return 200 <= int(response.status) < 500
    except (URLError, OSError, ValueError):
        return False


def _terminate_process_group(pid: int | None) -> None:
    if not pid:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        return


def _stop_preview_processes(preview: dict[str, Any]) -> None:
    for service_key in ("frontend", "backend"):
        service = preview.get(service_key) or {}
        _terminate_process_group(service.get("pid"))


def _start_service_process(
    *,
    command: str,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
    host: str,
    port: int,
) -> _PreviewProcess:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    parts = _expand_command(command, env)
    handle = log_path.open("ab")
    process = subprocess.Popen(  # noqa: S603
        parts,
        cwd=str(cwd),
        env={**os.environ, **env},
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    return _PreviewProcess(
        pid=process.pid,
        log_path=str(log_path),
        url=_service_url(host, port),
        port=port,
    )


def _process_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


async def get_project_preview_profile(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ProjectPreviewProfile | None:
    return await session.scalar(
        select(ProjectPreviewProfile).where(
            ProjectPreviewProfile.project_id == project_id,
            ProjectPreviewProfile.tenant_id == tenant_id,
        )
    )


async def upsert_project_preview_profile(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    tenant_id: uuid.UUID,
    payload: dict[str, Any],
) -> ProjectPreviewProfile:
    profile = await get_project_preview_profile(session, tenant_id=tenant_id, project_id=project_id)
    if profile is None:
        profile = ProjectPreviewProfile(project_id=project_id, tenant_id=tenant_id)
        session.add(profile)
    for field, value in payload.items():
        if hasattr(profile, field):
            setattr(profile, field, value)
    await session.flush()
    return profile


async def _count_active_previews(session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID | None = None) -> int:
    runs = (
        await session.execute(
            select(Run).where(Run.tenant_id == tenant_id)
        )
    ).scalars().all()
    count = 0
    now = _now()
    for run in runs:
        if project_id and run.project_id != project_id:
            continue
        preview = _preview_summary(run)
        expires_at = _coerce_datetime(preview.get("expires_at"))
        if preview.get("status") in {"STARTING", "READY"} and (expires_at is None or expires_at > now):
            count += 1
    return count


async def cleanup_expired_previews(session: AsyncSession, *, tenant_id: uuid.UUID) -> None:
    runs = (await session.execute(select(Run).where(Run.tenant_id == tenant_id))).scalars().all()
    now = _now()
    for run in runs:
        preview = _preview_summary(run)
        if not preview:
            continue
        expires_at = _coerce_datetime(preview.get("expires_at"))
        if expires_at and expires_at <= now:
            _stop_preview_processes(preview)
            preview["status"] = "EXPIRED"
            preview["last_checked_at"] = now.isoformat()
            _write_preview_summary(run, preview)
            session.add(run)
    await session.flush()


def _build_preview_response(
    run: Run,
    *,
    profile: ProjectPreviewProfile | None,
    repository_connected: bool,
) -> RunPreviewOut:
    preview = _preview_summary(run)
    frontend = preview.get("frontend") if isinstance(preview.get("frontend"), dict) else None
    backend = preview.get("backend") if isinstance(preview.get("backend"), dict) else None
    return RunPreviewOut(
        run_id=run.id,
        project_id=run.project_id,
        status=str(preview.get("status") or DEFAULT_PREVIEW_STATUS),
        mode=str(preview.get("mode") or (profile.mode if profile else "local")),
        branch_name=run.branch_name,
        reusable=bool(preview.get("reusable")),
        launched_at=_coerce_datetime(preview.get("launched_at")),
        expires_at=_coerce_datetime(preview.get("expires_at")),
        ttl_hours=int(preview.get("ttl_hours") or (profile.ttl_hours if profile else get_settings().preview_default_ttl_hours)),
        preview_url=preview.get("preview_url"),
        frontend=RunPreviewServiceRef.model_validate(frontend) if frontend else None,
        backend=RunPreviewServiceRef.model_validate(backend) if backend else None,
        compose_file=profile.compose_file if profile else None,
        reuse_reason=preview.get("reuse_reason"),
        requires_verification=run.status != "COMPLETED",
        verification_note="Run must be completed before preview launch." if run.status != "COMPLETED" else None,
        profile_configured=profile is not None and profile.enabled,
        repository_connected=repository_connected,
    )


async def get_run_preview(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
) -> RunPreviewOut:
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id))
    if run is None:
        raise ValueError("Run not found")
    profile = await get_project_preview_profile(session, tenant_id=tenant_id, project_id=run.project_id)
    repo = await session.scalar(
        select(ProjectRepository).where(ProjectRepository.project_id == run.project_id, ProjectRepository.tenant_id == tenant_id)
    )
    preview = _preview_summary(run)
    now = _now()
    changed = False
    if preview:
        expires_at = _coerce_datetime(preview.get("expires_at"))
        if expires_at and expires_at <= now and preview.get("status") in {"STARTING", "READY"}:
            _stop_preview_processes(preview)
            preview["status"] = "EXPIRED"
            changed = True
        else:
            for service_key in ("frontend", "backend"):
                service = preview.get(service_key) or {}
                url = service.get("url")
                path = service.get("healthcheck_path")
                pid = service.get("pid")
                if url and preview.get("status") in {"STARTING", "READY"}:
                    healthy = _service_healthcheck(url, path)
                    service["status"] = "READY" if healthy else ("FAILED" if not _process_running(pid) else service.get("status") or "STARTING")
                    if preview.get("status") == "READY" and not healthy and not _process_running(pid):
                        preview["status"] = "FAILED"
                    changed = True
            preview["last_checked_at"] = now.isoformat()
        if changed:
            _write_preview_summary(run, preview)
            session.add(run)
            await session.flush()
    return _build_preview_response(run, profile=profile, repository_connected=repo is not None)


async def launch_run_preview(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    reuse_if_healthy: bool = True,
) -> RunPreviewOut:
    await cleanup_expired_previews(session, tenant_id=tenant_id)
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id))
    if run is None:
        raise ValueError("Run not found")
    profile = await get_project_preview_profile(session, tenant_id=tenant_id, project_id=run.project_id)
    if profile is None or not profile.enabled:
        raise ValueError("Project preview profile is not configured")
    if profile.compose_file and not (profile.frontend_start_command or profile.backend_start_command):
        raise ValueError("Compose-only preview profiles are not supported in the local preview launcher yet")
    if run.status != "COMPLETED":
        raise ValueError("Run must be completed before preview launch")

    repo = await session.scalar(
        select(ProjectRepository).where(ProjectRepository.project_id == run.project_id, ProjectRepository.tenant_id == tenant_id)
    )
    preview = _preview_summary(run)
    if reuse_if_healthy and preview.get("status") == "READY":
        expires_at = _coerce_datetime(preview.get("expires_at"))
        frontend = preview.get("frontend") or {}
        backend = preview.get("backend") or {}
        services = [service for service in (frontend, backend) if isinstance(service, dict) and service.get("url")]
        if services and (expires_at is None or expires_at > _now()) and all(
            _service_healthcheck(service["url"], service.get("healthcheck_path")) for service in services
        ):
            preview["reuse_reason"] = "healthy_existing_preview"
            preview["reusable"] = True
            _write_preview_summary(run, preview)
            session.add(run)
            await session.flush()
            return _build_preview_response(run, profile=profile, repository_connected=repo is not None)

    project_active = await _count_active_previews(session, tenant_id=tenant_id, project_id=run.project_id)
    global_active = await _count_active_previews(session, tenant_id=tenant_id)
    max_project = profile.max_previews_per_project or get_settings().preview_max_per_project
    max_global = get_settings().preview_max_global
    if project_active >= max_project:
        raise ValueError("Project preview limit reached")
    if global_active >= max_global:
        raise ValueError("Global preview limit reached")

    workspace_root = _workspace_path(run)
    repo_root = _repo_root(run)
    logs_dir = workspace_root / "logs" / "preview"
    logs_dir.mkdir(parents=True, exist_ok=True)
    preview_dir = workspace_root / "context"
    host = get_settings().preview_host
    env_overrides = {str(key): str(value) for key, value in (profile.env_overrides or {}).items()}
    ttl_hours = profile.ttl_hours or get_settings().preview_default_ttl_hours
    launched_at = _now()
    expires_at = launched_at + timedelta(hours=ttl_hours)

    if preview:
        _stop_preview_processes(preview)

    frontend_service: dict[str, Any] | None = None
    backend_service: dict[str, Any] | None = None

    async def _run_build_if_configured(command: str | None, cwd: Path, label: str) -> None:
        if not command:
            return
        result = await run_workspace_command_async(
            shlex.split(command),
            cwd=cwd,
            log_dir=logs_dir,
            label=label,
            env=env_overrides,
            timeout_seconds=300,
        )
        if result.status != "SUCCEEDED":
            raise ValueError(result.stderr or result.stdout or f"{label} failed")

    await _run_build_if_configured(profile.frontend_build_command, _root_path(repo_root, profile.frontend_root), "preview-frontend-build")
    await _run_build_if_configured(profile.backend_build_command, _root_path(repo_root, profile.backend_root), "preview-backend-build")

    try:
        if profile.frontend_start_command:
            port = _pick_port(profile.frontend_port)
            env = {
                **env_overrides,
                "PORT": str(port),
                "HOST": host,
                "ENV": "preview",
                "PREVIEW_ENV": "preview",
                "BRANCH_NAME": run.branch_name or "",
            }
            process = _start_service_process(
                command=profile.frontend_start_command,
                cwd=_root_path(repo_root, profile.frontend_root),
                env=env,
                log_path=logs_dir / "frontend-preview.log",
                host=host,
                port=port,
            )
            frontend_service = {
                "kind": "frontend",
                "status": "STARTING",
                "url": process.url,
                "pid": process.pid,
                "port": process.port,
                "root": profile.frontend_root,
                "start_command": profile.frontend_start_command,
                "build_command": profile.frontend_build_command,
                "healthcheck_path": profile.frontend_healthcheck_path or "/",
                "log_path": process.log_path,
                "last_error": None,
            }

        if profile.backend_start_command:
            port = _pick_port(profile.backend_port)
            env = {
                **env_overrides,
                "PORT": str(port),
                "HOST": host,
                "ENV": "preview",
                "PREVIEW_ENV": "preview",
                "BRANCH_NAME": run.branch_name or "",
            }
            process = _start_service_process(
                command=profile.backend_start_command,
                cwd=_root_path(repo_root, profile.backend_root),
                env=env,
                log_path=logs_dir / "backend-preview.log",
                host=host,
                port=port,
            )
            backend_service = {
                "kind": "backend",
                "status": "STARTING",
                "url": process.url,
                "pid": process.pid,
                "port": process.port,
                "root": profile.backend_root,
                "start_command": profile.backend_start_command,
                "build_command": profile.backend_build_command,
                "healthcheck_path": profile.backend_healthcheck_path or "/",
                "log_path": process.log_path,
                "last_error": None,
            }

        if not frontend_service and not backend_service:
            raise ValueError("Preview profile must define at least one start command")

        deadline = time.time() + 15
        while time.time() < deadline:
            frontend_ready = True
            backend_ready = True
            if frontend_service:
                frontend_ready = _service_healthcheck(frontend_service["url"], frontend_service["healthcheck_path"])
                frontend_service["status"] = "READY" if frontend_ready else "STARTING"
            if backend_service:
                backend_ready = _service_healthcheck(backend_service["url"], backend_service["healthcheck_path"])
                backend_service["status"] = "READY" if backend_ready else "STARTING"
            if frontend_ready and backend_ready:
                break
            time.sleep(0.5)
        else:
            raise ValueError("Preview health checks did not pass")
    except Exception:
        if frontend_service:
            _terminate_process_group(frontend_service.get("pid"))
        if backend_service:
            _terminate_process_group(backend_service.get("pid"))
        raise

    preview_url = (frontend_service or backend_service or {}).get("url")
    preview_payload = {
        "status": "READY",
        "mode": profile.mode,
        "preview_url": preview_url,
        "frontend": frontend_service,
        "backend": backend_service,
        "ttl_hours": ttl_hours,
        "launched_at": launched_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "reusable": True,
        "reuse_reason": None,
        "last_checked_at": launched_at.isoformat(),
    }
    _write_preview_summary(run, preview_payload)
    session.add(run)
    await session.flush()
    (preview_dir / "preview.json").write_text(json.dumps(preview_payload, indent=2), encoding="utf-8")
    return _build_preview_response(run, profile=profile, repository_connected=repo is not None)


async def stop_run_preview(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
) -> RunPreviewOut:
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id))
    if run is None:
        raise ValueError("Run not found")
    profile = await get_project_preview_profile(session, tenant_id=tenant_id, project_id=run.project_id)
    repo = await session.scalar(
        select(ProjectRepository).where(ProjectRepository.project_id == run.project_id, ProjectRepository.tenant_id == tenant_id)
    )
    preview = _preview_summary(run)
    if not preview:
        return _build_preview_response(run, profile=profile, repository_connected=repo is not None)

    _stop_preview_processes(preview)
    now = _now()
    preview["status"] = "STOPPED"
    preview["reusable"] = False
    preview["stopped_at"] = now.isoformat()
    preview["last_checked_at"] = now.isoformat()
    _write_preview_summary(run, preview)
    session.add(run)
    await session.flush()
    return _build_preview_response(run, profile=profile, repository_connected=repo is not None)
