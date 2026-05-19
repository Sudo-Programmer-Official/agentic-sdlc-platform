from app.services.architecture_drift_service import (
    detect_architecture_drift,
    generate_canonical_contract_patch,
)


def test_generate_canonical_contract_patch_normalizes_integrations_and_roots():
    profile_json = {
        "repo_layout": {
            "packages": [
                {"name": "apps/api", "kind": "backend"},
                {"name": "apps/web", "kind": "frontend"},
            ]
        },
        "integrations": [
            {"name": "repository", "provider": None, "repo_full_name": None, "default_branch": None},
            {"name": "repository", "provider": "github", "repo_full_name": "acme/repo", "default_branch": "main"},
            {"name": "preview", "mode": "local", "frontend_root": None, "backend_root": None},
        ],
        "environment_assumptions": {
            "repo_connected": False,
            "preview_profile_configured": False,
            "frontend_root": None,
            "backend_root": None,
        },
        "release_flow": {"branch_strategy": "run_branch_then_pr"},
    }

    patch = generate_canonical_contract_patch(profile_json)
    assert patch["integrations"][0]["name"] == "repository"
    assert patch["integrations"][0]["provider"] == "github"
    assert patch["integrations"][1]["name"] == "preview"
    assert patch["integrations"][1]["frontend_root"] == "apps/web"
    assert patch["integrations"][1]["backend_root"] == "apps/api"
    assert patch["environment_assumptions"]["repo_connected"] is True
    assert patch["environment_assumptions"]["preview_profile_configured"] is True
    assert patch["release_flow"]["default_branch"] == "main"
    assert patch["release_flow"]["preview_mode"] == "local"


def test_detect_architecture_drift_reports_violations_and_fixes():
    profile_json = {
        "repo_layout": {"packages": [{"name": "apps/web", "kind": "frontend"}]},
        "integrations": [
            {"name": "repository", "provider": None},
            {"name": "repository", "provider": "github", "repo_full_name": "acme/repo", "default_branch": "main"},
        ],
        "environment_assumptions": {"repo_connected": False, "preview_profile_configured": False},
        "release_flow": {},
    }

    drift = detect_architecture_drift(profile_json)
    assert drift["severity"] == "MEDIUM"
    assert any(v["code"] == "duplicate_repository_integrations" for v in drift["violations"])
    assert any(f["field"] == "integrations" for f in drift["fixes"])
