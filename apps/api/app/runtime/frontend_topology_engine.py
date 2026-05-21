from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class FrontendZone:
    id: str
    zone_component: str
    semantic_type: str
    default_component: str
    required: bool


@dataclass(frozen=True)
class FrontendTopology:
    layout: str
    shell: str
    zones: tuple[FrontendZone, ...]


DEFAULT_LANDING_TOPOLOGY = FrontendTopology(
    layout="landing",
    shell="PageShell",
    zones=(
        FrontendZone("hero", "HeroZone", "marketing", "HeroPlaceholder", True),
        FrontendZone("feature", "FeatureZone", "feature", "FeaturePlaceholder", True),
        FrontendZone("testimonials", "TestimonialsZone", "social-proof", "TestimonialsPlaceholder", True),
        FrontendZone("cta", "CTAZone", "conversion", "CTAPlaceholder", True),
    ),
)


_ZONE_INNER_RE = re.compile(
    r"<(?P<zone>HeroZone|FeatureZone|TestimonialsZone|CTAZone)\b[^>]*>(?P<body>.*?)</(?P=zone)>",
    re.IGNORECASE | re.DOTALL,
)


def _first_component_markup(content: str, component_name: str) -> str | None:
    token = re.escape(component_name)
    paired = re.search(rf"<{token}\b[^>]*>.*?</{token}>", content, flags=re.IGNORECASE | re.DOTALL)
    if paired:
        return paired.group(0).strip()
    self_closing = re.search(rf"<{token}\b[^>]*/>", content, flags=re.IGNORECASE)
    if self_closing:
        return self_closing.group(0).strip()
    return None


def semantic_mutation_plan(*, task_text: str, topology: FrontendTopology) -> dict[str, Any]:
    text = (task_text or "").lower()
    for zone in topology.zones:
        if zone.id in text or zone.semantic_type in text:
            return {
                "mutation_type": "composition_insert",
                "target_zone": zone.id,
                "target_graph": topology.layout,
                "allowed_nodes": [zone.zone_component],
                "protected_nodes": [topology.shell],
            }
    return {
        "mutation_type": "composition_insert",
        "target_zone": topology.zones[0].id,
        "target_graph": topology.layout,
        "allowed_nodes": [topology.zones[0].zone_component],
        "protected_nodes": [topology.shell],
    }


def validate_graph_integrity(*, content: str, topology: FrontendTopology, stability_mode: bool) -> list[str]:
    violations: list[str] = []
    has_shell = f"<{topology.shell}" in content
    if not has_shell and not stability_mode:
        violations.append(f"shell_missing:{topology.shell}")
    for zone in topology.zones:
        if zone.required and f"<{zone.zone_component}" not in content:
            violations.append(f"zone_missing:{zone.id}")
    return violations


def normalize_landing_graph_content(
    *,
    content: str,
    topology: FrontendTopology,
    stability_mode: bool,
) -> tuple[str, list[str], bool]:
    if not isinstance(content, str) or not content.strip():
        return content, ["normalization_failed:empty_content"], False

    warnings: list[str] = []
    source = content
    zone_bodies: dict[str, str] = {}
    for match in _ZONE_INNER_RE.finditer(source):
        zone_component = str(match.group("zone") or "").strip()
        body = str(match.group("body") or "").strip()
        if zone_component and body:
            zone_bodies[zone_component.lower()] = body

    zone_component_inference: dict[str, list[str]] = {
        "hero": ["HeroSection"],
        "feature": [
            "FeatureSection",
            "FeaturesSection",
            "ProblemSolutionSection",
            "CapabilitiesGridSection",
            "HowItWorksSection",
            "ROICalculatorSection",
            "ProofSection",
            "PricingSection",
        ],
        "testimonials": ["TestimonialsSection"],
        "cta": ["CTASection", "LeadCaptureSection"],
    }
    blocks: list[str] = []
    for zone in topology.zones:
        key = zone.zone_component.lower()
        body = zone_bodies.get(key)
        if not body:
            for component_name in zone_component_inference.get(zone.id, []):
                inferred = _first_component_markup(source, component_name)
                if inferred:
                    body = inferred
                    break
        if not body:
            body = f"<{zone.default_component} />"
        blocks.append(f"    <{zone.zone_component}>\n      {body}\n    </{zone.zone_component}>")
    zone_body = "\n".join(blocks)

    has_shell = f"<{topology.shell}" in source
    if has_shell:
        template = f"<template>\n  <{topology.shell}>\n{zone_body}\n  </{topology.shell}>\n</template>\n"
    else:
        if not stability_mode:
            return content, ["normalization_failed:shell_missing"], False
        warnings.append(f"[stability_mode] shell_missing:{topology.shell}")
        template = f"<template>\n  <main class=\"landing-page\">\n{zone_body}\n  </main>\n</template>\n"

    script_match = re.search(r"<script\b[^>]*>.*?</script>", source, flags=re.IGNORECASE | re.DOTALL)
    style_match = re.search(r"<style\b[^>]*>.*?</style>", source, flags=re.IGNORECASE | re.DOTALL)
    normalized = template
    if script_match:
        normalized += "\n" + script_match.group(0).strip() + "\n"
    if style_match:
        normalized += "\n" + style_match.group(0).strip() + "\n"

    if "<template>" not in normalized or "</template>" not in normalized:
        return content, ["normalization_failed:invalid_template"], False
    return normalized, warnings, True
