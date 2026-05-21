from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Project, Run, RunLedger, StageLedger, WorkItem
from app.services.run_execution_console import _merge_command_audit_records, build_run_execution_console


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


@pytest.mark.anyio
async def test_build_run_execution_console_surfaces_targeting_and_reuse_telemetry(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'run-execution-console.db'}", future=True)
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
    work_item_id = uuid.uuid4()
    now = datetime.now(UTC)
    try:
        async with session_factory() as session:
            session.add(Project(id=project_id, name="Console project", tenant_id=tenant_id))
            session.add(
                Run(
                    id=run_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    status="RUNNING",
                    executor="codex",
                    workspace_status="READY",
                    branch_name="feature/runtime-proof",
                    summary={"goal": "Improve landing page hero targeting"},
                )
            )
            session.add(
                WorkItem(
                    id=work_item_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=run_id,
                    type="CODE_FRONTEND",
                    key="CODE_FRONTEND",
                    status="DONE",
                    priority=10,
                    executor="codex",
                    attempt=1,
                    payload={"task_title": "Implement hero section"},
                    result={},
                    started_at=now,
                    finished_at=now + timedelta(seconds=20),
                )
            )
            session.add(
                StageLedger(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=run_id,
                    work_item_id=work_item_id,
                    stage_name="CODE_FRONTEND",
                    lifecycle_state="DONE",
                    started_at=now,
                    finished_at=now + timedelta(seconds=20),
                    duration_ms=20000,
                    retries=1,
                    recovery_count=0,
                    model_tier="standard",
                    files_touched=2,
                    lines_added=45,
                    lines_removed=4,
                    package_affinity="apps/web",
                    layer_affinity="component",
                    topology_zone="landing",
                    architecture_compliance_score=0.95,
                    payload={
                        "targeting_strategy": "repo_graph_neighbor_expansion",
                        "target_file_count": 2,
                        "selected_existing_files_count": 1,
                        "neighbor_files_count": 1,
                        "component_reuse_preferred": True,
                        "module_reuse_preferred": False,
                        "reuse_ratio": 0.5,
                        "primary_targeting_reasons": ["identity:hero", "semantic:landing", "component_shell_bias"],
                        "primary_target_score": 14,
                        "runner_up_target_score": 8,
                        "targeting_confidence_delta": 6,
                        "targeting_confidence_label": "decisive",
                        "top_ranked_candidates": [
                            {
                                "path": "apps/web/src/components/landing/HeroSection.vue",
                                "score": 14,
                                "reasons": ["identity:hero", "semantic:landing", "component_shell_bias"],
                            },
                            {
                                "path": "apps/web/src/pages/LandingPage.vue",
                                "score": 8,
                                "reasons": ["semantic:landing", "page_shell_penalty"],
                            },
                        ],
                    },
                )
            )
            session.add(
                RunLedger(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=run_id,
                    event_type="RUN_COMPLETED",
                    total_cost_cents=3.5,
                    total_duration_ms=20000,
                    recovery_overhead_pct=0.0,
                    preview_failures=0,
                    drift_events=0,
                    payload={
                        "targeted_stage_count": 1,
                        "component_reuse_ratio": 1.0,
                        "module_reuse_ratio": 0.0,
                        "avg_reuse_ratio": 0.5,
                        "package_drift_count": 0,
                        "monolith_risk_max": 0.12,
                        "preview_continuity_score": 1.0,
                        "avg_targeting_confidence_delta": 6.0,
                        "decisive_targeting_count": 1,
                        "moderate_targeting_count": 0,
                        "close_targeting_count": 0,
                    },
                )
            )
            await session.commit()

            response = await build_run_execution_console(session, tenant_id=tenant_id, run_id=run_id)

            assert response.summary.ledger is not None
            assert response.summary.ledger.targeted_stage_count == 1
            assert response.summary.ledger.component_reuse_ratio == 1.0
            assert response.summary.ledger.avg_reuse_ratio == 0.5
            assert response.summary.ledger.preview_continuity_score == 1.0
            assert response.summary.ledger.avg_targeting_confidence_delta == 6.0
            assert response.summary.ledger.decisive_targeting_count == 1
            assert response.summary.ledger.moderate_targeting_count == 0
            assert response.summary.ledger.close_targeting_count == 0

            assert len(response.stage_telemetry) == 1
            stage = response.stage_telemetry[0]
            assert stage.package_affinity == "apps/web"
            assert stage.layer_affinity == "component"
            assert stage.topology_zone == "landing"
            assert stage.targeting_strategy == "repo_graph_neighbor_expansion"
            assert stage.target_file_count == 2
            assert stage.selected_existing_files_count == 1
            assert stage.neighbor_files_count == 1
            assert stage.component_reuse_preferred is True
            assert stage.module_reuse_preferred is False
            assert stage.reuse_ratio == 0.5
            assert stage.primary_targeting_reasons == ["identity:hero", "semantic:landing", "component_shell_bias"]
            assert stage.primary_target_score == 14.0
            assert stage.runner_up_target_score == 8.0
            assert stage.targeting_confidence_delta == 6.0
            assert stage.targeting_confidence_label == "decisive"
            assert stage.top_ranked_candidates[0]["path"].endswith("HeroSection.vue")
            assert stage.top_ranked_candidates[1]["path"].endswith("LandingPage.vue")
    finally:
        await engine.dispose()
