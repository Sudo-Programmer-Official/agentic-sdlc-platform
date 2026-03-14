from app.db.models import Run


def test_run_runtime_timestamps_are_timezone_aware():
    assert Run.__table__.c.started_at.type.timezone is True
    assert Run.__table__.c.finished_at.type.timezone is True
