from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ArchitectureProfile, ProjectRepository


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _profile_packages(profile: ArchitectureProfile | None) -> list[dict[str, Any]]:
    if not profile or not isinstance(profile.profile_json, dict):
        return []
    repo_layout = profile.profile_json.get("repo_layout")
    if not isinstance(repo_layout, dict):
        return []
    return [item for item in _as_list(repo_layout.get("packages")) if isinstance(item, dict)]


def _profile_commands(profile: ArchitectureProfile | None) -> dict[str, Any]:
    if not profile or not isinstance(profile.profile_json, dict):
        return {}
    commands = profile.profile_json.get("commands")
    return commands if isinstance(commands, dict) else {}


def _has_kind(packages: list[dict[str, Any]], *kinds: str) -> bool:
    wanted = {kind.lower() for kind in kinds}
    for package in packages:
        kind = str(package.get("kind") or "").lower()
        name = str(package.get("name") or "").lower()
        if kind in wanted:
            return True
        if "frontend" in wanted and any(token in name for token in ("web", "frontend", "client", "ui")):
            return True
        if "backend" in wanted and any(token in name for token in ("api", "backend", "server")):
            return True
    return False


def _has_command(commands: dict[str, Any], *needles: str) -> bool:
    lowered = " ".join(f"{key} {value}" for key, value in commands.items()).lower()
    return any(needle in lowered for needle in needles)


def _check(key: str, label: str, passed: bool, detail: str) -> dict[str, str]:
    return {
        "key": key,
        "label": label,
        "status": "PASS" if passed else "MISSING",
        "detail": detail,
    }


async def build_foundation_readiness(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> dict[str, Any]:
    repo = await session.scalar(
        select(ProjectRepository).where(
            ProjectRepository.project_id == project_id,
            ProjectRepository.tenant_id == tenant_id,
        )
    )
    profile = await session.scalar(
        select(ArchitectureProfile).where(
            ArchitectureProfile.project_id == project_id,
            ArchitectureProfile.tenant_id == tenant_id,
        )
    )
    packages = _profile_packages(profile)
    commands = _profile_commands(profile)
    repo_connected = repo is not None
    profile_present = profile is not None
    frontend_present = _has_kind(packages, "frontend")
    backend_present = _has_kind(packages, "backend", "service")
    validation_present = _has_command(commands, "test", "pytest", "vitest", "playwright")
    package_manager_present = _has_command(commands, "npm", "pnpm", "yarn", "uv", "pip", "poetry")

    checks = [
        _check(
            "repo_connected",
            "Repository connected",
            repo_connected,
            repo.repo_full_name or repo.repo_url if repo else "Connect a repository before feature execution.",
        ),
        _check(
            "architecture_profile",
            "Architecture profile",
            profile_present,
            profile.summary if profile and profile.summary else "Bootstrap or derive an architecture profile.",
        ),
        _check(
            "frontend_package",
            "Frontend package",
            frontend_present,
            "Frontend workspace detected." if frontend_present else "No frontend package detected yet.",
        ),
        _check(
            "backend_package",
            "Backend/API package",
            backend_present,
            "Backend/API workspace detected." if backend_present else "No backend/API package detected yet.",
        ),
        _check(
            "validation_command",
            "Validation command",
            validation_present,
            "Test command detected." if validation_present else "No test command detected in architecture profile.",
        ),
        _check(
            "package_manager",
            "Package manager/tooling",
            package_manager_present,
            "Tooling command detected." if package_manager_present else "No package manager command detected.",
        ),
    ]
    missing = [item["key"] for item in checks if item["status"] != "PASS"]
    passed = len(checks) - len(missing)
    if not repo_connected:
        mode = "new_bootstrap"
    else:
        mode = "existing_repo_enhancement"
    if not missing:
        status = "READY"
    elif passed >= 3:
        status = "PARTIAL"
    else:
        status = "MISSING"
    if status == "READY":
        next_step = "Feature planning can proceed from the requirements graph."
    elif not repo_connected:
        next_step = "Connect a repository, then bootstrap the architecture profile."
    elif not profile_present:
        next_step = "Bootstrap or derive the architecture profile before regenerating feature tasks."
    else:
        next_step = "Create bootstrap tasks for missing foundation checks before feature execution."
    return {
        "status": status,
        "mode": mode,
        "repo_connected": repo_connected,
        "architecture_profile_present": profile_present,
        "checks": checks,
        "missing_prerequisites": missing,
        "recommended_next_step": next_step,
    }
