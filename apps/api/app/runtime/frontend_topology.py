from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_ALLOWED_PREFIXES = (
    "src/components/",
    "src/sections/",
    "src/layouts/",
    "src/pages/",
    "src/styles/",
    "src/content/",
    "src/contracts/",
    "apps/web/src/components/",
    "apps/web/src/sections/",
    "apps/web/src/layouts/",
    "apps/web/src/pages/",
    "apps/web/src/styles/",
    "apps/web/src/content/",
    "apps/web/src/contracts/",
    # transitional compatibility with current repo
    "apps/web/src/views/",
    "src/views/",
)

_ALLOWED_ROOT_FILES = {
    "index.html",
    "apps/web/index.html",
    "src/main.ts",
    "apps/web/src/main.ts",
    "src/app.vue",
    "apps/web/src/app.vue",
}

_FRONTEND_SUFFIXES = {".vue", ".ts", ".tsx", ".js", ".jsx", ".css", ".scss", ".html"}


def _is_frontend_path(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in _FRONTEND_SUFFIXES


def _normalized(path: str) -> str:
    return path.strip().replace("\\", "/")


def validate_frontend_topology(*, actions: list[Any], enforce: bool = True) -> list[str]:
    if not enforce:
        return []
    violations: list[str] = []

    for action in actions:
        action_type = getattr(action, "type", None)
        if action_type != "write_file":
            continue
        raw_path = getattr(action, "path", None)
        content = getattr(action, "content", None)
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        path = _normalized(raw_path)
        if not _is_frontend_path(path):
            continue

        if "/" not in path and path not in _ALLOWED_ROOT_FILES:
            violations.append(
                f"Frontend topology violation: root-level file '{path}' is not allowed. "
                "Use src/components|sections|layouts|pages|styles|content|contracts."
            )

        if "/" in path and not path.startswith(_ALLOWED_PREFIXES) and path not in _ALLOWED_ROOT_FILES:
            violations.append(
                f"Frontend topology violation: '{path}' is outside governed frontend folders. "
                "Allowed: src/components, src/sections, src/layouts, src/pages, src/styles, src/content, src/contracts."
            )

        if not isinstance(content, str):
            continue

        line_count = content.count("\n") + (1 if content else 0)
        style_attrs = len(re.findall(r"\bstyle\s*=", content, flags=re.IGNORECASE))
        section_count = len(re.findall(r"<section\b", content, flags=re.IGNORECASE))
        style_block_chars = sum(len(m.group(0)) for m in re.finditer(r"<style[\s\S]*?</style>", content, flags=re.IGNORECASE))
        has_component_tags = bool(re.search(r"<[A-Z][A-Za-z0-9_]*\b", content))
        has_token_usage = "var(--" in content or "--" in content

        if path in {"index.html", "apps/web/index.html", "src/app.vue", "apps/web/src/app.vue"}:
            if (line_count > 260 and section_count >= 6) or (section_count >= 8 and style_block_chars > 1500):
                violations.append(
                    f"Frontend topology violation: {path} appears as a single-file app dump "
                    f"({line_count} lines, {section_count} sections). Compose via governed components."
                )
            if style_attrs >= 8 or style_block_chars > 2500:
                violations.append(
                    f"Frontend topology violation: {path} contains inline CSS dump patterns. "
                    "Move styles to src/styles and tokenized classes."
                )
            if line_count > 140 and not has_component_tags:
                violations.append(
                    f"Frontend topology violation: {path} lacks component composition markers for a large root file."
                )
            if style_block_chars > 1200 and not has_token_usage:
                violations.append(
                    f"Frontend topology violation: {path} large style blocks must use design tokens/CSS variables."
                )

    return violations
