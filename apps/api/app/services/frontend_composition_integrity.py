from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _normalize_smart_quotes(text: str) -> str:
    return (
        text.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )


def _extract_vue_import_targets(text: str) -> list[str]:
    targets: list[str] = []
    for match in re.finditer(r'import\s+[^"\']+\s+from\s+["\']([^"\']+)["\']', text):
        targets.append(match.group(1).strip())
    return targets


def _component_name_from_path(path: str) -> str:
    stem = Path(path).stem
    return re.sub(r"[^A-Za-z0-9_]", "", stem)


def _zone_owner_from_component_path(path: Path) -> str:
    normalized = path.as_posix().lower()
    if "/components/zones/" in normalized:
        return path.stem
    if "hero" in normalized:
        return "HeroZone"
    if "feature" in normalized:
        return "FeatureZone"
    if "testimonial" in normalized:
        return "TestimonialsZone"
    if "cta" in normalized:
        return "CTAZone"
    return "shared"


def _primitive_type_from_component(path: Path) -> str:
    normalized = path.as_posix().lower()
    if "/components/ui/" in normalized:
        return "primitive"
    if "/components/layout/" in normalized:
        return "layout"
    if "/components/zones/" in normalized:
        return "zone"
    return "feature_component"


def _topology_role_from_component(path: Path) -> str:
    name = path.stem
    if name == "PageShell":
        return "shell"
    if name.endswith("Zone"):
        return "zone"
    if name in {"Navbar", "Footer", "MobileNav"}:
        return "shell_component"
    if name in {"SectionContainer", "ContentGrid", "Stack", "SectionHeading", "PrimaryButton"}:
        return "layout_primitive"
    return "component"


_FRONTEND_FOUNDATION_TEMPLATE_FILES = (
    "apps/web/index.html",
    "apps/web/package.json",
    "apps/web/vite.config.ts",
    "apps/web/src/main.ts",
    "apps/web/src/App.vue",
    "apps/web/src/pages/LandingPage.vue",
    "apps/web/src/layouts/PageShell.vue",
    "apps/web/src/components/layout/Navbar.vue",
    "apps/web/src/components/layout/Footer.vue",
    "apps/web/src/components/layout/MobileNav.vue",
    "apps/web/src/components/ui/SectionContainer.vue",
    "apps/web/src/components/ui/ContentGrid.vue",
    "apps/web/src/components/ui/Stack.vue",
    "apps/web/src/components/ui/SectionHeading.vue",
    "apps/web/src/components/ui/PrimaryButton.vue",
    "apps/web/src/components/zones/HeroZone.vue",
    "apps/web/src/components/zones/FeatureZone.vue",
    "apps/web/src/components/zones/TestimonialsZone.vue",
    "apps/web/src/components/zones/CTAZone.vue",
    "runtime-contracts/component-manifest.json",
    "runtime-contracts/foundation_version.json",
    "runtime-contracts/topology_hash.json",
)


def _template_source_roots(repo_root: Path) -> list[Path]:
    return [
        repo_root / "runtime-templates" / "frontend-foundation",
        repo_root / "runtime-templates" / "fullstack-monorepo",
    ]


def _copy_template_file_if_missing(*, source_root: Path, relative_path: str, target_root: Path) -> bool:
    source = source_root / relative_path
    target = target_root / relative_path
    if target.exists() or not source.exists() or not source.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def ensure_frontend_foundation_files(*, repo_root: Path) -> list[str]:
    copied: list[str] = []
    source_roots = [root for root in _template_source_roots(repo_root) if root.exists()]
    if not source_roots:
        return copied

    for relative_path in _FRONTEND_FOUNDATION_TEMPLATE_FILES:
        for source_root in source_roots:
            if _copy_template_file_if_missing(source_root=source_root, relative_path=relative_path, target_root=repo_root):
                copied.append(relative_path)
                break

    # Keep the runtime shell normalized after any missing file recovery.
    copied.extend(reconcile_frontend_runtime_shell(repo_root=repo_root))
    return list(dict.fromkeys(copied))


def _build_component_manifest(repo_root: Path) -> dict[str, Any]:
    src = repo_root / "apps" / "web" / "src"
    components: dict[str, dict[str, str]] = {}
    for vue_file in src.rglob("*.vue"):
        if not vue_file.is_file():
            continue
        rel = vue_file.relative_to(repo_root).as_posix()
        name = vue_file.stem
        components[name] = {
            "path": rel,
            "zone_owner": _zone_owner_from_component_path(vue_file),
            "primitive_type": _primitive_type_from_component(vue_file),
            "topology_role": _topology_role_from_component(vue_file),
        }
    return {"version": 1, "components": dict(sorted(components.items())), "source": "filesystem_scan"}


def _collect_feature_components(repo_root: Path, payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    values: list[str] = []
    for key in ("target_files", "files", "expected_files", "related_files"):
        items = payload.get(key)
        if isinstance(items, list):
            values.extend(item for item in items if isinstance(item, str))
    features: list[str] = []
    for raw in values:
        normalized = raw.replace("\\", "/").strip().lstrip("./")
        if not normalized.endswith(".vue"):
            continue
        if not normalized.startswith("apps/web/src/components/"):
            continue
        if (repo_root / normalized).exists():
            features.append(normalized)
    return sorted(set(features))


def validate_frontend_composition_integrity(
    *,
    repo_root: Path,
    payload: dict[str, Any] | None = None,
    recovery_repairs: list[str] | None = None,
) -> dict[str, Any]:
    web_src = repo_root / "apps" / "web" / "src"
    main_ts = web_src / "main.ts"
    app_vue = web_src / "App.vue"
    landing_page = web_src / "pages" / "LandingPage.vue"
    legacy_landing_page = web_src / "LandingPage.vue"
    landing_effective = landing_page if landing_page.exists() else legacy_landing_page

    main_text = _read_text(main_ts)
    app_text = _read_text(app_vue)
    landing_text = _read_text(landing_effective) if landing_effective.exists() else ""

    main_imports = _extract_vue_import_targets(main_text)
    app_imports = _extract_vue_import_targets(app_text)
    landing_imports = _extract_vue_import_targets(landing_text)

    app_compose_landing = (
        ("./pages/LandingPage.vue" in app_imports or "./LandingPage.vue" in app_imports)
        and "<LandingPage" in app_text
    )
    app_entry_ok = ("./App.vue" in main_imports) and app_vue.exists()
    landing_exists = landing_effective.exists()

    feature_components = _collect_feature_components(repo_root, payload)
    reachable_features: list[str] = []
    disconnected_features: list[str] = []
    for feature in feature_components:
        comp_name = _component_name_from_path(feature)
        import_hit = feature.split("apps/web/src/")[-1]
        rel_a = f'./{import_hit}'
        rel_b = f'../{import_hit}'
        landing_has_import = rel_a in landing_imports or rel_b in landing_imports or comp_name in landing_text
        landing_has_tag = f"<{comp_name}" in landing_text
        if landing_has_import and landing_has_tag:
            reachable_features.append(feature)
        else:
            disconnected_features.append(feature)

    total_checks = 3 + (1 if feature_components else 0)
    passed_checks = int(app_entry_ok) + int(app_compose_landing) + int(landing_exists)
    if feature_components:
        passed_checks += int(len(disconnected_features) == 0)
    integrity_score = round(passed_checks / max(total_checks, 1), 3)

    topology_repairs = recovery_repairs or []
    recovery_topology_mutations = sum(
        1
        for entry in topology_repairs
        if any(token in entry for token in ("src/main.ts", "src/App.vue", "src/pages/LandingPage.vue", "src/LandingPage.vue"))
    )

    return {
        "composition_integrity_ok": bool(app_entry_ok and app_compose_landing and landing_exists and len(disconnected_features) == 0),
        "composition_integrity_score": integrity_score,
        "disconnected_feature_count": len(disconnected_features),
        "disconnected_features": disconnected_features,
        "recovery_topology_mutations": recovery_topology_mutations,
        "preserved_feature_graph": {
            "runtime_entry": "apps/web/src/main.ts -> apps/web/src/App.vue" if app_entry_ok else "broken",
            "app_to_page": str(landing_effective.relative_to(repo_root)) if app_compose_landing else "broken",
            "reachable_features": reachable_features,
            "expected_features": feature_components,
        },
    }


def reconcile_frontend_runtime_shell(*, repo_root: Path) -> list[str]:
    frontend_root = repo_root / "apps" / "web"
    src = frontend_root / "src"
    main_ts = src / "main.ts"
    app_vue = src / "App.vue"
    landing_page = src / "pages" / "LandingPage.vue"
    legacy_landing = src / "LandingPage.vue"
    repairs: list[str] = []
    feature_components = sorted(
        path
        for path in (src / "components").rglob("*.vue")
        if path.is_file() and "/tests/" not in path.as_posix() and not path.name.startswith("test_")
    )

    if not src.exists():
        return repairs

    if not main_ts.exists():
        return repairs

    for vue_file in src.rglob("*.vue"):
        if not vue_file.is_file():
            continue
        original = _read_text(vue_file)
        normalized = _normalize_smart_quotes(original)
        if normalized != original:
            vue_file.write_text(normalized, encoding="utf-8")
            rel = vue_file.relative_to(repo_root).as_posix()
            repairs.append(f"{rel} (smart_quote_normalized)")

    main_text = _read_text(main_ts)
    if "./App.vue" not in main_text:
        updated = main_text
        updated = re.sub(
            r'import\s+[A-Za-z0-9_]+\s+from\s+["\']\./pages/LandingPage\.vue["\'];?',
            'import App from "./App.vue";',
            updated,
        )
        updated = re.sub(
            r'import\s+[A-Za-z0-9_]+\s+from\s+["\']\./LandingPage\.vue["\'];?',
            'import App from "./App.vue";',
            updated,
        )
        updated = re.sub(r"createApp\(\s*[A-Za-z0-9_]+\s*\)\.mount", "createApp(App).mount", updated)
        if updated != main_text:
            main_ts.write_text(updated, encoding="utf-8")
            repairs.append("apps/web/src/main.ts (runtime_shell_reconciled)")

    if not landing_page.exists() and not legacy_landing.exists() and feature_components:
        landing_page.parent.mkdir(parents=True, exist_ok=True)
        import_lines: list[str] = []
        tag_lines: list[str] = []
        for comp in feature_components:
            rel = os.path.relpath(comp, start=(src / "pages")).replace("\\", "/")
            if not rel.startswith("."):
                rel = f"./{rel}"
            name = _component_name_from_path(comp.name)
            import_lines.append(f'import {name} from "{rel}";')
            tag_lines.append(f"    <{name} />")
        landing_text = (
            "<template>\n"
            "  <main>\n"
            + "\n".join(tag_lines)
            + "\n  </main>\n"
            "</template>\n\n"
            "<script setup lang=\"ts\">\n"
            + "\n".join(import_lines)
            + "\n</script>\n"
        )
        landing_page.write_text(landing_text, encoding="utf-8")
        repairs.append("apps/web/src/pages/LandingPage.vue (runtime_shell_reconciled)")

    app_fallback = "<template>\n  <main>\n    <h1>Landing Page</h1>\n  </main>\n</template>\n"
    if landing_page.exists():
        desired_app = (
            "<template>\n  <LandingPage />\n</template>\n\n"
            "<script setup lang=\"ts\">\n"
            'import LandingPage from "./pages/LandingPage.vue";\n'
            "</script>\n"
        )
    elif legacy_landing.exists():
        desired_app = (
            "<template>\n  <LandingPage />\n</template>\n\n"
            "<script setup lang=\"ts\">\n"
            'import LandingPage from "./LandingPage.vue";\n'
            "</script>\n"
        )
    else:
        desired_app = app_fallback

    current_app = _read_text(app_vue)
    if current_app != desired_app:
        app_vue.parent.mkdir(parents=True, exist_ok=True)
        app_vue.write_text(desired_app, encoding="utf-8")
        repairs.append("apps/web/src/App.vue (runtime_shell_reconciled)")

    runtime_contracts = repo_root / "runtime-contracts"
    runtime_contracts.mkdir(parents=True, exist_ok=True)
    topology_hash = runtime_contracts / "topology_hash.json"
    topology_target = (
        '{\n'
        '  "shell": "PageShell",\n'
        '  "zones": ["hero", "features", "testimonials", "cta"],\n'
        '  "foundation_version": 1\n'
        '}\n'
    )
    if not topology_hash.exists() or _read_text(topology_hash) != topology_target:
        topology_hash.write_text(topology_target, encoding="utf-8")
        repairs.append("runtime-contracts/topology_hash.json (foundation_bootstrap)")
    manifest = runtime_contracts / "component-manifest.json"
    manifest_target = json.dumps(_build_component_manifest(repo_root), indent=2) + "\n"
    if not manifest.exists() or _read_text(manifest) != manifest_target:
        manifest.write_text(manifest_target, encoding="utf-8")
        repairs.append("runtime-contracts/component-manifest.json (foundation_bootstrap)")
    foundation_version = runtime_contracts / "foundation_version.json"
    foundation_target = (
        '{\n'
        '  "foundation_version": 1,\n'
        '  "template": "frontend-foundation",\n'
        '  "framework": "vue-vite-tailwind"\n'
        '}\n'
    )
    if not foundation_version.exists() or _read_text(foundation_version) != foundation_target:
        foundation_version.write_text(foundation_target, encoding="utf-8")
        repairs.append("runtime-contracts/foundation_version.json (foundation_bootstrap)")
    return repairs
