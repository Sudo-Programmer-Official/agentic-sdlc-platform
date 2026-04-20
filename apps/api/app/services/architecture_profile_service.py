from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ArchitectureProfile, Project, ProjectPreviewProfile, ProjectRepository, RepoFile
from app.schemas.architecture_profile import ArchitectureProfileSummaryOut
from app.services.repo_map import refresh_project_repo_map

_MONOREPO_ROOTS = {"apps", "packages", "services"}
_FRONTEND_NAMES = {"frontend", "front-end", "web", "client", "ui", "site"}
_BACKEND_NAMES = {"backend", "back-end", "api", "server", "worker"}
_SHARED_NAMES = {"packages", "shared", "core", "lib", "agent"}
_PROTECTED_ZONE_HINTS = (
    ("infra", "Infrastructure and deployment configuration"),
    ("migrations", "Schema migrations"),
    (".github/workflows", "CI workflow definitions"),
    ("apps/api/app/db/models", "Persistence models"),
    ("apps/api/alembic", "Database migrations"),
)


def _normalize_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        return normalized
    pure = PurePosixPath(normalized)
    return "." if str(pure) == "." else str(pure)


def _path_matches_prefix(path: str, prefix: str) -> bool:
    normalized_path = _normalize_path(path)
    normalized_prefix = _normalize_path(prefix)
    if not normalized_path or not normalized_prefix:
        return False
    if normalized_prefix == ".":
        return True
    path_parts = PurePosixPath(normalized_path).parts
    prefix_parts = PurePosixPath(normalized_prefix).parts
    if len(prefix_parts) > len(path_parts):
        return False
    return path_parts[: len(prefix_parts)] == prefix_parts


def _unique_strings(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        cleaned = _normalize_path(value)
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen


def _coerce_zone_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    zones: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            zones.append(item)
        elif isinstance(item, dict):
            candidate = item.get("path")
            if isinstance(candidate, str) and candidate.strip():
                zones.append(candidate)
    return _unique_strings(zones)


def _coerce_command_index(commands: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(commands, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for name, raw in commands.items():
        if not isinstance(name, str) or not name.strip():
            continue
        key = name.strip()
        if isinstance(raw, str):
            normalized[key] = {"command": raw.strip()}
            continue
        if not isinstance(raw, dict):
            continue
        command = raw.get("command")
        if isinstance(command, str) and command.strip():
            normalized[key] = {
                "command": command.strip(),
                "kind": raw.get("kind"),
                "label": raw.get("label"),
                "paths": _coerce_zone_list(raw.get("paths")),
            }
    return normalized


def _coerce_validation_recipes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    recipes: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        recipes.append(
            {
                "name": name.strip(),
                "label": item.get("label"),
                "paths": _coerce_zone_list(item.get("paths")),
                "commands": _unique_strings(
                    [entry for entry in item.get("commands", []) if isinstance(entry, str) and entry.strip()]
                ),
                "kind": item.get("kind"),
            }
        )
    return recipes


def _coerce_packages(profile_json: dict[str, Any]) -> list[dict[str, Any]]:
    repo_layout = profile_json.get("repo_layout")
    if not isinstance(repo_layout, dict):
        return []
    packages = repo_layout.get("packages")
    if not isinstance(packages, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in packages:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        normalized.append(
            {
                "name": _normalize_path(name),
                "kind": item.get("kind"),
                "owned_by": item.get("owned_by"),
            }
        )
    return normalized


def _deep_merge(existing: Any, incoming: Any) -> Any:
    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged = {key: value for key, value in existing.items()}
        for key, value in incoming.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    if isinstance(existing, list) and isinstance(incoming, list):
        if all(isinstance(item, str) for item in existing + incoming):
            return _unique_strings([*existing, *incoming])
        merged = list(existing)
        for item in incoming:
            if item not in merged:
                merged.append(item)
        return merged
    if existing in (None, "", [], {}):
        return incoming
    return existing


def _guess_package_kind(prefix: str, paths: list[str], preview: ProjectPreviewProfile | None) -> str:
    name = PurePosixPath(prefix).name.lower()
    if preview and prefix == _normalize_path(preview.frontend_root or ""):
        return "frontend"
    if preview and prefix == _normalize_path(preview.backend_root or ""):
        return "backend"
    if prefix.startswith("packages/") or name in _SHARED_NAMES:
        return "shared"
    if prefix.startswith("services/"):
        return "service"
    if name in _FRONTEND_NAMES:
        return "frontend"
    if name in _BACKEND_NAMES:
        return "backend"
    lowered_paths = [path.lower() for path in paths]
    if any(path.endswith((".vue", ".tsx", ".jsx", ".css", ".scss", ".html")) for path in lowered_paths):
        return "frontend"
    if any(path.endswith(".py") for path in lowered_paths):
        return "backend"
    return "package"


def _candidate_package_prefixes(
    repo_paths: list[str],
    preview: ProjectPreviewProfile | None,
) -> list[str]:
    candidates: list[str] = []
    for path in repo_paths:
        pure = PurePosixPath(path)
        parts = pure.parts
        if len(parts) >= 2 and parts[0] in _MONOREPO_ROOTS:
            candidates.append("/".join(parts[:2]))
            continue
        if parts:
            first = parts[0]
            if first in {"frontend", "backend", "web", "api", "client", "server", "infra", "core", "agent"}:
                candidates.append(first)
    if preview:
        if preview.frontend_root:
            candidates.append(preview.frontend_root)
        if preview.backend_root:
            candidates.append(preview.backend_root)
        if preview.compose_file:
            parent = str(PurePosixPath(preview.compose_file).parent)
            candidates.append(parent if parent != "." else preview.compose_file)
    return _unique_strings(candidates)


def _build_package_inventory(
    repo_paths: list[str],
    preview: ProjectPreviewProfile | None,
) -> list[dict[str, Any]]:
    by_prefix: dict[str, list[str]] = defaultdict(list)
    for prefix in _candidate_package_prefixes(repo_paths, preview):
        by_prefix.setdefault(prefix, [])
    for path in repo_paths:
        for prefix in list(by_prefix.keys()):
            if _path_matches_prefix(path, prefix):
                by_prefix[prefix].append(path)
                break

    packages: list[dict[str, Any]] = []
    for prefix, paths in sorted(by_prefix.items()):
        if prefix == ".":
            continue
        kind = _guess_package_kind(prefix, paths, preview)
        owner = (
            "product-ui"
            if kind == "frontend"
            else "platform-runtime"
            if kind in {"backend", "service"}
            else "shared-platform"
        )
        packages.append(
            {
                "name": prefix,
                "kind": kind,
                "owned_by": owner,
                "file_count": len(paths),
            }
        )
    return packages


def _set_command(
    commands: dict[str, dict[str, Any]],
    *,
    key: str,
    command: str | None,
    label: str,
    kind: str,
    paths: list[str] | None = None,
) -> None:
    if not isinstance(command, str) or not command.strip():
        return
    commands[key] = {
        "command": command.strip(),
        "label": label,
        "kind": kind,
        "paths": _coerce_zone_list(paths or []),
    }


def _infer_commands(
    *,
    preview: ProjectPreviewProfile | None,
    repo_paths: list[str],
    packages: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    commands: dict[str, dict[str, Any]] = {}
    repo_set = set(repo_paths)
    if preview:
        _set_command(
            commands,
            key="frontend_build",
            command=preview.frontend_build_command,
            label="Frontend build",
            kind="build",
            paths=[preview.frontend_root] if preview.frontend_root else [],
        )
        _set_command(
            commands,
            key="backend_build",
            command=preview.backend_build_command,
            label="Backend build",
            kind="build",
            paths=[preview.backend_root] if preview.backend_root else [],
        )
        _set_command(
            commands,
            key="frontend_start",
            command=preview.frontend_start_command,
            label="Frontend preview start",
            kind="preview",
            paths=[preview.frontend_root] if preview.frontend_root else [],
        )
        _set_command(
            commands,
            key="backend_start",
            command=preview.backend_start_command,
            label="Backend preview start",
            kind="preview",
            paths=[preview.backend_root] if preview.backend_root else [],
        )
    if "apps/web/package.json" in repo_set and "frontend_build" not in commands:
        _set_command(
            commands,
            key="frontend_build",
            command="npm -C apps/web run build",
            label="Frontend build",
            kind="build",
            paths=["apps/web"],
        )
    if "apps/web/package.json" in repo_set and "frontend_test" not in commands:
        _set_command(
            commands,
            key="frontend_test",
            command="npm -C apps/web run test",
            label="Frontend tests",
            kind="test",
            paths=["apps/web"],
        )
    if "apps/api/pyproject.toml" in repo_set or "apps/api/requirements.txt" in repo_set:
        _set_command(
            commands,
            key="api_tests",
            command="python3 -m pytest -q apps/api/tests",
            label="API tests",
            kind="test",
            paths=["apps/api"],
        )
    if "package.json" in repo_set and "frontend_build" not in commands:
        _set_command(
            commands,
            key="root_build",
            command="npm run build",
            label="Workspace build",
            kind="build",
            paths=["."],
        )
    if ("pyproject.toml" in repo_set or "requirements.txt" in repo_set) and "repo_tests" not in commands:
        _set_command(
            commands,
            key="repo_tests",
            command="python3 -m pytest -q",
            label="Repository tests",
            kind="test",
            paths=["."],
        )
    if "index.html" in repo_set and "frontend_build" not in commands and "frontend_start" not in commands:
        _set_command(
            commands,
            key="static_preview",
            command="python3 -m http.server $PORT --bind $HOST",
            label="Static preview",
            kind="preview",
            paths=["."],
        )
    if not commands and packages:
        for package in packages[:2]:
            if package["kind"] == "frontend":
                _set_command(
                    commands,
                    key=f"{package['name'].replace('/', '_')}_build",
                    command=f"npm -C {package['name']} run build",
                    label=f"{package['name']} build",
                    kind="build",
                    paths=[package["name"]],
                )
            elif package["kind"] in {"backend", "service"}:
                _set_command(
                    commands,
                    key=f"{package['name'].replace('/', '_')}_tests",
                    command=f"python3 -m pytest -q {package['name']}",
                    label=f"{package['name']} tests",
                    kind="test",
                    paths=[package["name"]],
                )
    return commands


def _infer_validation_recipes(
    *,
    commands: dict[str, dict[str, Any]],
    packages: list[dict[str, Any]],
    preview: ProjectPreviewProfile | None,
) -> list[dict[str, Any]]:
    recipes: list[dict[str, Any]] = []
    for package in packages:
        name = package["name"]
        kind = package.get("kind") or "package"
        command_names = [
            command_name
            for command_name, meta in commands.items()
            if any(_path_matches_prefix(name, path) or _path_matches_prefix(path, name) for path in meta.get("paths", []))
        ]
        if not command_names:
            if kind == "frontend":
                command_names = [name for name in commands if "frontend" in name or "build" in name]
            elif kind in {"backend", "service"}:
                command_names = [name for name in commands if "api" in name or "test" in name]
        if not command_names:
            continue
        recipes.append(
            {
                "name": f"{name.replace('/', '_')}_validation",
                "label": f"{name} validation",
                "kind": kind,
                "paths": [name],
                "commands": _unique_strings(command_names),
            }
        )
    if preview and preview.frontend_root and not any(recipe["kind"] == "frontend" for recipe in recipes):
        recipes.append(
            {
                "name": "frontend_validation",
                "label": "Frontend validation",
                "kind": "frontend",
                "paths": [preview.frontend_root],
                "commands": [name for name in commands if "frontend" in name or "static" in name][:3],
            }
        )
    return recipes


def _infer_safe_zones(
    *,
    packages: list[dict[str, Any]],
    preview: ProjectPreviewProfile | None,
    repo_paths: list[str],
) -> list[str]:
    safe_zones: list[str] = []
    for package in packages:
        name = package["name"]
        kind = package.get("kind")
        if kind == "frontend":
            safe_zones.append(f"{name}/src")
            safe_zones.append(f"{name}/src/views")
            safe_zones.append(f"{name}/src/components")
        elif kind in {"backend", "service"}:
            safe_zones.append(f"{name}/app")
            safe_zones.append(f"{name}/app/services")
            safe_zones.append(f"{name}/tests")
    if preview and preview.frontend_root:
        safe_zones.append(f"{preview.frontend_root}/src")
    if "index.html" in repo_paths:
        safe_zones.append("index.html")
    return [zone for zone in _unique_strings(safe_zones) if zone != "."]


def _infer_protected_zones(repo_paths: list[str]) -> list[dict[str, str]]:
    zones: list[dict[str, str]] = []
    for prefix, reason in _PROTECTED_ZONE_HINTS:
        if any(_path_matches_prefix(path, prefix) for path in repo_paths):
            zones.append({"path": prefix, "reason": reason})
    return zones


def _infer_boundaries(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    boundaries: list[dict[str, Any]] = []
    frontend_packages = [package for package in packages if package.get("kind") == "frontend"]
    backend_packages = [package for package in packages if package.get("kind") in {"backend", "service"}]
    shared_packages = [package for package in packages if package.get("kind") == "shared"]
    for frontend in frontend_packages:
        for backend in backend_packages:
            boundaries.append(
                {
                    "from": frontend["name"],
                    "to": backend["name"],
                    "rule": "http_only",
                    "notes": "Frontend changes should integrate through explicit API boundaries.",
                }
            )
    for shared in shared_packages:
        boundaries.append(
            {
                "from": shared["name"],
                "to": "*",
                "rule": "shared_module",
                "notes": "Shared packages may be reused across execution slices but should remain dependency-light.",
            }
        )
    return boundaries


def _build_bootstrap_profile(
    *,
    project: Project,
    repo: ProjectRepository | None,
    preview: ProjectPreviewProfile | None,
    repo_paths: list[str],
) -> tuple[dict[str, Any], str]:
    packages = _build_package_inventory(repo_paths, preview)
    commands = _infer_commands(preview=preview, repo_paths=repo_paths, packages=packages)
    validation_recipes = _infer_validation_recipes(commands=commands, packages=packages, preview=preview)
    safe_zones = _infer_safe_zones(packages=packages, preview=preview, repo_paths=repo_paths)
    protected_zones = _infer_protected_zones(repo_paths)
    repo_layout = {
        "monorepo": len(packages) > 1 and any("/" in package["name"] for package in packages),
        "label": "Monorepo" if len(packages) > 1 else "Repository",
        "packages": packages,
    }
    profile_json = {
        "repo_layout": repo_layout,
        "boundaries": _infer_boundaries(packages),
        "module_ownership": [
            {"path": package["name"], "owner": package["owned_by"], "kind": package["kind"]}
            for package in packages
        ],
        "integrations": [
            {
                "name": "repository",
                "provider": repo.provider if repo else None,
                "repo_full_name": repo.repo_full_name if repo else None,
                "default_branch": repo.default_branch if repo else None,
            },
            {
                "name": "preview",
                "mode": preview.mode if preview else None,
                "frontend_root": preview.frontend_root if preview else None,
                "backend_root": preview.backend_root if preview else None,
            },
        ],
        "commands": commands,
        "validation_recipes": validation_recipes,
        "safe_refactor_zones": safe_zones,
        "do_not_touch_zones": protected_zones,
        "conventions": {
            "branch_strategy": "run_branch_then_pr",
            "bounded_slice_required": True,
            "preferred_patch_style": "minimal_patch",
        },
        "release_flow": {
            "branch_strategy": "run_branch_then_pr",
            "requires_review_before_pr": True,
            "default_branch": repo.default_branch if repo else "main",
            "preview_mode": preview.mode if preview else None,
        },
        "environment_assumptions": {
            "repo_connected": repo is not None,
            "preview_profile_configured": preview is not None and preview.enabled,
            "frontend_root": preview.frontend_root if preview else None,
            "backend_root": preview.backend_root if preview else None,
        },
    }
    summary = (
        f"{project.name} uses "
        f"{'a monorepo' if repo_layout['monorepo'] else 'a repository'} contract with "
        f"{len(packages)} package slice{'s' if len(packages) != 1 else ''}, "
        f"{len(validation_recipes)} validation recipe{'s' if len(validation_recipes) != 1 else ''}, and "
        f"{len(protected_zones)} protected zone{'s' if len(protected_zones) != 1 else ''}."
    )
    return profile_json, summary


def _derive_profile_json(
    profile_json: dict[str, Any],
) -> dict[str, Any]:
    packages = _coerce_packages(profile_json)
    commands = _coerce_command_index(profile_json.get("commands"))
    validation_recipes = _coerce_validation_recipes(profile_json.get("validation_recipes"))
    safe_zones = _coerce_zone_list(profile_json.get("safe_refactor_zones"))
    protected_items = profile_json.get("do_not_touch_zones")
    protected_zones = _coerce_zone_list(protected_items)
    protected_zone_index: dict[str, dict[str, Any]] = {}
    if isinstance(protected_items, list):
        for item in protected_items:
            if isinstance(item, dict):
                path = item.get("path")
                if isinstance(path, str) and path.strip():
                    protected_zone_index[_normalize_path(path)] = {
                        "approval_required": True,
                        "reason": item.get("reason") or "Protected zone",
                    }
    for path in protected_zones:
        protected_zone_index.setdefault(path, {"approval_required": True, "reason": "Protected zone"})

    path_boundary_index: dict[str, dict[str, Any]] = {}
    module_ownership_index: dict[str, dict[str, Any]] = {}
    for package in packages:
        path_boundary_index[package["name"]] = {
            "kind": package.get("kind"),
            "owner": package.get("owned_by"),
        }
        module_ownership_index[package["name"]] = {
            "owner": package.get("owned_by"),
            "kind": package.get("kind"),
        }

    validation_recipe_index = {
        recipe["name"]: {
            "paths": recipe.get("paths", []),
            "commands": recipe.get("commands", []),
            "kind": recipe.get("kind"),
        }
        for recipe in validation_recipes
    }
    integration_surface_index = {}
    if isinstance(profile_json.get("integrations"), list):
        for item in profile_json["integrations"]:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    integration_surface_index[name.strip()] = item

    return {
        "path_boundary_index": path_boundary_index,
        "module_ownership_index": module_ownership_index,
        "validation_recipe_index": validation_recipe_index,
        "integration_surface_index": integration_surface_index,
        "safe_zone_index": {path: {"editable": True} for path in safe_zones},
        "protected_zone_index": protected_zone_index,
        "command_index": commands,
        "summary_cards": {
            "package_count": len(packages),
            "protected_zone_count": len(protected_zone_index),
            "safe_zone_count": len(safe_zones),
            "validation_recipe_count": len(validation_recipes),
            "command_count": len(commands),
        },
    }


def _execution_slice_for_files(packages: list[str], touched_files: list[str]) -> list[str]:
    if not touched_files:
        return packages[:3]
    slices: list[str] = []
    for package in packages:
        if any(_path_matches_prefix(path, package) for path in touched_files):
            slices.append(package)
    return _unique_strings(slices)


def _zone_hits(touched_files: list[str], zones: list[str]) -> list[str]:
    hits: list[str] = []
    for zone in zones:
        if any(_path_matches_prefix(path, zone) for path in touched_files):
            hits.append(zone)
    return _unique_strings(hits)


def _assumptions_from_profile(profile_json: dict[str, Any], repo_full_name: str | None, default_branch: str | None) -> list[str]:
    assumptions: list[str] = []
    if repo_full_name:
        assumptions.append(f"Repository: {repo_full_name}")
    if default_branch:
        assumptions.append(f"Default branch: {default_branch}")
    release_flow = profile_json.get("release_flow")
    if isinstance(release_flow, dict):
        branch_strategy = release_flow.get("branch_strategy")
        if isinstance(branch_strategy, str) and branch_strategy.strip():
            assumptions.append(f"Branch strategy: {branch_strategy.strip()}")
        preview_mode = release_flow.get("preview_mode")
        if isinstance(preview_mode, str) and preview_mode.strip():
            assumptions.append(f"Preview mode: {preview_mode.strip()}")
    environment = profile_json.get("environment_assumptions")
    if isinstance(environment, dict):
        for key in ("frontend_root", "backend_root"):
            value = environment.get(key)
            if isinstance(value, str) and value.strip():
                assumptions.append(f"{key.replace('_', ' ').title()}: {value.strip()}")
    return assumptions[:6]


def _build_summary(
    *,
    profile_exists: bool,
    profile_id: uuid.UUID | None,
    status: str,
    source: str | None,
    version: int | None,
    summary: str | None,
    repo_full_name: str | None,
    repo_default_branch: str | None,
    profile_json: dict[str, Any],
    derived_json: dict[str, Any],
    last_derived_at: datetime | None,
    touched_files: list[str] | None = None,
) -> ArchitectureProfileSummaryOut:
    touched = _unique_strings(touched_files or [])
    packages = [item["name"] for item in _coerce_packages(profile_json)]
    safe_zones = sorted((derived_json.get("safe_zone_index") or {}).keys())
    protected_zones = sorted((derived_json.get("protected_zone_index") or {}).keys())
    commands = list(_coerce_command_index(profile_json.get("commands")).keys())
    validation_recipes = [item["name"] for item in _coerce_validation_recipes(profile_json.get("validation_recipes"))]
    repo_layout = profile_json.get("repo_layout") if isinstance(profile_json.get("repo_layout"), dict) else {}
    return ArchitectureProfileSummaryOut(
        profile_exists=profile_exists,
        profile_id=profile_id,
        status=status,
        source=source,
        version=version,
        summary=summary,
        repo_full_name=repo_full_name,
        repo_default_branch=repo_default_branch,
        repo_layout_label=str(repo_layout.get("label") or ("Monorepo" if repo_layout.get("monorepo") else "Repository")),
        monorepo=bool(repo_layout.get("monorepo")),
        package_count=len(packages),
        packages=packages[:8],
        boundary_count=len(profile_json.get("boundaries", [])) if isinstance(profile_json.get("boundaries"), list) else 0,
        protected_zone_count=len(protected_zones),
        protected_zones=protected_zones[:8],
        safe_zone_count=len(safe_zones),
        safe_zones=safe_zones[:8],
        command_coverage_count=len(commands),
        commands=commands[:8],
        validation_recipe_count=len(validation_recipes),
        derived_ready=bool(derived_json),
        last_derived_at=last_derived_at,
        execution_slice=_execution_slice_for_files(packages, touched),
        validation_recipes=validation_recipes[:8],
        protected_zones_touched=_zone_hits(touched, protected_zones),
        safe_zones_touched=_zone_hits(touched, safe_zones),
        assumptions_used=_assumptions_from_profile(profile_json, repo_full_name, repo_default_branch),
    )


async def _get_project(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> Project:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
    if project is None:
        raise ValueError("Project not found")
    return project


async def _get_profile(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ArchitectureProfile | None:
    return await session.scalar(
        select(ArchitectureProfile).where(
            ArchitectureProfile.project_id == project_id,
            ArchitectureProfile.tenant_id == tenant_id,
        )
    )


async def _collect_repo_hints(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    refresh_repo_map_requested: bool = False,
) -> dict[str, Any]:
    repo = await session.scalar(
        select(ProjectRepository).where(
            ProjectRepository.project_id == project_id,
            ProjectRepository.tenant_id == tenant_id,
        )
    )
    preview = await session.scalar(
        select(ProjectPreviewProfile).where(
            ProjectPreviewProfile.project_id == project_id,
            ProjectPreviewProfile.tenant_id == tenant_id,
        )
    )
    repo_rows = (
        await session.execute(
            select(RepoFile.path).where(RepoFile.project_id == project_id, RepoFile.tenant_id == tenant_id)
        )
    ).all()
    repo_paths = [_normalize_path(row[0]) for row in repo_rows if isinstance(row[0], str)]
    repo_map_message = None
    if refresh_repo_map_requested and repo is not None:
        try:
            repo_map = await refresh_project_repo_map(session, tenant_id=tenant_id, project_id=project_id, limit=240)
            for file in repo_map.files:
                repo_paths.append(file.path)
        except ValueError as exc:
            repo_map_message = str(exc)
    repo_paths = _unique_strings(repo_paths)
    return {
        "repo": repo,
        "preview": preview,
        "repo_paths": repo_paths,
        "repo_map_message": repo_map_message,
    }


def _runtime_meta_from_profile(profile: ArchitectureProfile) -> dict[str, Any]:
    profile_json = profile.profile_json if isinstance(profile.profile_json, dict) else {}
    derived_json = profile.derived_json if isinstance(profile.derived_json, dict) else {}
    summary = _build_summary(
        profile_exists=True,
        profile_id=profile.id,
        status=profile.status,
        source=profile.source,
        version=profile.version,
        summary=profile.summary,
        repo_full_name=profile.repo_full_name,
        repo_default_branch=profile.repo_default_branch,
        profile_json=profile_json,
        derived_json=derived_json,
        last_derived_at=profile.last_derived_at,
    )
    return {
        "profile_id": str(profile.id),
        "status": profile.status,
        "source": profile.source,
        "version": profile.version,
        "summary": summary.model_dump(mode="json"),
        "protected_paths": sorted((derived_json.get("protected_zone_index") or {}).keys()),
        "safe_paths": sorted((derived_json.get("safe_zone_index") or {}).keys()),
        "validation_recipe_index": derived_json.get("validation_recipe_index") or {},
        "command_index": derived_json.get("command_index") or {},
    }


async def get_architecture_profile(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ArchitectureProfile:
    await _get_project(session, tenant_id=tenant_id, project_id=project_id)
    profile = await _get_profile(session, tenant_id=tenant_id, project_id=project_id)
    if profile is None:
        raise ValueError("Architecture profile not found")
    return profile


async def get_architecture_runtime_meta(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> dict[str, Any] | None:
    profile = await _get_profile(session, tenant_id=tenant_id, project_id=project_id)
    if profile is None:
        return None
    return _runtime_meta_from_profile(profile)


async def upsert_architecture_profile(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    status: str,
    source: str,
    summary: str | None,
    profile_json: dict[str, Any],
    created_by: str | None,
    updated_by: str | None,
) -> ArchitectureProfile:
    await _get_project(session, tenant_id=tenant_id, project_id=project_id)
    repo_hints = await _collect_repo_hints(session, tenant_id=tenant_id, project_id=project_id)
    derived_json = _derive_profile_json(profile_json)
    profile = await _get_profile(session, tenant_id=tenant_id, project_id=project_id)
    now = datetime.now(timezone.utc)
    if profile is None:
        profile = ArchitectureProfile(
            tenant_id=tenant_id,
            project_id=project_id,
            status=status,
            source=source,
            version=1,
            repo_full_name=repo_hints["repo"].repo_full_name if repo_hints["repo"] else None,
            repo_default_branch=repo_hints["repo"].default_branch if repo_hints["repo"] else None,
            summary=summary,
            profile_json=profile_json,
            derived_json=derived_json,
            last_derived_at=now,
            created_by=created_by or updated_by,
            updated_by=updated_by or created_by,
        )
        session.add(profile)
    else:
        profile.status = status
        profile.source = source
        profile.summary = summary
        profile.profile_json = profile_json
        profile.derived_json = derived_json
        profile.last_derived_at = now
        profile.updated_by = updated_by or created_by or profile.updated_by
        profile.repo_full_name = repo_hints["repo"].repo_full_name if repo_hints["repo"] else profile.repo_full_name
        profile.repo_default_branch = (
            repo_hints["repo"].default_branch if repo_hints["repo"] else profile.repo_default_branch
        )
        profile.version += 1
        session.add(profile)
    await session.flush()
    return profile


async def patch_architecture_profile(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    summary: str | None,
    sections: dict[str, Any],
    updated_by: str | None,
) -> ArchitectureProfile:
    profile = await get_architecture_profile(session, tenant_id=tenant_id, project_id=project_id)
    merged = _deep_merge(profile.profile_json if isinstance(profile.profile_json, dict) else {}, sections)
    profile.profile_json = merged
    if summary is not None:
        profile.summary = summary
    profile.derived_json = _derive_profile_json(merged)
    profile.last_derived_at = datetime.now(timezone.utc)
    profile.updated_by = updated_by or profile.updated_by
    profile.version += 1
    session.add(profile)
    await session.flush()
    return profile


async def bootstrap_architecture_profile(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    refresh_repo_map_requested: bool = False,
    created_by: str | None = None,
) -> ArchitectureProfile:
    project = await _get_project(session, tenant_id=tenant_id, project_id=project_id)
    repo_hints = await _collect_repo_hints(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        refresh_repo_map_requested=refresh_repo_map_requested,
    )
    bootstrap_json, bootstrap_summary = _build_bootstrap_profile(
        project=project,
        repo=repo_hints["repo"],
        preview=repo_hints["preview"],
        repo_paths=repo_hints["repo_paths"],
    )
    profile = await _get_profile(session, tenant_id=tenant_id, project_id=project_id)
    now = datetime.now(timezone.utc)
    if profile is None:
        profile = ArchitectureProfile(
            tenant_id=tenant_id,
            project_id=project_id,
            status="DRAFT",
            source="BOOTSTRAP",
            version=1,
            repo_full_name=repo_hints["repo"].repo_full_name if repo_hints["repo"] else None,
            repo_default_branch=repo_hints["repo"].default_branch if repo_hints["repo"] else None,
            summary=bootstrap_summary,
            profile_json=bootstrap_json,
            derived_json=_derive_profile_json(bootstrap_json),
            last_derived_at=now,
            created_by=created_by,
            updated_by=created_by,
        )
        session.add(profile)
    else:
        merged = _deep_merge(profile.profile_json if isinstance(profile.profile_json, dict) else {}, bootstrap_json)
        changed = merged != (profile.profile_json if isinstance(profile.profile_json, dict) else {})
        profile.profile_json = merged
        profile.derived_json = _derive_profile_json(merged)
        profile.last_derived_at = now
        profile.repo_full_name = repo_hints["repo"].repo_full_name if repo_hints["repo"] else profile.repo_full_name
        profile.repo_default_branch = (
            repo_hints["repo"].default_branch if repo_hints["repo"] else profile.repo_default_branch
        )
        if not profile.summary:
            profile.summary = bootstrap_summary
        if changed:
            profile.version += 1
        profile.updated_by = created_by or profile.updated_by
        session.add(profile)
    await session.flush()
    return profile


async def derive_architecture_profile(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    refresh_repo_map_requested: bool = False,
    bootstrap_if_missing: bool = False,
    updated_by: str | None = None,
) -> ArchitectureProfile:
    profile = await _get_profile(session, tenant_id=tenant_id, project_id=project_id)
    if profile is None:
        if not bootstrap_if_missing:
            raise ValueError("Architecture profile not found")
        profile = await bootstrap_architecture_profile(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            refresh_repo_map_requested=refresh_repo_map_requested,
            created_by=updated_by,
        )
        return profile

    repo_hints = await _collect_repo_hints(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        refresh_repo_map_requested=refresh_repo_map_requested,
    )
    profile.derived_json = _derive_profile_json(profile.profile_json if isinstance(profile.profile_json, dict) else {})
    profile.last_derived_at = datetime.now(timezone.utc)
    profile.updated_by = updated_by or profile.updated_by
    profile.repo_full_name = repo_hints["repo"].repo_full_name if repo_hints["repo"] else profile.repo_full_name
    profile.repo_default_branch = (
        repo_hints["repo"].default_branch if repo_hints["repo"] else profile.repo_default_branch
    )
    session.add(profile)
    await session.flush()
    return profile


async def summarize_architecture_profile(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    touched_files: list[str] | None = None,
) -> ArchitectureProfileSummaryOut:
    await _get_project(session, tenant_id=tenant_id, project_id=project_id)
    profile = await _get_profile(session, tenant_id=tenant_id, project_id=project_id)
    if profile is not None:
        return _build_summary(
            profile_exists=True,
            profile_id=profile.id,
            status=profile.status,
            source=profile.source,
            version=profile.version,
            summary=profile.summary,
            repo_full_name=profile.repo_full_name,
            repo_default_branch=profile.repo_default_branch,
            profile_json=profile.profile_json if isinstance(profile.profile_json, dict) else {},
            derived_json=profile.derived_json if isinstance(profile.derived_json, dict) else {},
            last_derived_at=profile.last_derived_at,
            touched_files=touched_files,
        )

    project = await _get_project(session, tenant_id=tenant_id, project_id=project_id)
    repo_hints = await _collect_repo_hints(session, tenant_id=tenant_id, project_id=project_id)
    bootstrap_json, bootstrap_summary = _build_bootstrap_profile(
        project=project,
        repo=repo_hints["repo"],
        preview=repo_hints["preview"],
        repo_paths=repo_hints["repo_paths"],
    )
    derived_json = _derive_profile_json(bootstrap_json)
    return _build_summary(
        profile_exists=False,
        profile_id=None,
        status="MISSING",
        source="INFERRED",
        version=None,
        summary=bootstrap_summary,
        repo_full_name=repo_hints["repo"].repo_full_name if repo_hints["repo"] else None,
        repo_default_branch=repo_hints["repo"].default_branch if repo_hints["repo"] else None,
        profile_json=bootstrap_json,
        derived_json=derived_json,
        last_derived_at=None,
        touched_files=touched_files,
    )
