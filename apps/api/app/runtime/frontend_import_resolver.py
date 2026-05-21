from __future__ import annotations

import re
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

CANONICAL_PRIMITIVE_REGISTRY: dict[str, str] = {
    "PrimaryButton": "apps/web/src/components/ui/PrimaryButton.vue",
    "CTAButton": "apps/web/src/components/ui/PrimaryButton.vue",
    "ActionButton": "apps/web/src/components/ui/PrimaryButton.vue",
    "SectionContainer": "apps/web/src/components/ui/SectionContainer.vue",
}

CANONICAL_COMPONENT_SEARCH_DIRS: tuple[str, ...] = (
    "apps/web/src/components/ui",
    "apps/web/src/components/layout",
    "apps/web/src/components/landing",
    "apps/web/src/components",
)

_MANIFEST_PATH = "runtime-contracts/component-manifest.json"

_ALIAS_TO_CANONICAL: dict[str, str] = {
    "PrimaryButton": "PrimaryButton",
    "CTAButton": "PrimaryButton",
    "ActionButton": "PrimaryButton",
}

_IMPORT_RE = re.compile(r"^(\s*import\s+)(.+?)(\s+from\s+)(['\"])([^'\"]+)(['\"])(\s*;?\s*)$", re.MULTILINE)
_TEMPLATE_COMPONENT_RE = re.compile(r"<([A-Z][A-Za-z0-9_]*)\b")


@dataclass(frozen=True)
class ImportNormalizationResult:
    content: str
    import_resolution_attempts: int
    resolved_component_imports: list[str]
    unresolved_component_imports: list[str]
    import_normalization_repairs: int


def _normalized_posix(path: str) -> str:
    return str(PurePosixPath(path.replace("\\", "/")))


def _relative_between(importing_file: str, target_file: str) -> str:
    importing_parts = PurePosixPath(importing_file).parent.parts
    target_parts = PurePosixPath(target_file).parts
    i = 0
    while i < min(len(importing_parts), len(target_parts)) and importing_parts[i] == target_parts[i]:
        i += 1
    up = [".."] * (len(importing_parts) - i)
    down = list(target_parts[i:])
    rel_parts = up + down
    rel = "/".join(rel_parts) if rel_parts else "."
    if not rel.startswith("."):
        rel = f"./{rel}"
    return rel


def _candidate_component_files(component_name: str) -> list[str]:
    canonical = _ALIAS_TO_CANONICAL.get(component_name, component_name)
    file_candidates = [f"{component_name}.vue"]
    if canonical == "PrimaryButton":
        file_candidates.append("Button.vue")
    if canonical != component_name:
        file_candidates.append(f"{canonical}.vue")
    dedup: list[str] = []
    for item in file_candidates:
        if item not in dedup:
            dedup.append(item)
    return dedup


def resolve_frontend_component_import(repo_root: Path, component_name: str, importing_file: str) -> str | None:
    manifest_registry = _load_manifest_registry(repo_root)
    canonical_key = _ALIAS_TO_CANONICAL.get(component_name, component_name)
    registry_target = manifest_registry.get(canonical_key) or CANONICAL_PRIMITIVE_REGISTRY.get(canonical_key)
    candidates: list[str] = []
    if registry_target:
        candidates.append(_normalized_posix(registry_target))

    file_names = _candidate_component_files(component_name)
    for base in CANONICAL_COMPONENT_SEARCH_DIRS:
        for file_name in file_names:
            candidates.append(_normalized_posix(f"{base}/{file_name}"))

    for rel_target in candidates:
        target_abs = repo_root / rel_target
        if target_abs.exists():
            return _relative_between(_normalized_posix(importing_file), rel_target)
    return None


def _load_manifest_registry(repo_root: Path) -> dict[str, str]:
    manifest_file = repo_root / _MANIFEST_PATH
    if not manifest_file.exists():
        return {}
    try:
        parsed = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    components = parsed.get("components") if isinstance(parsed, dict) else {}
    if not isinstance(components, dict):
        return {}
    out: dict[str, str] = {}
    for name, path in components.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if isinstance(path, str) and path.strip():
            out[name.strip()] = _normalized_posix(path.strip())
            continue
        if isinstance(path, dict):
            candidate = path.get("path")
            if isinstance(candidate, str) and candidate.strip():
                out[name.strip()] = _normalized_posix(candidate.strip())
    return out


def _imported_default_symbol(clause: str) -> str | None:
    text = clause.strip()
    if not text:
        return None
    if text.startswith("{") or text.startswith("*"):
        return None
    first = text.split(",", 1)[0].strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", first):
        return None
    return first


def _component_usages(content: str) -> set[str]:
    return {m.group(1) for m in _TEMPLATE_COMPONENT_RE.finditer(content)}


def _resolve_existing_import_source(repo_root: Path, importing_file: str, source: str) -> bool:
    src = str(source or "").strip()
    if not src:
        return False
    importing_dir = PurePosixPath(importing_file).parent
    if src.startswith("@/"):
        rel = _normalized_posix(f"apps/web/src/{src[2:]}")
    elif src.startswith("."):
        rel = _normalized_posix(str(PurePosixPath(importing_dir, src)))
    else:
        return True
    return (repo_root / Path(rel)).resolve().exists()


def _script_block_bounds(content: str) -> tuple[int, int] | None:
    m = re.search(r"<script[^>]*>", content)
    if not m:
        return None
    start = m.end()
    end = content.find("</script>", start)
    if end == -1:
        return None
    return start, end


def normalize_frontend_imports(repo_root: Path, importing_file: str, content: str) -> ImportNormalizationResult:
    attempts = 0
    repairs = 0
    resolved: list[str] = []
    unresolved: list[str] = []

    imported_symbols: dict[str, str] = {}
    seen_symbol_source: set[tuple[str, str]] = set()

    def _rewrite(match: re.Match[str]) -> str:
        nonlocal attempts, repairs
        prefix, clause, middle, open_quote, source, close_quote, suffix = match.groups()
        symbol = _imported_default_symbol(clause)
        new_source = source
        keep = True
        if symbol:
            imported_symbols[symbol] = source
            current_ok = _resolve_existing_import_source(repo_root, importing_file, source)
            if not current_ok:
                attempts += 1
                resolved_import = resolve_frontend_component_import(repo_root, symbol, importing_file)
                if resolved_import:
                    new_source = resolved_import
                    repairs += 1
                    resolved.append(f"{symbol}:{new_source}")
                else:
                    unresolved.append(symbol)
            key = (symbol, new_source)
            if key in seen_symbol_source:
                keep = False
                repairs += 1
            else:
                seen_symbol_source.add(key)
        return "" if not keep else f"{prefix}{clause}{middle}{open_quote}{new_source}{close_quote}{suffix}"

    updated = _IMPORT_RE.sub(_rewrite, content)

    # Inject canonical imports for used primitives/components when missing.
    used = _component_usages(updated)
    manifest_registry = _load_manifest_registry(repo_root)
    canonical_names = set(CANONICAL_PRIMITIVE_REGISTRY.keys()) | set(manifest_registry.keys())
    missing_candidates = [name for name in sorted(used) if name in canonical_names and name not in imported_symbols]
    injections: list[str] = []
    for symbol in missing_candidates:
        attempts += 1
        resolved_import = resolve_frontend_component_import(repo_root, symbol, importing_file)
        if resolved_import:
            injections.append(f'import {symbol} from "{resolved_import}";')
            repairs += 1
            resolved.append(f"{symbol}:{resolved_import}")
        else:
            unresolved.append(symbol)

    if injections:
        bounds = _script_block_bounds(updated)
        if bounds is not None:
            start, _ = bounds
            updated = updated[:start] + "\n" + "\n".join(injections) + updated[start:]
        else:
            unresolved.extend(missing_candidates)

    return ImportNormalizationResult(
        content=updated,
        import_resolution_attempts=attempts,
        resolved_component_imports=sorted(set(resolved)),
        unresolved_component_imports=sorted(set(unresolved)),
        import_normalization_repairs=repairs,
    )
