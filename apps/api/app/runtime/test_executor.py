from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from app.core.config import get_settings
from app.runtime.executor import TaskExecutor, TaskResult
from app.runtime.context import RunContext
from app.db.models import WorkItem
from app.services.workspace_supervisor import workspace_uri
from app.services.workspace_commands import run_workspace_command_async


class TestExecutor(TaskExecutor):
    __test__ = False
    name = "test"

    def __init__(self, repo_root: Path | None = None):
        self.settings = get_settings()
        self.repo_root = repo_root or Path.cwd()

    def _command_env(self) -> dict[str, str]:
        python_bin = str(Path(sys.executable).resolve().parent)
        current_path = os.environ.get("PATH", "")
        path_parts = [part for part in current_path.split(os.pathsep) if part]
        if python_bin not in path_parts:
            path_parts.insert(0, python_bin)
        return {"PATH": os.pathsep.join(path_parts) if path_parts else python_bin}

    def _normalize_test_command(self, command: list[str]) -> list[str]:
        if not command:
            return command
        executable = Path(command[0]).name
        if executable == "pytest":
            return [sys.executable, "-m", "pytest", *command[1:]]
        return command

    @staticmethod
    def _is_pytest_command(command: list[str]) -> bool:
        if not command:
            return False
        executable = Path(command[0]).name
        if executable == "pytest":
            return True
        return len(command) >= 3 and command[1] == "-m" and command[2] == "pytest"

    async def execute(self, work_item: WorkItem, context: RunContext) -> TaskResult:
        repo_root = Path(context.repo_path) if context.repo_path else self.repo_root
        cmd = self._normalize_test_command(shlex.split(self.settings.test_command))
        log_dir = Path(context.logs_path) if context.logs_path else repo_root / ".agentic-sdlc-logs"
        try:
            result = await run_workspace_command_async(
                cmd,
                cwd=repo_root,
                log_dir=log_dir,
                label=f"test-{work_item.type.lower()}",
                timeout_seconds=self.settings.test_timeout_seconds,
                output_max_bytes=self.settings.test_output_max_bytes,
                env=self._command_env(),
            )
            if result.status == "BLOCKED":
                return {
                    "status": "FAILED",
                    "message": "Test command blocked by workspace policy",
                    "payload": {
                        "exit_code": None,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "command_status": result.status,
                    },
                }
            if result.timed_out:
                return {
                    "status": "FAILED",
                    "message": "Test command timed out",
                    "payload": {
                        "exit_code": None,
                        "stdout": result.stdout,
                        "stderr": result.stderr or "timeout",
                        "command_status": result.status,
                    },
                }

            out = result.stdout
            err = result.stderr
            exit_code = result.exit_code
            no_tests_collected = self._is_pytest_command(cmd) and exit_code == 5
            status = "SKIPPED" if no_tests_collected else ("DONE" if exit_code == 0 else "FAILED")
            artifacts: list[dict] = []
            if result.log_path:
                log_path = Path(result.log_path)
                log_name = log_path.name
                uri = workspace_uri("logs", log_name) if context.logs_path else str(log_path)
                artifacts.append(
                    {
                        "type": "test_log",
                        "uri": uri,
                        "path": str(log_path),
                        "payload": {
                            "exit_code": exit_code,
                            "command_status": result.status,
                            "command_audit_path": result.audit_path,
                        },
                    }
                )
            if no_tests_collected:
                message = "No relevant tests were collected; validation skipped."
            else:
                message = "Tests passed" if status == "DONE" else "Tests failed"
            return {
                "status": status,
                "message": message,
                "payload": {
                    "exit_code": exit_code,
                    "stdout": out,
                    "stderr": err,
                    "message": message,
                    "skip_reason": "no_tests_collected" if no_tests_collected else None,
                    "command_status": result.status,
                    "command_audit_path": result.audit_path,
                    "artifacts": artifacts,
                },
            }
        except Exception as exc:
            return {
                "status": "FAILED",
                "message": f"Test executor error: {exc}",
                "payload": {},
            }
