from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RepoEdge, RepoFile, RepoSnapshot, RepoSymbol, RepoTestLink


async def load_repo_files(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> list[RepoFile]:
    return (
        await session.execute(
            select(RepoFile)
            .where(RepoFile.project_id == project_id, RepoFile.tenant_id == tenant_id)
            .order_by(RepoFile.path.asc())
        )
    ).scalars().all()


async def load_symbols_by_file(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    file_ids: list[uuid.UUID],
) -> tuple[dict[uuid.UUID, list[str]], int]:
    symbols_by_file: dict[uuid.UUID, list[str]] = {file_id: [] for file_id in file_ids}
    if not file_ids:
        return symbols_by_file, 0
    symbol_rows = (
        await session.execute(
            select(RepoSymbol)
            .where(
                RepoSymbol.project_id == project_id,
                RepoSymbol.tenant_id == tenant_id,
                RepoSymbol.file_id.in_(file_ids),
            )
            .order_by(RepoSymbol.name.asc(), RepoSymbol.line_start.asc())
        )
    ).scalars().all()
    for symbol in symbol_rows:
        bucket = symbols_by_file.setdefault(symbol.file_id, [])
        if symbol.name not in bucket and len(bucket) < 8:
            bucket.append(symbol.name)
    return symbols_by_file, len(symbol_rows)


async def load_index_counts(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> tuple[int, int]:
    edge_count = (
        await session.execute(
            select(func.count(RepoEdge.id)).where(RepoEdge.project_id == project_id, RepoEdge.tenant_id == tenant_id)
        )
    ).scalar_one()
    test_link_count = (
        await session.execute(
            select(func.count(RepoTestLink.id)).where(
                RepoTestLink.project_id == project_id, RepoTestLink.tenant_id == tenant_id
            )
        )
    ).scalar_one()
    return int(edge_count or 0), int(test_link_count or 0)


async def load_latest_snapshot(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> RepoSnapshot | None:
    return await session.scalar(
        select(RepoSnapshot)
        .where(RepoSnapshot.project_id == project_id, RepoSnapshot.tenant_id == tenant_id)
        .order_by(RepoSnapshot.indexed_at.desc(), RepoSnapshot.id.desc())
        .limit(1)
    )


async def load_related_tests_for_targets(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    target_file_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[RepoFile]]:
    if not target_file_ids:
        return {}
    rows = (
        await session.execute(
            select(RepoTestLink, RepoFile)
            .join(RepoFile, RepoFile.id == RepoTestLink.test_file_id)
            .where(
                RepoTestLink.project_id == project_id,
                RepoTestLink.tenant_id == tenant_id,
                RepoTestLink.target_file_id.in_(target_file_ids),
            )
            .order_by(RepoTestLink.confidence.desc(), RepoFile.path.asc())
        )
    ).all()
    grouped: dict[uuid.UUID, list[RepoFile]] = {}
    for link, test_file in rows:
        grouped.setdefault(link.target_file_id, [])
        if all(existing.id != test_file.id for existing in grouped[link.target_file_id]):
            grouped[link.target_file_id].append(test_file)
    return grouped
