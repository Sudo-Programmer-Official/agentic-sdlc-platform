from __future__ import annotations

from typing import Protocol, Dict, List


class VCSAdapter(Protocol):
    """Interface for VCS integrations."""

    def get_pr_files(self, repo: str, pr_number: int, installation_id: int | None = None) -> Dict[str, List[str]]:
        ...

    def post_pr_comment(self, repo: str, pr_number: int, body: str, installation_id: int | None = None) -> str | None:
        ...
