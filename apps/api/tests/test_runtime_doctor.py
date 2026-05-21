from __future__ import annotations

import uuid
from pathlib import Path

from app.services.runtime_doctor import run_runtime_doctor
from app.services.runtime_template_instantiation import instantiate_runtime_template


def test_runtime_doctor_passes_on_frontend_foundation_template(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()

    instantiation = instantiate_runtime_template(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        template_key="frontend-foundation",
        template_version=1,
    )

    result = run_runtime_doctor(repo_root=instantiation.repo_root)

    assert result.ok is True
    statuses = {check["key"]: check["status"] for check in result.checks}
    assert statuses["foundation_version"] == "PASS"
    assert statuses["component_manifest"] == "PASS"
    assert statuses["topology_hash"] == "PASS"
    assert statuses["shell_integrity"] == "PASS"
    assert statuses["import_graph"] == "PASS"
    assert statuses["preview_bootable"] == "PASS"
    assert statuses["primitive_existence"] == "PASS"
