from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.request
import base64
from typing import Dict, List, Optional

import jwt

from app.services.vcs.base import VCSAdapter
from app.services.vcs.github_store import InMemoryGitHubIntegrationStore


class GitHubAppAdapter(VCSAdapter):
    """GitHub App adapter (single installation, single tenant)."""

    def __init__(
        self,
        app_id: str,
        private_key_pem: str,
        webhook_secret: str | None,
        allowed_org: Optional[str],
        store: InMemoryGitHubIntegrationStore,
    ) -> None:
        self._app_id = app_id
        self._private_key_pem = private_key_pem
        self._webhook_secret = webhook_secret or ""
        self._allowed_org = allowed_org
        self._store = store

    # --- JWT / tokens -----------------------------------------------------------------
    def generate_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 600, "iss": self._app_id}
        token = jwt.encode(payload, self._private_key_pem, algorithm="RS256")
        return token if isinstance(token, str) else token.decode("utf-8")

    def get_installation_token(self, installation_id: int) -> str:
        jwt_token = self.generate_jwt()
        url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        req = urllib.request.Request(
            url,
            method="POST",
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "agentic-sdlc",
            },
            data=b"",  # empty body
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data["token"]

    # --- Core ops ---------------------------------------------------------------------
    def get_pr_files(
        self, repo: str, pr_number: int, installation_id: int | None = None
    ) -> Dict[str, List[str]]:
        token = self._token_for_installation(installation_id)
        url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "agentic-sdlc",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            files = json.loads(resp.read().decode())
            return self._categorize_files(files)

    def post_pr_comment(
        self, repo: str, pr_number: int, body: str, installation_id: int | None = None
    ) -> Optional[str]:
        token = self._token_for_installation(installation_id)
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        payload = json.dumps({"body": body}).encode()
        req = urllib.request.Request(
            url,
            method="POST",
            data=payload,
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "agentic-sdlc",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("id") or data.get("url")

    def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
        installation_id: int | None = None,
    ) -> dict:
        token = self._token_for_installation(installation_id)
        url = f"https://api.github.com/repos/{repo}/pulls"
        payload = json.dumps(
            {
                "title": title,
                "body": body,
                "head": head,
                "base": base,
            }
        ).encode()
        req = urllib.request.Request(
            url,
            method="POST",
            data=payload,
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "agentic-sdlc",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def list_installation_repositories(self, installation_id: int) -> List[dict]:
        token = self.get_installation_token(installation_id)
        req = urllib.request.Request(
            "https://api.github.com/installation/repositories?per_page=100",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "agentic-sdlc",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode())
            repos = payload.get("repositories") or []
            normalized: List[dict] = []
            for repo in repos:
                owner = repo.get("owner") or {}
                normalized.append(
                    {
                        "id": repo.get("id"),
                        "name": repo.get("name"),
                        "full_name": repo.get("full_name"),
                        "clone_url": repo.get("clone_url"),
                        "ssh_url": repo.get("ssh_url"),
                        "html_url": repo.get("html_url"),
                        "default_branch": repo.get("default_branch") or "main",
                        "private": bool(repo.get("private")),
                        "owner_login": owner.get("login"),
                    }
                )
            return normalized

    @staticmethod
    def build_clone_url(repo_full_name: str) -> str:
        return f"https://github.com/{repo_full_name.removesuffix('.git')}.git"

    def build_git_http_config(self, installation_id: int, host: str = "https://github.com/") -> List[tuple[str, str]]:
        token = self.get_installation_token(installation_id)
        basic = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
        return [(f"http.{host}.extraheader", f"AUTHORIZATION: Basic {basic}")]

    # --- Helpers ----------------------------------------------------------------------
    def _token_for_installation(self, installation_id: int | None) -> str:
        integration = self._store.get()
        install_id = installation_id or (integration.installation_id if integration else None)
        if not install_id:
            raise PermissionError("GitHub installation not configured")
        return self.get_installation_token(install_id)

    @staticmethod
    def _categorize_files(files: List[dict]) -> Dict[str, List[str]]:
        added: List[str] = []
        modified: List[str] = []
        removed: List[str] = []
        for item in files:
            status = item.get("status")
            filename = item.get("filename")
            if not filename:
                continue
            if status == "added":
                added.append(filename)
            elif status == "removed":
                removed.append(filename)
            else:  # modified, renamed, changed
                modified.append(filename)
        all_files = sorted(set(added + modified + removed))
        return {"added": added, "modified": modified, "removed": removed, "all_files": all_files}

    # --- Webhook signature ------------------------------------------------------------
    def verify_signature(self, body: bytes, signature_header: str | None) -> bool:
        if not self._webhook_secret:
            return False
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        given = signature_header.split("sha256=")[-1]
        mac = hmac.new(self._webhook_secret.encode(), msg=body, digestmod=hashlib.sha256)
        expected = mac.hexdigest()
        return hmac.compare_digest(given, expected)

    def assert_org_allowed(self, org_login: str) -> None:
        if self._allowed_org and org_login.lower() != self._allowed_org.lower():
            raise PermissionError(f"Org {org_login} not allowed")


def build_github_adapter(store: InMemoryGitHubIntegrationStore) -> Optional[GitHubAppAdapter]:
    """Factory that reads env vars and returns adapter if configured."""
    app_id = os.getenv("GITHUB_APP_ID")
    private_key = os.getenv("GITHUB_PRIVATE_KEY")
    webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    allowed_org = os.getenv("GITHUB_ALLOWED_ORG")
    if not (app_id and private_key):
        return None
    return GitHubAppAdapter(
        app_id=app_id,
        private_key_pem=private_key,
        webhook_secret=webhook_secret,
        allowed_org=allowed_org,
        store=store,
    )
