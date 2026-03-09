from __future__ import annotations

from collections.abc import Callable

from app.runtime.dummy_executor import DummyExecutor
from app.runtime.codex_executor import CodexExecutor
from app.runtime.executor import TaskExecutor
from app.runtime.test_executor import TestExecutor

# Instantiate executors lazily so provider-backed executors do not run at import time.
_EXECUTOR_FACTORIES: dict[str, Callable[[], TaskExecutor]] = {
    "dummy": DummyExecutor,
    "codex": CodexExecutor,
    "test": TestExecutor,
}


def get_executor(name: str) -> TaskExecutor:
    factory = _EXECUTOR_FACTORIES.get(name.lower(), _EXECUTOR_FACTORIES["dummy"])
    return factory()
