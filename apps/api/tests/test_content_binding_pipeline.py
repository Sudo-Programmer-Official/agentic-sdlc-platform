from app.runtime.content_binding.literal_extractor import extract_literals
from app.runtime.content_binding.binding_registry import build_binding_registry
from app.runtime.content_binding.binding_registry import BindingEntry
from app.runtime.content_binding.slot_rewriter import rewrite_with_content_slots, validate_binding_rewrite


def test_literal_extraction_and_slot_rewrite():
    content = """
    <section>
      <h1>Ready to Accelerate Your Workflow?</h1>
      <p>Ship governed updates faster with runtime controls.</p>
      <button>Start Free</button>
    </section>
    """
    literals = extract_literals(content)
    assert len(literals) >= 3

    bindings = build_binding_registry(rel_path="apps/web/src/views/PublicLanding.vue", literals=literals)
    assert bindings

    rewritten = rewrite_with_content_slots(content, bindings)
    assert "<ContentSlot content-key=" in rewritten.content

    violations = validate_binding_rewrite(rewritten.content, bindings)
    assert not violations


def test_slot_rewrite_uses_bound_fallback_for_quoted_text():
    content = '<blockquote>He said "ship faster"</blockquote>'
    bindings = [BindingEntry(key="quote", value='He said "ship faster"', source="text")]
    rewritten = rewrite_with_content_slots(content, bindings)
    assert '<ContentSlot content-key="quote" :fallback=' in rewritten.content
    assert 'fallback="He said "ship faster""' not in rewritten.content


def test_slot_rewrite_converts_moustache_fallback_to_expression_binding():
    content = "<blockquote>{{ testimonial.quote }}</blockquote>"
    bindings = [BindingEntry(key="quote_dynamic", value="{{ testimonial.quote }}", source="text")]
    rewritten = rewrite_with_content_slots(content, bindings)
    assert ':fallback="testimonial.quote"' in rewritten.content
