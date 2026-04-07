import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Project, WorkItem
from app.runtime.dag import TaskScopeError, _payload_for_stage, _task_payload_from_summary, generate_template_dag


def test_task_payload_from_summary_carries_target_scope_and_budget():
    payload = _task_payload_from_summary(
        {
            "task_id": "task-123",
            "task_title": "Improve homepage layout",
            "goal": "Improve homepage layout",
            "target_files": ["index.html", "styles.css"],
            "edit_budget": {
                "mode": "minimal_patch",
                "max_files": 2,
                "hard_max_files": 4,
            },
        }
    )

    assert payload["target_files"] == ["index.html", "styles.css"]
    assert payload["files"] == ["index.html", "styles.css"]
    assert payload["expected_files"] == ["index.html", "styles.css"]
    assert payload["edit_budget"] == {
        "mode": "minimal_patch",
        "max_files": 2,
        "hard_max_files": 4,
    }


def test_task_payload_from_summary_infers_frontend_entrypoint_from_hero_goal():
    payload = _task_payload_from_summary(
        {
            "task_id": "task-hero",
            "task_title": "Implement hero section",
            "goal": "Implement hero section: Add a hero section to the homepage.",
        }
    )

    assert payload["expected_files"] == ["index.html"]


def test_payload_for_write_tests_targets_generated_test_file():
    payload = _payload_for_stage(
        "WRITE_TESTS",
        {
            "task_id": "task-hero",
            "task_title": "Implement hero section",
            "goal": "Implement hero section",
            "expected_files": ["index.html"],
        },
    )

    assert payload["related_files"] == ["index.html"]
    assert payload["target_files"] == ["test_index_html.py"]
    assert payload["expected_files"] == ["test_index_html.py"]


@pytest.mark.anyio
async def test_generate_template_dag_omits_backend_for_frontend_scoped_task(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-dag.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Project.metadata.create_all)

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        async with session_factory() as session:
            session.add(Project(id=project_id, name="Portfolio", tenant_id=tenant_id))
            await session.flush()

            created = await generate_template_dag(
                session,
                project_id,
                run_id,
                executor="codex",
                tenant_id=tenant_id,
                run_summary={
                    "task_id": "task-hero",
                    "task_title": "Implement hero section",
                    "goal": "Implement hero section: Add a hero section to the homepage.",
                },
            )
            await session.commit()

            assert created == 6
            work_items = (
                await session.execute(
                    select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.priority.desc(), WorkItem.created_at.asc())
                )
            ).scalars().all()
            keys = [item.key for item in work_items]

            assert "CODE_BACKEND" not in keys
            assert keys == [
                "PLAN_DAG",
                "CODE_FRONTEND",
                "WRITE_TESTS",
                "REVIEW_DIFF",
                "RUN_TESTS",
                "REVIEW_INTEGRATION",
            ]

            frontend = next(item for item in work_items if item.key == "CODE_FRONTEND")
            write_tests = next(item for item in work_items if item.key == "WRITE_TESTS")
            run_tests = next(item for item in work_items if item.key == "RUN_TESTS")

            assert frontend.payload["target_files"] == ["index.html"]
            assert write_tests.payload["target_files"] == ["test_index_html.py"]
            assert write_tests.payload["related_files"] == ["index.html"]
            assert run_tests.payload["target_files"] == ["test_index_html.py"]
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_generate_template_dag_rejects_task_runs_without_file_scope(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-dag-empty-scope.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Project.metadata.create_all)

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        async with session_factory() as session:
            session.add(Project(id=project_id, name="Scope-less project", tenant_id=tenant_id))
            await session.flush()

            with pytest.raises(TaskScopeError, match="has no file scope"):
                await generate_template_dag(
                    session,
                    project_id,
                    run_id,
                    executor="codex",
                    tenant_id=tenant_id,
                    run_summary={
                        "task_id": "task-noscope",
                        "task_title": "Implement backend",
                        "goal": "Implement backend",
                    },
                )
    finally:
        await engine.dispose()
