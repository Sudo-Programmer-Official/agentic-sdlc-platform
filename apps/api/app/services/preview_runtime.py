from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PreviewProjectType(str, Enum):
    STATIC_HTML = "STATIC_HTML"
    VITE_APP = "VITE_APP"
    MONOREPO = "MONOREPO"
    MONOREPO_VITE_FASTAPI = "MONOREPO_VITE_FASTAPI"
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


def _index_module_entry_candidates(root: Path) -> list[str]:
    html = root / "index.html"
    if not html.exists():
        return []
    try:
        content = html.read_text(encoding="utf-8")
    except OSError:
        return []
    matches = re.findall(
        r'<script[^>]*type=["\']module["\'][^>]*src=["\'](/src/[^"\']+)["\']',
        content,
        flags=re.IGNORECASE,
    )
    candidates: list[str] = []
    seen: set[str] = set()
    for raw in matches:
        rel = raw.lstrip("/")
        if rel.startswith("src/") and rel not in seen:
            candidates.append(rel)
            seen.add(rel)
    return candidates


def resolve_vite_entrypoint(frontend_root: Path) -> str | None:
    for candidate in _index_module_entry_candidates(frontend_root):
        if (frontend_root / candidate).exists():
            return candidate
    for fallback in ("src/main.ts", "src/main.js", "src/main.tsx", "src/main.jsx", "src/main.mjs"):
        if (frontend_root / fallback).exists():
            return fallback
    return None


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


def _has_fastapi_markers(root: Path) -> bool:
    if not root.exists():
        return False
    if (root / "requirements.txt").exists() and (root / "main.py").exists():
        return True
    app_main = root / "app" / "main.py"
    if app_main.exists():
        try:
            content = app_main.read_text(encoding="utf-8")
        except OSError:
            return False
        return "FastAPI" in content
    return False


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
        backend_candidates = [
            repo_root / "apps" / "api",
            repo_root / "api",
            repo_root / "backend",
        ]
        backend_present = any(_has_fastapi_markers(candidate) for candidate in backend_candidates)
        return PreviewRuntimeContract(
            project_type=(
                PreviewProjectType.MONOREPO_VITE_FASTAPI
                if backend_present
                else PreviewProjectType.MONOREPO
            ),
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
