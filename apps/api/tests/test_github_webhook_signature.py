import hmac
import hashlib
import os
from fastapi.testclient import TestClient
from unittest import mock

from app.main import create_app
from app import services
from app.api.v1 import routes


class DummyAdapter:
    def verify_signature(self, body: bytes, signature_header: str | None) -> bool:
        import os, hmac, hashlib

        mac = hmac.new(os.getenv("GITHUB_WEBHOOK_SECRET").encode(), msg=body, digestmod=hashlib.sha256)
        expected = f"sha256={mac.hexdigest()}"
        return signature_header == expected

    def get_pr_files(self, *args, **kwargs):
        return {"added": [], "modified": [], "removed": [], "all_files": []}

    def post_pr_comment(self, *args, **kwargs):
        return "ok"

    def assert_org_allowed(self, org_login: str) -> None:
        return None


def _with_env(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "dummy")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "supersecret")
    monkeypatch.setenv("GITHUB_ALLOWED_ORG", "example")


def test_webhook_signature_success(monkeypatch):
    _with_env(monkeypatch)
    dummy = DummyAdapter()
    monkeypatch.setattr(services, "github_adapter", dummy)
    monkeypatch.setattr(routes, "github_adapter", dummy)
    monkeypatch.setattr(routes, "documentation_guard", services.documentation_guard)
    monkeypatch.setattr(routes, "github_store", services.github_store)

    client = TestClient(create_app())
    body = b'{"action":"opened","repository":{"full_name":"example/repo","owner":{"login":"example"}},"pull_request":{"number":1},"installation":{"id":99}}'
    mac = hmac.new(os.getenv("GITHUB_WEBHOOK_SECRET").encode(), msg=body, digestmod=hashlib.sha256)
    signature = f"sha256={mac.hexdigest()}"
    res = client.post(
        "/api/v1/webhooks/github",
        data=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": signature,
        },
    )
    assert res.status_code == 200
    assert res.json()["guard_status"] in {"OK", "WARNING"}


def test_webhook_signature_invalid(monkeypatch):
    _with_env(monkeypatch)
    dummy = DummyAdapter()
    monkeypatch.setattr(services, "github_adapter", dummy)
    monkeypatch.setattr(routes, "github_adapter", dummy)
    monkeypatch.setattr(routes, "documentation_guard", services.documentation_guard)
    monkeypatch.setattr(routes, "github_store", services.github_store)
    client = TestClient(create_app())
    body = b'{}'
    res = client.post(
        "/api/v1/webhooks/github",
        data=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=deadbeef",
        },
    )
    assert res.status_code == 401
