from __future__ import annotations

import re
from pathlib import PurePosixPath

from app.services.repo_index_types import ScannedSymbol


def extract_symbols(text: str) -> list[ScannedSymbol]:
    symbols: list[ScannedSymbol] = []
    seen: set[tuple[str, str, int]] = set()
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        candidates: list[tuple[str, str]] = []
        if match := re.match(r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)", stripped):
            candidates.append((match.group(1), "function"))
        if match := re.match(r"(?:export\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)", stripped):
            candidates.append((match.group(1), "class"))
        if match := re.match(r"def\s+([A-Za-z_][A-Za-z0-9_]*)", stripped):
            candidates.append((match.group(1), "function"))
        if match := re.match(r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", stripped):
            candidates.append((match.group(1), "variable"))
        if match := re.match(r"(?:export\s+default\s+)?(?:const\s+)?([A-Z][A-Za-z0-9_]*)\s*=", stripped):
            candidates.append((match.group(1), "component"))
        if match := re.search(r"name:\s*['\"]([A-Z][A-Za-z0-9_]*)['\"]", stripped):
            candidates.append((match.group(1), "component"))
        for name, symbol_type in candidates:
            key = (name, symbol_type, line_no)
            if name.startswith("_") or key in seen:
                continue
            seen.add(key)
            symbols.append(ScannedSymbol(name=name, type=symbol_type, line_start=line_no))
            if len(symbols) >= 24:
                return symbols
    return symbols


def ensure_file_stem_symbol(relative_path: PurePosixPath, symbols: list[ScannedSymbol]) -> list[ScannedSymbol]:
    stem = relative_path.stem
    if relative_path.suffix.lower() not in {".vue", ".tsx", ".jsx"}:
        return symbols
    if not stem or not stem[0].isupper():
        return symbols
    if any(symbol.name == stem for symbol in symbols):
        return symbols
    return [ScannedSymbol(name=stem, type="component", line_start=1), *symbols][:24]
