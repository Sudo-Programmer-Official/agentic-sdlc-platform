import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.api.v1 import generation as generation_module
from app.api.v1 import persistence as persistence_module
from app.db.base import Base
from app.db.models import AIJobRun, ArchitectureProfile, Document, Project, ProjectRepository, ProjectBlueprint, ProjectGenesisRun, ProjectTopologySnapshot, Run, RunSummary, Task, Trace
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app
from app.schemas.generation import GeneratedTask
from app.services.ai_policy import AIContextPack, AIJobPolicy, PreparedAIExecution
from app.services.llm_generator import LLMTaskGenerator, TASK_SCHEMA
from app.core.config import get_settings
from app.services import repo_provisioning_service
from app.services.runtime_lifecycle_service import set_runtime_state


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


@pytest.fixture(autouse=True)
def stub_runtime_readiness(monkeypatch):
    async def fake_assess_preview_runtime_readiness(**_kwargs):
        return {
            "ready": True,
            "repository_connected": True,
            "preview_profile_enabled": True,
            "preview_profile_resolved": True,
            "dependencies_ready_frontend": True,
            "dependencies_ready_backend": True,
            "preview_runtime_ready": True,
            "backend_runtime_ready": True,
            "frontend_install_status": "cached",
            "backend_install_status": "cached",
            "runtime_boot_duration_seconds": 0.25,
            "dependency_repair_attempts": 0,
            "cached_hydration_state": {"frontend": "hit", "backend": "hit"},
        }

    monkeypatch.setattr(
        persistence_module,
        "assess_preview_runtime_readiness",
        fake_assess_preview_runtime_readiness,
    )


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
                "commands": {
                    "test": {"command": "pytest -q"},
                    "web": {"command": "npm run build"},
                    "preview": {"command": "npm -C apps/web run dev"},
                    "backend_start": {"command": "python3 apps/api/main.py"}
                },
            },
        )
    )
    session.add(
        Run(
            project_id=project.id,
            tenant_id=tenant_id,
            status="COMPLETED",
            executor="codex",
            summary={
                "preview": {
                    "status": "READY",
                    "diagnostics": {
                        "dependencies_ready_frontend": True,
                        "dependencies_ready_backend": True,
                        "preview_runtime_ready": True,
                        "backend_runtime_ready": True,
                        "frontend_install_status": "cached",
                        "backend_install_status": "cached",
                    },
                }
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
    frontend_check = next(item for item in data["checks"] if item["key"] == "dependencies_ready_frontend")
    backend_check = next(item for item in data["checks"] if item["key"] == "dependencies_ready_backend")
    preview_check = next(item for item in data["checks"] if item["key"] == "preview_runtime_ready")
    backend_runtime_check = next(item for item in data["checks"] if item["key"] == "backend_runtime_ready")
    executable_check = next(item for item in data["checks"] if item["key"] == "foundation_executable_ready")
    assert frontend_check["status"] == "PASS"
    assert backend_check["status"] == "PASS"
    assert preview_check["status"] == "PASS"
    assert backend_runtime_check["status"] == "PASS"
    assert executable_check["status"] == "PASS"


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
async def test_create_project_instantiates_runtime_template(db_session, tmp_path, monkeypatch):
    _session, _tenant_id = db_session
    template_root = tmp_path / "runtime-templates"
    source = template_root / "fullstack-monorepo"
    (source / "apps" / "web").mkdir(parents=True, exist_ok=True)
    (source / "README.md").write_text("# template\n", encoding="utf-8")

    bootstrap_root = tmp_path / "workspace-bootstrap"
    monkeypatch.setenv("RUNTIME_TEMPLATES_ROOT", str(template_root))
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(bootstrap_root))
    get_settings.cache_clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/v1/projects",
            json={
                "name": "Template Instantiation Project",
                "starter_blueprint_enabled": True,
                "project_intent": {
                    "setup_experience": "recommended",
                    "template_key": "fullstack-monorepo",
                    "template_version": 1,
                },
            },
        )

    assert create_resp.status_code == 201
    created = create_resp.json()
    project_id = created["id"]
    manifest_path = Path(bootstrap_root) / "project-templates" / str(_tenant_id) / project_id / "runtime_template_manifest.json"
    repo_root = manifest_path.parent / "repo"
    assert manifest_path.exists()
    assert (repo_root / "README.md").exists()
    assert (repo_root / "apps" / "web").exists()
    project_row = await _session.scalar(select(Project).where(Project.id == uuid.UUID(project_id)))
    lifecycle = ((project_row.project_intent_json or {}).get("runtime_lifecycle") if project_row else None) or {}
    assert lifecycle.get("state") == "GOVERNANCE_READY"
    assert any(item.get("state") == "TEMPLATE_INSTANTIATED" for item in lifecycle.get("timeline", []))
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_create_project_auto_creates_repo_for_new_repo_intent(db_session, tmp_path, monkeypatch):
    _session, _tenant_id = db_session
    template_root = tmp_path / "runtime-templates"
    source = template_root / "fullstack-monorepo"
    (source / "apps" / "web").mkdir(parents=True, exist_ok=True)
    (source / "README.md").write_text("# template\n", encoding="utf-8")
    bootstrap_root = tmp_path / "workspace-bootstrap"
    monkeypatch.setenv("RUNTIME_TEMPLATES_ROOT", str(template_root))
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(bootstrap_root))
    monkeypatch.setenv("GITHUB_ALLOWED_ORG", "acme")
    get_settings.cache_clear()

    async def fake_auto_provision(
        session,
        *,
        project,
        project_intent,
        template_repo_root,
        actor_id,
        github_adapter,
        github_allowed_org,
    ):
        repo = ProjectRepository(
            tenant_id=project.tenant_id,
            project_id=project.id,
            provider="github",
            repo_url="https://github.com/acme/auto-repo-project.git",
            repo_full_name="acme/auto-repo-project",
            default_branch="main",
            installation_id=1234,
            auth_strategy="runtime_default",
            created_by=actor_id,
        )
        session.add(repo)
        await session.flush()
        return SimpleNamespace(attempted=True, connected=True, failed=False, reason=None)

    monkeypatch.setattr(persistence_module, "auto_provision_project_repository", fake_auto_provision)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/projects",
            json={
                "name": "Auto Repo Project",
                "starter_blueprint_enabled": True,
                "project_intent": {
                    "setup_experience": "recommended",
                    "repo_type": "new_repo",
                    "repo_owner": "acme",
                    "repo_name": "auto-repo-project",
                    "installation_id": 1234,
                },
            },
        )

    assert resp.status_code == 201
    created = resp.json()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_resp = await client.get(f"/api/v1/projects/{created['id']}/repo")
    assert repo_resp.status_code == 200
    repo = repo_resp.json()
    assert repo["repo_full_name"] == "acme/auto-repo-project"
    assert repo["repo_url"] == "https://github.com/acme/auto-repo-project.git"
    project_row = await _session.scalar(select(Project).where(Project.id == uuid.UUID(created["id"])))
    lifecycle = ((project_row.project_intent_json or {}).get("runtime_lifecycle") if project_row else None) or {}
    assert lifecycle.get("state") == "ACTIVE"
    assert any(item.get("state") == "REPO_CONNECTED" for item in lifecycle.get("timeline", []))
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_create_project_new_repo_intent_without_owner_does_not_fail_runtime(db_session, tmp_path, monkeypatch):
    _session, _tenant_id = db_session
    template_root = tmp_path / "runtime-templates"
    source = template_root / "fullstack-monorepo"
    (source / "apps" / "web").mkdir(parents=True, exist_ok=True)
    (source / "README.md").write_text("# template\n", encoding="utf-8")
    bootstrap_root = tmp_path / "workspace-bootstrap"
    monkeypatch.setenv("RUNTIME_TEMPLATES_ROOT", str(template_root))
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(bootstrap_root))
    monkeypatch.delenv("GITHUB_ALLOWED_ORG", raising=False)
    get_settings.cache_clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/projects",
            json={
                "name": "Repo Owner Missing Project",
                "starter_blueprint_enabled": True,
                "project_intent": {
                    "setup_experience": "recommended",
                    "repo_type": "new_repo",
                    "repo_name": "repo-owner-missing-project",
                },
            },
        )

    assert resp.status_code == 201
    created = resp.json()
    project_row = await _session.scalar(select(Project).where(Project.id == uuid.UUID(created["id"])))
    lifecycle = ((project_row.project_intent_json or {}).get("runtime_lifecycle") if project_row else None) or {}
    assert lifecycle.get("state") != "FAILED"
    assert not any(item.get("state") == "FAILED" for item in lifecycle.get("timeline", []))
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_auto_provision_connect_existing_repo_mode_attaches_repo(db_session, monkeypatch):
    session, tenant_id = db_session
    project = Project(
        name="Connect Existing Repo",
        tenant_id=tenant_id,
    )
    session.add(project)
    await session.flush()

    async def fake_connect_repo(
        session,
        *,
        project,
        provider,
        repo_url,
        default_branch,
        repo_full_name=None,
        installation_id=None,
        auth_strategy=None,
        created_by=None,
    ):
        repo = ProjectRepository(
            tenant_id=project.tenant_id,
            project_id=project.id,
            provider=provider,
            repo_url=repo_url,
            repo_full_name=repo_full_name,
            default_branch=default_branch,
            installation_id=installation_id,
            auth_strategy=auth_strategy or "runtime_default",
            created_by=created_by,
        )
        session.add(repo)
        await session.flush()
        return repo

    monkeypatch.setattr(
        repo_provisioning_service,
        "preflight_repo_access",
        lambda **kwargs: SimpleNamespace(ok=True, error=None),
    )
    monkeypatch.setattr(repo_provisioning_service, "connect_repo", fake_connect_repo)
    monkeypatch.setattr(
        repo_provisioning_service,
        "_classify_repository_shape",
        lambda **kwargs: repo_provisioning_service.RepoShapeClassification(kind="nearly_empty", tracked_files=1),
    )
    pr_calls: list[dict] = []
    find_calls: list[dict] = []

    monkeypatch.setattr(
        repo_provisioning_service,
        "_bootstrap_template_into_existing_repo",
        lambda **kwargs: repo_provisioning_service.ExistingRepoBootstrapResult(
            created=True,
            commit_sha="abc123",
            reason="bootstrapped",
            branch_name="foundation/connect-existing-repo",
            local_clone_path="/tmp/workspaces/project/repo",
        ),
    )

    result = await repo_provisioning_service.auto_provision_project_repository(
        session,
        project=project,
        project_intent={
            "repo_type": "new_repo",
            "repository_mode": "connect_existing",
            "repo_url": "https://github.com/abhishek-jha-ai/growth-marketing.git",
            "repo_full_name": "abhishek-jha-ai/growth-marketing",
            "default_branch": "main",
            "installation_id": 1234,
        },
        template_repo_root="/tmp/runtime-template",
        actor_id="ui-user",
        github_adapter=SimpleNamespace(
            find_open_pull_request=lambda **kwargs: find_calls.append(kwargs)
            or {"html_url": "https://github.com/abhishek-jha-ai/growth-marketing/pull/1", "number": 1},
            create_pull_request=lambda **kwargs: pr_calls.append(kwargs)
            or {"html_url": "https://github.com/abhishek-jha-ai/growth-marketing/pull/1", "number": 1},
        ),
        github_allowed_org=None,
    )
    assert result.connected is True
    assert len(find_calls) == 1
    assert len(pr_calls) == 0
    connected_repo = await session.scalar(select(ProjectRepository).where(ProjectRepository.project_id == project.id))
    assert connected_repo is not None
    assert connected_repo.repo_full_name == "abhishek-jha-ai/growth-marketing"


@pytest.mark.anyio
async def test_get_project_runtime_lifecycle_endpoint_returns_timeline(db_session):
    session, tenant_id = db_session
    project = Project(
        name="Lifecycle endpoint project",
        tenant_id=tenant_id,
        project_intent_json={
            "runtime_lifecycle": {
                "state": "ACTIVE",
                "updated_at": "2026-05-19T00:00:00+00:00",
                "timeline": [
                    {
                        "state": "CREATED",
                        "from_state": None,
                        "ts": "2026-05-18T23:59:00+00:00",
                        "diagnostics": {"starter_blueprint_enabled": True},
                        "error": None,
                    },
                    {
                        "state": "ACTIVE",
                        "from_state": "GOVERNANCE_READY",
                        "ts": "2026-05-19T00:00:00+00:00",
                        "diagnostics": {},
                        "error": None,
                    },
                ],
                "last_error": None,
                "retry_count": 0,
            }
        },
    )
    session.add(project)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/projects/{project.id}/runtime-lifecycle")

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ACTIVE"
    assert len(body["timeline"]) == 2
    assert body["timeline"][0]["state"] == "CREATED"


@pytest.mark.anyio
async def test_initialize_runtime_endpoint_advances_lifecycle(db_session, tmp_path, monkeypatch):
    session, tenant_id = db_session
    template_root = tmp_path / "runtime-templates"
    source = template_root / "fullstack-monorepo"
    (source / "apps" / "web").mkdir(parents=True, exist_ok=True)
    (source / "README.md").write_text("# template\n", encoding="utf-8")
    bootstrap_root = tmp_path / "workspace-bootstrap"
    monkeypatch.setenv("RUNTIME_TEMPLATES_ROOT", str(template_root))
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(bootstrap_root))
    get_settings.cache_clear()

    project = Project(
        name="Initialize runtime project",
        tenant_id=tenant_id,
        project_intent_json={
            "setup_experience": "recommended",
            "template_key": "fullstack-monorepo",
            "template_version": 1,
        },
    )
    session.add(project)
    await session.flush()
    await persistence_module.set_runtime_state(
        session,
        project=project,
        state="CREATED",
        actor_id="test-user",
        diagnostics={"starter_blueprint_enabled": True},
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/v1/projects/{project.id}/initialize-runtime")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] in {"GOVERNANCE_READY", "ACTIVE"}
    states = [item["state"] for item in body["timeline"]]
    assert "TEMPLATE_INSTANTIATED" in states
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_initialize_runtime_from_failed_state_enters_repairing_and_recovers(db_session, tmp_path, monkeypatch):
    session, tenant_id = db_session
    template_root = tmp_path / "runtime-templates"
    source = template_root / "fullstack-monorepo"
    (source / "apps" / "web").mkdir(parents=True, exist_ok=True)
    (source / "README.md").write_text("# template\n", encoding="utf-8")
    bootstrap_root = tmp_path / "workspace-bootstrap"
    monkeypatch.setenv("RUNTIME_TEMPLATES_ROOT", str(template_root))
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(bootstrap_root))
    get_settings.cache_clear()

    project = Project(
        name="Repairing runtime project",
        tenant_id=tenant_id,
        project_intent_json={
            "setup_experience": "recommended",
            "template_key": "fullstack-monorepo",
            "template_version": 1,
            "runtime_lifecycle": {
                "state": "FAILED",
                "updated_at": "2026-05-19T00:00:00+00:00",
                "timeline": [],
                "last_error": "previous bootstrap failure",
                "retry_count": 1,
            },
        },
    )
    session.add(project)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/v1/projects/{project.id}/initialize-runtime")
    assert resp.status_code == 200
    body = resp.json()
    states = [item["state"] for item in body["timeline"]]
    assert "REPAIRING" in states
    assert "TEMPLATE_INSTANTIATED" in states
    assert body["state"] in {"GOVERNANCE_READY", "ACTIVE"}
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_initialize_runtime_skips_auto_provision_when_repo_already_connected(db_session, tmp_path, monkeypatch):
    session, tenant_id = db_session
    template_root = tmp_path / "runtime-templates"
    source = template_root / "fullstack-monorepo"
    (source / "apps" / "web").mkdir(parents=True, exist_ok=True)
    (source / "README.md").write_text("# template\n", encoding="utf-8")
    bootstrap_root = tmp_path / "workspace-bootstrap"
    monkeypatch.setenv("RUNTIME_TEMPLATES_ROOT", str(template_root))
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(bootstrap_root))
    get_settings.cache_clear()

    project = Project(
        name="Existing connected repo project",
        tenant_id=tenant_id,
        project_intent_json={
            "setup_experience": "recommended",
            "repo_type": "new_repo",
            "template_key": "fullstack-monorepo",
            "template_version": 1,
            "runtime_lifecycle": {
                "state": "FAILED",
                "updated_at": "2026-05-19T00:00:00+00:00",
                "timeline": [],
                "last_error": "repo_owner is required for auto repository creation when github_allowed_org is unset",
                "retry_count": 1,
            },
        },
    )
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            tenant_id=tenant_id,
            project_id=project.id,
            provider="github",
            repo_url="https://github.com/abhishek-jha-ai/growth-marketing.git",
            repo_full_name="abhishek-jha-ai/growth-marketing",
            default_branch="main",
            installation_id=111321279,
            auth_strategy="runtime_default",
            created_by="ui-user",
        )
    )
    await session.commit()
    async def fake_reconcile(*args, **kwargs):
        return None
    monkeypatch.setattr(persistence_module, "reconcile_connected_repository_foundation", fake_reconcile)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/v1/projects/{project.id}/initialize-runtime")

    assert resp.status_code == 200
    body = resp.json()
    states = [item["state"] for item in body["timeline"]]
    assert "REPAIRING" in states
    assert "REPO_CONNECTED" in states
    assert body["state"] in {"GOVERNANCE_READY", "ACTIVE"}
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_initialize_runtime_existing_repo_runs_foundation_reconcile(db_session, tmp_path, monkeypatch):
    session, tenant_id = db_session
    template_root = tmp_path / "runtime-templates"
    source = template_root / "fullstack-monorepo"
    (source / "apps" / "web").mkdir(parents=True, exist_ok=True)
    (source / "README.md").write_text("# template\n", encoding="utf-8")
    bootstrap_root = tmp_path / "workspace-bootstrap"
    monkeypatch.setenv("RUNTIME_TEMPLATES_ROOT", str(template_root))
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(bootstrap_root))
    get_settings.cache_clear()

    project = Project(
        name="Existing repo reconcile project",
        tenant_id=tenant_id,
        project_intent_json={
            "setup_experience": "recommended",
            "template_key": "fullstack-monorepo",
            "template_version": 1,
            "runtime_lifecycle": {"state": "CREATED", "timeline": [], "retry_count": 0},
        },
    )
    session.add(project)
    await session.flush()
    session.add(
        ProjectRepository(
            tenant_id=tenant_id,
            project_id=project.id,
            provider="github",
            repo_url="https://github.com/abhishek-jha-ai/growth-marketing.git",
            repo_full_name="abhishek-jha-ai/growth-marketing",
            default_branch="main",
            installation_id=111321279,
            auth_strategy="runtime_default",
            created_by="ui-user",
        )
    )
    await session.commit()

    reconcile_calls: list[dict] = []

    async def fake_reconcile(*args, **kwargs):
        reconcile_calls.append(kwargs)

    monkeypatch.setattr(persistence_module, "reconcile_connected_repository_foundation", fake_reconcile)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/v1/projects/{project.id}/initialize-runtime")
    assert resp.status_code == 200
    assert len(reconcile_calls) == 1
    assert reconcile_calls[0]["project_repo"].repo_full_name == "abhishek-jha-ai/growth-marketing"
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_runtime_lifecycle_rejects_invalid_state_jump(db_session):
    session, tenant_id = db_session
    project = Project(name="Invalid transition project", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    await set_runtime_state(
        session,
        project=project,
        state="CREATED",
        actor_id="test-user",
        diagnostics={"starter_blueprint_enabled": False},
    )
    with pytest.raises(ValueError, match="Invalid runtime lifecycle transition"):
        await set_runtime_state(session, project=project, state="ACTIVE", actor_id="test-user")


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


@pytest.mark.anyio
async def test_force_regenerate_requirements_graph_preserves_genesis_setup_tasks(db_session, monkeypatch):
    session, tenant_id = db_session
    project = Project(name="Force Preserve Genesis", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    document = Document(
        project_id=project.id,
        tenant_id=tenant_id,
        type="requirements_graph",
        version=2,
        title="Approved requirements graph v2",
        body="{}",
    )
    session.add(document)
    await session.flush()

    genesis_task = Task(
        tenant_id=tenant_id,
        project_id=project.id,
        document_id=document.id,
        generated_from_document_version=document.version,
        title="initialize monorepo",
        description="setup",
        category="func",
        status="PENDING",
        source="ai",
        source_type="genesis_setup",
        source_node_id="genesis.foundation",
    )
    stale_feature_task = Task(
        tenant_id=tenant_id,
        project_id=project.id,
        document_id=document.id,
        generated_from_document_version=document.version,
        title="Build Hero Section",
        description="stale",
        category="func",
        status="PENDING",
        source="ai",
        source_type="requirement_propagation",
        source_node_id="req",
    )
    session.add_all([genesis_task, stale_feature_task])
    await session.commit()

    async def fake_generate(self, title, body, payload):
        return (
            [GeneratedTask(title="Fresh task", description="new", category="func", confidence=0.9)],
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
        resp = await client.post(
            f"/api/v1/projects/{project.id}/documents/{document.id}/generate-tasks?force=true",
            json={},
        )

    assert resp.status_code == 201
    await session.refresh(genesis_task)
    await session.refresh(stale_feature_task)
    assert genesis_task.status == "PENDING"
    assert stale_feature_task.status == "DEPRECATED"
