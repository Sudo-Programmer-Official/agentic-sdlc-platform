from __future__ import annotations

import re
from dataclasses import dataclass

from app.runtime.content_binding.binding_registry import BindingEntry


@dataclass(slots=True)
class RewriteResult:
    content: str
    applied_keys: list[str]


_TEXT_NODE_RE = re.compile(r">\s*([^<\n][^<]{2,}?)\s*<")


def rewrite_with_content_slots(content: str, bindings: list[BindingEntry]) -> RewriteResult:
    if not bindings:
        return RewriteResult(content=content, applied_keys=[])

    rewritten = content
    applied: list[str] = []

    # Rewrite plain text nodes into <ContentSlot ... /> wrappers.
    for entry in bindings:
        escaped = re.escape(entry.value)
        node_pattern = re.compile(rf">\s*{escaped}\s*<")
        if node_pattern.search(rewritten):
            slot = f'><ContentSlot content-key="{entry.key}" fallback="{entry.value}" /><'
            rewritten = node_pattern.sub(slot, rewritten, count=1)
            applied.append(entry.key)
            continue

    return RewriteResult(content=rewritten, applied_keys=applied)


def validate_binding_rewrite(content: str, bindings: list[BindingEntry]) -> list[str]:
    violations: list[str] = []
    keys = [entry.key for entry in bindings]
    if len(keys) != len(set(keys)):
        violations.append("duplicate content keys generated")

    for entry in bindings:
        if entry.key not in content:
            violations.append(f"missing registry binding usage for key {entry.key}")

    if content.count("<ContentSlot") < sum(1 for _ in bindings):
        violations.append("malformed ContentSlot wrappers or missing slot insertions")

    scrubbed = re.sub(r'fallback="[^"]*"', 'fallback=""', content)
    long_literals = [entry.value for entry in bindings if len(entry.value) >= 40 and entry.value in scrubbed]
    if long_literals:
        violations.append("large user-facing literals remain after rewrite")

    return violations
