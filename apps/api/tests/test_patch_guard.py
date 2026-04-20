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
