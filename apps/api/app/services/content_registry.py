from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.content_item import ContentItem, ContentItemVersion, ContentPublishEvent

ALLOWED_CONTENT_TYPES = {"text", "rich_text", "pricing", "list", "json"}
ALLOWED_ENVIRONMENTS = {"PREVIEW", "STAGING", "PRODUCTION"}
ALLOWED_PROMOTION_PATHS = {
    ("PREVIEW", "STAGING"),
    ("STAGING", "PRODUCTION"),
}


def normalize_environment(environment: str | None) -> str:
    env = (environment or "PREVIEW").strip().upper()
    if env not in ALLOWED_ENVIRONMENTS:
        raise ValueError("environment must be PREVIEW, STAGING, or PRODUCTION")
    return env


def validate_promotion_path(source_environment: str, target_environment: str) -> None:
    source = normalize_environment(source_environment)
    target = normalize_environment(target_environment)
    if source == target:
        raise ValueError("source and target environments must differ")
    if (source, target) not in ALLOWED_PROMOTION_PATHS:
        raise ValueError("invalid content promotion path; allowed paths are PREVIEW->STAGING and STAGING->PRODUCTION")


def classify_change_request(message: str) -> str:
    lowered = (message or "").strip().lower()
    if not lowered:
        return "UNKNOWN"
    structural_terms = {
        "add section", "add ", "section", "layout", "style", "animation", "animated", "route", "routing", "component", "topology",
        "interaction", "state", "composable", "hook", "grid", "responsive", "refactor", "new page",
    }
    content_terms = {
        "change", "update", "headline", "title", "cta", "copy", "pricing", "faq", "testimonial",
        "label", "button text", "description", "rename", "text",
    }
    if any(term in lowered for term in structural_terms):
        return "STRUCTURAL"
    if any(term in lowered for term in content_terms):
        return "CONTENT"
    return "UNKNOWN"


async def list_content_items(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    environment: str,
) -> list[ContentItem]:
    env = normalize_environment(environment)
    rows = await session.execute(
        select(ContentItem)
        .where(
            ContentItem.tenant_id == tenant_id,
            ContentItem.project_id == project_id,
            ContentItem.environment == env,
        )
        .order_by(ContentItem.key.asc())
    )
    return list(rows.scalars().all())


async def upsert_content_item(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    project_id: uuid.UUID,
    environment: str,
    key: str,
    content_type: str,
    value: Any,
    source: str,
    updated_by: str | None,
    status: str = "DRAFT",
) -> ContentItem:
    env = normalize_environment(environment)
    normalized_type = (content_type or "text").strip().lower()
    if normalized_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError("type must be one of: text, rich_text, pricing, list, json")
    normalized_status = (status or "DRAFT").strip().upper()
    if normalized_status not in {"DRAFT", "PUBLISHED"}:
        raise ValueError("status must be DRAFT or PUBLISHED")

    existing = await session.scalar(
        select(ContentItem).where(
            ContentItem.tenant_id == tenant_id,
            ContentItem.project_id == project_id,
            ContentItem.environment == env,
            ContentItem.key == key,
        )
    )
    if existing is None:
        item = ContentItem(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
            environment=env,
            key=key,
            type=normalized_type,
            value=value,
            version=1,
            status=normalized_status,
            source=source,
            updated_by=updated_by,
            published_at=datetime.now(timezone.utc) if normalized_status == "PUBLISHED" else None,
        )
        session.add(item)
        await session.flush()
    else:
        existing.type = normalized_type
        existing.value = value
        existing.version = int(existing.version or 0) + 1
        existing.status = normalized_status
        existing.source = source
        existing.updated_by = updated_by
        if normalized_status == "PUBLISHED":
            existing.published_at = datetime.now(timezone.utc)
        session.add(existing)
        item = existing
        await session.flush()

    session.add(
        ContentItemVersion(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
            content_item_id=item.id,
            environment=env,
            key=item.key,
            type=item.type,
            value=item.value,
            version=item.version,
            status=item.status,
            source=item.source,
            updated_by=updated_by,
        )
    )
    await session.flush()
    return item


async def publish_environment(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    source_environment: str,
    target_environment: str,
    published_by: str | None,
    notes: str | None = None,
) -> ContentPublishEvent:
    source_env = normalize_environment(source_environment)
    target_env = normalize_environment(target_environment)
    validate_promotion_path(source_env, target_env)

    source_items = await list_content_items(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        environment=source_env,
    )
    if not source_items:
        raise ValueError(f"no content items found in source environment {source_env}")
    snapshot = {
        "source_environment": source_env,
        "target_environment": target_env,
        "items": [
            {
                "key": item.key,
                "type": item.type,
                "value": item.value,
                "version": item.version,
                "status": item.status,
            }
            for item in source_items
        ],
    }

    await session.execute(
        delete(ContentItem).where(
            ContentItem.tenant_id == tenant_id,
            ContentItem.project_id == project_id,
            ContentItem.environment == target_env,
        )
    )

    for item in source_items:
        await upsert_content_item(
            session,
            tenant_id=tenant_id,
            workspace_id=item.workspace_id,
            project_id=project_id,
            environment=target_env,
            key=item.key,
            content_type=item.type,
            value=item.value,
            source="publish",
            updated_by=published_by,
            status="PUBLISHED",
        )

    event = ContentPublishEvent(
        tenant_id=tenant_id,
        workspace_id=source_items[0].workspace_id if source_items else None,
        project_id=project_id,
        source_environment=source_env,
        target_environment=target_env,
        snapshot=snapshot,
        published_by=published_by,
        notes=notes,
    )
    session.add(event)
    await session.flush()
    return event


async def rollback_content_item(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    environment: str,
    key: str,
    target_version: int,
    updated_by: str | None,
) -> ContentItem:
    env = normalize_environment(environment)
    history = await session.scalar(
        select(ContentItemVersion)
        .where(
            ContentItemVersion.tenant_id == tenant_id,
            ContentItemVersion.project_id == project_id,
            ContentItemVersion.environment == env,
            ContentItemVersion.key == key,
            ContentItemVersion.version == target_version,
        )
        .order_by(ContentItemVersion.created_at.desc())
        .limit(1)
    )
    if history is None:
        raise ValueError("requested content version does not exist")
    rollback_status = "PUBLISHED" if env in {"STAGING", "PRODUCTION"} else "DRAFT"

    return await upsert_content_item(
        session,
        tenant_id=tenant_id,
        workspace_id=history.workspace_id,
        project_id=project_id,
        environment=env,
        key=key,
        content_type=history.type,
        value=history.value,
        source="operator",
        updated_by=updated_by,
        status=rollback_status,
    )


async def get_content_history(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    environment: str,
    key: str,
) -> list[ContentItemVersion]:
    env = normalize_environment(environment)
    rows = await session.execute(
        select(ContentItemVersion)
        .where(
            ContentItemVersion.tenant_id == tenant_id,
            ContentItemVersion.project_id == project_id,
            ContentItemVersion.environment == env,
            ContentItemVersion.key == key,
        )
        .order_by(ContentItemVersion.version.desc())
    )
    return list(rows.scalars().all())
