import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Project
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'content-lifecycle.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    tenant_id = uuid.uuid4()

    async def override_get_tenant_context():
        return TenantContext(tenant_id=tenant_id, user_id="ui-user", role=None, enforcement=False)

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_tenant_context] = override_get_tenant_context
    session: AsyncSession = session_factory()
    try:
        yield session, tenant_id
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_tenant_context, None)
        await session.close()
        await engine.dispose()


@pytest.mark.anyio
async def test_content_publish_lifecycle_preview_to_staging_to_production(db_session):
    session, tenant_id = db_session
    project = Project(name="Content lifecycle", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        save = await client.put(
            f"/api/v1/projects/{project.id}/content-items?environment=PREVIEW&publish=false",
            json={"key": "landing.hero.title", "type": "text", "value": "Automate your workflow", "source": "operator"},
        )
        assert save.status_code == 200, save.text
        assert save.json()["status"] == "DRAFT"

        preview_to_staging = await client.post(
            f"/api/v1/projects/{project.id}/content-items/publish",
            json={"source_environment": "PREVIEW", "target_environment": "STAGING"},
        )
        assert preview_to_staging.status_code == 200, preview_to_staging.text

        staging_items = await client.get(f"/api/v1/projects/{project.id}/content-items?environment=STAGING")
        assert staging_items.status_code == 200
        assert staging_items.json()[0]["status"] == "PUBLISHED"

        staging_to_prod = await client.post(
            f"/api/v1/projects/{project.id}/content-items/publish",
            json={"source_environment": "STAGING", "target_environment": "PRODUCTION"},
        )
        assert staging_to_prod.status_code == 200, staging_to_prod.text

        prod_items = await client.get(f"/api/v1/projects/{project.id}/content-items?environment=PRODUCTION")
        assert prod_items.status_code == 200
        assert prod_items.json()[0]["status"] == "PUBLISHED"


@pytest.mark.anyio
async def test_content_publish_rejects_invalid_promotion_path(db_session):
    session, tenant_id = db_session
    project = Project(name="Content invalid path", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.put(
            f"/api/v1/projects/{project.id}/content-items?environment=PREVIEW&publish=true",
            json={"key": "landing.hero.title", "type": "text", "value": "Automate your workflow", "source": "operator"},
        )
        assert seed.status_code == 200, seed.text

        invalid = await client.post(
            f"/api/v1/projects/{project.id}/content-items/publish",
            json={"source_environment": "PREVIEW", "target_environment": "PRODUCTION"},
        )
        assert invalid.status_code == 400
        assert "invalid content promotion path" in invalid.text


@pytest.mark.anyio
async def test_content_rollback_keeps_published_status_in_production(db_session):
    session, tenant_id = db_session
    project = Project(name="Content rollback", tenant_id=tenant_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.put(
            f"/api/v1/projects/{project.id}/content-items?environment=PREVIEW&publish=true",
            json={"key": "landing.hero.title", "type": "text", "value": "Title v1", "source": "operator"},
        )
        await client.put(
            f"/api/v1/projects/{project.id}/content-items?environment=PREVIEW&publish=true",
            json={"key": "landing.hero.title", "type": "text", "value": "Title v2", "source": "operator"},
        )
        promote_stage = await client.post(
            f"/api/v1/projects/{project.id}/content-items/publish",
            json={"source_environment": "PREVIEW", "target_environment": "STAGING"},
        )
        assert promote_stage.status_code == 200
        promote_prod = await client.post(
            f"/api/v1/projects/{project.id}/content-items/publish",
            json={"source_environment": "STAGING", "target_environment": "PRODUCTION"},
        )
        assert promote_prod.status_code == 200

        rollback = await client.post(
            f"/api/v1/projects/{project.id}/content-items/rollback",
            json={"key": "landing.hero.title", "environment": "PRODUCTION", "target_version": 1},
        )
        assert rollback.status_code == 200, rollback.text
        assert rollback.json()["status"] == "PUBLISHED"
