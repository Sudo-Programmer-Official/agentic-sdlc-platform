from __future__ import annotations

from app.services.run_execution_console import _merge_command_audit_records


def test_merge_command_audit_records_promotes_running_to_finished():
    commands = _merge_command_audit_records(
        [
            {
                "command_id": "abc123",
                "phase": "started",
                "started_at": "2026-03-15T00:00:00+00:00",
                "label": "frontend-build",
                "command": ["npm", "run", "build"],
                "cwd": "/tmp/repo",
                "status": "RUNNING",
                "log_path": "/tmp/repo/logs/build.log",
            },
            {
                "command_id": "abc123",
                "phase": "finished",
                "started_at": "2026-03-15T00:00:00+00:00",
                "finished_at": "2026-03-15T00:00:04+00:00",
                "label": "frontend-build",
                "command": ["npm", "run", "build"],
                "cwd": "/tmp/repo",
                "status": "SUCCEEDED",
                "duration_ms": 4012,
                "exit_code": 0,
                "log_path": "/tmp/repo/logs/build.log",
            },
        ]
    )

    assert len(commands) == 1
    assert commands[0].command_id == "abc123"
    assert commands[0].status == "SUCCEEDED"
    assert commands[0].duration_ms == 4012
    assert commands[0].exit_code == 0
