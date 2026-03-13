from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Approval, Artifact, Project, ProjectRepository, Run
from app.services.artifact_diff import build_artifact_diff_preview
from app.services.mission_control_overview import build_mission_control_overview
from app.services.run_comparison import compare_runs
from app.services.run_timeline import build_run_timeline


async def get_current_project(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> dict[str, Any]:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
    if project is None:
        raise ValueError("Project not found")

    repo = await session.scalar(
        select(ProjectRepository).where(
            ProjectRepository.project_id == project_id,
            ProjectRepository.tenant_id == tenant_id,
        )
    )
    overview = await build_mission_control_overview(session, tenant_id=tenant_id, project_id=project_id)
    latest_run = overview.recent_runs[0] if overview.recent_runs else None
    return {
        "project_id": str(project.id),
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "repository": {
            "provider": repo.provider,
            "repo_url": repo.repo_url,
            "repo_full_name": repo.repo_full_name,
            "default_branch": repo.default_branch,
        }
        if repo
        else None,
        "work_intake_count": len(overview.work_intake),
        "recent_run_count": len(overview.recent_runs),
        "latest_run": {
            "id": str(latest_run.run_id),
            "status": latest_run.status,
            "executor": latest_run.executor,
        }
        if latest_run
        else None,
    }


async def get_latest_run(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> dict[str, Any]:
    run = await session.scalar(
        select(Run)
        .where(Run.project_id == project_id, Run.tenant_id == tenant_id)
        .order_by(Run.created_at.desc(), Run.id.desc())
        .limit(1)
    )
    if run is None:
        raise ValueError("Run not found")
    timeline = await build_run_timeline(session, tenant_id=tenant_id, run_id=run.id)
    return {
        "run_id": str(run.id),
        "status": run.status,
        "executor": run.executor,
        "branch_name": run.branch_name,
        "workspace_status": run.workspace_status,
        "workspace_root": run.workspace_root,
        "repo_path": run.repo_path,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "goal_text": timeline.summary.goal_text,
        "primary_error": timeline.summary.primary_error,
        "recovery_count": timeline.summary.recovery_count,
        "changed_files": timeline.summary.changed_files,
        "pull_request_url": timeline.summary.pull_request_url,
    }


async def get_run_by_id(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
) -> dict[str, Any]:
    run = await session.scalar(
        select(Run).where(Run.id == run_id, Run.project_id == project_id, Run.tenant_id == tenant_id)
    )
    if run is None:
        raise ValueError("Run not found")
    timeline = await build_run_timeline(session, tenant_id=tenant_id, run_id=run.id)
    return {
        "run_id": str(run.id),
        "status": run.status,
        "executor": run.executor,
        "branch_name": run.branch_name,
        "workspace_status": run.workspace_status,
        "workspace_root": run.workspace_root,
        "repo_path": run.repo_path,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "goal_text": timeline.summary.goal_text,
        "primary_error": timeline.summary.primary_error,
        "recovery_count": timeline.summary.recovery_count,
        "changed_files": timeline.summary.changed_files,
        "pull_request_url": timeline.summary.pull_request_url,
    }


async def explain_artifact(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    artifact_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    if artifact_id is None:
        artifact = await session.scalar(
            select(Artifact)
            .where(
                Artifact.project_id == project_id,
                Artifact.tenant_id == tenant_id,
                Artifact.type == "git_diff",
                Artifact.deleted_at.is_(None),
            )
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
            .limit(1)
        )
    else:
        artifact = await session.scalar(
            select(Artifact).where(
                Artifact.id == artifact_id,
                Artifact.project_id == project_id,
                Artifact.tenant_id == tenant_id,
                Artifact.deleted_at.is_(None),
            )
        )
    if artifact is None:
        raise ValueError("Artifact not found")
    diff = await build_artifact_diff_preview(session, project_id=project_id, artifact_id=artifact.id)
    latest_approval = await session.scalar(
        select(Approval)
        .where(
            Approval.project_id == project_id,
            Approval.tenant_id == tenant_id,
            Approval.target_type == "artifact",
            Approval.target_id == artifact.id,
            Approval.deleted_at.is_(None),
        )
        .order_by(Approval.created_at.desc(), Approval.id.desc())
    )
    return {
        "artifact_id": str(artifact.id),
        "run_id": str(artifact.run_id) if artifact.run_id else None,
        "work_item_id": str(artifact.work_item_id) if artifact.work_item_id else None,
        "type": artifact.type,
        "uri": artifact.uri,
        "approval_status": latest_approval.status if latest_approval else "PENDING",
        "file_count": diff.file_count,
        "additions": diff.additions,
        "deletions": diff.deletions,
        "changed_files": [file.path for file in diff.files],
    }


async def compare_project_runs(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    run_a_id: uuid.UUID | None = None,
    run_b_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    if run_a_id is None or run_b_id is None:
        runs = (
            await session.execute(
                select(Run)
                .where(Run.project_id == project_id, Run.tenant_id == tenant_id)
                .order_by(Run.created_at.desc(), Run.id.desc())
                .limit(2)
            )
        ).scalars().all()
        if len(runs) < 2:
            raise ValueError("Need at least two runs to compare")
        run_a_id, run_b_id = runs[0].id, runs[1].id

    comparison = await compare_runs(session, tenant_id=tenant_id, run_a_id=run_a_id, run_b_id=run_b_id)
    return {
        "run_a_id": str(comparison.run_a.id),
        "run_b_id": str(comparison.run_b.id),
        "run_a_status": comparison.run_a.status,
        "run_b_status": comparison.run_b.status,
        "run_a_elapsed_seconds": comparison.run_a.elapsed_seconds,
        "run_b_elapsed_seconds": comparison.run_b.elapsed_seconds,
        "run_a_recovery_count": comparison.run_a.recovery_count,
        "run_b_recovery_count": comparison.run_b.recovery_count,
        "run_a_files_changed": comparison.run_a.files_changed,
        "run_b_files_changed": comparison.run_b.files_changed,
        "faster_run_id": str(comparison.summary.faster_run_id) if comparison.summary.faster_run_id else None,
        "faster_by_seconds": comparison.summary.faster_by_seconds,
        "pull_request_run_id": str(comparison.summary.pull_request_run_id)
        if comparison.summary.pull_request_run_id
        else None,
    }


async def get_workspace_status(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    run: Run | None
    if run_id is not None:
        run = await session.scalar(
            select(Run).where(Run.id == run_id, Run.project_id == project_id, Run.tenant_id == tenant_id)
        )
    else:
        run = await session.scalar(
            select(Run)
            .where(Run.project_id == project_id, Run.tenant_id == tenant_id)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(1)
        )
    if run is None:
        raise ValueError("Run not found")
    return {
        "run_id": str(run.id),
        "workspace_status": run.workspace_status,
        "workspace_root": run.workspace_root,
        "repo_path": run.repo_path,
        "branch_name": run.branch_name,
        "workspace_error": run.workspace_error,
    }
