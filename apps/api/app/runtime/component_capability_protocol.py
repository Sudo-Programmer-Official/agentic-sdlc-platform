from __future__ import annotations

from typing import Any


_COMPONENT_CAPABILITIES: dict[str, dict[str, Any]] = {
    "HeroSection": {
        "tokens": ["--color-brand", "--color-text", "--space-xl"],
        "slots": ["title", "subtitle", "primaryCta", "secondaryCta"],
        "allowed_props": ["align", "tone", "density"],
        "variants": ["premium_saas", "enterprise", "technical"],
    },
    "PricingCard": {
        "tokens": ["--color-surface", "--color-accent", "--space-md"],
        "slots": ["title", "price", "description", "cta"],
        "allowed_props": ["plan", "highlighted", "billing"],
        "variants": ["simple", "comparison", "enterprise"],
    },
    "CTASection": {
        "tokens": ["--color-cta-bg", "--color-cta-text", "--radius-lg"],
        "slots": ["headline", "supportingText", "primaryCta"],
        "allowed_props": ["tone", "layout", "size"],
        "variants": ["inline", "panel", "banner"],
    },
    "FeatureGrid": {
        "tokens": ["--space-sm", "--space-md", "--space-lg"],
        "slots": ["items"],
        "allowed_props": ["columns", "iconStyle", "density"],
        "variants": ["cards", "list", "iconic"],
    },
    "ProblemSolutionSection": {
        "tokens": ["--color-muted", "--color-success", "--space-lg"],
        "slots": ["problem", "solution"],
        "allowed_props": ["layout", "emphasis", "arrowStyle"],
        "variants": ["split", "timeline", "paired"],
    },
}


def build_component_capability_packet(*, allowed_components: list[str], variant: str = "premium_saas") -> dict[str, Any]:
    allowed = [name for name in (allowed_components or []) if isinstance(name, str) and name.strip()]
    components: list[dict[str, Any]] = []
    for name in allowed:
        definition = _COMPONENT_CAPABILITIES.get(name)
        if not definition:
            continue
        chosen_variant = variant if variant in definition["variants"] else definition["variants"][0]
        components.append(
            {
                "capability": name,
                "variant": chosen_variant,
                "allowed_props": definition["allowed_props"],
                "slots": definition["slots"],
                "tokens": definition["tokens"],
            }
        )
    return {
        "mode": "governed_component_assembly",
        "components": components,
        "constraints": {
            "no_inline_section_invention": True,
            "compose_from_registry": True,
            "respect_allowed_props": True,
        },
    }


def resolve_component_capability(capability: str, *, variant: str = "premium_saas") -> dict[str, Any]:
    key = (capability or "").strip()
    definition = _COMPONENT_CAPABILITIES.get(key)
    if definition is None:
        raise ValueError("unknown component capability")
    chosen_variant = variant if variant in definition["variants"] else definition["variants"][0]
    return {
        "capability": key,
        "variant": chosen_variant,
        "allowed_props": definition["allowed_props"],
        "slots": definition["slots"],
        "tokens": definition["tokens"],
        "variants": definition["variants"],
    }
