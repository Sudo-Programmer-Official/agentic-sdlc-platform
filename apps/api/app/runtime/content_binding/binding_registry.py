from __future__ import annotations

import re
from dataclasses import dataclass

from app.runtime.content_binding.literal_extractor import ExtractedLiteral


@dataclass(slots=True)
class BindingEntry:
    key: str
    value: str
    source: str


def _slugify(text: str, *, limit: int = 5) -> str:
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    if not tokens:
        return "content"
    return "_".join(tokens[:limit])


def build_binding_registry(*, rel_path: str, literals: list[ExtractedLiteral]) -> list[BindingEntry]:
    path_slug = _slugify(rel_path.replace("/", " ").replace(".", " "), limit=4)
    entries: list[BindingEntry] = []
    used: set[str] = set()
    for idx, literal in enumerate(literals, start=1):
        text_slug = _slugify(literal.text)
        base = f"{path_slug}.{text_slug}"
        key = base
        counter = 2
        while key in used:
            key = f"{base}_{counter}"
            counter += 1
        used.add(key)
        entries.append(BindingEntry(key=key, value=literal.text, source=literal.source))
    return entries
