from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from app.services.build_info import get_current_build_info


def _normalize_runtime_git_auth_mode(value: str | None) -> str:
    normalized = str(value or "auto").strip().lower()
    if normalized in {"auto", "github_app_https", "ssh", "none"}:
        return normalized
    return "auto"


@dataclass(frozen=True)
class RuntimeStartupDiagnostics:
    build_version: str | None
    build_sha: str | None
    runtime_mode: str
    runtime_git_auth_mode: str
    git_binary: str | None
    ssh_binary: str | None
    github_app_id_present: bool
    github_private_key_present: bool
    github_webhook_secret_present: bool

    @property
    def runtime_git_auth_missing(self) -> tuple[str, ...]:
        missing: list[str] = []
        if not self.git_binary:
            missing.append("git")
        if self.runtime_git_auth_mode == "ssh" and not self.ssh_binary:
            missing.append("ssh")
        if self.runtime_git_auth_mode == "github_app_https":
            if not self.github_app_id_present:
                missing.append("GITHUB_APP_ID")
            if not self.github_private_key_present:
                missing.append("GITHUB_PRIVATE_KEY")
        return tuple(missing)

    @property
    def runtime_git_auth_ready(self) -> bool:
        return not self.runtime_git_auth_missing

    @property
    def runtime_git_auth_status(self) -> str:
        return "READY" if self.runtime_git_auth_ready else "BLOCKED"

    @property
    def github_clone_auth_missing(self) -> tuple[str, ...]:
        missing: list[str] = []
        if not self.git_binary:
            missing.append("git")
        if not self.github_app_id_present:
            missing.append("GITHUB_APP_ID")
        if not self.github_private_key_present:
            missing.append("GITHUB_PRIVATE_KEY")
        return tuple(missing)

    @property
    def github_clone_auth_ready(self) -> bool:
        return not self.github_clone_auth_missing

    @property
    def github_clone_auth_status(self) -> str:
        return "READY" if self.github_clone_auth_ready else "BLOCKED"


def collect_runtime_startup_diagnostics(runtime_mode: str, runtime_git_auth_mode: str = "auto") -> RuntimeStartupDiagnostics:
    build = get_current_build_info()
    return RuntimeStartupDiagnostics(
        build_version=build.get("version"),
        build_sha=build.get("short_sha"),
        runtime_mode=runtime_mode,
        runtime_git_auth_mode=_normalize_runtime_git_auth_mode(runtime_git_auth_mode),
        git_binary=shutil.which("git"),
        ssh_binary=shutil.which("ssh"),
        github_app_id_present=bool(os.getenv("GITHUB_APP_ID")),
        github_private_key_present=bool(os.getenv("GITHUB_PRIVATE_KEY")),
        github_webhook_secret_present=bool(os.getenv("GITHUB_WEBHOOK_SECRET")),
    )
