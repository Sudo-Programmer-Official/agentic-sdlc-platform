from types import SimpleNamespace

from app.runtime.tools.repo_tools import RepoTools


def test_apply_patch_uses_recount_for_model_generated_diffs(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def fake_run_workspace_command(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(
            status="COMPLETED",
            blocked_reason=None,
            exit_code=0,
            stderr="",
            stdout="",
        )

    monkeypatch.setattr("app.runtime.tools.repo_tools.run_workspace_command", fake_run_workspace_command)

    repo = RepoTools(tmp_path)
    repo.apply_patch(
        "diff --git a/index.html b/index.html\n"
        "--- a/index.html\n"
        "+++ b/index.html\n"
        "@@ -1 +1 @@\n"
        "-<body>Old</body>\n"
        "+<body>New</body>\n"
    )

    assert calls == [
        ["git", "apply", "--recount", "--check", "-"],
        ["git", "apply", "--recount", "--whitespace=nowarn", "--reject", "-"],
    ]
