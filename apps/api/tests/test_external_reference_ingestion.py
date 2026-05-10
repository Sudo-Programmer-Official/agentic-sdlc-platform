from __future__ import annotations

import io
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Artifact
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app
from app.core.config import get_settings
from app.services.external_reference_ingestion import ingest_external_url, persist_external_reference


class _FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, *, status: int = 200, content_type: str = "text/html") -> None:
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.mark.anyio
async def test_external_reference_ingest_endpoint_persists_linkage_and_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("EXTERNAL_REFERENCE_DOMAIN_ALLOWLIST", "example.com")
    get_settings.cache_clear()

    def _fake_urlopen(_req, timeout=0):
        return _FakeResponse(b"<html><body><h1>Guide</h1><script>bad()</script>Use safe retries.</body></html>")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'external_ref.db'}", future=True)
    session_factory = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=AsyncSession)
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

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_project = await client.post("/api/v1/projects", json={"name": "Refs"})
        assert create_project.status_code == 201
        project_id = create_project.json()["id"]

        ingest = await client.post(
            f"/api/v1/projects/{project_id}/external-references",
            json={
                "url": "https://example.com/docs/runtime-guide",
                "label": "Runtime Guide",
                "requirement_id": "FR-001",
            },
        )
        assert ingest.status_code == 200
        payload = ingest.json()
        assert payload["type"] == "external_reference"
        assert payload["requirement_id"] == "FR-001"
        assert payload["metadata"]["domain"] == "example.com"
        assert "script" not in payload["metadata"]["sanitized_text"].lower()

    async with session_factory() as session:
        rows = (await session.execute(Artifact.__table__.select())).all()
        assert len(rows) == 1

    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_tenant_context, None)
    await engine.dispose()


def test_external_reference_sanitization_and_replay_consistency(monkeypatch):
    monkeypatch.setenv("EXTERNAL_REFERENCE_DOMAIN_ALLOWLIST", "example.com")
    get_settings.cache_clear()

    html = b"<html><body><h1>Example</h1><style>.x{}</style><p>Stable summary text.</p></body></html>"

    def _fake_urlopen(_req, timeout=0):
        return _FakeResponse(html)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    first = ingest_external_url("https://example.com/path")
    second = ingest_external_url("https://example.com/path")

    assert "<" not in first.sanitized_text
    assert "style" not in first.sanitized_text.lower()
    assert first.content_sha256 == second.content_sha256
    assert first.summary == second.summary


@pytest.mark.anyio
async def test_external_reference_content_limit_enforced(tmp_path, monkeypatch):
    monkeypatch.setenv("EXTERNAL_REFERENCE_DOMAIN_ALLOWLIST", "example.com")
    monkeypatch.setenv("EXTERNAL_REFERENCE_MAX_CONTENT_BYTES", "32")
    get_settings.cache_clear()

    def _fake_urlopen(_req, timeout=0):
        return _FakeResponse(b"a" * 128, content_type="text/plain")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    with pytest.raises(ValueError, match="byte limit"):
        ingest_external_url("https://example.com/large")

    # Also verify persistence path propagates the same guard.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'external_ref_limit.db'}", future=True)
    session_factory = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        with pytest.raises(ValueError, match="byte limit"):
            await persist_external_reference(
                session,
                tenant_id=uuid.uuid4(),
                project_id=uuid.uuid4(),
                source_url="https://example.com/large",
            )
    await engine.dispose()
