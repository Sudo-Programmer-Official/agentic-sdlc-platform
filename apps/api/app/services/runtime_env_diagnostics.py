from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from app.services.build_info import get_current_build_info


@dataclass(frozen=True)
class RuntimeStartupDiagnostics:
    build_version: str | None
    build_sha: str | None
    runtime_mode: str
    git_binary: str | None
    github_app_id_present: bool
    github_private_key_present: bool
    github_webhook_secret_present: bool


def collect_runtime_startup_diagnostics(runtime_mode: str) -> RuntimeStartupDiagnostics:
    build = get_current_build_info()
    return RuntimeStartupDiagnostics(
        build_version=build.get("version"),
        build_sha=build.get("short_sha"),
        runtime_mode=runtime_mode,
        git_binary=shutil.which("git"),
        github_app_id_present=bool(os.getenv("GITHUB_APP_ID")),
        github_private_key_present=bool(os.getenv("GITHUB_PRIVATE_KEY")),
        github_webhook_secret_present=bool(os.getenv("GITHUB_WEBHOOK_SECRET")),
    )
