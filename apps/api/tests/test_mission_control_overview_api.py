import uuid
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import TenantContext, get_tenant_context
from app.db.base import Base
from app.db.models import Approval, Artifact, Document, Project, ProjectPreviewProfile, ProjectRepository, Run, RunEvent, Task, WorkItem
from app.db.models.tenant import Tenant  # noqa: F401
from app.db.models.tenant_member import TenantMember  # noqa: F401
from app.db.session import get_session
from app.main import app
from app.runtime.execution_contract import build_execution_contract


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mission-control-overview.db'}", future=True)
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
async def test_mission_control_overview_returns_intake_impact_and_insights(db_session):
    session, tenant_id = db_session
    project = Project(name="Mission control", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="https://github.com/acme/example.git",
            repo_full_name="acme/example",
            default_branch="main",
        )
    )
    session.add(
        ProjectPreviewProfile(
            project_id=project.id,
            tenant_id=tenant_id,
            enabled=True,
            mode="local",
            frontend_root="apps/web",
            backend_root="apps/api",
            frontend_start_command="npm run dev",
            backend_start_command="uvicorn app.main:app --host $HOST --port $PORT",
            ttl_hours=24,
        )
    )

    document = Document(
        tenant_id=tenant_id,
        project_id=project.id,
        type="PRD",
        version=1,
        title="Fix authentication test failure",
        body="GET /login returns 500 when auth fixture is missing. Update auth flow and tests.",
        source="manual",
        created_by="ui-user",
    )
    session.add(document)
    await session.flush()

    session.add(
        Task(
            tenant_id=tenant_id,
            project_id=project.id,
            document_id=document.id,
            title="Inspect auth service and update failing tests",
            category="func",
            stage="PLAN",
            status="PENDING",
            source="manual",
            created_by="ui-user",
        )
    )

    started = datetime.utcnow() - timedelta(minutes=6)
    older_run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/minimal-patch",
        workspace_status="SEEDED",
        started_at=started,
        finished_at=started + timedelta(seconds=70),
        summary={
            "goal": "Fix failing auth tests with a minimal patch",
            "strategy_type": "minimal_patch",
            "strategy_label": "Minimal Patch",
        },
    )
    latest_run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/auth-fix",
        workspace_status="SEEDED",
        started_at=started + timedelta(minutes=2),
        finished_at=started + timedelta(minutes=2, seconds=84),
        summary={
            "goal": "Fix failing auth tests and open a PR",
            "pull_request_url": "https://github.com/acme/example/pull/42",
            "pull_request_number": 42,
            "strategy_type": "minimal_patch",
            "strategy_label": "Minimal Patch",
            "preview": {
                "status": "READY",
                "mode": "local",
                "preview_url": "http://127.0.0.1:3100",
                "frontend": {"url": "http://127.0.0.1:3100"},
                "backend": {"url": "http://127.0.0.1:8100"},
                "expires_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            },
            "execution_contract": build_execution_contract(
                run_summary={
                    "goal": "Fix failing auth tests and open a PR",
                    "target_files": ["app/auth_service.py"],
                    "expected_files": ["app/auth_service.py", "tests/test_auth.py"],
                    "edit_budget": {"mode": "minimal_patch", "max_files": 2, "hard_max_files": 4},
                },
                architecture_profile={
                    "protected_paths": ["app/db/models"],
                    "safe_paths": ["app"],
                    "command_index": {
                        "repo_tests": {
                            "command": "python3 -m pytest -q tests/test_auth.py",
                            "kind": "test",
                            "paths": ["tests"],
                        }
                    },
                },
                plan_snapshot={
                    "validation_steps": ["Run tests", "Review diff"],
                    "success_criteria": ["Auth tests pass"],
                    "risk_level": "MEDIUM",
                },
            ).to_dict(),
        },
    )
    session.add_all([older_run, latest_run])
    await session.flush()

    patch = (
        "diff --git a/app/auth_service.py b/app/auth_service.py\n"
        "--- a/app/auth_service.py\n"
        "+++ b/app/auth_service.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
        "diff --git a/tests/test_auth.py b/tests/test_auth.py\n"
        "--- a/tests/test_auth.py\n"
        "+++ b/tests/test_auth.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )

    patch_artifact = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        run_id=latest_run.id,
        type="git_diff",
        uri="workspace://patches/auth.patch",
        version=1,
        extra_metadata={"content": patch},
    )
    pr_artifact = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        run_id=latest_run.id,
        type="pull_request",
        uri="https://github.com/acme/example/pull/42",
        version=1,
        extra_metadata={"number": 42},
    )
    older_patch = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        run_id=older_run.id,
        type="git_diff",
        uri="workspace://patches/older.patch",
        version=1,
        extra_metadata={"content": patch},
    )
    external_ref = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        run_id=latest_run.id,
        type="external_reference",
        uri="https://docs.python.org/3/library/asyncio.html",
        version=1,
        extra_metadata={
            "label": "asyncio docs",
            "summary": "Use timeout and cancellation boundaries.",
            "domain": "docs.python.org",
            "trust_score": 0.9,
            "fetched_at": datetime.utcnow().isoformat(),
            "used_in_execution_count": 2,
        },
    )
    session.add_all([patch_artifact, pr_artifact, older_patch, external_ref])
    await session.flush()

    session.add(
        Approval(
            tenant_id=tenant_id,
            project_id=project.id,
            target_type="artifact",
            target_id=patch_artifact.id,
            status="APPROVED",
            decided_by="reviewer",
            decided_at=datetime.utcnow().isoformat(),
            comment="Looks safe",
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/mission-control/overview")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["work_intake"]
    assert data["work_intake"][0]["title"] == "Fix authentication test failure"
    assert "auth_service.py" in ",".join(data["work_intake"][0]["predicted_files"])
    assert data["recent_runs"][0]["run_id"] == str(latest_run.id)
    assert data["recent_runs"][0]["approval_status"] == "APPROVED"
    assert data["latest_change_impact"]["run_id"] == str(latest_run.id)
    assert "auth_service" in data["latest_change_impact"]["modules_impacted"]
    assert "tests/test_auth.py" in data["latest_change_impact"]["tests_impacted"]
    assert "GET /login" in data["latest_change_impact"]["api_impact"]
    assert data["architecture_profile"]["repo_full_name"] == "acme/example"
    assert data["architecture_profile"]["package_count"] >= 2
    assert "apps/web" in data["architecture_profile"]["packages"]
    assert data["project_contract"]["status"] in {"MISSING", "DRAFT"}
    assert data["latest_execution_contract"]["lifecycle_state"] == "PENDING"
    assert data["latest_execution_contract"]["validation_state"] == "PENDING"
    assert data["latest_execution_contract"]["budget"]["budget_mode"] == "NORMAL"
    assert data["recent_runs"][0]["execution_contract"]["test_command"] == "python3 -m pytest -q tests/test_auth.py"
    assert data["imported_references"]
    assert data["imported_references"][0]["type"] == "external_reference"
    assert "docs.python.org" in data["imported_references"][0]["uri"]
    assert data["imported_references"][0]["domain"] == "docs.python.org"
    assert "trust_score" in data["imported_references"][0]
    assert "freshness_score" in data["imported_references"][0]
    assert data["violation_insights"]["latest_run_total"] == 0
    assert data["violation_insights"]["recent_total"] == 0


@pytest.mark.anyio
async def test_mission_control_overview_surfaces_project_contract_violation_insights(db_session):
    session, tenant_id = db_session
    project = Project(name="Violation analytics", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    started = datetime.utcnow() - timedelta(minutes=5)
    latest_run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="FAILED",
        executor="codex",
        branch_name="run/strict-enforcement",
        workspace_status="SEEDED",
        started_at=started + timedelta(minutes=2),
        finished_at=started + timedelta(minutes=2, seconds=40),
        summary={
            "goal": "Apply hero styling with project contract enforcement",
        },
    )
    older_run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/warn-enforcement",
        workspace_status="SEEDED",
        started_at=started,
        finished_at=started + timedelta(seconds=75),
        summary={
            "goal": "Retry hero change in warn mode",
        },
    )
    session.add_all([older_run, latest_run])
    await session.flush()

    session.add_all(
        [
            WorkItem(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=latest_run.id,
                type="WRITE_TESTS",
                status="FAILED",
                executor="codex",
                result={
                    "patch_guard": {
                        "project_enforcement_mode": "strict",
                        "project_violation_records": [
                            {
                                "work_item_id": str(uuid.uuid4()),
                                "work_item_type": "WRITE_TESTS",
                                "mode": "strict",
                                "blocking": True,
                                "type": "raw_hex_color",
                                "rule": "no_raw_hex_colors",
                                "file": "index.html",
                                "value": "#ff00ff",
                                "message": "Raw hex color '#ff00ff' is not allowed.",
                            }
                        ],
                    }
                },
            ),
            WorkItem(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=latest_run.id,
                type="CODE_FRONTEND",
                status="DONE",
                executor="codex",
                result={
                    "patch_guard": {
                        "project_enforcement_mode": "warn",
                        "project_violation_records": [
                            {
                                "work_item_id": str(uuid.uuid4()),
                                "work_item_type": "CODE_FRONTEND",
                                "mode": "warn",
                                "blocking": False,
                                "type": "inline_style",
                                "rule": "no_inline_styles",
                                "file": "index.html",
                                "value": "style=\"color:#fff\"",
                                "message": "Inline style detected.",
                            }
                        ],
                    }
                },
            ),
            WorkItem(
                tenant_id=tenant_id,
                project_id=project.id,
                run_id=older_run.id,
                type="CODE_FRONTEND",
                status="DONE",
                executor="codex",
                result={
                    "patch_guard": {
                        "project_enforcement_mode": "warn",
                        "project_violation_records": [
                            {
                                "work_item_id": str(uuid.uuid4()),
                                "work_item_type": "CODE_FRONTEND",
                                "mode": "warn",
                                "blocking": False,
                                "type": "inline_style",
                                "rule": "no_inline_styles",
                                "file": "components/hero.html",
                                "message": "Inline style detected.",
                            }
                        ],
                    }
                },
            ),
        ]
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/mission-control/overview")

    assert response.status_code == 200, response.text
    data = response.json()
    insights = data["violation_insights"]
    assert insights["latest_run_id"] == str(latest_run.id)
    assert insights["latest_run_total"] == 2
    assert insights["latest_run_blocking"] == 1
    assert insights["latest_run_warning"] == 1
    assert insights["recent_run_window"] == 2
    assert insights["recent_total"] == 3

    assert insights["top_rules"][0] == {"name": "no_inline_styles", "count": 2}
    assert insights["top_types"][0] == {"name": "inline_style", "count": 2}
    assert insights["top_files"][0] == {"name": "index.html", "count": 2}

    assert len(insights["recent_samples"]) == 3
    assert all(sample["run_id"] in {str(latest_run.id), str(older_run.id)} for sample in insights["recent_samples"])
    assert any(
        sample["run_id"] == str(latest_run.id)
        and sample["blocking"] is True
        and sample["rule"] == "no_raw_hex_colors"
        for sample in insights["recent_samples"]
    )


@pytest.mark.anyio
async def test_mission_control_overview_surfaces_default_preview_contract_for_repo_backed_project(db_session):
    session, tenant_id = db_session
    project = Project(name="Default preview contract", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/static-site.git",
            repo_full_name="acme/static-site",
            default_branch="main",
        )
    )

    run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/static-site",
        workspace_status="SEEDED",
        summary={"goal": "Create static homepage"},
    )
    session.add(run)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/mission-control/overview")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["previews_and_prs"]["repository_connected"] is True
    assert data["previews_and_prs"]["profile_configured"] is True
    assert data["previews_and_prs"]["preview_mode"] == "local"
    assert data["previews_and_prs"]["preview_status"] == "NOT_CONFIGURED"


@pytest.mark.anyio
async def test_mission_control_overview_preview_panel_prefers_latest_deliverable_run(db_session):
    session, tenant_id = db_session
    project = Project(name="Deliverable selection", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    started = datetime.utcnow() - timedelta(minutes=10)

    session.add(
        ProjectRepository(
            project_id=project.id,
            tenant_id=tenant_id,
            provider="github",
            repo_url="git@github.com:acme/static-site.git",
            repo_full_name="acme/static-site",
            default_branch="main",
        )
    )

    deliverable_run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/deliverable",
        workspace_status="SEEDED",
        started_at=started,
        finished_at=started + timedelta(seconds=75),
        summary={
            "goal": "Ship a deliverable patch",
            "remote_branch_pushed": True,
            "remote_branch_name": "run/deliverable",
            "preview": {
                "status": "READY",
                "mode": "local",
                "preview_url": "http://127.0.0.1:3100",
                "frontend": {"url": "http://127.0.0.1:3100"},
            },
        },
    )
    latest_noop_run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="COMPLETED",
        executor="dummy",
        branch_name="run/noop",
        workspace_status="SEEDED",
        started_at=started + timedelta(minutes=3),
        finished_at=started + timedelta(minutes=3, seconds=20),
        summary={"goal": "No-op run"},
    )
    session.add_all([deliverable_run, latest_noop_run])
    await session.flush()

    patch_artifact = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        run_id=deliverable_run.id,
        type="git_diff",
        uri="workspace://patches/deliverable.patch",
        version=1,
        extra_metadata={
            "content": (
                "diff --git a/index.html b/index.html\n"
                "--- a/index.html\n"
                "+++ b/index.html\n"
                "@@ -1 +1 @@\n-old\n+new\n"
            )
        },
    )
    session.add(patch_artifact)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/mission-control/overview")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["recent_runs"][0]["run_id"] == str(latest_noop_run.id)
    assert data["previews_and_prs"]["run_id"] == str(deliverable_run.id)
    assert data["previews_and_prs"]["branch_name"] == "run/deliverable"
    assert data["previews_and_prs"]["preview_status"] == "READY"
    assert data["previews_and_prs"]["preview_url"] == "http://127.0.0.1:3100"
    assert data["previews_and_prs"]["active_preview_url"] == "http://127.0.0.1:3100"
    assert data["previews_and_prs"]["stale_preview_url"] is None
    assert data["previews_and_prs"]["frontend_port"] is None
    assert data["previews_and_prs"]["backend_port"] is None
    assert data["previews_and_prs"]["last_health_check_at"] is None
    assert data["previews_and_prs"]["preview_domain_host"] is not None
    assert data["previews_and_prs"]["preview_domain_url"].startswith("https://")
    assert data["previews_and_prs"]["file_count"] == 1


@pytest.mark.anyio
async def test_mission_control_overview_preview_panel_exposes_active_vs_stale_urls_and_health_fields(db_session):
    session, tenant_id = db_session
    project = Project(name="Preview URL split", tenant_id=tenant_id)
    session.add(project)
    await session.flush()
    started = datetime.utcnow() - timedelta(minutes=8)

    deliverable_run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/preview-split",
        workspace_status="SEEDED",
        started_at=started,
        finished_at=started + timedelta(seconds=50),
        summary={
            "goal": "Refresh preview after restart",
            "preview": {
                "status": "READY",
                "mode": "local",
                "preview_url": "http://127.0.0.1:3100",
                "last_checked_at": datetime.utcnow().isoformat(),
                "frontend": {
                    "url": "http://127.0.0.1:3200",
                    "port": 3200,
                },
                "backend": {
                    "url": "http://127.0.0.1:9100",
                    "port": 9100,
                },
            },
        },
    )
    session.add(deliverable_run)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/mission-control/overview")

    assert response.status_code == 200, response.text
    panel = response.json()["previews_and_prs"]
    assert panel["run_id"] == str(deliverable_run.id)
    assert panel["preview_status"] == "READY"
    assert panel["preview_url"] == "http://127.0.0.1:3100"
    assert panel["active_preview_url"] == "http://127.0.0.1:3200"
    assert panel["stale_preview_url"] == "http://127.0.0.1:3100"
    assert panel["frontend_port"] == 3200
    assert panel["backend_port"] == 9100
    assert panel["last_health_check_at"] is not None


@pytest.mark.anyio
async def test_execution_console_surfaces_execution_contract_telemetry(db_session):
    session, tenant_id = db_session
    project = Project(name="Execution console telemetry", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="RUNNING",
        executor="codex",
        branch_name="run/runtime-contract",
        workspace_status="READY",
        summary={
            "goal": "Fix runtime contract drift",
            "execution_contract": build_execution_contract(
                run_summary={
                    "goal": "Fix runtime contract drift",
                    "target_files": ["apps/api/app/runtime/codex_executor.py"],
                    "expected_files": ["apps/api/app/runtime/codex_executor.py"],
                },
                architecture_profile={
                    "command_index": {
                        "repo_tests": {
                            "command": "python3 -m pytest -q apps/api/tests/test_codex_executor.py",
                            "kind": "test",
                            "paths": ["apps/api/tests"],
                        }
                    }
                },
                plan_snapshot={
                    "validation_steps": ["Run tests"],
                    "risk_level": "LOW",
                },
            ).to_dict(),
        },
    )
    session.add(run)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/runs/{run.id}/execution-console")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["summary"]["execution_contract"]["lifecycle_state"] == "PENDING"
    assert data["summary"]["execution_contract"]["validation_steps"] == ["Run tests"]
    assert data["summary"]["execution_contract"]["budget"]["budget_mode"] == "NORMAL"


@pytest.mark.anyio
async def test_mission_control_overview_pr_trust_metadata_and_approval_state(db_session):
    session, tenant_id = db_session
    project = Project(name="PR trust", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="COMPLETED",
        executor="codex",
        branch_name="run/pr-trust",
        workspace_status="SEEDED",
        started_at=datetime.utcnow() - timedelta(minutes=2),
        finished_at=datetime.utcnow() - timedelta(minutes=1),
        summary={"goal": "Prepare approved patch for PR"},
    )
    session.add(run)
    await session.flush()

    patch = (
        "diff --git a/app/auth.py b/app/auth.py\n"
        "--- a/app/auth.py\n"
        "+++ b/app/auth.py\n"
        "@@ -1 +1 @@\n"
        "-print('old')\n"
        "+print('new')\n"
    )
    artifact = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        run_id=run.id,
        type="git_diff",
        uri="artifact://patches/pr-trust.diff",
        extra_metadata={"content": patch},
        version=1,
    )
    session.add(artifact)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/mission-control/overview?include_heavy=true")

    assert response.status_code == 200, response.text
    payload = response.json()
    preview_panel = payload["previews_and_prs"]

    assert preview_panel["run_id"] == str(run.id)
    assert preview_panel["approval_status"] in {None, "PENDING", "REJECTED", "APPROVED"}
    assert preview_panel["file_count"] >= 1
    assert isinstance(preview_panel["additions"], int)
    assert isinstance(preview_panel["deletions"], int)


@pytest.mark.anyio
async def test_mission_control_overview_includes_stalled_runs(db_session):
    session, tenant_id = db_session
    project = Project(name="Stalled detector", tenant_id=tenant_id)
    session.add(project)
    await session.flush()

    run = Run(
        tenant_id=tenant_id,
        project_id=project.id,
        status="RUNNING",
        executor="codex",
        summary={"goal": "Long running update"},
        started_at=datetime.utcnow() - timedelta(minutes=20),
    )
    session.add(run)
    await session.flush()
    session.add(
        RunEvent(
            tenant_id=tenant_id,
            project_id=project.id,
            run_id=run.id,
            event_type="RUN_RUNNING",
            ts=datetime.utcnow() - timedelta(minutes=12),
            payload={"status": "RUNNING"},
        )
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project.id}/mission-control/overview")

    assert response.status_code == 200, response.text
    payload = response.json()
    stalled = payload["stalled_runs"]
    assert len(stalled) == 1
    assert stalled[0]["run_id"] == str(run.id)
    assert stalled[0]["status"] == "RUNNING"
    assert stalled[0]["stale_seconds"] >= 300
