from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RepoMapFileOut(BaseModel):
    path: str
    kind: str
    summary: str
    features: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    size_bytes: int
    score: float | None = None


class RepoMapOut(BaseModel):
    source_type: str
    repo_root: str
    repo_full_name: str | None = None
    branch_name: str | None = None
    total_files: int
    indexed_symbols: int = 0
    dependency_edges: int = 0
    test_links: int = 0
    snapshot_indexed_at: datetime | None = None
    directories: list[str] = Field(default_factory=list)
    top_features: list[str] = Field(default_factory=list)
    files: list[RepoMapFileOut] = Field(default_factory=list)


class RepoMapSearchOut(BaseModel):
    query: str
    source_type: str
    repo_root: str
    repo_full_name: str | None = None
    branch_name: str | None = None
    total_files: int
    matches: list[RepoMapFileOut] = Field(default_factory=list)


class RepoMapSymbolOut(BaseModel):
    name: str
    type: str
    path: str
    line_start: int
    line_end: int | None = None
    kind: str | None = None
    summary: str | None = None
    score: float | None = None


class RepoMapSymbolSearchOut(BaseModel):
    query: str
    source_type: str
    repo_root: str
    repo_full_name: str | None = None
    branch_name: str | None = None
    total_files: int
    total_symbols: int
    matches: list[RepoMapSymbolOut] = Field(default_factory=list)


class RepoMapImpactOut(BaseModel):
    source_type: str
    repo_root: str
    repo_full_name: str | None = None
    branch_name: str | None = None
    query_file: str | None = None
    query_symbol: str | None = None
    depth: int = 1
    primary_files: list[RepoMapFileOut] = Field(default_factory=list)
    dependent_files: list[RepoMapFileOut] = Field(default_factory=list)
    related_tests: list[RepoMapFileOut] = Field(default_factory=list)
