from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_RESPONSIVE_HINT_RE = re.compile(r"\b(sm:|md:|lg:|xl:|2xl:)\b")
_MAX_WIDTH_RE = re.compile(r"\bmax-w-[\w-]+\b")
_CONTAINER_RE = re.compile(r"\b(container|max-w-[\w-]+)\b")
_CENTER_RE = re.compile(r"\bmx-auto\b")
_SPACING_RE = re.compile(r"\b(p[xytrbl]?|m[xytrbl]?)-\d+\b")
_TYPO_RE = re.compile(r"\b(text-(xs|sm|base|lg|xl|2xl|3xl|4xl)|font-(bold|semibold|medium))\b")
_GRID_FLEX_RE = re.compile(r"\b(grid|flex)\b")
_OVERFLOW_SAFE_RE = re.compile(r"\boverflow-(hidden|x-hidden|clip)\b")
_ARBITRARY_GIANT_RE = re.compile(r"\b(?:w|h|min-w|min-h|max-w|max-h)-\[(\d+)(px|rem|vh|vw)\]")
_SVG_GIANT_RE = re.compile(r"<svg\b[^>]*\b(?:width|height)\s*=\s*\"(\d{4,})\"", re.IGNORECASE)
_SVG_CLASS_RE = re.compile(r"<svg\b[^>]*class\s*=\s*\"([^\"]*)\"", re.IGNORECASE)
_STYLE_ATTR_RE = re.compile(r"\bstyle\s*=", re.IGNORECASE)
_SCRIPT_IMPORT_RE = re.compile(r"import\s+([A-Za-z_][A-Za-z0-9_]*)\s+from\s+[\"']([^\"']+)[\"']")
_TAG_RE = re.compile(r"<([A-Z][A-Za-z0-9_]*)\b")

_TESTIMONIAL_PRIMITIVES = ("SectionContainer", "SectionHeading", "ContentGrid", "TestimonialCard")


@dataclass(frozen=True)
class FrontendCompositionAssessment:
    violations: list[str]
    layout_integrity_score: float
    responsive_safety_score: float
    overflow_risk_score: float
    typography_consistency_score: float
    visual_composition_score: float


@dataclass(frozen=True)
class FrontendFoundationAssessment:
    violations: list[str]
    foundation_layout_score: float
    navigation_integrity: float
    responsive_shell_score: float
    design_system_score: float


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _normalized(path: str) -> str:
    return path.replace("\\", "/").strip()


def _is_frontend_vue(path: str) -> bool:
    p = _normalized(path).lower()
    return p.endswith(".vue") and (p.startswith("apps/web/src/") or p.startswith("src/"))


def _resolve_local_import(path: str, source: str) -> str | None:
    src = str(source or "").strip()
    if not src:
        return None
    base = Path(_normalized(path)).parent
    if src.startswith("@/"):
        return _normalized(str(Path("apps/web/src") / src[2:]))
    if src.startswith("."):
        return _normalized(str(base / src))
    return None


def evaluate_frontend_composition_governance(
    *,
    actions: list[Any],
    enforce: bool = True,
    repo_root: Path | None = None,
) -> FrontendCompositionAssessment:
    if not enforce:
        return FrontendCompositionAssessment([], 1.0, 1.0, 0.0, 1.0, 1.0)

    violations: list[str] = []
    files_seen = 0
    container_hits = 0
    responsive_hits = 0
    overflow_hits = 0
    spacing_hits = 0
    typo_hits = 0
    giant_hits = 0
    hierarchy_hits = 0
    written_content_by_path: dict[str, str] = {}

    for action in actions:
        if getattr(action, "type", None) != "write_file":
            continue
        path = str(getattr(action, "path", "") or "")
        content = getattr(action, "content", None)
        if not _is_frontend_vue(path) or not isinstance(content, str):
            continue
        norm_path = _normalized(path)
        written_content_by_path[norm_path] = content
        files_seen += 1
        compact = content.replace("\n", " ")
        component_tags = set(_TAG_RE.findall(content))

        if _STYLE_ATTR_RE.search(compact):
            violations.append(f"Layout governance violation in {path}: inline style attributes are disallowed.")

        if _CONTAINER_RE.search(compact):
            container_hits += 1
        else:
            violations.append(f"Layout governance violation in {path}: missing responsive container/max-width wrapper.")

        if _CENTER_RE.search(compact):
            container_hits += 1
        else:
            violations.append(f"Layout governance violation in {path}: missing horizontal centering (mx-auto).")

        if _RESPONSIVE_HINT_RE.search(compact):
            responsive_hits += 1
        else:
            violations.append(f"Layout governance violation in {path}: missing responsive breakpoint classes.")

        if _SPACING_RE.search(compact):
            spacing_hits += 1
        else:
            violations.append(f"Layout governance violation in {path}: missing spacing rhythm utilities (p*/m*).")

        if _TYPO_RE.search(compact):
            typo_hits += 1
        else:
            violations.append(f"Layout governance violation in {path}: missing typography hierarchy utilities.")

        if _GRID_FLEX_RE.search(compact):
            hierarchy_hits += 1
        else:
            violations.append(f"Layout governance violation in {path}: missing flex/grid composition hierarchy.")

        has_overflow_safe = bool(_OVERFLOW_SAFE_RE.search(compact))
        has_large_visual = bool(re.search(r"\b(w|h)-(\d{3,}|screen)\b", compact)) or bool(_SVG_CLASS_RE.search(compact))
        if has_overflow_safe or not has_large_visual:
            overflow_hits += 1
        else:
            violations.append(f"Layout governance violation in {path}: potential overflow without overflow safety guard.")

        for m in _ARBITRARY_GIANT_RE.findall(compact):
            num = int(m[0])
            unit = m[1]
            limit = 1200 if unit == "px" else 120
            if num > limit:
                giant_hits += 1
                violations.append(f"Tailwind governance violation in {path}: oversized arbitrary dimension {num}{unit}.")

        for m in _SVG_GIANT_RE.findall(compact):
            giant_hits += 1
            violations.append(f"Layout governance violation in {path}: unbounded SVG dimension {m}.")

        for class_match in _SVG_CLASS_RE.findall(compact):
            if not re.search(r"\b(w-\d+|h-\d+|size-\d+)\b", class_match):
                violations.append(f"Layout governance violation in {path}: svg missing explicit bounded size class.")

        if not _MAX_WIDTH_RE.search(compact) and "container" not in compact:
            violations.append(f"Tailwind governance violation in {path}: missing max-width/container utility.")

        if norm_path.lower().endswith("/components/landing/testimonialssection.vue"):
            imported: dict[str, str] = {}
            for symbol, src in _SCRIPT_IMPORT_RE.findall(content):
                imported[symbol] = src
            used_primitives = [name for name in _TESTIMONIAL_PRIMITIVES if name in component_tags]
            for primitive in used_primitives:
                rel_import = _resolve_local_import(norm_path, imported.get(primitive, ""))
                if rel_import is None:
                    violations.append(
                        f"Visible content validation failed in {path}: {primitive} is used but not imported from a local, verifiable path."
                    )
                    continue
                exists_in_write_set = rel_import in written_content_by_path
                exists_on_disk = bool(repo_root and (repo_root / rel_import).exists())
                if not exists_in_write_set and not exists_on_disk:
                    violations.append(
                        f"Primitive registry validation failed in {path}: imported primitive {primitive} is missing at {rel_import}."
                    )

            # Ensure testimonial content is visibly renderable without relying on opaque wrappers.
            has_direct_quote = "testimonial.quote" in content or "quote" in content.lower()
            has_direct_name = "testimonial.name" in content or "name" in content.lower()
            has_direct_role = "testimonial.role" in content or "role" in content.lower() or "company" in content.lower()
            article_nodes = len(re.findall(r"<article\b[^>]*>", content, re.IGNORECASE))
            testimonial_card_nodes = len(re.findall(r"<(article|div)\b[^>]*>", content, re.IGNORECASE))
            testimonial_uses_vfor = "v-for" in content and "testimonial" in content
            static_cards_look_complete = (
                article_nodes >= 3
                and bool(re.search(r"<h[23]\b", content, re.IGNORECASE))
                and len(re.findall(r"<p\b", content, re.IGNORECASE)) >= 3
            )
            if "TestimonialCard" in component_tags:
                if not (has_direct_quote and has_direct_name and has_direct_role):
                    violations.append(
                        f"Visible content validation failed in {path}: testimonial quote/name/role text is not reachable in section markup."
                    )
            elif not static_cards_look_complete:
                violations.append(
                    f"Visible content validation failed in {path}: testimonial cards are not visibly composed (need 3 card nodes with name/role/quote content)."
                )
            if testimonial_card_nodes < 3 and not testimonial_uses_vfor:
                violations.append(
                    f"Visible content validation failed in {path}: expected at least 3 testimonial card nodes or a testimonial v-for loop."
                )
            if re.search(r"(^|[\s\"'])(hidden|h-0|min-h-0|max-h-0)([\s\"']|$)", compact):
                violations.append(
                    f"Visible content validation failed in {path}: zero-height/hidden container classes detected."
                )

    if files_seen == 0:
        return FrontendCompositionAssessment([], 1.0, 1.0, 0.0, 1.0, 1.0)

    layout_integrity = _clamp01((container_hits + spacing_hits + hierarchy_hits) / (files_seen * 4))
    responsive_safety = _clamp01((responsive_hits + overflow_hits) / (files_seen * 2))
    typography_consistency = _clamp01(typo_hits / files_seen)
    overflow_risk = _clamp01((giant_hits + max(0, files_seen - overflow_hits)) / (files_seen * 2))
    visual_composition = _clamp01(
        0.32 * layout_integrity
        + 0.24 * responsive_safety
        + 0.18 * typography_consistency
        + 0.26 * (1.0 - overflow_risk)
    )

    return FrontendCompositionAssessment(
        violations=violations,
        layout_integrity_score=layout_integrity,
        responsive_safety_score=responsive_safety,
        overflow_risk_score=overflow_risk,
        typography_consistency_score=typography_consistency,
        visual_composition_score=visual_composition,
    )


def evaluate_frontend_foundation_governance(*, actions: list[Any], enforce: bool = True) -> FrontendFoundationAssessment:
    if not enforce:
        return FrontendFoundationAssessment([], 1.0, 1.0, 1.0, 1.0)

    written_files: dict[str, str] = {}
    for action in actions:
        if getattr(action, "type", None) != "write_file":
            continue
        path = str(getattr(action, "path", "") or "").replace("\\", "/").strip()
        content = getattr(action, "content", None)
        if not path or not isinstance(content, str):
            continue
        written_files[path] = content

    violations: list[str] = []
    shell_files = {
        "apps/web/src/components/layout/Navbar.vue",
        "apps/web/src/components/layout/Footer.vue",
        "apps/web/src/layouts/PageShell.vue",
        "apps/web/src/components/layout/SectionContainer.vue",
        "apps/web/src/pages/LandingPage.vue",
    }
    existing_shell = sum(1 for path in shell_files if path in written_files)
    layout_score = _clamp01(existing_shell / len(shell_files))

    landing = written_files.get("apps/web/src/pages/LandingPage.vue", "")
    if not landing:
        violations.append("Foundation quality violation: LandingPage skeleton is missing.")
    else:
        required_placeholders = {
            "HeroZone",
            "FeatureZone",
            "TestimonialsZone",
            "CTAZone",
            "Footer",
        }
        missing = [token for token in required_placeholders if f"<{token}" not in landing]
        if missing:
            violations.append(
                "Foundation quality violation: LandingPage missing placeholders/components: " + ", ".join(missing) + "."
            )

    navbar = written_files.get("apps/web/src/components/layout/Navbar.vue", "")
    footer = written_files.get("apps/web/src/components/layout/Footer.vue", "")
    navigation_integrity = 1.0 if navbar and footer else (0.5 if navbar or footer else 0.0)
    if navigation_integrity < 1.0:
        violations.append("Foundation quality violation: navigation shell incomplete (Navbar/Footer required).")

    shell_candidates = [
        written_files.get("apps/web/src/layouts/PageShell.vue", ""),
        written_files.get("apps/web/src/pages/LandingPage.vue", ""),
    ]
    shell_text = " ".join(shell_candidates)
    has_container = bool(_CONTAINER_RE.search(shell_text))
    has_center = bool(_CENTER_RE.search(shell_text))
    has_responsive = bool(_RESPONSIVE_HINT_RE.search(shell_text))
    responsive_shell_score = _clamp01(sum(int(x) for x in (has_container, has_center, has_responsive)) / 3.0)
    if not has_container:
        violations.append("Foundation quality violation: container wrappers missing from shell.")
    if not has_responsive:
        violations.append("Foundation quality violation: responsive shell breakpoints missing.")

    has_spacing = bool(_SPACING_RE.search(shell_text))
    has_typography = bool(_TYPO_RE.search(shell_text))
    design_system_score = _clamp01(sum(int(x) for x in (has_spacing, has_typography)) / 2.0)
    if not has_spacing:
        violations.append("Foundation quality violation: spacing system utilities missing.")
    if not has_typography:
        violations.append("Foundation quality violation: typography scale utilities missing.")

    return FrontendFoundationAssessment(
        violations=violations,
        foundation_layout_score=layout_score,
        navigation_integrity=navigation_integrity,
        responsive_shell_score=responsive_shell_score,
        design_system_score=design_system_score,
    )
