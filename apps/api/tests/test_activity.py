from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

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
