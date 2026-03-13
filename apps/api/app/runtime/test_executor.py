from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.runtime.executor import TaskExecutor, TaskResult
from app.runtime.context import RunContext
from app.db.models import WorkItem
from app.services.workspace_supervisor import workspace_uri


class TestExecutor(TaskExecutor):
    name = "test"

    def __init__(self, repo_root: Path | None = None):
        self.settings = get_settings()
        self.repo_root = repo_root or Path.cwd()

    async def execute(self, work_item: WorkItem, context: RunContext) -> TaskResult:
        repo_root = Path(context.repo_path) if context.repo_path else self.repo_root
        cmd = self.settings.test_command.split()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=repo_root,
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
            artifacts: list[dict] = []
            if context.logs_path:
                log_dir = Path(context.logs_path)
                log_dir.mkdir(parents=True, exist_ok=True)
                log_name = f"{work_item.type.lower()}-{work_item.id}.log"
                log_path = log_dir / log_name
                log_body = out or ""
                if err:
                    log_body = f"{log_body}\n\n--- STDERR ---\n{err}" if log_body else f"--- STDERR ---\n{err}"
                log_path.write_text(log_body, encoding="utf-8")
                artifacts.append(
                    {
                        "type": "test_log",
                        "uri": workspace_uri("logs", log_name),
                        "path": str(log_path),
                        "payload": {"exit_code": exit_code},
                    }
                )
            return {
                "status": status,
                "message": "Tests passed" if status == "DONE" else "Tests failed",
                "payload": {
                    "exit_code": exit_code,
                    "stdout": out,
                    "stderr": err,
                    "artifacts": artifacts,
                },
            }
        except Exception as exc:
            return {
                "status": "FAILED",
                "message": f"Test executor error: {exc}",
                "payload": {},
            }
