import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.api.v1 import generation as generation_module
from app.db.base import Base
from app.db.models import Document, Project, Task, Trace
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app
from app.schemas.generation import GeneratedTask
from app.services.ai_policy import AIContextPack, AIJobPolicy, PreparedAIExecution
from app.services.llm_generator import LLMTaskGenerator, TASK_SCHEMA


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'generation.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    tenant_id = uuid.uuid4()

    async def override_get_tenant_context():
        return TenantContext(tenant_id=tenant_id, user_id="ui-user", role=None, enforcement=False)

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_tenant_context] = override_get_tenant_context
    session: AsyncSession = session_factory()
    try:
        yield session, tenant_id
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_tenant_context, None)
        await session.close()
        await engine.dispose()


@pytest.mark.anyio
async def test_public_generate_tasks_route_creates_tenant_scoped_tasks_and_traces(db_session, monkeypatch):
    session, tenant_id = db_session
    project = Project(name="Generation API", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    document = Document(
        project_id=project.id,
        tenant_id=tenant_id,
        type="prd",
        version=1,
        title="PRD",
        body="Build the feature",
    )
    session.add(document)
    await session.commit()

    async def fake_generate(self, title, body, payload):
        return (
            [GeneratedTask(title="Generated task", description="Do the work", category="func", confidence=0.9)],
            {"ai_model_name": "test-model", "ai_prompt_hash": "abc123"},
        )

    async def fake_health(project_id, session):
        return {"graph_cycles_detected": False}

    async def fake_lifecycle(project_id, session):
        return {"health_index": 100}

    monkeypatch.setattr(generation_module.LLMTaskGenerator, "generate", fake_generate)
    monkeypatch.setattr(generation_module, "project_health", fake_health)
    monkeypatch.setattr(generation_module, "lifecycle_score", fake_lifecycle)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/v1/projects/{project.id}/documents/{document.id}/generate-tasks", json={})

    assert resp.status_code == 201
    data = resp.json()
    assert data["tasks"][0]["title"] == "Generated task"

    tasks = (await session.execute(select(Task).where(Task.project_id == project.id))).scalars().all()
    assert len(tasks) == 1
    assert tasks[0].tenant_id == tenant_id

    traces = (
        await session.execute(
            select(Trace).where(Trace.project_id == project.id, Trace.relation_type.in_(["derives", "supersedes"]))
        )
    ).scalars().all()
    assert traces
    assert all(trace.tenant_id == tenant_id for trace in traces)


@pytest.mark.anyio
async def test_llm_task_generator_uses_named_json_schema_response_format(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    captured: dict[str, object] = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"tasks":[{"title":"Build homepage","confidence":0.9}]}'))],
                usage=SimpleNamespace(prompt_tokens=19, completion_tokens=11),
            )

    class FakeJobManager:
        async def load_context_pack(self, *args, **kwargs):
            return AIContextPack(
                fragments={},
                text="",
                cache_hits=0,
                cache_keys=[],
                pack_key="document-task-generation",
                pack_hash="pack-hash",
                pack_cache_hit=False,
            )

        def route_job(self, request):
            return AIJobPolicy(
                task_type="planning",
                ambiguity_level="high",
                risk_level="medium",
                max_model_tier="tier_premium",
                selected_model_tier="tier_premium",
                max_retries=0,
                max_context_tokens=2048,
                budget_cents=5.0,
                requires_human_review=False,
            )

        async def prepare_job(self, *args, **kwargs):
            return PreparedAIExecution(
                job_id=uuid.uuid4(),
                policy=self.route_job(None),
                model_name="gpt-test",
                estimated_input_tokens=0,
                estimated_output_tokens=0,
                estimated_cost_cents=0,
                context_size=0,
                cache_hit_count=0,
                blocked=False,
                stop_reason=None,
                next_action=None,
            )

        async def record_attempt(self, *args, **kwargs):
            return None

        async def complete_job(self, *args, **kwargs):
            return None

    generator = LLMTaskGenerator()
    generator.client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    generator._job_manager = FakeJobManager()

    tasks, provenance = await generator.generate(
        "Approved requirements graph v2",
        "FR1: Create homepage\nQR1: Load without browser errors",
        generation_module.TaskGenInput(),
    )

    assert len(tasks) == 1
    assert tasks[0].title == "Build homepage"
    assert provenance["ai_model_name"] == "gpt-test"
    assert captured["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "task_generation",
            "schema": TASK_SCHEMA,
        },
    }
