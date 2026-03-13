from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RepoEdge, RepoFile, RepoSnapshot, RepoSymbol, RepoTestLink
from app.services.repo_hot_context import record_repo_hot_context
from app.services.repo_index_types import ScannedRepoFile
from app.services.repo_test_linker import build_test_links


@dataclass(frozen=True)
class RepoRefreshResult:
    file_count: int
    symbol_count: int
    edge_count: int
    test_link_count: int
    changed_paths: list[str]


async def refresh_repo_index(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    scanned_files: list[ScannedRepoFile],
    commit_sha: str | None = None,
) -> RepoRefreshResult:
    existing_files = (
        await session.execute(
            select(RepoFile).where(RepoFile.project_id == project_id, RepoFile.tenant_id == tenant_id)
        )
    ).scalars().all()
    existing_by_path = {row.path: row for row in existing_files}
    changed_paths: list[str] = []
    scanned_by_path = {entry.path: entry for entry in scanned_files}
    for path, scanned in scanned_by_path.items():
        row = existing_by_path.get(path)
        if row is None or row.checksum != scanned.checksum or row.kind != scanned.kind or row.language != scanned.language:
            changed_paths.append(path)
    for path in existing_by_path:
        if path not in scanned_by_path:
            changed_paths.append(path)

    await session.execute(delete(RepoEdge).where(RepoEdge.project_id == project_id, RepoEdge.tenant_id == tenant_id))
    await session.execute(delete(RepoTestLink).where(RepoTestLink.project_id == project_id, RepoTestLink.tenant_id == tenant_id))
    await session.execute(delete(RepoSymbol).where(RepoSymbol.project_id == project_id, RepoSymbol.tenant_id == tenant_id))
    await session.execute(delete(RepoFile).where(RepoFile.project_id == project_id, RepoFile.tenant_id == tenant_id))
    await session.flush()

    now = datetime.now(timezone.utc)
    file_rows: list[RepoFile] = []
    for scanned in scanned_files:
        row = RepoFile(
            tenant_id=tenant_id,
            project_id=project_id,
            path=scanned.path,
            language=scanned.language,
            kind=scanned.kind,
            summary=scanned.summary,
            features=scanned.features,
            size_bytes=scanned.size_bytes,
            checksum=scanned.checksum,
            last_indexed_at=now,
        )
        session.add(row)
        file_rows.append(row)
    await session.flush()

    path_to_id = {scanned.path: row.id for scanned, row in zip(scanned_files, file_rows)}
    row_by_path = {scanned.path: row for scanned, row in zip(scanned_files, file_rows)}

    symbol_count = 0
    edge_count = 0
    for scanned, row in zip(scanned_files, file_rows):
        for symbol in scanned.symbols:
            session.add(
                RepoSymbol(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    file_id=row.id,
                    name=symbol.name,
                    type=symbol.type,
                    line_start=symbol.line_start,
                    line_end=symbol.line_end,
                )
            )
            symbol_count += 1
        for target_path in scanned.imports:
            target_id = path_to_id.get(target_path)
            if not target_id or target_id == row.id:
                continue
            session.add(
                RepoEdge(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    source_file_id=row.id,
                    target_file_id=target_id,
                    relation_type="import",
                )
            )
            edge_count += 1

    test_link_count = 0
    for test_path, target_path, relation_type, confidence in build_test_links(scanned_files):
        test_row = row_by_path.get(test_path)
        target_row = row_by_path.get(target_path)
        if not test_row or not target_row or test_row.id == target_row.id:
            continue
        session.add(
            RepoTestLink(
                tenant_id=tenant_id,
                project_id=project_id,
                test_file_id=test_row.id,
                target_file_id=target_row.id,
                relation_type=relation_type,
                confidence=confidence,
            )
        )
        test_link_count += 1

    session.add(
        RepoSnapshot(
            tenant_id=tenant_id,
            project_id=project_id,
            commit_sha=commit_sha,
            indexed_at=now,
            file_count=len(file_rows),
            symbol_count=symbol_count,
            edge_count=edge_count,
            test_link_count=test_link_count,
            changed_paths=changed_paths,
        )
    )
    await session.commit()

    record_repo_hot_context(
        project_id,
        files=changed_paths[:12] or [scanned.path for scanned in scanned_files[:12]],
        subsystems=["/".join(path.split("/")[:2]) for path in changed_paths if "/" in path][:8],
        patch_clusters=[" | ".join(changed_paths[:3])] if changed_paths else [],
    )
    return RepoRefreshResult(
        file_count=len(file_rows),
        symbol_count=symbol_count,
        edge_count=edge_count,
        test_link_count=test_link_count,
        changed_paths=changed_paths,
    )
