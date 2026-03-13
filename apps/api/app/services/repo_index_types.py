from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScannedSymbol:
    name: str
    type: str
    line_start: int
    line_end: int | None = None


@dataclass(frozen=True)
class ScannedRepoFile:
    path: str
    language: str | None
    kind: str
    summary: str
    features: list[str]
    symbols: list[ScannedSymbol]
    size_bytes: int
    checksum: str
    imports: list[str]
