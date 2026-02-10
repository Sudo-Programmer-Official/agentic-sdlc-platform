from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Protocol, Set

from core.models import Stage


class StateStore(Protocol):
    def get_stage(self, project_id: str) -> Stage:
        ...

    def set_stage(self, project_id: str, stage: Stage) -> None:
        ...


class InMemoryStateStore:
    def __init__(self, initial: Optional[Dict[str, Stage]] = None) -> None:
        self._state: Dict[str, Stage] = dict(initial or {})

    def get_stage(self, project_id: str) -> Stage:
        return self._state.get(project_id, Stage.INTAKE)

    def set_stage(self, project_id: str, stage: Stage) -> None:
        self._state[project_id] = stage


@dataclass(frozen=True)
class TransitionResult:
    from_stage: Stage
    to_stage: Stage


class SDLCStateMachine:
    def __init__(
        self,
        store: StateStore,
        allowed_transitions: Optional[Dict[Stage, Iterable[Stage]]] = None,
        approval_checker: Optional[callable] = None,
    ) -> None:
        self._store = store
        self._allowed_transitions = self._normalize_transitions(
            allowed_transitions or default_transitions()
        )
        self._approval_checker = approval_checker

    def get_stage(self, project_id: str) -> Stage:
        return self._store.get_stage(project_id)

    def can_transition(self, project_id: str, to_stage: Stage) -> bool:
        current = self.get_stage(project_id)
        return to_stage in self._allowed_transitions.get(current, set())

    def transition(self, project_id: str, to_stage: Stage) -> TransitionResult:
        current = self.get_stage(project_id)
        self._validate_transition(current, to_stage)
        if self._approval_checker is not None:
            self._approval_checker(project_id, to_stage)
        self._store.set_stage(project_id, to_stage)
        return TransitionResult(from_stage=current, to_stage=to_stage)

    def _validate_transition(self, current: Stage, to_stage: Stage) -> None:
        allowed = self._allowed_transitions.get(current, set())
        if to_stage not in allowed:
            raise ValueError(
                f"Invalid transition: {current} -> {to_stage}. Allowed: {sorted(stage.value for stage in allowed)}"
            )

    @staticmethod
    def _normalize_transitions(
        transitions: Dict[Stage, Iterable[Stage]]
    ) -> Dict[Stage, Set[Stage]]:
        return {stage: set(options) for stage, options in transitions.items()}


def default_transitions() -> Dict[Stage, Iterable[Stage]]:
    return {
        Stage.INTAKE: [Stage.REQUIREMENTS_DRAFTED],
        Stage.REQUIREMENTS_DRAFTED: [Stage.REQUIREMENTS_APPROVED],
        Stage.REQUIREMENTS_APPROVED: [Stage.DESIGN_DRAFTED],
        Stage.DESIGN_DRAFTED: [Stage.DESIGN_APPROVED],
        Stage.DESIGN_APPROVED: [Stage.PLAN_READY],
        Stage.PLAN_READY: [Stage.IMPLEMENTING],
        Stage.IMPLEMENTING: [Stage.TESTING],
        Stage.TESTING: [Stage.READY_FOR_REVIEW],
        Stage.READY_FOR_REVIEW: [Stage.MERGED],
        Stage.MERGED: [Stage.DEPLOYED],
        Stage.DEPLOYED: [],
    }
