from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class GitHubIntegration:
    installation_id: int
    org_login: str
    allowed_repos: List[str] = field(default_factory=list)
    connected_at: datetime = field(default_factory=datetime.utcnow)


class InMemoryGitHubIntegrationStore:
    def __init__(self) -> None:
        self._integration: Optional[GitHubIntegration] = None

    def save(self, integration: GitHubIntegration) -> None:
        self._integration = integration

    def get(self) -> Optional[GitHubIntegration]:
        return self._integration

    def is_repo_allowed(self, repo_full_name: str) -> bool:
        if not self._integration:
            return False
        if not self._integration.allowed_repos:
            return True
        return repo_full_name in self._integration.allowed_repos
