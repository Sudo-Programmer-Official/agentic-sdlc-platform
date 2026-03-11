from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artifact, Trace, WorkItem, WorkItemArtifact


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _artifact_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    payload = artifact.get("payload")
    if isinstance(payload, dict):
        merged = dict(payload)
    else:
        merged = {}
    for key, value in artifact.items():
        if key not in {"type", "uri", "version", "task_id", "run_id", "work_item_id"}:
            merged[key] = value
    return merged


async def link_run_to_work_item(session: AsyncSession, work_item: WorkItem) -> None:
    session.add(
        Trace(
            tenant_id=work_item.tenant_id,
            project_id=work_item.project_id,
            from_type="run",
            from_id=work_item.run_id,
            to_type="work_item",
            to_id=work_item.id,
            relation_type="executes",
            relation_strength=1.0,
        )
    )


async def persist_work_item_artifacts(
    session: AsyncSession,
    work_item: WorkItem,
    artifacts: list[dict[str, Any]] | None,
) -> list[Artifact]:
    created: list[Artifact] = []
    for index, artifact in enumerate(artifacts or [], start=1):
        artifact_type = str(artifact.get("type") or "artifact")
        artifact_uri = (
            artifact.get("uri")
            or artifact.get("path")
            or f"inline://work-items/{work_item.id}/{artifact_type}/{index}"
        )
        payload = _artifact_payload(artifact)

        session.add(
            WorkItemArtifact(
                tenant_id=work_item.tenant_id,
                work_item_id=work_item.id,
                type=artifact_type,
                uri=artifact_uri,
                payload=payload,
            )
        )

        canonical_artifact = Artifact(
            tenant_id=work_item.tenant_id,
            project_id=work_item.project_id,
            task_id=_coerce_uuid(artifact.get("task_id")),
            run_id=_coerce_uuid(artifact.get("run_id")) or work_item.run_id,
            work_item_id=_coerce_uuid(artifact.get("work_item_id")) or work_item.id,
            type=artifact_type,
            uri=artifact_uri,
            version=int(artifact.get("version") or 1),
            extra_metadata=payload or None,
        )
        session.add(canonical_artifact)
        await session.flush()
        created.append(canonical_artifact)

        session.add(
            Trace(
                tenant_id=work_item.tenant_id,
                project_id=work_item.project_id,
                from_type="work_item",
                from_id=work_item.id,
                to_type="artifact",
                to_id=canonical_artifact.id,
                relation_type="produces",
                relation_strength=1.0,
            )
        )

    return created
