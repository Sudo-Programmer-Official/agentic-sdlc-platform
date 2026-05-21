from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData

from app.api.deps import TenantContext, get_tenant_context
from app.db.session import get_session
from app.main import app
from app.services.activity_log import log_activity
from app.schemas.activity import ActivityOut


def test_activity_out_allows_missing_metadata_attribute():
    row = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        entity_type="project",
        entity_id=None,
        action_type="project.created",
        actor=None,
        created_at=datetime.now(timezone.utc),
    )

    activity = ActivityOut.model_validate(row)

    assert activity.metadata is None


def test_activity_out_prefers_extra_metadata_over_sqlalchemy_metadata():
    row = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        entity_type="project",
        entity_id=None,
        action_type="project.updated",
        extra_metadata={"source": "activity-log"},
        metadata=MetaData(),
        actor="system",
        created_at=datetime.now(timezone.utc),
    )

    activity = ActivityOut.model_validate(row)

    assert activity.metadata == {"source": "activity-log"}


@pytest.mark.anyio
async def test_list_activity_serializes_metadata_as_dict():
    project_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    row = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        entity_type="project",
        entity_id=None,
        action_type="project.updated",
        extra_metadata={"source": "activity-log", "count": 2},
        metadata=MetaData(),
        actor="system",
        created_at=datetime.now(timezone.utc),
    )

    class FakeScalarResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakeExecuteResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return FakeScalarResult(self._rows)

    class FakeSession:
        async def scalar(self, statement):
            return SimpleNamespace(id=project_id, tenant_id=tenant_id)

        async def execute(self, statement):
            return FakeExecuteResult([row])

    async def override_get_session():
        yield FakeSession()

    async def override_get_tenant_context():
        return TenantContext(tenant_id=tenant_id, user_id="ui-user", role=None, enforcement=False)

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_tenant_context] = override_get_tenant_context

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/projects/{project_id}/activity")
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_tenant_context, None)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["metadata"] == {"source": "activity-log", "count": 2}


@pytest.mark.anyio
async def test_log_activity_serializes_uuid_metadata():
    class DummySession:
        def __init__(self):
            self.entries = []

        def add(self, entry):
            self.entries.append(entry)

    session = DummySession()
    project_id = uuid.uuid4()
    task_id = uuid.uuid4()

    await log_activity(
        session,
        project_id=project_id,
        entity_type="document",
        entity_id=uuid.uuid4(),
        action_type="impact.preview",
        event_type="impact",
        metadata={"impacted_tasks": [task_id], "seen_at": datetime(2026, 3, 11, tzinfo=timezone.utc)},
        previous_state={"task_id": task_id},
        new_state={"task_ids": [task_id]},
    )

    entry = session.entries[0]
    assert entry.extra_metadata["impacted_tasks"] == [str(task_id)]
    assert entry.previous_state["task_id"] == str(task_id)
    assert entry.new_state["task_ids"] == [str(task_id)]


@pytest.mark.anyio
async def test_log_activity_trims_overlong_string_fields():
    class DummySession:
        def __init__(self):
            self.entries = []

        def add(self, entry):
            self.entries.append(entry)

    session = DummySession()
    await log_activity(
        session,
        project_id=uuid.uuid4(),
        entity_type="x" * 80,
        entity_id=uuid.uuid4(),
        action_type="y" * 80,
        event_type="z" * 80,
        actor="a" * 180,
    )

    entry = session.entries[0]
    assert len(entry.entity_type) == 32
    assert len(entry.action_type) == 32
    assert len(entry.event_type) == 32
    assert len(entry.actor) == 100
