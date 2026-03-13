from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run
from app.schemas.run_narrative import RunPatchPlan, RunPatchVerificationFinding, RunPatchVerificationSummary
from app.services.repo_map import build_project_repo_impact

DEFAULT_MAX_FILES = 5
DEFAULT_MAX_DEPTH = 2
HARD_MAX_FILES = 15
SENSITIVE_TOKENS = {"auth", "payment", "billing", "migration", "migrations", "tenant", "security"}


def _common_subsystem(paths: list[str]) -> str | None:
    directory_parts = [PurePosixPath(path).parent.parts for path in paths if path]
    if not directory_parts:
        return None
    shared = list(directory_parts[0])
    for parts in directory_parts[1:]:
        limit = min(len(shared), len(parts))
        index = 0
        while index < limit and shared[index] == parts[index]:
            index += 1
        shared = shared[:index]
        if not shared:
            break
    if len(shared) >= 2:
        return "/".join(shared[:2])
    if shared:
        return "/".join(shared)
    return None


def _sensitive_scope(paths: list[str], subsystem: str | None) -> bool:
    haystack = " ".join([*(paths or []), subsystem or ""]).lower()
    return any(token in haystack for token in SENSITIVE_TOKENS)


def _risk_level(*, file_count: int, dependent_count: int, sensitive_scope: bool) -> str:
    if sensitive_scope or file_count > DEFAULT_MAX_FILES or dependent_count >= 4:
        return "HIGH"
    if file_count >= 3 or dependent_count >= 2:
        return "MEDIUM"
    return "LOW"


async def build_run_patch_plan_and_verification(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run: Run,
    goal: str | None,
    planned_steps: list[str],
    planned_files: list[str],
    confidence_score: float | None,
) -> tuple[RunPatchPlan, RunPatchVerificationSummary]:
    primary_files = list(dict.fromkeys(path for path in planned_files if isinstance(path, str) and path.strip()))
    subsystem = _common_subsystem(primary_files)

    dependent_files: list[str] = []
    related_tests: list[str] = []
    max_detected_depth = 1
    findings: list[RunPatchVerificationFinding] = []

    for file_path in primary_files[:DEFAULT_MAX_FILES]:
        try:
            impact = await build_project_repo_impact(
                session,
                tenant_id=tenant_id,
                project_id=run.project_id,
                file_path=file_path,
                depth=1,
                max_files=HARD_MAX_FILES,
            )
        except ValueError:
            continue

        max_detected_depth = max(max_detected_depth, impact.depth)
        for item in impact.dependent_files:
            if item.path not in primary_files and item.path not in dependent_files:
                dependent_files.append(item.path)
        for item in impact.related_tests:
            if item.path not in related_tests:
                related_tests.append(item.path)

    if dependent_files:
        findings.append(
            RunPatchVerificationFinding(
                code="dependent_files",
                severity="warning",
                title="Dependent files may need review",
                detail="Imported or downstream files were detected around the planned patch scope.",
                files=dependent_files[:6],
            )
        )
    if not related_tests and primary_files:
        findings.append(
            RunPatchVerificationFinding(
                code="missing_tests",
                severity="warning",
                title="No nearby tests detected",
                detail="The current scope does not map cleanly to a nearby test file. Review test coverage before applying the patch.",
                files=[],
            )
        )

    total_scope_files = len({*primary_files, *dependent_files, *related_tests})
    sensitive_scope = _sensitive_scope(primary_files + dependent_files, subsystem)
    risk_level = _risk_level(
        file_count=len(primary_files),
        dependent_count=len(dependent_files),
        sensitive_scope=sensitive_scope,
    )
    requires_confirmation = (
        risk_level in {"MEDIUM", "HIGH"}
        or len(primary_files) > DEFAULT_MAX_FILES
        or total_scope_files > DEFAULT_MAX_FILES
        or max_detected_depth > 1
    )

    if sensitive_scope:
        findings.append(
            RunPatchVerificationFinding(
                code="sensitive_scope",
                severity="high",
                title="Sensitive subsystem detected",
                detail="The planned patch touches a subsystem that should stay under explicit review.",
                files=primary_files[:6],
            )
        )
    if len(primary_files) > DEFAULT_MAX_FILES:
        findings.append(
            RunPatchVerificationFinding(
                code="file_cap_exceeded",
                severity="high",
                title="Patch exceeds normal file budget",
                detail=f"Planned primary scope touches {len(primary_files)} files; the normal autonomous cap is {DEFAULT_MAX_FILES}.",
                files=primary_files[:8],
            )
        )
    if max_detected_depth > 1:
        findings.append(
            RunPatchVerificationFinding(
                code="dependency_depth",
                severity="warning",
                title="Dependency chain expanded past the default depth",
                detail="The scope required deeper dependency expansion than the normal safe default.",
                files=dependent_files[:6],
            )
        )

    if not primary_files:
        requires_confirmation = True
        findings.append(
            RunPatchVerificationFinding(
                code="no_scope",
                severity="warning",
                title="No planned patch files identified yet",
                detail="The system can describe the run, but it does not yet have a bounded patch file envelope for this run.",
                files=[],
            )
        )

    patch_plan = RunPatchPlan(
        goal=goal,
        subsystem=subsystem,
        primary_files=primary_files,
        dependent_files=dependent_files,
        related_tests=related_tests,
        steps=planned_steps,
        risk_level=risk_level,
        scope_depth=max_detected_depth,
        total_scope_files=total_scope_files,
    )
    verification = RunPatchVerificationSummary(
        status="NO_SCOPE" if not primary_files else "REQUIRES_CONFIRMATION" if requires_confirmation else "READY",
        requires_confirmation=requires_confirmation,
        risk_level=risk_level,
        confidence_score=confidence_score,
        subsystem=subsystem,
        file_count=len(primary_files),
        scope_depth=max_detected_depth,
        max_files=DEFAULT_MAX_FILES,
        max_dependency_depth=DEFAULT_MAX_DEPTH,
        nearest_tests=related_tests[:6],
        verified_files=primary_files[:DEFAULT_MAX_FILES],
        findings=findings,
        suggested_next_action=(
            "Require operator confirmation before patch execution."
            if requires_confirmation
            else "Proceed with the bounded patch and validation sequence."
        ),
    )
    return patch_plan, verification
