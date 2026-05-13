import asyncio

from sqlalchemy.exc import OperationalError

from app.runtime.worker_service import _degraded_backoff_seconds, _is_transient_worker_error


def test_worker_transient_error_classifier():
    assert _is_transient_worker_error(TimeoutError("timed out"))
    assert _is_transient_worker_error(asyncio.TimeoutError("timeout"))
    assert _is_transient_worker_error(ConnectionError("connection reset by peer"))
    assert _is_transient_worker_error(OperationalError("select 1", {}, Exception("connection refused")))
    assert not _is_transient_worker_error(ValueError("invalid task payload"))


def test_worker_transient_backoff_is_bounded():
    assert _degraded_backoff_seconds(1) == 1.0
    assert _degraded_backoff_seconds(2) == 2.0
    assert _degraded_backoff_seconds(3) == 4.0
    assert _degraded_backoff_seconds(4) == 8.0
    assert _degraded_backoff_seconds(50) == 8.0
