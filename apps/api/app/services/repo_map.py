from __future__ import annotations

import hashlib
import os
import re
import uuid
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import RepoEdge, RepoFile, RepoSymbol, Run
from app.schemas.repo_map import (
    RepoMapFileOut,
    RepoMapImpactOut,
    RepoMapOut,
    RepoMapSearchOut,
    RepoMapSymbolOut,
    RepoMapSymbolSearchOut,
)
from app.services.repo_dependency_indexer import extract_import_targets
from app.services.repo_hot_context import record_repo_hot_context
from app.services.repo_index_store import (
    load_index_counts,
    load_latest_snapshot,
    load_related_tests_for_targets,
    load_repo_files,
    load_symbols_by_file,
)
from app.services.repo_index_types import ScannedRepoFile
from app.services.repo_refresh import refresh_repo_index
from app.services.repo_connector import get_project_repository
from app.services.repo_symbol_indexer import ensure_file_stem_symbol, extract_symbols

_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".turbo",
    ".cache",
    ".pytest_cache",
    "__pycache__",
    "coverage",
    ".mypy_cache",
    ".ruff_cache",
}

_LIKELY_TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".vue",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".css",
    ".scss",
    ".html",
    ".sql",
    ".sh",
    ".txt",
    ".toml",
    ".ini",
    ".env",
}

_COMMON_PATH_TOKENS = {
    "src",
    "app",
    "apps",
    "packages",
    "lib",
    "core",
    "test",
    "tests",
    "components",
    "views",
    "pages",
    "services",
    "utils",
    "shared",
    "feature",
    "features",
    "modules",
    "api",
    "web",
    "client",
    "server",
}

_COMMON_QUERY_WORDS = {
    "the",
    "a",
    "an",
    "for",
    "in",
    "on",
    "with",
    "to",
    "show",
    "find",
    "locate",
    "where",
    "is",
    "file",
    "files",
    "repo",
    "repository",
    "map",
    "codebase",
    "please",
    "component",
    "symbol",
}

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,}")
@dataclass(frozen=True)
class RepoSource:
    repo_root: Path
    source_type: str
    branch_name: str | None
    repo_full_name: str | None
    run_id: uuid.UUID | None


def _normalize_query_tokens(text: str) -> list[str]:
    seen: list[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        if raw in _COMMON_QUERY_WORDS:
            continue
        if raw not in seen:
            seen.append(raw)
    return seen


def _split_identifier_tokens(value: str) -> list[str]:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value.replace("-", " ").replace("_", " "))
    return [token.lower() for token in normalized.split() if len(token) > 1]


def _is_candidate_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if any(part in _IGNORED_DIRS for part in path.parts):
        return False
    if path.name.startswith(".") and path.suffix not in {".env", ".env.example"}:
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size == 0 or size > 64_000:
        return False
    if path.suffix.lower() in _LIKELY_TEXT_SUFFIXES:
        return True
    return size < 16_000 and "." not in path.name


def _read_file_excerpt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:12_000]
    except OSError:
        return ""


def _classify_kind(relative_path: PurePosixPath) -> str:
    lowered = str(relative_path).lower()
    suffix = relative_path.suffix.lower()
    parts = set(relative_path.parts)
    if suffix == ".vue":
        return "page_view" if {"views", "pages"} & parts else "ui_component"
    if suffix in {".tsx", ".jsx"}:
        return "page_view" if {"views", "pages"} & parts else "ui_component"
    if suffix in {".css", ".scss"}:
        return "style_asset"
    if suffix in {".md", ".txt"}:
        return "documentation"
    if suffix in {".yml", ".yaml", ".toml", ".json", ".ini"}:
        return "config"
    if "test" in lowered or "spec" in lowered:
        return "test_file"
    if "service" in lowered:
        return "service_module"
    if "store" in lowered:
        return "store_module"
    if "route" in lowered or "controller" in lowered or "/api/" in lowered:
        return "api_module"
    if "migration" in lowered or "alembic" in lowered:
        return "migration"
    if suffix == ".py":
        return "backend_module"
    if suffix in {".ts", ".js"}:
        return "frontend_module"
    return "source_file"


def _language_for(relative_path: PurePosixPath) -> str | None:
    suffix = relative_path.suffix.lower()
    mapping = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".vue": "vue",
        ".sql": "sql",
        ".md": "markdown",
        ".json": "json",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".css": "css",
        ".scss": "scss",
        ".sh": "shell",
    }
    return mapping.get(suffix)


def _extract_features(relative_path: PurePosixPath, symbols: list) -> list[str]:
    features: list[str] = []
    for part in relative_path.parts[:-1]:
        lowered = part.lower()
        if lowered in _COMMON_PATH_TOKENS or lowered in _IGNORED_DIRS:
            continue
        if len(lowered) > 1 and lowered not in features:
            features.append(lowered)
    for token in _split_identifier_tokens(relative_path.stem):
        if token not in _COMMON_PATH_TOKENS and token not in features:
            features.append(token)
    for symbol in symbols[:4]:
        for token in _split_identifier_tokens(symbol.name):
            if token not in _COMMON_PATH_TOKENS and token not in features:
                features.append(token)
    return features[:8]


def _summarize_file(relative_path: PurePosixPath, kind: str, features: list[str], symbols: list[ScannedSymbol]) -> str:
    parent = str(relative_path.parent) if str(relative_path.parent) != "." else "repo root"
    summary = f"{kind.replace('_', ' ')} in {parent}."
    if features:
        summary += f" Related to {', '.join(features[:3])}."
    if symbols:
        summary += f" Symbols: {', '.join(symbol.name for symbol in symbols[:3])}."
    return summary


def _checksum_for(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


async def resolve_project_repo_source(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> RepoSource:
    project_repo = await get_project_repository(session, project_id=project_id, tenant_id=tenant_id)
    recent_runs = (
        await session.execute(
            select(Run)
            .where(
                Run.project_id == project_id,
                Run.tenant_id == tenant_id,
                Run.repo_path.is_not(None),
            )
            .order_by(Run.updated_at.desc(), Run.created_at.desc(), Run.id.desc())
            .limit(12)
        )
    ).scalars().all()
    for run in recent_runs:
        repo_path = Path(run.repo_path or "").expanduser()
        if repo_path.exists() and repo_path.is_dir() and any(repo_path.iterdir()):
            return RepoSource(
                repo_root=repo_path.resolve(),
                source_type="workspace",
                branch_name=run.branch_name or (project_repo.default_branch if project_repo else None),
                repo_full_name=project_repo.repo_full_name if project_repo else None,
                run_id=run.id,
            )

    settings = get_settings()
    if settings.workspace_repo_source:
        configured = Path(settings.workspace_repo_source).expanduser()
        if configured.exists() and configured.is_dir():
            return RepoSource(
                repo_root=configured.resolve(),
                source_type="configured_source",
                branch_name=project_repo.default_branch if project_repo else None,
                repo_full_name=project_repo.repo_full_name if project_repo else None,
                run_id=None,
            )

    cwd = Path.cwd().resolve()
    if (cwd / ".git").exists():
        return RepoSource(
            repo_root=cwd,
            source_type="local_checkout",
            branch_name=project_repo.default_branch if project_repo else None,
            repo_full_name=project_repo.repo_full_name if project_repo else None,
            run_id=None,
        )

    raise ValueError("No local repo workspace is available yet. Start a repo-backed run first.")


def _scan_repo(repo_root: Path) -> list[ScannedRepoFile]:
    indexed: list[ScannedRepoFile] = []
    for current_root, dirs, files in os.walk(repo_root):
        dirs[:] = [directory for directory in dirs if directory not in _IGNORED_DIRS]
        base = Path(current_root)
        for filename in files:
            absolute = base / filename
            if not _is_candidate_file(absolute):
                continue
            relative = PurePosixPath(absolute.relative_to(repo_root).as_posix())
            excerpt = _read_file_excerpt(absolute)
            symbols = ensure_file_stem_symbol(relative, extract_symbols(excerpt))
            features = _extract_features(relative, symbols)
            kind = _classify_kind(relative)
            indexed.append(
                ScannedRepoFile(
                    path=relative.as_posix(),
                    language=_language_for(relative),
                    kind=kind,
                    summary=_summarize_file(relative, kind, features, symbols),
                    features=features,
                    symbols=symbols,
                    size_bytes=absolute.stat().st_size,
                    checksum=_checksum_for(excerpt),
                    imports=extract_import_targets(repo_root, relative, excerpt),
                )
            )
    indexed.sort(key=lambda entry: entry.path)
    return indexed


def _repo_file_out(row: RepoFile, symbols: list[str] | None = None, score: float | None = None) -> RepoMapFileOut:
    return RepoMapFileOut(
        path=row.path,
        kind=row.kind,
        summary=row.summary,
        features=list(row.features or []),
        symbols=symbols or [],
        size_bytes=row.size_bytes,
        score=score,
    )


async def _persist_repo_index(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    repo_root: Path,
    commit_sha: str | None = None,
):
    scanned_files = _scan_repo(repo_root)
    return await refresh_repo_index(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        scanned_files=scanned_files,
        commit_sha=commit_sha,
    )


async def _ensure_repo_index(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    force_refresh: bool = False,
) -> RepoSource:
    source = await resolve_project_repo_source(session, tenant_id=tenant_id, project_id=project_id)
    existing = (
        await session.execute(
            select(RepoFile.id).where(RepoFile.project_id == project_id, RepoFile.tenant_id == tenant_id).limit(1)
        )
    ).scalar_one_or_none()
    if force_refresh or existing is None:
        await _persist_repo_index(session, tenant_id=tenant_id, project_id=project_id, repo_root=source.repo_root)
    return source


async def _load_index_rows(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> tuple[list[RepoFile], dict[uuid.UUID, list[str]], int]:
    files = await load_repo_files(session, tenant_id=tenant_id, project_id=project_id)
    file_ids = [row.id for row in files]
    symbols_by_file, total_symbols = await load_symbols_by_file(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        file_ids=file_ids,
    )
    return files, symbols_by_file, total_symbols


async def _index_counts(session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID) -> tuple[int, int]:
    return await load_index_counts(session, tenant_id=tenant_id, project_id=project_id)


def _score_match(entry: RepoMapFileOut, query: str, tokens: list[str]) -> float:
    path_text = entry.path.lower()
    summary_text = entry.summary.lower()
    feature_text = " ".join(entry.features).lower()
    symbol_text = " ".join(entry.symbols).lower()
    score = 0.0
    for token in tokens:
        if token in path_text:
            score += 5.5
        if token in feature_text:
            score += 4.0
        if token in symbol_text:
            score += 4.8
        if token in summary_text:
            score += 1.8
    phrase = " ".join(tokens)
    if phrase and phrase in path_text:
        score += 7.5
    if "button" in tokens and entry.kind == "ui_component":
        score += 1.5
    if any(token in {"view", "page", "screen"} for token in tokens) and entry.kind == "page_view":
        score += 1.5
    if "service" in tokens and entry.kind == "service_module":
        score += 1.2
    return round(score, 2)


async def build_project_repo_map(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int = 180,
) -> RepoMapOut:
    source = await _ensure_repo_index(session, tenant_id=tenant_id, project_id=project_id)
    files, symbols_by_file, total_symbols = await _load_index_rows(session, tenant_id=tenant_id, project_id=project_id)
    edge_count, test_link_count = await _index_counts(session, tenant_id=tenant_id, project_id=project_id)
    latest_snapshot = await load_latest_snapshot(session, tenant_id=tenant_id, project_id=project_id)
    directories = Counter(str(PurePosixPath(entry.path).parent) for entry in files if str(PurePosixPath(entry.path).parent) != ".")
    features = Counter(feature for entry in files for feature in (entry.features or []))
    return RepoMapOut(
        source_type=source.source_type,
        repo_root=str(source.repo_root),
        repo_full_name=source.repo_full_name,
        branch_name=source.branch_name,
        total_files=len(files),
        indexed_symbols=total_symbols,
        dependency_edges=edge_count,
        test_links=test_link_count,
        snapshot_indexed_at=latest_snapshot.indexed_at if latest_snapshot else None,
        directories=[name for name, _count in directories.most_common(12)],
        top_features=[name for name, _count in features.most_common(12)],
        files=[_repo_file_out(row, symbols=symbols_by_file.get(row.id, [])) for row in files[:limit]],
    )


async def refresh_project_repo_map(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int = 180,
) -> RepoMapOut:
    source = await _ensure_repo_index(session, tenant_id=tenant_id, project_id=project_id, force_refresh=True)
    files, symbols_by_file, total_symbols = await _load_index_rows(session, tenant_id=tenant_id, project_id=project_id)
    edge_count, test_link_count = await _index_counts(session, tenant_id=tenant_id, project_id=project_id)
    latest_snapshot = await load_latest_snapshot(session, tenant_id=tenant_id, project_id=project_id)
    directories = Counter(str(PurePosixPath(entry.path).parent) for entry in files if str(PurePosixPath(entry.path).parent) != ".")
    features = Counter(feature for entry in files for feature in (entry.features or []))
    return RepoMapOut(
        source_type=source.source_type,
        repo_root=str(source.repo_root),
        repo_full_name=source.repo_full_name,
        branch_name=source.branch_name,
        total_files=len(files),
        indexed_symbols=total_symbols,
        dependency_edges=edge_count,
        test_links=test_link_count,
        snapshot_indexed_at=latest_snapshot.indexed_at if latest_snapshot else None,
        directories=[name for name, _count in directories.most_common(12)],
        top_features=[name for name, _count in features.most_common(12)],
        files=[_repo_file_out(row, symbols=symbols_by_file.get(row.id, [])) for row in files[:limit]],
    )


async def search_project_repo_map(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    query: str,
    limit: int = 8,
) -> RepoMapSearchOut:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query is required")
    source = await _ensure_repo_index(session, tenant_id=tenant_id, project_id=project_id)
    rows, symbols_by_file, _total_symbols = await _load_index_rows(session, tenant_id=tenant_id, project_id=project_id)
    tokens = _normalize_query_tokens(normalized_query)
    if not tokens:
        tokens = _split_identifier_tokens(normalized_query)
    matches: list[RepoMapFileOut] = []
    for row in rows:
        entry = _repo_file_out(row, symbols=symbols_by_file.get(row.id, []))
        score = _score_match(entry, normalized_query.lower(), tokens)
        if score <= 0:
            continue
        matches.append(entry.model_copy(update={"score": score}))
    matches.sort(key=lambda item: ((item.score or 0), -len(item.path), item.path), reverse=True)
    record_repo_hot_context(
        project_id,
        files=[item.path for item in matches[:limit]],
        subsystems=["/".join(PurePosixPath(item.path).parts[:2]) for item in matches[:limit] if "/" in item.path],
    )
    return RepoMapSearchOut(
        query=normalized_query,
        source_type=source.source_type,
        repo_root=str(source.repo_root),
        repo_full_name=source.repo_full_name,
        branch_name=source.branch_name,
        total_files=len(rows),
        matches=matches[:limit],
    )


async def search_project_repo_symbols(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    query: str,
    limit: int = 10,
) -> RepoMapSymbolSearchOut:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query is required")
    source = await _ensure_repo_index(session, tenant_id=tenant_id, project_id=project_id)
    rows = (
        await session.execute(
            select(RepoSymbol, RepoFile)
            .join(RepoFile, RepoFile.id == RepoSymbol.file_id)
            .where(RepoSymbol.project_id == project_id, RepoSymbol.tenant_id == tenant_id)
        )
    ).all()
    tokens = _normalize_query_tokens(normalized_query) or _split_identifier_tokens(normalized_query)
    matches: list[RepoMapSymbolOut] = []
    for symbol, file_row in rows:
        haystack = " ".join([symbol.name.lower(), symbol.type.lower(), file_row.path.lower(), file_row.summary.lower()])
        score = 0.0
        for token in tokens:
            if token in symbol.name.lower():
                score += 6.0
            if token in file_row.path.lower():
                score += 3.0
            if token in haystack:
                score += 1.0
        if score <= 0:
            continue
        matches.append(
            RepoMapSymbolOut(
                name=symbol.name,
                type=symbol.type,
                path=file_row.path,
                line_start=symbol.line_start,
                line_end=symbol.line_end,
                kind=file_row.kind,
                summary=file_row.summary,
                score=round(score, 2),
            )
        )
    matches.sort(key=lambda item: ((item.score or 0), item.name, item.path), reverse=True)
    record_repo_hot_context(
        project_id,
        files=[item.path for item in matches[:limit]],
        symbols=[item.name for item in matches[:limit]],
        subsystems=["/".join(PurePosixPath(item.path).parts[:2]) for item in matches[:limit] if "/" in item.path],
    )
    return RepoMapSymbolSearchOut(
        query=normalized_query,
        source_type=source.source_type,
        repo_root=str(source.repo_root),
        repo_full_name=source.repo_full_name,
        branch_name=source.branch_name,
        total_files=len({file_row.id for _symbol, file_row in rows}),
        total_symbols=len(rows),
        matches=matches[:limit],
    )


def _test_match_score(file_row: RepoFile, primary_tokens: set[str]) -> int:
    path_tokens = set(_split_identifier_tokens(PurePosixPath(file_row.path).stem))
    return len(primary_tokens & path_tokens)


async def build_project_repo_impact(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    file_path: str | None = None,
    symbol_name: str | None = None,
    depth: int = 1,
    max_files: int = 15,
) -> RepoMapImpactOut:
    if not file_path and not symbol_name:
        raise ValueError("file or symbol is required")
    source = await _ensure_repo_index(session, tenant_id=tenant_id, project_id=project_id)
    files = (
        await session.execute(
            select(RepoFile).where(RepoFile.project_id == project_id, RepoFile.tenant_id == tenant_id).order_by(RepoFile.path.asc())
        )
    ).scalars().all()
    files_by_id = {row.id: row for row in files}
    files_by_path = {row.path: row for row in files}

    primary_rows: list[RepoFile] = []
    if file_path:
        row = files_by_path.get(file_path)
        if row:
            primary_rows = [row]
    elif symbol_name:
        symbol_rows = (
            await session.execute(
                select(RepoFile)
                .join(RepoSymbol, RepoSymbol.file_id == RepoFile.id)
                .where(
                    RepoSymbol.project_id == project_id,
                    RepoSymbol.tenant_id == tenant_id,
                    RepoSymbol.name.ilike(f"%{symbol_name}%"),
                )
            )
        ).scalars().all()
        unique: dict[uuid.UUID, RepoFile] = {row.id: row for row in symbol_rows}
        primary_rows = list(unique.values())

    if not primary_rows:
        raise ValueError("No indexed file matches the requested file/symbol")

    reverse_edges = (
        await session.execute(
            select(RepoEdge)
            .where(RepoEdge.project_id == project_id, RepoEdge.tenant_id == tenant_id, RepoEdge.relation_type == "import")
        )
    ).scalars().all()
    dependents_by_target: dict[uuid.UUID, list[uuid.UUID]] = {}
    for edge in reverse_edges:
        dependents_by_target.setdefault(edge.target_file_id, []).append(edge.source_file_id)

    primary_ids = {row.id for row in primary_rows}
    dependent_ids: set[uuid.UUID] = set()
    queue: deque[tuple[uuid.UUID, int]] = deque((row.id, 0) for row in primary_rows)
    while queue and len(dependent_ids) < max_files:
        current_id, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        for source_id in dependents_by_target.get(current_id, []):
            if source_id in primary_ids or source_id in dependent_ids:
                continue
            dependent_ids.add(source_id)
            if len(dependent_ids) >= max_files:
                break
            queue.append((source_id, current_depth + 1))

    expanded_rows = [files_by_id[file_id] for file_id in sorted(dependent_ids, key=lambda item: files_by_id[item].path)]
    dependent_rows = [row for row in expanded_rows if row.kind != "test_file"]
    direct_test_rows = [row for row in expanded_rows if row.kind == "test_file"]

    primary_tokens = set()
    for row in [*primary_rows, *dependent_rows, *direct_test_rows]:
        primary_tokens.update(_split_identifier_tokens(PurePosixPath(row.path).stem))

    linked_tests_by_target = await load_related_tests_for_targets(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        target_file_ids=[row.id for row in [*primary_rows, *dependent_rows]],
    )
    heuristic_test_rows = [
        row
        for row in files
        if row.kind == "test_file" and row.id not in primary_ids and row.id not in dependent_ids and _test_match_score(row, primary_tokens) > 0
    ]
    related_tests_by_id: dict[uuid.UUID, RepoFile] = {row.id: row for row in direct_test_rows}
    for linked_rows in linked_tests_by_target.values():
        for row in linked_rows:
            related_tests_by_id.setdefault(row.id, row)
    for row in sorted(heuristic_test_rows, key=lambda item: (_test_match_score(item, primary_tokens), item.path), reverse=True):
        related_tests_by_id.setdefault(row.id, row)
    related_tests = list(related_tests_by_id.values())
    record_repo_hot_context(
        project_id,
        files=[row.path for row in [*primary_rows, *dependent_rows][:12]],
        subsystems=["/".join(PurePosixPath(row.path).parts[:2]) for row in [*primary_rows, *dependent_rows] if "/" in row.path],
        failing_tests=[row.path for row in related_tests[:6]],
        patch_clusters=[" | ".join([row.path for row in [*primary_rows, *dependent_rows][:3]])] if primary_rows else [],
    )

    return RepoMapImpactOut(
        source_type=source.source_type,
        repo_root=str(source.repo_root),
        repo_full_name=source.repo_full_name,
        branch_name=source.branch_name,
        query_file=file_path,
        query_symbol=symbol_name,
        depth=depth,
        primary_files=[_repo_file_out(row) for row in primary_rows],
        dependent_files=[_repo_file_out(row) for row in dependent_rows[:max_files]],
        related_tests=[_repo_file_out(row) for row in related_tests[: max(3, min(6, max_files // 2 or 1))]],
    )
