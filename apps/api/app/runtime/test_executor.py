from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from app.core.config import get_settings
from app.runtime.executor import TaskExecutor, TaskResult
from app.runtime.context import RunContext
from app.db.models import WorkItem


class TestExecutor(TaskExecutor):
    name = "test"

    def __init__(self, repo_root: Path | None = None):
        self.settings = get_settings()
        self.repo_root = repo_root or Path.cwd()

    async def execute(self, work_item: WorkItem, context: RunContext) -> TaskResult:
        cmd = self.settings.test_command.split()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.repo_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.settings.test_timeout_seconds
                )
            except asyncio.TimeoutError:
                proc.kill()
                return {
                    "status": "FAILED",
                    "message": "Test command timed out",
                    "payload": {
                        "exit_code": None,
                        "stdout": "",
                        "stderr": "timeout",
                    },
                }

            out = (stdout or b"")[: self.settings.test_output_max_bytes].decode(errors="ignore")
            err = (stderr or b"")[: self.settings.test_output_max_bytes].decode(errors="ignore")
            exit_code = proc.returncode
            status = "DONE" if exit_code == 0 else "FAILED"
            return {
                "status": status,
                "message": "Tests passed" if status == "DONE" else "Tests failed",
                "payload": {
                    "exit_code": exit_code,
                    "stdout": out,
                    "stderr": err,
                },
            }
        except Exception as exc:
            return {
                "status": "FAILED",
                "message": f"Test executor error: {exc}",
                "payload": {},
            }
