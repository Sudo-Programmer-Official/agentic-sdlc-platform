from __future__ import annotations

from typing import Dict, Optional, Set, Tuple
from uuid import uuid4

from core.models import Project, Stage
from core.sdlc import ApprovalGate, SDLCStateMachine, InMemoryStateStore, TransitionResult

from .artifact_service import ArtifactSnapshotService
from .errors import (
    ApprovalRequiredError,
    InvalidStageError,
    InvalidTransitionError,
    ProjectNotFoundError,
)
from .errors import RequirementGraphNotApprovedError, RequirementGraphStaleError
from .requirements_service import RequirementGraphService


class InMemoryProjectStore:
    def __init__(self) -> None:
        self._projects: Dict[str, Project] = {}

    def add(self, project: Project) -> None:
        self._projects[project.id] = project

    def get(self, project_id: str) -> Project:
        if project_id not in self._projects:
            raise ProjectNotFoundError(f"Project {project_id} not found")
        return self._projects[project_id]

    def update(self, project: Project) -> None:
        self._projects[project.id] = project


class ProjectService:
    def __init__(
        self,
        project_store: InMemoryProjectStore,
        state_store: InMemoryStateStore,
        approval_gate: ApprovalGate,
        artifact_service: ArtifactSnapshotService,
        requirements_service: RequirementGraphService | None = None,
        plan_checker=None,
        approval_required: Optional[Set[Tuple[Stage, Stage]]] = None,
    ) -> None:
        self._project_store = project_store
        self._state_store = state_store
        self._approval_gate = approval_gate
        self._artifact_service = artifact_service
        self._requirements_service = requirements_service
        self._plan_checker = plan_checker
        self._state_machine = SDLCStateMachine(state_store)
        self._approval_required = approval_required or {
            (Stage.REQUIREMENTS_DRAFTED, Stage.REQUIREMENTS_APPROVED),
            (Stage.DESIGN_DRAFTED, Stage.DESIGN_APPROVED),
        }

    def create_project(self, name: str, description: Optional[str] = None) -> Project:
        project = Project(id=str(uuid4()), name=name, description=description)
        self._project_store.add(project)
        self._state_store.set_stage(project.id, project.current_stage)
        return project

    def get_project(self, project_id: str) -> Project:
        project = self._project_store.get(project_id)
        project.current_stage = self._state_store.get_stage(project_id)
        return project

    def advance_stage(self, project_id: str, to_stage: str) -> tuple[Project, TransitionResult]:
        project = self.get_project(project_id)
        next_stage = self._parse_stage(to_stage)
        current_stage = self._state_machine.get_stage(project_id)

        if self._requirements_service:
            if next_stage == Stage.REQUIREMENTS_APPROVED:
                self._requirements_service.assert_approved(project_id)
            if next_stage in {
                Stage.DESIGN_DRAFTED,
                Stage.DESIGN_APPROVED,
                Stage.IMPLEMENTING,
                Stage.TESTING,
                Stage.READY_FOR_REVIEW,
                Stage.MERGED,
                Stage.DEPLOYED,
            }:
                self._requirements_service.assert_fresh(project_id)
            if next_stage == Stage.PLAN_READY:
                graph = self._requirements_service.get_graph(project_id)
                if self._plan_checker and not self._plan_checker(project_id, graph.compute_hash()):
                    raise StaleArtifactsError("Plan is missing or stale relative to requirements graph.")

        self._artifact_service.assert_not_stale(project_id, next_stage)

        if not self._state_machine.can_transition(project_id, next_stage):
            raise InvalidTransitionError(f"Invalid transition {current_stage} -> {next_stage}")

        if (current_stage, next_stage) in self._approval_required:
            try:
                self._approval_gate.assert_stage_approved(project_id, current_stage)
            except ValueError as exc:
                raise ApprovalRequiredError(str(exc)) from exc

        result = self._state_machine.transition(project_id, next_stage)
        project.current_stage = result.to_stage
        self._project_store.update(project)
        return project, result

    def set_stage(self, project_id: str, stage: Stage) -> Project:
        project = self.get_project(project_id)
        self._state_store.set_stage(project_id, stage)
        project.current_stage = stage
        self._project_store.update(project)
        return project

    def set_refresh_flags(
        self,
        project_id: str,
        *,
        architecture: Optional[bool] = None,
        plan: Optional[bool] = None,
        tests: Optional[bool] = None,
    ) -> Project:
        project = self._project_store.get(project_id)
        if architecture is not None:
            project.architecture_refresh_needed = architecture
        if plan is not None:
            project.plan_refresh_needed = plan
        if tests is not None:
            project.test_refresh_needed = tests
        self._project_store.update(project)
        return project

    @staticmethod
    def _parse_stage(raw: str) -> Stage:
        cleaned = raw.strip()
        try:
            return Stage(cleaned)
        except ValueError:
            try:
                return Stage[cleaned.upper()]
            except KeyError as exc:
                raise InvalidStageError(f"Unknown stage '{raw}'") from exc
