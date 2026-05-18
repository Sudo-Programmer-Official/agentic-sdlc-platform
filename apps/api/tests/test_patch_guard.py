from app.runtime.patch_guard import evaluate_patch_guard
from app.runtime.schemas.executor_io import Action


def test_patch_guard_blocks_protected_architecture_zones():
    decision = evaluate_patch_guard(
        actions=[
            Action(
                type="write_file",
                path="apps/api/app/db/models/user.py",
                content="class User: ...",
            )
        ],
        allowed_files=["apps/api/app/db/models/user.py"],
        protected_paths=["apps/api/app/db/models"],
        safe_paths=["apps/web/src"],
    )

    assert decision.ok is False
    assert decision.protected_zones == ["apps/api/app/db/models"]
    assert any("protected architecture zones" in violation for violation in decision.violations)


def test_patch_guard_tracks_safe_zone_matches_without_failing():
    decision = evaluate_patch_guard(
        actions=[
            Action(
                type="write_file",
                path="apps/web/src/views/Home.vue",
                content="<template />",
            )
        ],
        allowed_files=["apps/web/src/views/Home.vue"],
        protected_paths=["apps/api/app/db/models"],
        safe_paths=["apps/web/src"],
    )

    assert decision.ok is True
    assert decision.safe_zones == ["apps/web/src"]
    assert decision.protected_zones == []


def test_patch_guard_enforces_project_contract_frontend_rules():
    decision = evaluate_patch_guard(
        actions=[
            Action(
                type="write_file",
                path="apps/web/src/views/Home.vue",
                content='<template><div style="color:#ff00aa">Hello</div></template>\n',
            )
        ],
        allowed_files=["apps/web/src/views/Home.vue"],
        project_contract={
            "summary": {
                "enforcement_enabled": True,
                "enforcement_mode": "strict",
                "active_rules": ["disallow_inline_styles", "enforce_color_tokens"],
            },
            "enforcement": {
                "enabled": True,
                "mode": "strict",
                "disallow_inline_styles": True,
                "enforce_color_tokens": True,
                "allowed_hex_values": ["#2563eb"],
                "active_rules": ["disallow_inline_styles", "enforce_color_tokens"],
            },
        },
    )

    assert decision.ok is False
    assert "disallow_inline_styles" in decision.project_rules_applied
    assert any("disallows inline style attributes" in violation for violation in decision.violations)
    assert any("requires brand color tokens" in violation for violation in decision.violations)


def test_patch_guard_warn_mode_logs_project_contract_violations_without_blocking():
    decision = evaluate_patch_guard(
        actions=[
            Action(
                type="write_file",
                path="apps/web/src/views/Home.vue",
                content='<template><div style="color:#ff00aa">Hello</div></template>\n',
            )
        ],
        allowed_files=["apps/web/src/views/Home.vue"],
        project_contract={
            "summary": {
                "enforcement_enabled": True,
                "enforcement_mode": "warn",
                "active_rules": ["disallow_inline_styles", "enforce_color_tokens"],
            },
            "enforcement": {
                "enabled": True,
                "mode": "warn",
                "disallow_inline_styles": True,
                "enforce_color_tokens": True,
                "allowed_hex_values": ["#2563eb"],
                "active_rules": ["disallow_inline_styles", "enforce_color_tokens"],
            },
        },
    )

    assert decision.ok is True
    assert decision.project_enforcement_mode == "warn"
    assert decision.violations == []
    assert any("disallows inline style attributes" in warning for warning in decision.project_warnings)
    assert any("requires brand color tokens" in warning for warning in decision.project_warnings)


def test_patch_guard_blocks_hardcoded_provider_and_secret_patterns():
    decision = evaluate_patch_guard(
        actions=[
            Action(
                type="write_file",
                path="apps/web/src/components/FormAction.vue",
                content='const url = "https://myproj.supabase.co/rest/v1/leads";\\nconst api_key = "sk_test_123456789";\\n',
            )
        ],
        allowed_files=["apps/web/src/components/FormAction.vue"],
    )

    assert decision.ok is False
    assert any("Capability governance violation" in violation for violation in decision.violations)


def test_patch_guard_enforces_backend_topology_for_code_backend():
    decision = evaluate_patch_guard(
        actions=[
            Action(
                type="write_file",
                path="apps/api/app/routes/lead_capture.py",
                content="from sqlalchemy import select\nresult = session.execute(select(Lead))\n",
            )
        ],
        work_item_type="CODE_BACKEND",
        work_item_payload={
            "backend_topology_plan": {
                "planned_files": [
                    "apps/api/app/routes/lead_capture.py",
                    "apps/api/app/services/lead_capture_service.py",
                    "apps/api/app/repositories/lead_capture_repository.py",
                ],
                "routes": ["apps/api/app/routes/lead_capture.py"],
                "services": ["apps/api/app/services/lead_capture_service.py"],
                "repositories": ["apps/api/app/repositories/lead_capture_repository.py"],
                "allowed_capabilities": ["lead_capture_storage"],
            }
        },
    )

    assert decision.ok is False
    assert any("Routes must not include DB logic" in violation for violation in decision.violations)


def test_patch_guard_blocks_route_level_capability_resolution():
    decision = evaluate_patch_guard(
        actions=[
            Action(
                type="write_file",
                path="apps/api/app/routes/lead_capture.py",
                content='adapter = resolve_capability("lead_capture_storage")\n',
            )
        ],
        work_item_type="CODE_BACKEND",
        work_item_payload={
            "backend_topology_plan": {
                "planned_files": ["apps/api/app/routes/lead_capture.py", "apps/api/app/services/lead_capture_service.py"],
                "routes": ["apps/api/app/routes/lead_capture.py"],
                "services": ["apps/api/app/services/lead_capture_service.py"],
                "allowed_capabilities": ["lead_capture_storage"],
            }
        },
    )

    assert decision.ok is False
    assert any("route resolved capability directly" in violation for violation in decision.violations)
