from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import PatchLedger, Project, Run, RunLedger, StageLedger, WorkItem
from app.services.runtime_execution_ledger import project_runtime_ledger_from_event


@pytest.mark.anyio
async def test_runtime_execution_ledger_records_targeting_and_run_aggregate_metrics(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-execution-ledger.db'}", future=True)
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
    now = datetime.now(UTC)
    try:
        async with session_factory() as session:
            session.add(Project(id=project_id, name="Ledger project", tenant_id=tenant_id))
            session.add(
                Run(
                    id=run_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    status="COMPLETED",
                    executor="codex",
                    started_at=now,
                    finished_at=now + timedelta(minutes=3),
                    summary={"feature_key": "cap-landing", "capability_key": "cap-landing"},
                )
            )

            frontend_item = WorkItem(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                type="CODE_FRONTEND",
                key="CODE_FRONTEND",
                status="DONE",
                executor="codex",
                attempt=1,
                payload={
                    "feature_key": "cap-landing",
                    "package_affinity": "apps/web",
                    "layer_affinity": "component",
                    "target_files": [
                        "apps/web/src/components/landing/HeroSection.vue",
                        "apps/web/src/pages/LandingPage.vue",
                    ],
                    "targeting_strategy": "repo_graph_neighbor_expansion",
                    "targeting_evidence": {
                        "repo_index_used": True,
                        "selected_existing_files": ["apps/web/src/components/landing/HeroSection.vue"],
                        "neighbor_files": ["apps/web/src/pages/LandingPage.vue"],
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
                    "component_reuse_preferred": True,
                },
                result={
                    "files": ["apps/web/src/components/landing/HeroSection.vue"],
                    "lines_added": 40,
                    "lines_removed": 5,
                    "selected_model_tier": "standard",
                    "execution_zone": "landing",
                    "architecture_compliance_score": 0.94,
                    "patch_entropy": 0.21,
                    "monolith_risk": 0.08,
                    "drift_risk_score": 0.12,
                    "risk_score": 0.15,
                },
                started_at=now,
                finished_at=now + timedelta(seconds=30),
            )
            backend_item = WorkItem(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                type="GENERATE_SERVICE",
                key="GENERATE_SERVICE",
                status="DONE",
                executor="codex",
                attempt=1,
                payload={
                    "feature_key": "cap-leads",
                    "package_affinity": "apps/api",
                    "layer_affinity": "service",
                    "target_files": ["apps/api/app/services/lead_capture_service.py"],
                    "targeting_strategy": "repo_index_reuse",
                    "targeting_evidence": {
                        "repo_index_used": True,
                        "selected_existing_files": ["apps/api/app/services/lead_capture_service.py"],
                        "top_ranked_candidates": [
                            {
                                "path": "apps/api/app/services/lead_capture_service.py",
                                "score": 11,
                                "reasons": ["identity:lead_capture", "layer_affinity"],
                            },
                            {
                                "path": "apps/api/app/routes/lead_capture.py",
                                "score": 9,
                                "reasons": ["semantic:lead_capture"],
                            },
                        ],
                    },
                    "module_reuse_preferred": True,
                },
                result={
                    "files": ["apps/api/app/services/lead_capture_service.py"],
                    "lines_added": 22,
                    "lines_removed": 0,
                    "selected_model_tier": "standard",
                    "execution_zone": "lead_capture",
                    "architecture_compliance_score": 0.97,
                    "patch_entropy": 0.14,
                    "monolith_risk": 0.05,
                    "drift_risk_score": 0.09,
                    "risk_score": 0.1,
                },
                started_at=now + timedelta(seconds=35),
                finished_at=now + timedelta(seconds=55),
            )
            preview_item = WorkItem(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                type="PREVIEW_VALIDATE",
                key="PREVIEW_VALIDATE",
                status="DONE",
                executor="codex",
                attempt=1,
                payload={"package_affinity": "apps/web"},
                result={"files": [], "selected_model_tier": "standard"},
                started_at=now + timedelta(seconds=60),
                finished_at=now + timedelta(seconds=80),
            )
            session.add_all([frontend_item, backend_item, preview_item])
            await session.flush()

            await project_runtime_ledger_from_event(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                work_item_id=frontend_item.id,
                event_type="WORK_ITEM_DONE",
                payload={"source": "test"},
            )
            await project_runtime_ledger_from_event(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                work_item_id=backend_item.id,
                event_type="WORK_ITEM_DONE",
                payload={"source": "test"},
            )
            await project_runtime_ledger_from_event(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                work_item_id=preview_item.id,
                event_type="WORK_ITEM_DONE",
                payload={"source": "test"},
            )
            await project_runtime_ledger_from_event(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                work_item_id=None,
                event_type="RUN_COMPLETED",
                payload={"source": "test"},
            )
            await session.commit()

            frontend_stage = await session.scalar(
                select(StageLedger).where(StageLedger.run_id == run_id, StageLedger.stage_name == "CODE_FRONTEND")
            )
            backend_patch = await session.scalar(
                select(PatchLedger).where(PatchLedger.run_id == run_id, PatchLedger.stage_name == "GENERATE_SERVICE")
            )
            run_ledger = await session.scalar(select(RunLedger).where(RunLedger.run_id == run_id))

            assert frontend_stage is not None
            assert frontend_stage.payload["targeting_strategy"] == "repo_graph_neighbor_expansion"
            assert frontend_stage.payload["selected_existing_files_count"] == 1
            assert frontend_stage.payload["neighbor_files_count"] == 1
            assert frontend_stage.payload["target_file_count"] == 2
            assert frontend_stage.payload["reuse_ratio"] == 0.5
            assert frontend_stage.payload["primary_target_score"] == 14.0
            assert frontend_stage.payload["runner_up_target_score"] == 8.0
            assert frontend_stage.payload["targeting_confidence_delta"] == 6.0
            assert frontend_stage.payload["targeting_confidence_label"] == "decisive"

            assert backend_patch is not None
            assert backend_patch.payload["targeting_strategy"] == "repo_index_reuse"
            assert backend_patch.payload["selected_existing_files_count"] == 1
            assert backend_patch.payload["reuse_ratio"] == 1.0
            assert backend_patch.payload["targeting_confidence_delta"] == 2.0
            assert backend_patch.payload["targeting_confidence_label"] == "moderate"

            assert run_ledger is not None
            assert run_ledger.preview_failures == 0
            assert run_ledger.payload["targeted_stage_count"] == 2
            assert run_ledger.payload["component_reuse_ratio"] == 0.5
            assert run_ledger.payload["module_reuse_ratio"] == 0.5
            assert run_ledger.payload["avg_reuse_ratio"] == 0.75
            assert run_ledger.payload["preview_continuity_score"] == 1.0
            assert run_ledger.payload["monolith_risk_max"] == 0.08
            assert run_ledger.payload["avg_targeting_confidence_delta"] == 4.0
            assert run_ledger.payload["decisive_targeting_count"] == 1
            assert run_ledger.payload["moderate_targeting_count"] == 1
            assert run_ledger.payload["close_targeting_count"] == 0
    finally:
        await engine.dispose()
