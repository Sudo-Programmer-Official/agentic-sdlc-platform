import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import AIJobRun
from app.db.models import Project, Run, WorkItem
from app.runtime.context import RunContext
from app.runtime.codex_executor import (
    _edit_budget_from_payload,
    _fix_test_failure_writable_scope,
    _is_static_frontend_scope,
    _stage_scope_violations,
    _target_files_from_payload,
    _verification_from_action_scope,
    CodexExecutor,
)
from app.runtime.execution_contract import build_execution_contract
from app.runtime.patch_guard import evaluate_patch_guard
from app.runtime.schemas.executor_io import Action
from app.schemas.run_narrative import RunPatchVerificationFinding, RunPatchVerificationSummary
from app.services.ai_policy import AIJobManager


class SequencePlanClient:
    def __init__(self, plans: list[dict]):
        self._plans = list(plans)
        self.prompts: list[str] = []
        self.system_prompts: list[str] = []

    def method_name(self) -> str:
        return "sequence-plan-client"

    def sdk_version(self) -> str:
        return "test"

    async def generate(self, system_prompt, user_prompt, **_kwargs):
        self.system_prompts.append(system_prompt)
        self.prompts.append(user_prompt)
        if not self._plans:
            raise AssertionError("No plan responses remaining")
        return json.dumps(self._plans.pop(0)), {"input_tokens": 1, "output_tokens": 1}


class SequenceRawClient:
    def __init__(self, responses: list[str | dict]):
        self._responses = list(responses)
        self.prompts: list[str] = []
        self.system_prompts: list[str] = []
        self.max_tokens: list[int | None] = []
        self.models: list[str | None] = []

    def method_name(self) -> str:
        return "sequence-raw-client"

    def sdk_version(self) -> str:
        return "test"

    async def generate(self, system_prompt, user_prompt, **kwargs):
        self.system_prompts.append(system_prompt)
        self.prompts.append(user_prompt)
        self.max_tokens.append(kwargs.get("max_tokens"))
        self.models.append(kwargs.get("model"))
        if not self._responses:
            raise AssertionError("No raw responses remaining")
        response = self._responses.pop(0)
        raw = json.dumps(response) if isinstance(response, dict) else response
        return raw, {"input_tokens": 1, "output_tokens": 1}


@pytest.fixture
async def db_session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'codex-executor.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield session_factory
    finally:
        await engine.dispose()


def _no_scope_verification() -> RunPatchVerificationSummary:
    return RunPatchVerificationSummary(
        status="NO_SCOPE",
        requires_confirmation=True,
        risk_level="LOW",
        file_count=0,
        max_files=5,
        findings=[
            RunPatchVerificationFinding(
                code="no_scope",
                severity="warning",
                title="No planned patch files identified yet",
                detail="The system can describe the run, but it does not yet have a bounded patch file envelope for this run.",
                files=[],
            )
        ],
        suggested_next_action="Require operator confirmation before patch execution.",
    )


def test_verification_from_action_scope_unblocks_bounded_plan_actions():
    verification = _verification_from_action_scope(
        _no_scope_verification(),
        ["hello_world.py", "test_hello_world.py"],
    )

    assert verification is not None
    assert verification.status == "READY"
    assert verification.requires_confirmation is False
    assert verification.file_count == 2
    assert verification.verified_files == ["hello_world.py", "test_hello_world.py"]
    assert verification.actual_files == ["hello_world.py", "test_hello_world.py"]
    assert verification.scope_match is True
    assert verification.suggested_next_action == "Proceed with the bounded patch and validation sequence."
    assert [finding.code for finding in verification.findings] == ["scope_from_actions"]


def test_verification_from_action_scope_keeps_confirmation_for_sensitive_paths():
    verification = _verification_from_action_scope(
        _no_scope_verification(),
        ["app/auth.py"],
    )

    assert verification is not None
    assert verification.status == "REQUIRES_CONFIRMATION"
    assert verification.requires_confirmation is True
    assert verification.file_count == 1
    assert verification.verified_files == ["app/auth.py"]
    assert verification.actual_files == ["app/auth.py"]
    assert verification.scope_match is True
    assert verification.suggested_next_action == "Require operator confirmation before patch execution."
    assert [finding.code for finding in verification.findings] == ["scope_from_actions"]


def test_target_files_from_payload_prefers_explicit_target_scope():
    target_files = _target_files_from_payload(
        {
            "target_files": ["index.html", "styles.css"],
            "files": ["README.md"],
        }
    )

    assert target_files == ["index.html", "styles.css"]


def test_target_files_from_payload_falls_back_to_expected_files():
    target_files = _target_files_from_payload(
        {
            "expected_files": ["index.html"],
        }
    )

    assert target_files == ["index.html"]


def test_target_files_from_payload_includes_singular_scope_hints():
    target_files = _target_files_from_payload(
        {
            "target_file": "index.html",
            "path": "ignored.html",
        }
    )

    assert target_files == ["index.html", "ignored.html"]


def test_edit_budget_from_payload_uses_minimal_patch_limits():
    edit_budget = _edit_budget_from_payload(
        {
            "edit_budget": {
                "mode": "minimal_patch",
                "max_files": 2,
                "hard_max_files": 4,
            }
        }
    )

    assert edit_budget == {
        "mode": "minimal_patch",
        "file_budget": 2,
        "hard_file_budget": 4,
    }


def test_static_frontend_scope_detects_html_css_only_targets():
    assert _is_static_frontend_scope({"expected_files": ["index.html", "styles.css"]}) is True
    assert _is_static_frontend_scope({"expected_files": ["index.html", "hero.py"]}) is False


def test_fix_test_failure_writable_scope_prefers_non_test_files():
    writable_scope = _fix_test_failure_writable_scope(
        {"target_files": ["test_index_html.py"]},
        None,
        ["test_index_html.py"],
        ["index.html", "test_index_html.py"],
    )

    assert writable_scope == ["index.html"]


def test_fix_test_failure_writable_scope_keeps_failing_tests_in_scope():
    writable_scope = _fix_test_failure_writable_scope(
        {
            "target_files": ["index.html"],
            "related_files": ["test_index_html.py"],
            "failing_test_files": ["test_index_html.py"],
        },
        None,
        ["index.html"],
        ["index.html", "test_index_html.py"],
    )

    assert writable_scope == ["index.html", "test_index_html.py"]


def test_instructions_for_write_tests_discourage_new_third_party_dependencies():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="WRITE_TESTS",
        payload={"expected_files": ["index.html"]},
    )

    instructions = executor._instructions_for(work_item)

    assert "Restrict edits to these files unless validation proves a neighboring file is required: index.html." in instructions
    assert "prefer write_file with the full updated file contents over apply_patch" in instructions
    assert "This is a static frontend task." in instructions
    assert "Do not introduce new third-party imports such as BeautifulSoup or bs4" in instructions
    assert "html.parser" in instructions


def test_instructions_for_static_frontend_prefer_write_file_when_exact_diff_is_awkward():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"expected_files": ["index.html"]},
    )

    instructions = executor._instructions_for(work_item)

    assert "prefer write_file with the full updated file contents" in instructions
    assert "never use placeholder headers such as @@ ... @@" in instructions


def test_instructions_for_plan_stage_forbid_mutations():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="PLAN_DAG",
        payload={"expected_files": ["index.html"]},
    )

    instructions = executor._instructions_for(work_item)

    assert "Do not mutate repository files." in instructions
    assert "Return only note actions" in instructions


def test_instructions_for_review_stage_forbid_mutations():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="REVIEW_DIFF",
        payload={"expected_files": ["index.html"]},
    )

    instructions = executor._instructions_for(work_item)

    assert "This is a review task." in instructions
    assert "Return only note actions" in instructions
    assert "Do not mutate repository files." in instructions
    assert "Never emit apply_patch, write_file, or delete_file actions." in instructions
    assert "prefer write_file" not in instructions


def test_system_prompt_for_review_stage_forbids_mutations():
    executor = CodexExecutor()
    prompt = executor._system_prompt_for(SimpleNamespace(type="REVIEW_DIFF"))

    assert "automated code review worker" in prompt
    assert "Return only note actions" in prompt
    assert "Never emit apply_patch, write_file, or delete_file actions." in prompt


def test_write_tests_stage_rejects_non_test_file_mutations():
    work_item = SimpleNamespace(type="WRITE_TESTS")

    violations = _stage_scope_violations(
        work_item,
        [],
        ["index.html", "test_index_html.py"],
    )

    assert violations == [
        "WRITE_TESTS may only modify Python test files; received out-of-scope file index.html."
    ]


def test_plan_stage_rejects_mutating_actions():
    work_item = SimpleNamespace(type="PLAN_DAG")
    patch = (
        "diff --git a/index.html b/index.html\n"
        "--- a/index.html\n"
        "+++ b/index.html\n"
        "@@ -1 +1 @@\n"
        "-<body>Old</body>\n"
        "+<body>New</body>\n"
    )

    violations = _stage_scope_violations(
        work_item,
        [Action(type="apply_patch", patch=patch)],
        ["index.html"],
    )

    assert violations == [
        "PLAN work items may only return note actions; mutating file operations are out of scope."
    ]


def test_review_stage_rejects_mutating_actions():
    work_item = SimpleNamespace(type="REVIEW_DIFF")
    patch = (
        "diff --git a/index.html b/index.html\n"
        "--- a/index.html\n"
        "+++ b/index.html\n"
        "@@ -1 +1 @@\n"
        "-<body>Old</body>\n"
        "+<body>New</body>\n"
    )

    violations = _stage_scope_violations(
        work_item,
        [Action(type="apply_patch", patch=patch)],
        ["index.html"],
    )

    assert violations == [
        "REVIEW work items may only return note actions; mutating file operations are out of scope."
    ]


def test_patch_guard_accepts_index_html_apply_patch_scope():
    patch = (
        "diff --git a/index.html b/index.html\n"
        "--- a/index.html\n"
        "+++ b/index.html\n"
        "@@ -1 +1 @@\n"
        "-<body>Old</body>\n"
        "+<body>New</body>\n"
    )

    decision = evaluate_patch_guard(
        actions=[Action(type="apply_patch", patch=patch)],
        allowed_files=["index.html"],
    )

    assert decision.touched_files == ["index.html"]
    assert decision.ok is True


def test_codex_executor_patch_parsers_preserve_index_html_paths():
    executor = CodexExecutor()
    patch = (
        "diff --git a/index.html b/index.html\n"
        "--- a/index.html\n"
        "+++ b/index.html\n"
        "@@ -1 +1 @@\n"
        "-<body>Old</body>\n"
        "+<body>New</body>\n"
    )

    assert executor._paths_from_diff(patch) == ["index.html"]
    assert executor._parse_patch_changes(patch) == {"index.html": 2}


def test_patch_structure_error_detects_hunk_without_file_headers():
    executor = CodexExecutor()
    patch = (
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    assert executor._patch_structure_error(patch) == "Patch is missing file headers (---/+++) before diff hunks."


def test_patch_ratio_for_single_file_static_frontend_scope_is_unbounded():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="PLAN_DAG",
        payload={"expected_files": ["index.html"]},
    )

    assert executor._patch_ratio_for(work_item) == float("inf")


def test_patch_ratio_for_write_tests_scope_is_unbounded():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="WRITE_TESTS",
        payload={"expected_files": ["test_index_html.py"]},
    )

    assert executor._patch_ratio_for(work_item) == float("inf")


def test_patch_ratio_for_non_frontend_plan_scope_preserves_default_plan_limit():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="PLAN_DAG",
        payload={"expected_files": ["app.py"]},
    )

    assert executor._patch_ratio_for(work_item) == 0.6


def test_patch_guard_uses_apply_patch_path_when_diff_headers_are_missing():
    decision = evaluate_patch_guard(
        actions=[
            Action(
                type="apply_patch",
                path="test_index_html.py",
                patch=(
                    "@@ -1 +1 @@\n"
                    "-old\n"
                    "+new\n"
                ),
            )
        ],
        allowed_files=["test_index_html.py"],
    )

    assert decision.touched_files == ["test_index_html.py"]
    assert decision.ok is True


@pytest.mark.anyio
async def test_codex_executor_repairs_placeholder_patch_by_regenerating_plan(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main><section id='projects'><p>Projects section coming soon.</p></section></main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Frontend patch repair", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="SHOWCASE_PROJECTS",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "index.html"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequencePlanClient(
        [
            {
                "status": "DONE",
                "message": "patched",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "patch": (
                            "diff --git a/index.html b/index.html\n"
                            "--- a/index.html\n"
                            "+++ b/index.html\n"
                            "@@ ... @@\n"
                            "-<p>Projects section coming soon.</p>\n"
                            "+<div class='projects-list'><article>Portfolio Website</article></div>\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
            {
                "status": "DONE",
                "message": "patched after repair",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": (
                            "<main>\n"
                            "  <section id='projects'>\n"
                            "    <h2>Projects</h2>\n"
                            "    <div class='projects-list'>\n"
                            "      <article>Portfolio Website</article>\n"
                            "      <article>Task Tracker App</article>\n"
                            "      <article>Weather Dashboard</article>\n"
                            "    </div>\n"
                            "  </section>\n"
                            "</main>\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    def fake_apply_patch(self, patch: str):
        raise ValueError("Patch apply error: Patch check failed: error: patch with only garbage at line 5")

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.runtime.codex_executor.RepoTools.apply_patch", fake_apply_patch)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Add showcase projects section",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Implement showcase projects section",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "CODE_FRONTEND",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "Task Tracker App" in index_path.read_text(encoding="utf-8")
    assert len(client.prompts) == 2
    assert "Do not use placeholder hunk headers such as @@ ... @@." in client.prompts[1]


@pytest.mark.anyio
async def test_codex_executor_repairs_hunk_only_patch_by_regenerating_plan(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main><p>Portfolio</p></main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Write tests patch repair", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="WRITE_TESTS",
            key="WRITE_TESTS",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "test_index_html.py"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequencePlanClient(
        [
            {
                "status": "DONE",
                "message": "patched",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "path": "test_index_html.py",
                        "patch": (
                            "@@ -1 +1,8 @@\n"
                            "+def test_index_html_contains_main():\n"
                            "+    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            "+        assert '<main>' in handle.read()\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
            {
                "status": "DONE",
                "message": "patched after repair",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "test_index_html.py",
                        "content": (
                            "def test_index_html_contains_main():\n"
                            "    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            "        assert '<main>' in handle.read()\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Add tests for contact section",
                    "expected_files": ["test_index_html.py"],
                    "steps": [
                        {
                            "title": "Add tests for contact section",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "WRITE_TESTS",
                            "expected_files": ["test_index_html.py"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "test_index_html_contains_main" in (tmp_path / "test_index_html.py").read_text(encoding="utf-8")
    assert len(client.prompts) == 2
    assert "Do not return hunk-only patch fragments that start with @@ before file headers." in client.prompts[1]


@pytest.mark.anyio
async def test_codex_executor_retries_truncated_json_with_higher_token_cap(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Frontend parse retry", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="THEME_PORTFOLIO",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "index.html"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            (
                "{"
                "\"status\":\"DONE\","
                "\"message\":\"patched\","
                "\"warnings\":[],"
                "\"actions\":[{"
                "\"type\":\"apply_patch\","
                "\"path\":\"index.html\","
                "\"patch\":\"diff --git a/index.html b/index.html\\n--- a/index.html\\n+++ b/index.html\\n@@ -1 +1 @@\\n-<main>Portfolio</main>\\n+<main>Rethemed"
            ),
            {
                "status": "DONE",
                "message": "patched after parse retry",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": "<main class='theme-shell'>Rethemed portfolio</main>\n",
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Retheme the single-file portfolio",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Implement themed portfolio shell",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "CODE_FRONTEND",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "Rethemed portfolio" in index_path.read_text(encoding="utf-8")
    assert len(client.prompts) == 2
    assert "truncated" in client.prompts[1]
    assert "Do not reconsider the broader feature plan" in client.prompts[1]
    assert "prefer write_file with the full updated contents of the scoped file instead of apply_patch" in client.prompts[1]
    assert client.models == ["gpt-4.1-mini", "gpt-4.1"]
    assert client.max_tokens[0] > 1200
    assert client.max_tokens[1] > client.max_tokens[0]
    assert result["payload"]["ai_attempt_tiers"] == ["tier_standard", "tier_premium"]
    assert result["payload"]["ai_effective_tier"] == "tier_premium"


@pytest.mark.anyio
async def test_review_diff_parse_retry_returns_note_actions_and_escalates(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    (tmp_path / "index.html").write_text("<main>Portfolio</main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Review diff parse retry", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="REVIEW_DIFF",
            key="REVIEW_DIFF",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "index.html"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            (
                "{"
                "\"status\":\"DONE\","
                "\"message\":\"reviewed\","
                "\"warnings\":[],"
                "\"actions\":[{"
                "\"type\":\"apply_patch\","
                "\"patch\":\"diff --git a/index.html b/index.html\\n--- a/index.html\\n+++ b/index.html\\n@@ -1 +1 @@\\n-<main>Portfolio</main>\\n+<main>Reviewed"
            ),
            {
                "status": "DONE",
                "message": "reviewed after parse retry",
                "warnings": [],
                "actions": [
                    {
                        "type": "note",
                        "text": "Review passed. Navigation premium badge is scoped to index.html and no blocking issues were found.",
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Review the premium navigation change",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Review the bounded navigation update",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "REVIEW_DIFF",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert len(client.prompts) == 2
    assert all("automated code review worker" in prompt for prompt in client.system_prompts)
    assert "This is a review stage. Return only note actions" in client.prompts[1]
    assert "Never emit apply_patch, write_file, or delete_file actions" in client.prompts[1]
    assert client.models == ["gpt-4.1-mini", "gpt-4.1"]
    assert result["payload"]["ai_attempt_tiers"] == ["tier_standard", "tier_premium"]
    assert result["payload"]["ai_effective_tier"] == "tier_premium"


@pytest.mark.anyio
async def test_plan_dag_parse_retry_runs_once_even_when_policy_disables_general_retries(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    (tmp_path / "index.html").write_text("<main>Portfolio</main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Planner parse retry", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="PLAN_DAG",
            key="PLAN_DAG",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "index.html"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            "{\"status\":\"DONE\",\"message\":\"plan",
            {
                "status": "DONE",
                "message": "planned after parse retry",
                "warnings": [],
                "actions": [{"type": "note", "text": "bounded plan confirmed"}],
                "artifacts": [],
            },
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Create a portfolio project",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Plan the bounded portfolio change",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "PLAN_DAG",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert len(client.prompts) == 2
    assert "structured output retry 1" in client.prompts[1].lower()
    assert client.models == ["gpt-4.1-mini", "gpt-4.1"]
    assert client.max_tokens[1] > client.max_tokens[0]
    assert result["payload"]["ai_attempt_tiers"] == ["tier_standard", "tier_premium"]
    assert result["payload"]["ai_effective_tier"] == "tier_premium"


@pytest.mark.anyio
async def test_write_tests_parse_retry_escalates_to_premium_model(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    (tmp_path / "index.html").write_text("<main>Portfolio</main>\n", encoding="utf-8")
    test_path = tmp_path / "test_index_html.py"
    test_path.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Write tests parse retry", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="WRITE_TESTS",
            key="WRITE_TESTS",
            status="QUEUED",
            executor="codex",
            payload={"target_files": ["test_index_html.py"], "related_files": ["index.html"]},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            "{\"status\":\"DONE\",\"message\":\"tests",
            {
                "status": "DONE",
                "message": "tests after parse retry",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "test_index_html.py",
                        "content": (
                            "def test_index_html_exists():\n"
                            "    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            "        assert '<main>' in handle.read()\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Write validation tests for the portfolio page",
                    "expected_files": ["test_index_html.py"],
                    "steps": [
                        {
                            "title": "Add bounded HTML validation tests",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "WRITE_TESTS",
                            "expected_files": ["test_index_html.py"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "test_index_html_exists" in test_path.read_text(encoding="utf-8")
    assert len(client.prompts) == 2
    assert "structured output retry 1" in client.prompts[1].lower()
    assert client.models == ["gpt-4.1-mini", "gpt-4.1"]
    assert client.max_tokens[1] > client.max_tokens[0]
    assert result["payload"]["ai_attempt_tiers"] == ["tier_standard", "tier_premium"]
    assert result["payload"]["ai_effective_tier"] == "tier_premium"


@pytest.mark.anyio
async def test_codex_executor_repairs_unapplyable_patch_by_regenerating_plan(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")
    test_path = tmp_path / "test_index_html.py"
    base_tests = (
        "def test_index_html_exists():\n"
        "    with open('index.html', 'r', encoding='utf-8') as handle:\n"
        "        assert '<main>' in handle.read()\n"
        "\n"
        "def test_index_html_contact_links_exist():\n"
        "    has_github = True\n"
        "    has_linkedin = True\n"
        "    assert has_github or has_linkedin, 'Contact section should have a GitHub or LinkedIn link placeholder.'\n"
    )
    test_path.write_text(base_tests, encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Write tests unapplyable patch repair", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="WRITE_TESTS",
            key="WRITE_TESTS",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "test_index_html.py"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequencePlanClient(
        [
            {
                "status": "DONE",
                "message": "patched",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "path": "test_index_html.py",
                        "patch": (
                            "--- a/test_index_html.py\n"
                            "+++ b/test_index_html.py\n"
                            "@@ -97,6 +97,18 @@\n"
                            "     assert has_github or has_linkedin, 'Contact section should have a GitHub or LinkedIn link placeholder.'\n"
                            " \n"
                            "+import re\n"
                            "+\n"
                            "+def test_index_html_has_theme_styles():\n"
                            "+    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            "+        content = handle.read().lower()\n"
                            "+    assert '<style' in content or re.search(r'<link[^>]+rel=[\"\\']stylesheet[\"\\']', content)\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
            {
                "status": "DONE",
                "message": "patched after repair",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "test_index_html.py",
                        "content": (
                            base_tests
                            + "\n"
                            + "import re\n"
                            + "\n"
                            + "def test_index_html_has_theme_styles():\n"
                            + "    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            + "        content = handle.read().lower()\n"
                            + "    assert '<style' in content or re.search(r'<link[^>]+rel=[\"\\']stylesheet[\"\\']', content)\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    def fake_apply_patch(self, patch: str):
        raise ValueError(
            "Patch apply error: Patch check failed: error: patch failed: test_index_html.py:97\n"
            "error: test_index_html.py: patch does not apply"
        )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.runtime.codex_executor.RepoTools.apply_patch", fake_apply_patch)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Add tests for themed portfolio styles",
                    "expected_files": ["test_index_html.py"],
                    "steps": [
                        {
                            "title": "Add tests for themed portfolio styles",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "WRITE_TESTS",
                            "expected_files": ["test_index_html.py"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "test_index_html_has_theme_styles" in test_path.read_text(encoding="utf-8")
    assert len(client.prompts) == 2
    assert "patch does not apply" in client.prompts[1]
    assert "prefer write_file with the full updated contents of the target test file" in client.prompts[1]


@pytest.mark.anyio
async def test_codex_executor_retries_truncated_patch_repair_output(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Fix failure repair parse retry", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="FIX_TEST_FAILURE",
            key="FIX_TEST_FAILURE",
            status="QUEUED",
            executor="codex",
            payload={
                "target_files": ["index.html"],
                "related_files": ["test_index_html.py"],
            },
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            {
                "status": "DONE",
                "message": "first fix patch",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "path": "index.html",
                        "patch": (
                            "--- a/index.html\n"
                            "+++ b/index.html\n"
                            "@@ -99,3 +99,5 @@\n"
                            "-<main>Portfolio</main>\n"
                            "+<section class=\"hero\"><main>Portfolio</main></section>\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
            "{\"status\":\"DONE\",\"message\":\"repair",
            {
                "status": "DONE",
                "message": "repair after parse retry",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": "<section class=\"hero\"><main>Portfolio</main></section>\n",
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    def fake_apply_patch(self, patch: str):
        raise ValueError(
            "Patch apply error: Patch check failed: error: patch failed: index.html:99\n"
            "error: index.html: patch does not apply"
        )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.runtime.codex_executor.RepoTools.apply_patch", fake_apply_patch)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Fix the hero markup after validation failed",
                    "expected_files": ["index.html", "test_index_html.py"],
                    "steps": [
                        {
                            "title": "Fix failing hero validation",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "FIX_TEST_FAILURE",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "class=\"hero\"" in index_path.read_text(encoding="utf-8")
    assert len(client.prompts) == 3
    assert "patch does not apply" in client.prompts[1]
    assert "structured output retry 1" in client.prompts[2].lower()
    assert client.max_tokens[2] > client.max_tokens[1]


@pytest.mark.anyio
async def test_fix_test_failure_retry_escalates_to_premium_model(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Fix failure escalation", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="FIX_TEST_FAILURE",
            key="FIX_TEST_FAILURE",
            status="QUEUED",
            executor="codex",
            payload={
                "target_files": ["index.html"],
                "related_files": ["test_index_html.py"],
            },
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            "{\"status\":\"DONE\",\"message\":\"repair",
            {
                "status": "DONE",
                "message": "repair after retry",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": "<main class='fixed'>Portfolio</main>\n",
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Fix the failing portfolio markup",
                    "expected_files": ["index.html", "test_index_html.py"],
                    "steps": [
                        {
                            "title": "Repair failing portfolio validation",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "FIX_TEST_FAILURE",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "class='fixed'" in index_path.read_text(encoding="utf-8")
    assert client.models == ["gpt-4.1-mini", "gpt-4.1"]
    assert result["payload"]["ai_attempt_tiers"] == ["tier_standard", "tier_premium"]
    assert result["payload"]["ai_effective_tier"] == "tier_premium"

    async with db_session_factory() as session:
        ai_job = (
            await session.execute(select(AIJobRun).where(AIJobRun.run_id == run_id))
        ).scalars().one()

    assert ai_job.actual_cost_cents == pytest.approx(0.0065, rel=1e-6)


@pytest.mark.anyio
async def test_codex_executor_stops_before_mutation_when_run_budget_is_exhausted(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")

    contract = build_execution_contract(
        run_summary={"target_files": ["index.html"]},
        architecture_profile=None,
        plan_snapshot={"expected_files": ["index.html"]},
    )
    contract.budget.max_cost_cents = 0.0001
    contract.budget.refresh()

    async with db_session_factory() as session:
        project = Project(name="Budget exhausted before apply", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(
            project_id=project.id,
            tenant_id=tenant_id,
            status="RUNNING",
            executor="codex",
            summary={
                "plan_snapshot": {"expected_files": ["index.html"]},
                "execution_contract": contract.to_dict(),
            },
        )
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="THEME_PORTFOLIO",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "index.html"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            {
                "status": "DONE",
                "message": "patched",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": "<main class='theme-shell'>Rethemed portfolio</main>\n",
                    }
                ],
                "artifacts": [],
            }
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Retheme the single-file portfolio",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Implement themed portfolio shell",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "CODE_FRONTEND",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
                execution_contract=contract,
            ),
        )

    assert result["status"] == "FAILED"
    assert result["message"] == "run_budget_exhausted"
    assert "Rethemed portfolio" not in index_path.read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_fix_test_failure_normalizes_failed_model_status_when_patch_applies(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<header><h1>Portfolio</h1></header>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Fix failure normalization", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="FIX_TEST_FAILURE",
            key="FIX_TEST_FAILURE",
            status="QUEUED",
            executor="codex",
            payload={"target_files": ["index.html"]},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequencePlanClient(
        [
            {
                "status": "FAILED",
                "message": "proposed a fix patch",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "path": "index.html",
                        "patch": (
                            "--- a/index.html\n"
                            "+++ b/index.html\n"
                            "@@ -1 +1 @@\n"
                            "-<header><h1>Portfolio</h1></header>\n"
                            "+<section class=\"hero\"><header><h1>Portfolio</h1></header></section>\n"
                        ),
                    }
                ],
                "artifacts": [],
            }
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)
    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Fix the failing hero-section validation",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Fix failing hero validation",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "FIX_TEST_FAILURE",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "candidate fix patch" in result["message"].lower()
    assert "fix_patch_applied_despite_failed_model_status" in result["payload"]["warnings"]
    assert "class=\"hero\"" in index_path.read_text(encoding="utf-8")
