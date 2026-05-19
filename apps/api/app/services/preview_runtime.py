from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PreviewProjectType(str, Enum):
    STATIC_HTML = "STATIC_HTML"
    VITE_APP = "VITE_APP"
    MONOREPO = "MONOREPO"
    DIST_BUILD = "DIST_BUILD"
    BACKEND_ONLY = "BACKEND_ONLY"
    INVALID = "INVALID"


class PreviewStrategy(str, Enum):
    STATIC_SERVER = "STATIC_SERVER"
    VITE_DEV = "VITE_DEV"
    DISABLED = "DISABLED"
    INVALID = "INVALID"


@dataclass(frozen=True)
class PreviewRuntimeContract:
    project_type: PreviewProjectType
    strategy: PreviewStrategy
    frontend_root: Path
    requires_node_modules: bool
    entrypoint: str | None
    reason: str | None = None


def _read_json(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _has_vite_markers(root: Path) -> bool:
    for vite_file in ("vite.config.ts", "vite.config.js", "vite.config.mjs", "vite.config.cjs"):
        if (root / vite_file).exists():
            return True
    pkg = root / "package.json"
    if pkg.exists():
        data = _read_json(pkg)
        scripts = data.get("scripts")
        if isinstance(scripts, dict) and "vite" in str(scripts.get("dev", "")).lower():
            return True
        for deps_key in ("dependencies", "devDependencies"):
            deps = data.get(deps_key)
            if isinstance(deps, dict) and "vite" in deps:
                return True
    html = root / "index.html"
    if html.exists():
        try:
            lower = html.read_text(encoding="utf-8").lower()
        except OSError:
            lower = ""
        if "/src/main.ts" in lower or "/src/main.js" in lower:
            return True
    return False


def _index_references_vite_entry(root: Path) -> bool:
    html = root / "index.html"
    if not html.exists():
        return False
    try:
        lower = html.read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "/src/main.ts" in lower or "/src/main.js" in lower


def _find_monorepo_frontend_root(repo_root: Path) -> Path | None:
    candidates = [
        repo_root / "apps" / "web",
        repo_root / "apps" / "frontend",
        repo_root / "web",
        repo_root / "frontend",
        repo_root / "client",
    ]
    for candidate in candidates:
        if candidate.exists() and _has_vite_markers(candidate):
            return candidate
    return None


def resolve_preview_runtime_contract(
    *,
    repo_root: Path,
    configured_frontend_root: Path,
) -> PreviewRuntimeContract:
    dist_root = repo_root / "dist"
    if (dist_root / "index.html").exists():
        return PreviewRuntimeContract(
            project_type=PreviewProjectType.DIST_BUILD,
            strategy=PreviewStrategy.STATIC_SERVER,
            frontend_root=dist_root,
            requires_node_modules=False,
            entrypoint="dist/index.html",
        )

    discovered = _find_monorepo_frontend_root(repo_root)
    if discovered is not None and discovered != configured_frontend_root:
        return PreviewRuntimeContract(
            project_type=PreviewProjectType.MONOREPO,
            strategy=PreviewStrategy.VITE_DEV,
            frontend_root=discovered,
            requires_node_modules=True,
            entrypoint="src/main.ts",
        )

    if _has_vite_markers(configured_frontend_root):
        if not (configured_frontend_root / "package.json").exists():
            # Soft fallback for generated/static repos where index.html contains
            # a stale Vite-like script tag but no runnable Vite project exists.
            src_main_ts = configured_frontend_root / "src" / "main.ts"
            src_main_js = configured_frontend_root / "src" / "main.js"
            if _index_references_vite_entry(configured_frontend_root) and not src_main_ts.exists() and not src_main_js.exists():
                return PreviewRuntimeContract(
                    project_type=PreviewProjectType.STATIC_HTML,
                    strategy=PreviewStrategy.STATIC_SERVER,
                    frontend_root=configured_frontend_root,
                    requires_node_modules=False,
                    entrypoint="index.html",
                    reason="Vite marker found in index.html but no package.json/src entrypoint; falling back to static preview.",
                )
            return PreviewRuntimeContract(
                project_type=PreviewProjectType.INVALID,
                strategy=PreviewStrategy.INVALID,
                frontend_root=configured_frontend_root,
                requires_node_modules=True,
                entrypoint="src/main.ts",
                reason="Vite runtime markers detected but package.json is missing at frontend root.",
            )
        return PreviewRuntimeContract(
            project_type=PreviewProjectType.VITE_APP,
            strategy=PreviewStrategy.VITE_DEV,
            frontend_root=configured_frontend_root,
            requires_node_modules=True,
            entrypoint="src/main.ts",
        )

    if (configured_frontend_root / "index.html").exists():
        return PreviewRuntimeContract(
            project_type=PreviewProjectType.STATIC_HTML,
            strategy=PreviewStrategy.STATIC_SERVER,
            frontend_root=configured_frontend_root,
            requires_node_modules=False,
            entrypoint="index.html",
        )

    if any((repo_root / marker).exists() for marker in ("pyproject.toml", "requirements.txt", "app", "main.py")):
        return PreviewRuntimeContract(
            project_type=PreviewProjectType.BACKEND_ONLY,
            strategy=PreviewStrategy.DISABLED,
            frontend_root=configured_frontend_root,
            requires_node_modules=False,
            entrypoint=None,
            reason="No previewable frontend artifact generated.",
        )

    return PreviewRuntimeContract(
        project_type=PreviewProjectType.INVALID,
        strategy=PreviewStrategy.INVALID,
        frontend_root=configured_frontend_root,
        requires_node_modules=False,
        entrypoint=None,
        reason="Preview runtime classification failed: unsupported repository shape.",
    )
