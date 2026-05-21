from app.runtime.frontend_topology_engine import (
    DEFAULT_LANDING_TOPOLOGY,
    normalize_landing_graph_content,
    semantic_mutation_plan,
    validate_graph_integrity,
)


def test_semantic_mutation_plan_targets_testimonials_zone():
    plan = semantic_mutation_plan(task_text="Add testimonials section", topology=DEFAULT_LANDING_TOPOLOGY)
    assert plan["mutation_type"] == "composition_insert"
    assert plan["target_zone"] == "testimonials"


def test_normalize_landing_graph_content_restores_required_zones():
    content = "<template><PageShell><section>generated</section></PageShell></template>"
    normalized, warnings, ok = normalize_landing_graph_content(
        content=content,
        topology=DEFAULT_LANDING_TOPOLOGY,
        stability_mode=True,
    )
    assert ok
    assert not warnings
    assert "<HeroZone>" in normalized
    assert "<FeatureZone>" in normalized
    assert "<TestimonialsZone>" in normalized
    assert "<CTAZone>" in normalized


def test_validate_graph_integrity_detects_missing_required_zone():
    content = "<template><PageShell><HeroZone /></PageShell></template>"
    violations = validate_graph_integrity(
        content=content,
        topology=DEFAULT_LANDING_TOPOLOGY,
        stability_mode=True,
    )
    assert any(item.startswith("zone_missing:") for item in violations)
