from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from app.core.config import Settings, get_settings


COMMAND_AUDIT_LOG_NAME = "commands.jsonl"
DEFAULT_ALLOWED_COMMAND_PREFIXES = [
    "git",
    "pytest",
    "python",
    "python3",
    "npm",
    "pnpm",
    "yarn",
    "node",
    "npx",
    "uv",
    "bash",
    "sh",
    "make",
    "go",
    "cargo",
    "eslint",
    "ruff",
]
DEFAULT_WORKSPACE_COMMAND_OUTPUT_MAX_BYTES = 200_000


@dataclass(frozen=True)
class WorkspaceCommandResult:
    command: list[str]
    cwd: str
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    blocked_reason: str | None = None
    log_path: str | None = None
    audit_path: str | None = None


def get_workspace_allowed_command_prefixes(settings: Settings | None = None) -> list[str]:
    cfg = settings or get_settings()
    raw = getattr(
        cfg,
        "workspace_allowed_command_prefixes",
        ",".join(DEFAULT_ALLOWED_COMMAND_PREFIXES),
    ).strip()
    return [item.strip() for item in raw.split(",") if item.strip()]


def workspace_command_audit_path(log_dir: Path | str | None) -> Path | None:
    if log_dir is None:
        return None
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path / COMMAND_AUDIT_LOG_NAME


def _command_prefix(command: Sequence[str]) -> tuple[str, str]:
    raw = command[0].strip()
    return raw, Path(raw).name


def _is_allowed(command: Sequence[str], allowed_prefixes: Sequence[str]) -> bool:
    raw, basename = _command_prefix(command)
    allowed = {item.strip() for item in allowed_prefixes if item.strip()}
    return raw in allowed or basename in allowed


def _command_log_path(log_dir: Path | None, label: str) -> Path | None:
    if log_dir is None:
        return None
    commands_dir = log_dir / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:8]
    safe_label = "-".join(part for part in label.lower().replace("_", "-").split() if part) or "command"
    return commands_dir / f"{safe_label}-{token}.log"


def _truncate_output(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8", errors="ignore")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _write_log(log_path: Path | None, stdout: str, stderr: str) -> None:
    if log_path is None:
        return
    parts: list[str] = []
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(f"--- STDERR ---\n{stderr}")
    body = "\n\n".join(parts)
    log_path.write_text(body, encoding="utf-8")


def _append_audit(audit_path: Path | None, record: dict) -> None:
    if audit_path is None:
        return
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def run_workspace_command(
    command: Sequence[str],
    *,
    cwd: Path,
    log_dir: Path | None = None,
    label: str = "workspace-command",
    timeout_seconds: int = 30,
    allowed_prefixes: Sequence[str] | None = None,
    stdin_text: str | None = None,
    env: dict[str, str] | None = None,
    output_max_bytes: int | None = None,
) -> WorkspaceCommandResult:
    if not command:
        raise ValueError("Workspace command is empty")
    if not cwd.exists():
        raise ValueError(f"Workspace command cwd does not exist: {cwd}")

    settings = get_settings()
    limit = output_max_bytes or getattr(
        settings,
        "workspace_command_output_max_bytes",
        DEFAULT_WORKSPACE_COMMAND_OUTPUT_MAX_BYTES,
    )
    audit_path = workspace_command_audit_path(log_dir)
    allowed = list(allowed_prefixes or get_workspace_allowed_command_prefixes(settings))
    started_at = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()
    log_path = _command_log_path(log_dir, label)
    command_list = [str(part) for part in command]
    status = "BLOCKED"
    exit_code: int | None = None
    stdout = ""
    stderr = ""
    blocked_reason: str | None = None
    timed_out = False

    if not _is_allowed(command_list, allowed):
        blocked_reason = f"Command prefix '{command_list[0]}' is not allowed in workspace simulation"
        stderr = blocked_reason
    else:
        merged_env = dict(os.environ)
        if env:
            merged_env.update(env)
        try:
            completed = subprocess.run(
                command_list,
                cwd=str(cwd),
                input=stdin_text,
                capture_output=True,
                text=True,
                env=merged_env,
                check=False,
                timeout=timeout_seconds,
            )
            exit_code = completed.returncode
            stdout = _truncate_output(completed.stdout or "", limit)
            stderr = _truncate_output(completed.stderr or "", limit)
            status = "SUCCEEDED" if completed.returncode == 0 else "FAILED"
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            status = "TIMEOUT"
            stdout = _truncate_output(exc.stdout or "", limit)
            stderr = _truncate_output(exc.stderr or "", limit)
        except Exception as exc:  # pragma: no cover - defensive path
            status = "FAILED"
            stderr = _truncate_output(str(exc), limit)

    _write_log(log_path, stdout, stderr)
    duration_ms = int((time.monotonic() - started_monotonic) * 1000)
    record = {
        "started_at": started_at.isoformat(),
        "label": label,
        "command": command_list,
        "cwd": str(cwd),
        "status": status,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "timed_out": timed_out,
        "blocked_reason": blocked_reason,
        "allowed_prefixes": allowed,
        "log_path": str(log_path) if log_path is not None else None,
    }
    _append_audit(audit_path, record)
    return WorkspaceCommandResult(
        command=command_list,
        cwd=str(cwd),
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        timed_out=timed_out,
        blocked_reason=blocked_reason,
        log_path=str(log_path) if log_path is not None else None,
        audit_path=str(audit_path) if audit_path is not None else None,
    )


async def run_workspace_command_async(
    command: Sequence[str],
    *,
    cwd: Path,
    log_dir: Path | None = None,
    label: str = "workspace-command",
    timeout_seconds: int = 30,
    allowed_prefixes: Sequence[str] | None = None,
    stdin_text: str | None = None,
    env: dict[str, str] | None = None,
    output_max_bytes: int | None = None,
) -> WorkspaceCommandResult:
    return await asyncio.to_thread(
        run_workspace_command,
        command,
        cwd=cwd,
        log_dir=log_dir,
        label=label,
        timeout_seconds=timeout_seconds,
        allowed_prefixes=allowed_prefixes,
        stdin_text=stdin_text,
        env=env,
        output_max_bytes=output_max_bytes,
    )
