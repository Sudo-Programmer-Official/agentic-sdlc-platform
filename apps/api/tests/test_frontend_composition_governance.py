from types import SimpleNamespace
from pathlib import Path

from app.runtime.frontend_composition_governance import (
    evaluate_frontend_composition_governance,
    evaluate_frontend_foundation_governance,
)


def _write(path: str, content: str):
    return SimpleNamespace(type="write_file", path=path, content=content)


def test_frontend_composition_governance_accepts_bounded_responsive_section():
    actions = [
        _write(
            "apps/web/src/components/landing/TestimonialsSection.vue",
            """
<template>
  <section class=\"overflow-hidden py-16\">
    <div class=\"mx-auto max-w-6xl px-4 sm:px-6 lg:px-8\">
      <div class=\"grid gap-6 md:grid-cols-3\">
        <article class=\"rounded-xl border p-6\">
          <h3 class=\"text-xl font-semibold\">Ava</h3>
          <p class=\"text-sm\">Growth Lead, Nova</p>
          <p class=\"text-base\">Great product experience.</p>
          <svg class=\"w-8 h-8\" viewBox=\"0 0 24 24\"></svg>
        </article>
        <article class=\"rounded-xl border p-6\">
          <h3 class=\"text-xl font-semibold\">Liam</h3>
          <p class=\"text-sm\">VP Marketing, Orbit</p>
          <p class=\"text-base\">Our conversion quality improved.</p>
          <svg class=\"w-8 h-8\" viewBox=\"0 0 24 24\"></svg>
        </article>
        <article class=\"rounded-xl border p-6\">
          <h3 class=\"text-xl font-semibold\">Mia</h3>
          <p class=\"text-sm\">Founder, Cedar</p>
          <p class=\"text-base\">Faster launches, cleaner handoff.</p>
          <svg class=\"w-8 h-8\" viewBox=\"0 0 24 24\"></svg>
        </article>
      </div>
    </div>
  </section>
</template>
""",
        )
    ]

    assessment = evaluate_frontend_composition_governance(actions=actions, enforce=True)

    assert assessment.violations == []
    assert assessment.layout_integrity_score >= 0.9
    assert assessment.responsive_safety_score >= 0.9
    assert assessment.overflow_risk_score <= 0.1
    assert assessment.typography_consistency_score >= 0.9
    assert assessment.visual_composition_score >= 0.85


def test_frontend_composition_governance_flags_oversized_unbounded_layout():
    actions = [
        _write(
            "apps/web/src/components/landing/TestimonialsSection.vue",
            """
<template>
  <section>
    <div style=\"color:#fff\">
      <svg width=\"5000\" height=\"5000\"></svg>
      <div class=\"w-[3000px] h-[2000px]\">Oversized</div>
      <p>No responsive classes</p>
    </div>
  </section>
</template>
""",
        )
    ]

    assessment = evaluate_frontend_composition_governance(actions=actions, enforce=True)

    assert any("inline style attributes are disallowed" in item for item in assessment.violations)
    assert any("missing responsive container/max-width wrapper" in item for item in assessment.violations)
    assert any("missing responsive breakpoint classes" in item for item in assessment.violations)
    assert any("oversized arbitrary dimension" in item for item in assessment.violations)
    assert any("unbounded SVG dimension" in item for item in assessment.violations)
    assert assessment.visual_composition_score < 0.6


def test_frontend_composition_governance_enforce_false_is_non_blocking():
    actions = [_write("apps/web/src/components/landing/TestimonialsSection.vue", "<template><section /></template>")]

    assessment = evaluate_frontend_composition_governance(actions=actions, enforce=False)

    assert assessment.violations == []
    assert assessment.layout_integrity_score == 1.0
    assert assessment.responsive_safety_score == 1.0
    assert assessment.overflow_risk_score == 0.0
    assert assessment.typography_consistency_score == 1.0
    assert assessment.visual_composition_score == 1.0


def test_frontend_foundation_governance_accepts_complete_shell():
    actions = [
        _write("apps/web/src/components/layout/Navbar.vue", "<template><nav class='mx-auto max-w-6xl sm:px-6'>Nav</nav></template>"),
        _write("apps/web/src/components/layout/Footer.vue", "<template><footer class='mx-auto max-w-6xl'>Footer</footer></template>"),
        _write("apps/web/src/layouts/PageShell.vue", "<template><div class='mx-auto max-w-6xl px-4 sm:px-6 text-base'><slot /></div></template>"),
        _write("apps/web/src/components/layout/SectionContainer.vue", "<template><section class='py-16'><slot /></section></template>"),
        _write(
            "apps/web/src/pages/LandingPage.vue",
            "<template><PageShell><HeroZone /><FeatureZone /><TestimonialsZone /><CTAZone /><Footer /></PageShell></template>",
        ),
    ]

    assessment = evaluate_frontend_foundation_governance(actions=actions, enforce=True)

    assert assessment.violations == []
    assert assessment.foundation_layout_score == 1.0
    assert assessment.navigation_integrity == 1.0
    assert assessment.responsive_shell_score >= 0.9
    assert assessment.design_system_score >= 0.5


def test_testimonials_section_flags_missing_governed_primitive_file(tmp_path: Path):
    actions = [
        _write(
            "apps/web/src/components/landing/TestimonialsSection.vue",
            """
<template>
  <SectionContainer>
    <SectionHeading>What Our Customers Say</SectionHeading>
    <ContentGrid :columns=\"1\" md:columns=\"3\" gap=\"lg\">
      <TestimonialCard v-for=\"(testimonial, idx) in testimonials\" :key=\"idx\" :name=\"testimonial.name\" :role=\"testimonial.role\" :quote=\"testimonial.quote\" />
    </ContentGrid>
  </SectionContainer>
</template>
<script setup lang=\"ts\">
import SectionContainer from \"../layout/SectionContainer.vue\";
import SectionHeading from \"../layout/SectionHeading.vue\";
import ContentGrid from \"../layout/ContentGrid.vue\";
import TestimonialCard from \"../layout/TestimonialCard.vue\";
const testimonials = [{ name: \"A\", role: \"R\", quote: \"Q\" }, { name: \"B\", role: \"R\", quote: \"Q\" }, { name: \"C\", role: \"R\", quote: \"Q\" }];
</script>
""",
        )
    ]

    repo_root = tmp_path
    (repo_root / "apps/web/src/components/layout").mkdir(parents=True, exist_ok=True)
    (repo_root / "apps/web/src/components/layout/SectionContainer.vue").write_text("<template><section><slot/></section></template>")
    (repo_root / "apps/web/src/components/layout/SectionHeading.vue").write_text("<template><h2><slot/></h2></template>")
    (repo_root / "apps/web/src/components/layout/ContentGrid.vue").write_text("<template><div><slot/></div></template>")
    # Intentionally leave out TestimonialCard.vue

    assessment = evaluate_frontend_composition_governance(actions=actions, enforce=True, repo_root=repo_root)
    assert any("Primitive registry validation failed" in item for item in assessment.violations)


def test_testimonials_section_flags_title_only_empty_composition():
    actions = [
        _write(
            "apps/web/src/components/landing/TestimonialsSection.vue",
            """
<template>
  <section class=\"py-12\">
    <h2 class=\"text-3xl font-bold\">What Our Customers Say</h2>
  </section>
</template>
""",
        )
    ]

    assessment = evaluate_frontend_composition_governance(actions=actions, enforce=True)
    assert any("Visible content validation failed" in item for item in assessment.violations)
