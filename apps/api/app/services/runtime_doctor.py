from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.frontend_composition_integrity import validate_frontend_composition_integrity
from app.services.preview_runtime import resolve_preview_runtime_contract


@dataclass(frozen=True)
class RuntimeDoctorResult:
    ok: bool
    checks: list[dict[str, Any]]
    summary: dict[str, Any]


def _check(key: str, label: str, passed: bool, detail: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": "PASS" if passed else "FAIL",
        "detail": detail,
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def run_runtime_doctor(*, repo_root: Path) -> RuntimeDoctorResult:
    runtime_contracts = repo_root / "runtime-contracts"
    foundation_version_path = runtime_contracts / "foundation_version.json"
    manifest_path = runtime_contracts / "component-manifest.json"
    topology_path = runtime_contracts / "topology_hash.json"

    foundation_version = _load_json(foundation_version_path)
    manifest = _load_json(manifest_path)
    topology = _load_json(topology_path)
    composition = validate_frontend_composition_integrity(repo_root=repo_root)
    frontend_root = repo_root / "apps" / "web"
    preview_contract = resolve_preview_runtime_contract(repo_root=repo_root, configured_frontend_root=frontend_root)

    required_components = [
        "PageShell",
        "Navbar",
        "Footer",
        "MobileNav",
        "SectionContainer",
        "ContentGrid",
        "Stack",
        "SectionHeading",
        "PrimaryButton",
        "HeroZone",
        "FeatureZone",
        "TestimonialsZone",
        "CTAZone",
    ]
    manifest_components = manifest.get("components") if isinstance(manifest.get("components"), dict) else {}
    def _manifest_component_path(name: str) -> Path | None:
        entry = manifest_components.get(name)
        if isinstance(entry, dict):
            raw = entry.get("path")
        else:
            raw = entry
        if not isinstance(raw, str) or not raw.strip():
            return None
        return repo_root / raw.strip()

    component_paths_ok = all(
        (component_path := _manifest_component_path(name)) is not None and component_path.exists()
        for name in required_components
    )
    shell_ok = (repo_root / "apps" / "web" / "src" / "layouts" / "PageShell.vue").exists()
    zones_ok = all(
        (repo_root / "apps" / "web" / "src" / "components" / "zones" / f"{zone}.vue").exists()
        for zone in ("HeroZone", "FeatureZone", "TestimonialsZone", "CTAZone")
    )
    preview_ok = preview_contract.project_type.value in {"VITE_APP", "MONOREPO", "MONOREPO_VITE_FASTAPI", "STATIC_HTML"}

    checks = [
        _check(
            "foundation_version",
            "Foundation version contract",
            foundation_version.get("foundation_version") == 1
            and foundation_version.get("template") == "frontend-foundation"
            and foundation_version.get("framework") == "vue-vite-tailwind",
            "foundation_version.json is present and pinned to frontend-foundation v1.",
        ),
        _check(
            "component_manifest",
            "Component manifest",
            manifest.get("version") == 1 and bool(manifest_components),
            "component-manifest.json is present and populated from the filesystem.",
        ),
        _check(
            "topology_hash",
            "Topology hash",
            topology.get("foundation_version") == 1 and topology.get("shell") == "PageShell",
            "topology_hash.json is present and pinned to PageShell v1.",
        ),
        _check(
            "shell_integrity",
            "Shell integrity",
            shell_ok and composition.get("composition_integrity_ok") is True,
            "LandingPage composes PageShell and required zones are reachable.",
        ),
        _check(
            "import_graph",
            "Import graph health",
            component_paths_ok,
            "Manifest entries resolve to existing component files.",
        ),
        _check(
            "preview_bootable",
            "Preview bootability",
            preview_ok and preview_contract.entrypoint is not None,
            f"Preview classified as {preview_contract.project_type.value} with entrypoint {preview_contract.entrypoint!r}.",
        ),
        _check(
            "primitive_existence",
            "Primitive existence",
            all(
                (repo_root / rel).exists()
                for rel in (
                    "apps/web/src/components/ui/SectionContainer.vue",
                    "apps/web/src/components/ui/ContentGrid.vue",
                    "apps/web/src/components/ui/Stack.vue",
                    "apps/web/src/components/ui/SectionHeading.vue",
                    "apps/web/src/components/ui/PrimaryButton.vue",
                )
            ),
            "All required layout primitives exist.",
        ),
    ]
    ok = all(check["status"] == "PASS" for check in checks)
    summary = {
        "repo_root": str(repo_root),
        "preview_project_type": preview_contract.project_type.value,
        "preview_strategy": preview_contract.strategy.value,
        "composition_integrity_score": composition.get("composition_integrity_score"),
    }
    return RuntimeDoctorResult(ok=ok, checks=checks, summary=summary)
