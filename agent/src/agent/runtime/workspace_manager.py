from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class WorkspaceInfo:
    project_id: str
    root: Path
    created: bool


class WorkspaceManager:
    def __init__(self, workspace_root: str | Path = "./workspaces") -> None:
        self._root = Path(workspace_root)

    def create_project_workspace(self, project_id: str) -> WorkspaceInfo:
        project_root = self._root / project_id
        created = False
        if not project_root.exists():
            project_root.mkdir(parents=True, exist_ok=True)
            created = True
        return WorkspaceInfo(project_id=project_id, root=project_root, created=created)

    def prepare_agent_branch(self, project_id: str, branch_name: str) -> str:
        """
        Placeholder for git branch creation.
        Returns the branch name for logging until git integration is added.
        """
        return f"{project_id}:{branch_name}"

    def generate_diff(self, project_id: str, branch_name: str) -> str:
        """
        Placeholder diff generation.
        Returns a stub string until git integration is added.
        """
        return f"diff for {project_id} on {branch_name} (stubbed)"

    def list_workspaces(self) -> List[Path]:
        if not self._root.exists():
            return []
        return [path for path in self._root.iterdir() if path.is_dir()]

    def workspace_path(self, project_id: str) -> Optional[Path]:
        path = self._root / project_id
        return path if path.exists() else None
