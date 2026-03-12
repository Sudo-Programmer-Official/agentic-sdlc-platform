from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

import pytest

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
