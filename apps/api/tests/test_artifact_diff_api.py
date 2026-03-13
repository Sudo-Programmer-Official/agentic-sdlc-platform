import uuid
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Artifact, Project, Run
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'artifact-diff.db'}", future=True)
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
async def test_public_artifact_diff_preview_returns_changed_files_and_counts(db_session):
    session, tenant_id = db_session
    project = Project(name="Artifact diff", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    run = Run(
        project_id=project.id,
        tenant_id=tenant_id,
        status="COMPLETED",
        executor="codex",
        workspace_status="SEEDED",
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
    )
    session.add(run)
    await session.flush()

    artifact = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        run_id=run.id,
        type="git_diff",
        uri="workspace://patches/auth.patch",
        version=1,
        extra_metadata={
            "content": (
                "diff --git a/app/auth_service.py b/app/auth_service.py\n"
                "--- a/app/auth_service.py\n"
                "+++ b/app/auth_service.py\n"
                "@@ -1 +1 @@\n-old\n+new\n"
                "diff --git a/tests/test_auth.py b/tests/test_auth.py\n"
                "--- a/tests/test_auth.py\n"
                "+++ b/tests/test_auth.py\n"
                "@@ -1 +1 @@\n-assert False\n+assert True\n"
            )
        },
    )
    session.add(artifact)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/artifacts/{artifact.id}/diff")

    assert response.status_code == 200
    data = response.json()
    assert data["artifact_id"] == str(artifact.id)
    assert data["file_count"] == 2
    assert data["additions"] == 2
    assert data["deletions"] == 2
    assert [file["path"] for file in data["files"]] == ["app/auth_service.py", "tests/test_auth.py"]
