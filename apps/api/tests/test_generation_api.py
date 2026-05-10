import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.api.v1 import generation as generation_module
from app.db.base import Base
from app.db.models import AIJobRun, ArchitectureProfile, Document, Project, ProjectRepository, ProjectBlueprint, ProjectGenesisRun, ProjectTopologySnapshot, Run, RunSummary, Task, Trace
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
    assert tasks[0].source_type == "document_generation"
    assert tasks[0].source_node_id == str(document.id)
    assert tasks[0].architecture_slice == "application"

    traces = (
        await session.execute(
            select(Trace).where(Trace.project_id == project.id, Trace.relation_type.in_(["derives", "supersedes"]))
        )
    ).scalars().all()
    assert traces
    assert all(trace.tenant_id == tenant_id for trace in traces)


@pytest.mark.anyio
async def test_foundation_readiness_reports_repo_profile_and_missing_checks(db_session):
    session, tenant_id = db_session
    project = Project(name="Foundation", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            tenant_id=tenant_id,
            project_id=project.id,
            repo_url="https://github.com/example/app.git",
            repo_full_name="example/app",
            default_branch="main",
            auth_strategy="public_https",
        )
    )
    session.add(
        ArchitectureProfile(
            tenant_id=tenant_id,
            project_id=project.id,
            status="ACTIVE",
            summary="Vue and FastAPI app",
            profile_json={
                "repo_layout": {
                    "packages": [
                        {"name": "apps/web", "kind": "frontend"},
                        {"name": "apps/api", "kind": "backend"},
                    ]
                },
                "commands": {"test": {"command": "pytest -q"}, "web": {"command": "npm run build"}},
            },
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/projects/{project.id}/foundation-readiness")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "READY"
    assert data["repo_connected"] is True
    assert data["architecture_profile_present"] is True


@pytest.mark.anyio
async def test_manual_task_create_keeps_lineage_defaults_backward_compatible(db_session):
    session, tenant_id = db_session
    project = Project(name="Manual Task", tenant_id=tenant_id)
    session.add(project)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/projects/{project.id}/tasks",
            json={"title": "Manual work item", "description": "No lineage supplied"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["source"] == "manual"
    assert data["source_type"] == "manual"
    assert data["derived_from_requirement_ids"] is None


@pytest.mark.anyio
async def test_project_genesis_blueprint_flow_creates_setup_tasks_and_records_blueprint(db_session):
    session, _tenant_id = db_session
    project = Project(name="Genesis API", tenant_id=_tenant_id)
    session.add(project)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            f"/api/v1/projects/{project.id}/blueprint",
            json={
                "blueprint_key": "fullstack_monorepo",
                "stack_preset_key": "vue_fastapi",
                "deployment_profile": "local_preview",
                "readiness_enforced": True,
            },
        )
        fetch_resp = await client.get(f"/api/v1/projects/{project.id}/blueprint")
        runs_resp = await client.get(f"/api/v1/projects/{project.id}/genesis-runs/latest")

    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["blueprint"]["blueprint_key"] == "fullstack_monorepo"
    assert created["blueprint"]["readiness_enforced"] is True
    assert len(created["genesis_run"]["created_task_ids"]) == 9
    assert create_resp.json()["topology_snapshot"]["topology_json"]["directories"]

    assert fetch_resp.status_code == 200
    assert fetch_resp.json()["project_id"] == str(project.id)

    assert runs_resp.status_code == 200
    assert runs_resp.json()["status"] == "COMPLETED"

    blueprint = await session.scalar(select(ProjectBlueprint).where(ProjectBlueprint.project_id == project.id))
    assert blueprint is not None


@pytest.mark.anyio
async def test_governance_kpis_endpoint_surfaces_genesis_and_context_pack_metrics(db_session):
    session, tenant_id = db_session
    project = Project(name="Governance KPIs", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    blueprint = ProjectBlueprint(
        tenant_id=tenant_id,
        project_id=project.id,
        blueprint_key="fullstack_monorepo",
        stack_preset_key="vue_fastapi",
        deployment_profile="local_preview",
        architecture="fullstack_monorepo",
        status="ACTIVE",
        readiness_enforced=True,
    )
    session.add(blueprint)
    await session.flush()

    session.add(
        ProjectTopologySnapshot(
            tenant_id=tenant_id,
            project_id=project.id,
            blueprint_id=blueprint.id,
            version=1,
            topology_json={"blueprint_key": "fullstack_monorepo", "directories": ["apps/web"]},
            summary="snapshot-1",
        )
    )
    session.add(
        ProjectGenesisRun(
            tenant_id=tenant_id,
            project_id=project.id,
            blueprint_id=blueprint.id,
            status="COMPLETED",
            validation={"status": "READY"},
        )
    )
    session.add(Run(tenant_id=tenant_id, project_id=project.id, status="COMPLETED", executor="codex", summary={"task_source": "manual"}))
    session.add(
        AIJobRun(
            tenant_id=tenant_id,
            project_id=project.id,
            workflow_type="runtime.run",
            role="executor",
            task_type="coding",
            ambiguity_level="medium",
            risk_level="medium",
            max_model_tier="tier_standard",
            selected_model_tier="tier_standard",
            details_json={"context_pack": {"key": "scope-a", "hash": "h1", "pack_cache_hit": True}},
            status="completed",
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/projects/{project.id}/governance-kpis")

    assert resp.status_code == 200
    data = resp.json()
    assert data["blueprint_present"] is True
    assert data["genesis_success_rate"] == 100.0
    assert data["deterministic_replay_match"] == 100.0
    assert data["feature_runs_without_genesis"] == 0
    assert data["context_pack_usage"] == 100.0


@pytest.mark.anyio
async def test_run_impact_score_endpoint_compares_prediction_to_actual_files(db_session):
    session, tenant_id = db_session
    project = Project(name="Impact Score", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="COMPLETED",
        executor="codex",
        summary={
            "impact_prediction": {
                "predicted_files": ["apps/api/app/main.py", "apps/web/src/views/Home.vue"],
                "predicted_validations": ["run_tests"],
                "predicted_risk": "MEDIUM",
            }
        },
    )
    session.add(run)
    await session.flush()
    session.add(
        RunSummary(
            run_id=run.id,
            tenant_id=tenant_id,
            project_id=project.id,
            goal_text="impact",
            status="COMPLETED",
            executor="codex",
            workspace_status="READY",
            recovery_count=1,
            artifact_count=0,
            changed_files=["apps/api/app/main.py", "apps/api/app/routes.py"],
            artifact_types=[],
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/runs/{run.id}/impact-score")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["precision"] == 50.0
    assert payload["recall"] == 50.0
    assert "apps/api/app/main.py" in payload["overlap_files"]
    assert "recovery_invoked" in payload["regression_signals"]


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
