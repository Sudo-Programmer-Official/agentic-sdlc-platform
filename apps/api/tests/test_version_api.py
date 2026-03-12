import json

from fastapi.testclient import TestClient

from app.main import create_app


def test_version_endpoints_expose_current_build_and_history(monkeypatch, tmp_path):
    build_info_path = tmp_path / "build_history.json"
    build_info_path.write_text(
        json.dumps(
            {
                "current": {
                    "version": "build-101.1",
                    "sha": "abcdef1234567890",
                    "short_sha": "abcdef1",
                    "branch": "main",
                    "built_at": "2026-03-11T12:00:00Z",
                    "run_number": 101,
                    "run_attempt": 1,
                    "run_url": "https://example.com/run/101",
                    "title": "Deploy version endpoints",
                },
                "history": [
                    {
                        "version": "build-100.1",
                        "sha": "1234567890abcdef",
                        "short_sha": "1234567",
                        "branch": "main",
                        "built_at": "2026-03-10T11:00:00Z",
                        "run_number": 100,
                        "run_attempt": 1,
                        "run_url": "https://example.com/run/100",
                        "title": "Previous deploy",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("BUILD_INFO_PATH", str(build_info_path))
    monkeypatch.setenv("BUILD_VERSION", "build-101.1")
    monkeypatch.setenv("BUILD_SHA", "abcdef1234567890")
    monkeypatch.setenv("BUILD_BRANCH", "main")
    monkeypatch.setenv("BUILD_AT", "2026-03-11T12:00:00Z")
    monkeypatch.setenv("BUILD_RUN_NUMBER", "101")
    monkeypatch.setenv("BUILD_RUN_ATTEMPT", "1")
    monkeypatch.setenv("BUILD_RUN_URL", "https://example.com/run/101")
    monkeypatch.setenv("BUILD_TITLE", "Deploy version endpoints")

    client = TestClient(create_app())

    version_response = client.get("/version")
    history_response = client.get("/version/history")

    assert version_response.status_code == 200
    assert version_response.json()["version"] == "build-101.1"
    assert version_response.json()["short_sha"] == "abcdef1"

    assert history_response.status_code == 200
    payload = history_response.json()
    assert payload["current"]["version"] == "build-101.1"
    assert payload["history"][0]["version"] == "build-101.1"
    assert payload["history"][1]["version"] == "build-100.1"
