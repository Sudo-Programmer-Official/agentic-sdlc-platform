from __future__ import annotations

import re
from dataclasses import dataclass

_TEXT_NODE_RE = re.compile(r">\s*([^<\n][^<]{2,}?)\s*<")
_STYLE_SCRIPT_BLOCK_RE = re.compile(r"<(style|script)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

_SKIP_TEXT_PATTERNS = (
    re.compile(r"^\s*$"),
    re.compile(r"^[\d\s.,:%$+-]+$"),
    re.compile(r"^[{}()[\];,:._/#@!?'\"`~|\\-]+$"),
)


@dataclass(slots=True)
class ExtractedLiteral:
    text: str
    source: str  # text_node | attribute


def _looks_extractable(text: str) -> bool:
    cleaned = " ".join(text.split())
    if len(cleaned) < 4:
        return False
    for pattern in _SKIP_TEXT_PATTERNS:
        if pattern.match(cleaned):
            return False
    return any(ch.isalpha() for ch in cleaned)


def extract_literals(content: str) -> list[ExtractedLiteral]:
    literals: list[ExtractedLiteral] = []
    if not isinstance(content, str) or not content.strip():
        return literals

    # Do not extract bindings from CSS/JS bodies or comments; these are
    # implementation details and produce malformed ContentSlot rewrites.
    normalized = _STYLE_SCRIPT_BLOCK_RE.sub(" ", content)
    normalized = _HTML_COMMENT_RE.sub(" ", normalized)

    for match in _TEXT_NODE_RE.finditer(normalized):
        text = " ".join(match.group(1).split())
        if _looks_extractable(text):
            literals.append(ExtractedLiteral(text=text, source="text_node"))

    seen: set[tuple[str, str]] = set()
    deduped: list[ExtractedLiteral] = []
    for literal in literals:
        key = (literal.text, literal.source)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(literal)
    return deduped
