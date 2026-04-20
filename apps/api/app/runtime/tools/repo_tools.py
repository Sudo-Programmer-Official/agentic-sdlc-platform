from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.runtime.execution_contract import ExecutionContract, coerce_execution_contract
from app.runtime.tools.redaction import redact
from app.services.workspace_commands import run_workspace_command


class RepoTools:
    def __init__(
        self,
        root: Path,
        logs_path: Path | None = None,
        execution_contract: ExecutionContract | dict | None = None,
    ):
        self.root = root.resolve()
        self.settings = get_settings()
        self.logs_path = logs_path
        self.execution_contract = coerce_execution_contract(execution_contract)
        self.allowed_command_prefixes = (
            list(self.execution_contract.allowed_command_prefixes)
            if self.execution_contract is not None and self.execution_contract.allowed_command_prefixes
            else None
        )

    def _safe_path(self, rel_path: str) -> Path:
        p = (self.root / rel_path).resolve()
        if not str(p).startswith(str(self.root)):
            raise ValueError("Path escapes repo root")
        return p

    def read_files(self, paths: list[str], max_bytes: int) -> dict[str, str]:
        out = {}
        remaining = max_bytes
        for rel in paths:
            p = self._safe_path(rel)
            if not p.exists() or not p.is_file():
                continue
            data = p.read_bytes()
            if len(data) > remaining:
                data = data[:remaining]
            remaining -= len(data)
            out[rel] = redact(data.decode(errors="ignore"))
            if remaining <= 0:
                break
        return out

    def write_file(self, rel_path: str, content: str):
        p = self._safe_path(rel_path)
        b = content.encode()
        if len(b) > self.settings.codex_max_write_bytes_total:
            raise ValueError("Write exceeds configured limit")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)

    def delete_file(self, rel_path: str):
        p = self._safe_path(rel_path)
        if p.exists():
            p.unlink()

    def apply_patch(self, unified_diff: str):
        """
        Apply a unified diff (git format) to the repository root.
        Raises ValueError on failure.
        """
        normalized_diff = unified_diff if unified_diff.endswith("\n") else f"{unified_diff}\n"
        # Basic safety: block obvious path traversal in diff headers
        for line in normalized_diff.splitlines():
            if line.startswith(("+++", "---")):
                # strip leading markers like "+++ b/path"
                header_path = line[4:].strip()
                if ".." in header_path:
                    raise ValueError("Patch header contains parent path reference")
        try:
            # dry-run check first
            check_res = run_workspace_command(
                ["git", "apply", "--recount", "--check", "-"],
                cwd=self.root,
                log_dir=self.logs_path,
                label="git-apply-check",
                timeout_seconds=10,
                allowed_prefixes=self.allowed_command_prefixes,
                stdin_text=normalized_diff,
                output_max_bytes=self.settings.workspace_command_output_max_bytes,
            )
            if check_res.status == "BLOCKED":
                raise ValueError(check_res.blocked_reason or "Patch check blocked by workspace policy")
            if check_res.exit_code != 0:
                raise ValueError(f"Patch check failed: {check_res.stderr.strip() or check_res.stdout.strip()}")

            res = run_workspace_command(
                ["git", "apply", "--recount", "--whitespace=nowarn", "--reject", "-"],
                cwd=self.root,
                log_dir=self.logs_path,
                label="git-apply",
                timeout_seconds=10,
                allowed_prefixes=self.allowed_command_prefixes,
                stdin_text=normalized_diff,
                output_max_bytes=self.settings.workspace_command_output_max_bytes,
            )
        except Exception as exc:
            raise ValueError(f"Patch apply error: {exc}") from exc

        if res.status == "BLOCKED":
            raise ValueError(res.blocked_reason or "Patch apply blocked by workspace policy")
        if res.exit_code != 0:
            raise ValueError(f"Patch apply failed: {res.stderr.strip() or res.stdout.strip()}")

    def git_diff(self) -> str:
        try:
            res = run_workspace_command(
                ["git", "diff"],
                cwd=self.root,
                log_dir=self.logs_path,
                label="git-diff",
                timeout_seconds=5,
                allowed_prefixes=self.allowed_command_prefixes,
                output_max_bytes=self.settings.workspace_command_output_max_bytes,
            )
            if res.status in {"BLOCKED", "TIMEOUT"} or res.exit_code not in {0, None}:
                return ""
            return res.stdout or ""
        except Exception:
            return ""
