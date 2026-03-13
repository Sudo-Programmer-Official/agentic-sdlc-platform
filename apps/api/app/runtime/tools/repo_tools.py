from __future__ import annotations

import os
from pathlib import Path
import subprocess

from app.core.config import get_settings
from app.runtime.tools.redaction import redact


class RepoTools:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.settings = get_settings()

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
            check_res = subprocess.run(
                ["git", "-C", str(self.root), "apply", "--check", "-"],
                input=normalized_diff,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            if check_res.returncode != 0:
                raise ValueError(f"Patch check failed: {check_res.stderr.strip() or check_res.stdout.strip()}")

            res = subprocess.run(
                ["git", "-C", str(self.root), "apply", "--whitespace=nowarn", "--reject", "-"],
                input=normalized_diff,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
        except Exception as exc:
            raise ValueError(f"Patch apply error: {exc}") from exc

        if res.returncode != 0:
            raise ValueError(f"Patch apply failed: {res.stderr.strip() or res.stdout.strip()}")

    def git_diff(self) -> str:
        try:
            res = subprocess.run(
                ["git", "-C", str(self.root), "diff"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            return res.stdout or ""
        except Exception:
            return ""
