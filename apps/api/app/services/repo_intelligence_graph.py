from __future__ import annotations

import uuid
from collections import defaultdict, deque
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RepoEdge, RepoFile, RepoSymbol, RepoTestLink
from app.schemas.repo_map import (
    RepoGraphCapabilityNeighborsOut,
    RepoGraphDependencyChainOut,
    RepoGraphFileNodeOut,
    RepoGraphNeighborsOut,
    RepoGraphSafeScopeOut,
)


def classify_layer(path: str, kind: str | None = None) -> str:
    lowered = str(path or "").lower()
    k = str(kind or "").lower()
    parts = set(PurePosixPath(lowered).parts)
    if "routes" in parts or "controller" in lowered or k == "api_module":
        return "ROUTE"
    if "services" in parts or "service" in lowered or k == "service_module":
        return "SERVICE"
    if "repositories" in parts or "repository" in lowered:
        return "REPOSITORY"
    if "capabilities" in parts or "binding" in lowered:
        return "CAPABILITY"
    if "components" in parts or k == "ui_component":
        return "COMPONENT"
    if "sections" in parts:
        return "SECTION"
    if "tests" in parts or "test" in lowered or k == "test_file":
        return "TEST"
    if any(token in parts for token in {"contracts", "schemas"}):
        return "CONTRACT"
    if k in {"config", "migration"} or PurePosixPath(lowered).suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini"}:
        return "CONFIG"
    return "MODULE"


def _capabilities_for_file(row: RepoFile) -> list[str]:
    features = [str(item).strip().lower() for item in (row.features or []) if str(item).strip()]
    caps = [item for item in features if any(token in item for token in ("cap", "auth", "lead", "analytics", "payment", "crm", "notify"))]
    return list(dict.fromkeys(caps))[:8]


def _to_node(row: RepoFile, symbols: list[str]) -> RepoGraphFileNodeOut:
    return RepoGraphFileNodeOut(
        path=row.path,
        kind=row.kind,
        layer=classify_layer(row.path, row.kind),
        capabilities=_capabilities_for_file(row),
        symbols=list(symbols)[:8],
    )


async def _load_graph(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> tuple[dict[uuid.UUID, RepoFile], dict[str, uuid.UUID], dict[uuid.UUID, set[uuid.UUID]], dict[uuid.UUID, list[str]], dict[uuid.UUID, set[uuid.UUID]]]:
    files = (
        await session.execute(
            select(RepoFile).where(RepoFile.tenant_id == tenant_id, RepoFile.project_id == project_id)
        )
    ).scalars().all()
    file_by_id = {row.id: row for row in files}
    id_by_path = {row.path: row.id for row in files}

    edges = (
        await session.execute(
            select(RepoEdge).where(RepoEdge.tenant_id == tenant_id, RepoEdge.project_id == project_id)
        )
    ).scalars().all()
    adjacency: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for edge in edges:
        adjacency[edge.source_file_id].add(edge.target_file_id)
        adjacency[edge.target_file_id].add(edge.source_file_id)

    symbols = (
        await session.execute(
            select(RepoSymbol).where(RepoSymbol.tenant_id == tenant_id, RepoSymbol.project_id == project_id)
        )
    ).scalars().all()
    symbols_by_file: dict[uuid.UUID, list[str]] = defaultdict(list)
    for symbol in symbols:
        bucket = symbols_by_file[symbol.file_id]
        if symbol.name not in bucket and len(bucket) < 8:
            bucket.append(symbol.name)

    test_links = (
        await session.execute(
            select(RepoTestLink).where(RepoTestLink.tenant_id == tenant_id, RepoTestLink.project_id == project_id)
        )
    ).scalars().all()
    tests_by_target: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for link in test_links:
        tests_by_target[link.target_file_id].add(link.test_file_id)

    return file_by_id, id_by_path, adjacency, symbols_by_file, tests_by_target


async def get_adjacent_files(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    anchor_file: str,
    depth: int = 1,
    limit: int = 30,
) -> RepoGraphNeighborsOut:
    file_by_id, id_by_path, adjacency, symbols_by_file, tests_by_target = await _load_graph(
        session, tenant_id=tenant_id, project_id=project_id
    )
    anchor_id = id_by_path.get(anchor_file)
    if anchor_id is None:
        raise ValueError("anchor file not found in repo index")
    visited = {anchor_id}
    queue: deque[tuple[uuid.UUID, int]] = deque([(anchor_id, 0)])
    ordered: list[uuid.UUID] = [anchor_id]
    while queue and len(ordered) < limit:
        node, d = queue.popleft()
        if d >= max(1, depth):
            continue
        neighbors = list(adjacency.get(node, set())) + list(tests_by_target.get(node, set()))
        for nxt in neighbors:
            if nxt in visited or nxt not in file_by_id:
                continue
            visited.add(nxt)
            ordered.append(nxt)
            queue.append((nxt, d + 1))
            if len(ordered) >= limit:
                break
    return RepoGraphNeighborsOut(
        anchor=anchor_file,
        depth=depth,
        files=[_to_node(file_by_id[file_id], symbols_by_file.get(file_id, [])) for file_id in ordered if file_id in file_by_id],
    )


async def get_dependency_chain(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    anchor: str,
    limit: int = 25,
) -> RepoGraphDependencyChainOut:
    file_by_id, id_by_path, adjacency, symbols_by_file, _tests_by_target = await _load_graph(
        session, tenant_id=tenant_id, project_id=project_id
    )
    anchor_id = id_by_path.get(anchor)
    if anchor_id is None:
        raise ValueError("anchor file not found in repo index")
    chain = [anchor_id]
    current = anchor_id
    visited = {anchor_id}
    while len(chain) < limit:
        candidates = [candidate for candidate in adjacency.get(current, set()) if candidate in file_by_id and candidate not in visited]
        if not candidates:
            break
        ranked = sorted(
            candidates,
            key=lambda cid: (
                0 if classify_layer(file_by_id[cid].path, file_by_id[cid].kind) in {"SERVICE", "REPOSITORY", "CAPABILITY"} else 1,
                file_by_id[cid].path,
            ),
        )
        nxt = ranked[0]
        visited.add(nxt)
        chain.append(nxt)
        current = nxt
    return RepoGraphDependencyChainOut(
        anchor=anchor,
        chain=[_to_node(file_by_id[file_id], symbols_by_file.get(file_id, [])) for file_id in chain if file_id in file_by_id],
    )


async def get_capability_neighbors(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    capability_key: str,
    limit: int = 30,
) -> RepoGraphCapabilityNeighborsOut:
    cap = (capability_key or "").strip().lower()
    if not cap:
        raise ValueError("capability key required")
    files = (
        await session.execute(
            select(RepoFile).where(RepoFile.tenant_id == tenant_id, RepoFile.project_id == project_id)
        )
    ).scalars().all()
    symbols = (
        await session.execute(
            select(RepoSymbol).where(RepoSymbol.tenant_id == tenant_id, RepoSymbol.project_id == project_id)
        )
    ).scalars().all()
    symbols_by_file: dict[uuid.UUID, list[str]] = defaultdict(list)
    for sym in symbols:
        if len(symbols_by_file[sym.file_id]) < 8 and sym.name not in symbols_by_file[sym.file_id]:
            symbols_by_file[sym.file_id].append(sym.name)
    matched = []
    for row in files:
        hay = " ".join([row.path.lower(), row.kind.lower(), row.summary.lower(), " ".join(str(item).lower() for item in (row.features or []))])
        if cap in hay:
            matched.append(row)
    matched.sort(key=lambda row: row.path)
    return RepoGraphCapabilityNeighborsOut(
        capability=cap,
        files=[_to_node(row, symbols_by_file.get(row.id, [])) for row in matched[:limit]],
    )


async def get_safe_mutation_scope(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    anchor_files: list[str],
    capabilities: list[str] | None = None,
    depth: int = 1,
    limit: int = 40,
) -> RepoGraphSafeScopeOut:
    cap_list = [str(item).strip().lower() for item in (capabilities or []) if str(item).strip()]
    aggregated: dict[str, RepoGraphFileNodeOut] = {}
    for anchor in [item for item in anchor_files if isinstance(item, str) and item.strip()]:
        try:
            adjacent = await get_adjacent_files(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                anchor_file=anchor,
                depth=depth,
                limit=max(8, limit // max(1, len(anchor_files))),
            )
            for node in adjacent.files:
                aggregated[node.path] = node
        except ValueError:
            continue
    for cap in cap_list:
        neighbors = await get_capability_neighbors(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            capability_key=cap,
            limit=12,
        )
        for node in neighbors.files:
            aggregated.setdefault(node.path, node)
    ordered = [aggregated[path] for path in sorted(aggregated.keys())][:limit]
    return RepoGraphSafeScopeOut(anchor_files=anchor_files, capabilities=cap_list, files=ordered)
