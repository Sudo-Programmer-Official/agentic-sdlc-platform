import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Document, Project, Run, Trace, WorkItem
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.runtime.codex_executor import CodexExecutor
from app.runtime.context import RunContext


class FakeClient:
    def __init__(self):
        self.user_prompt = None

    async def generate(self, system_prompt, user_prompt):
        self.user_prompt = user_prompt
        return (
            json.dumps(
                {
                    "status": "DONE",
                    "message": "ok",
                    "actions": [],
                    "artifacts": [],
                    "warnings": [],
                }
            ),
            {"input_tokens": 1, "output_tokens": 1},
        )


class StaticPlanClient:
    def __init__(self, plan: dict):
        self.plan = plan
        self.user_prompt = None

    async def generate(self, system_prompt, user_prompt):
        self.user_prompt = user_prompt
        return json.dumps(self.plan), {"input_tokens": 1, "output_tokens": 1}


@pytest.fixture
async def db_session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'codex-graph.db'}", future=True)
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


@pytest.mark.anyio
async def test_codex_executor_includes_graph_context_in_prompt(monkeypatch, db_session_factory, tmp_path):
    tenant_id = uuid.uuid4()
    async with db_session_factory() as session:
        project = Project(name="Prompt graph", tenant_id=tenant_id, description="Authentication runtime project")
        session.add(project)
        await session.flush()

        document = Document(
            project_id=project.id,
            tenant_id=tenant_id,
            type="PRD",
            version=1,
            title="Authentication PRD",
            body="Implement login and token validation for the API.",
        )
        session.add(document)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_BACKEND",
            key="AUTH_MIDDLEWARE",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "apps/api/app/auth.py"},
        )
        session.add(work_item)
        await session.flush()

        session.add(
            Trace(
                project_id=project.id,
                tenant_id=tenant_id,
                from_type="run",
                from_id=run.id,
                to_type="work_item",
                to_id=work_item.id,
                relation_type="executes",
            )
        )
        await session.commit()
        work_item_id = work_item.id
        project_id = project.id
        run_id = run.id

    fake_client = FakeClient()
    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    monkeypatch.setattr(executor, "_get_client", lambda: fake_client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(work_item, RunContext(project_id=project_id, run_id=run_id))

    assert result["status"] == "DONE"
    prompt = json.loads(fake_client.user_prompt)
    assert "graph_context" in prompt
    assert prompt["graph_context"]["root"]["type"] == "work_item"
    assert any(node["type"] == "run" for node in prompt["graph_context"]["ancestors"])
    assert "documents" in prompt["graph_context"]["project_brief"]
    assert prompt["graph_context"]["budget"]["max_depth"] == 3
    assert "lineage" in prompt["graph_context"]


@pytest.mark.anyio
async def test_codex_executor_blocks_out_of_scope_patch(monkeypatch, db_session_factory, tmp_path):
    tenant_id = uuid.uuid4()
    (tmp_path / "feature.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("value = 2\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Patch guard", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_BACKEND",
            key="PATCH_FEATURE",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "feature.py"},
        )
        session.add(work_item)
        await session.commit()
        work_item_id = work_item.id
        project_id = project.id
        run_id = run.id

    client = StaticPlanClient(
        {
            "status": "DONE",
            "message": "patched",
            "warnings": [],
            "actions": [
                {
                    "type": "apply_patch",
                    "patch": (
                        "diff --git a/other.py b/other.py\n"
                        "--- a/other.py\n"
                        "+++ b/other.py\n"
                        "@@ -1 +1 @@\n-value = 2\n+value = 3\n"
                    ),
                }
            ],
            "artifacts": [],
        }
    )
    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
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
                    "goal": "Patch feature",
                    "expected_files": ["feature.py"],
                    "steps": [
                        {
                            "title": "Patch feature",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "CODE_BACKEND",
                            "expected_files": ["feature.py"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "FAILED"
    assert "outside the planned scope" in result["message"]


@pytest.mark.anyio
async def test_codex_executor_blocks_confirmation_required_patch(monkeypatch, db_session_factory, tmp_path):
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    (auth_dir / "auth.py").write_text("value = 1\n", encoding="utf-8")

    tenant_id = uuid.uuid4()
    async with db_session_factory() as session:
        project = Project(name="Sensitive patch", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_BACKEND",
            key="PATCH_AUTH",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "auth/auth.py"},
        )
        session.add(work_item)
        await session.commit()
        work_item_id = work_item.id
        project_id = project.id
        run_id = run.id

    client = StaticPlanClient(
        {
            "status": "DONE",
            "message": "patched",
            "warnings": [],
            "actions": [
                {
                    "type": "apply_patch",
                    "patch": (
                        "diff --git a/auth/auth.py b/auth/auth.py\n"
                        "--- a/auth/auth.py\n"
                        "+++ b/auth/auth.py\n"
                        "@@ -1 +1 @@\n-value = 1\n+value = 2\n"
                    ),
                }
            ],
            "artifacts": [],
        }
    )
    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
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
                    "goal": "Patch auth validation",
                    "expected_files": ["auth/auth.py"],
                    "steps": [
                        {
                            "title": "Patch auth validation",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "CODE_BACKEND",
                            "expected_files": ["auth/auth.py"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "FAILED"
    assert "requires operator confirmation" in result["message"]
