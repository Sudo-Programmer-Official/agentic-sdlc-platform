from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from core.ledger import ActionLedger
from core.models import ArtifactSnapshot, Stage

from .errors import StaleArtifactsError


REQUIREMENTS_ARTIFACTS: List[str] = [
    "PRD.md",
    "USER_STORIES.md",
    "ACCEPTANCE.md",
]

REQUIREMENTS_STALE_STAGES: Set[Stage] = {
    Stage.REQUIREMENTS_APPROVED,
    Stage.DESIGN_DRAFTED,
    Stage.DESIGN_APPROVED,
    Stage.PLAN_READY,
    Stage.IMPLEMENTING,
    Stage.TESTING,
    Stage.READY_FOR_REVIEW,
    Stage.MERGED,
    Stage.DEPLOYED,
}


@dataclass
class SnapshotBundle:
    project_id: str
    stage: Stage
    approved_at: datetime
    snapshots: List[ArtifactSnapshot]


class InMemoryArtifactSnapshotStore:
    def __init__(self) -> None:
        self._snapshots: Dict[str, Dict[str, ArtifactSnapshot]] = {}

    def set_snapshots(self, project_id: str, snapshots: Iterable[ArtifactSnapshot]) -> None:
        self._snapshots[project_id] = {snap.artifact: snap for snap in snapshots}

    def get_snapshots(self, project_id: str) -> List[ArtifactSnapshot]:
        return list(self._snapshots.get(project_id, {}).values())

    def get_snapshot_map(self, project_id: str) -> Dict[str, ArtifactSnapshot]:
        return dict(self._snapshots.get(project_id, {}))


class InMemoryStaleStageStore:
    def __init__(self) -> None:
        self._auto: Dict[str, Set[Stage]] = {}
        self._manual: Dict[str, Set[Stage]] = {}

    def set_auto(self, project_id: str, stages: Set[Stage]) -> None:
        self._auto[project_id] = set(stages)

    def add_manual(self, project_id: str, stages: Set[Stage]) -> None:
        current = self._manual.get(project_id, set())
        self._manual[project_id] = set(current) | set(stages)

    def clear(self, project_id: str) -> None:
        self._auto[project_id] = set()
        self._manual[project_id] = set()

    def clear_auto(self, project_id: str) -> None:
        self._auto[project_id] = set()

    def clear_manual(self, project_id: str) -> None:
        self._manual[project_id] = set()

    def get(self, project_id: str) -> Set[Stage]:
        return set(self._auto.get(project_id, set())) | set(self._manual.get(project_id, set()))


class ArtifactSnapshotService:
    def __init__(
        self,
        store: InMemoryArtifactSnapshotStore,
        stale_store: InMemoryStaleStageStore,
        ledger: ActionLedger,
        docs_root: Optional[Path] = None,
    ) -> None:
        self._store = store
        self._stale_store = stale_store
        self._ledger = ledger
        self._docs_root = docs_root or self._resolve_docs_root()

    def capture_snapshot(self, project_id: str, stage: Stage, approved_at: datetime) -> SnapshotBundle:
        if stage != Stage.REQUIREMENTS_DRAFTED:
            return SnapshotBundle(project_id=project_id, stage=stage, approved_at=approved_at, snapshots=[])

        snapshots: List[ArtifactSnapshot] = []
        missing: List[str] = []
        for artifact in REQUIREMENTS_ARTIFACTS:
            path = self._docs_root / artifact
            if not path.exists():
                missing.append(artifact)
                artifact_hash = "missing"
            else:
                artifact_hash = self._hash_file(path)
            snapshots.append(
                ArtifactSnapshot(
                    project_id=project_id,
                    artifact=artifact,
                    hash=artifact_hash,
                    approved_stage=stage,
                    approved_at=approved_at,
                )
            )

        self._store.set_snapshots(project_id, snapshots)
        self._stale_store.clear_auto(project_id)

        self._ledger.log(
            run_id="system",
            project_id=project_id,
            stage=stage,
            agent_name="system",
            tool_name="artifact_snapshot",
            message="Captured requirements artifact snapshots",
            details={
                "artifacts": [snap.artifact for snap in snapshots],
                "missing": missing,
            },
        )
        return SnapshotBundle(
            project_id=project_id, stage=stage, approved_at=approved_at, snapshots=snapshots
        )

    def refresh_staleness(self, project_id: str) -> Set[Stage]:
        snapshots = self._store.get_snapshot_map(project_id)
        if not snapshots:
            self._stale_store.clear_auto(project_id)
            return set()

        mismatched: List[Dict[str, str]] = []
        for artifact, snapshot in snapshots.items():
            path = self._docs_root / artifact
            current_hash = "missing" if not path.exists() else self._hash_file(path)
            if current_hash != snapshot.hash:
                mismatched.append(
                    {
                        "artifact": artifact,
                        "expected": snapshot.hash,
                        "actual": current_hash,
                    }
                )

        if mismatched:
            self._stale_store.set_auto(project_id, set(REQUIREMENTS_STALE_STAGES))
            self._ledger.log(
                run_id="system",
                project_id=project_id,
                stage=Stage.REQUIREMENTS_DRAFTED,
                agent_name="system",
                tool_name="artifact_snapshot",
                message="Requirements changed since last approval",
                details={"mismatched": mismatched},
            )
        else:
            self._stale_store.clear_auto(project_id)
        return self._stale_store.get(project_id)

    def assert_not_stale(self, project_id: str, stage: Stage) -> None:
        stale_stages = self.refresh_staleness(project_id)
        if stage in stale_stages:
            raise StaleArtifactsError("Requirements changed since last approval")

    def get_stale_stages(self, project_id: str) -> Set[Stage]:
        return self.refresh_staleness(project_id)

    def mark_stale(self, project_id: str, stages: Set[Stage], reason: str) -> None:
        if not stages:
            return
        self._stale_store.add_manual(project_id, set(stages))
        self._ledger.log(
            run_id="system",
            project_id=project_id,
            stage=Stage.REQUIREMENTS_DRAFTED,
            agent_name="system",
            tool_name="artifact_snapshot",
            message="Stages marked stale due to change request",
            details={"reason": reason, "stages": [stage.value for stage in stages]},
        )

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = sha256(path.read_bytes()).hexdigest()
        return f"sha256:{digest}"

    @staticmethod
    def _resolve_docs_root() -> Path:
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "docs").exists() and (parent / "apps").exists():
                return parent / "docs"
        return Path.cwd() / "docs"
