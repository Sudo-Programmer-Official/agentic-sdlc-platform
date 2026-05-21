from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings


DEFAULT_TEMPLATE_KEY = "fullstack-monorepo"
DEFAULT_TEMPLATE_VERSION = 1


@dataclass(frozen=True)
class RuntimeTemplateInstantiation:
    template_key: str
    template_version: int
    source_dir: Path
    project_root: Path
    repo_root: Path
    manifest_path: Path


def _repo_root() -> Path:
    # .../apps/api/app/services -> repo root
    return Path(__file__).resolve().parents[4]


def _templates_root() -> Path:
    settings = get_settings()
    configured = str(getattr(settings, "runtime_templates_root", "") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (_repo_root() / "runtime-templates").resolve()


def _template_source_dir(template_key: str) -> Path:
    source = _templates_root() / template_key
    if not source.exists() or not source.is_dir():
        raise ValueError(f"Runtime template not found: {template_key}")
    return source


def _project_template_root(*, project_id: uuid.UUID, tenant_id: uuid.UUID) -> Path:
    settings = get_settings()
    base = Path(settings.workspace_base_dir).expanduser().resolve()
    return base / "project-templates" / str(tenant_id) / str(project_id)


def _git_init(repo_root: Path) -> None:
    if (repo_root / ".git").exists():
        return
    subprocess.run(["git", "init"], cwd=str(repo_root), check=False, capture_output=True, text=True, timeout=15)


def instantiate_runtime_template(
    *,
    project_id: uuid.UUID,
    tenant_id: uuid.UUID,
    template_key: str = DEFAULT_TEMPLATE_KEY,
    template_version: int = DEFAULT_TEMPLATE_VERSION,
) -> RuntimeTemplateInstantiation:
    source_dir = _template_source_dir(template_key)
    project_root = _project_template_root(project_id=project_id, tenant_id=tenant_id)
    repo_root = project_root / "repo"
    manifest_path = project_root / "runtime_template_manifest.json"

    if repo_root.exists():
        shutil.rmtree(repo_root)
    repo_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, repo_root)
    _git_init(repo_root)

    manifest = {
        "template_key": template_key,
        "template_version": template_version,
        "source_dir": str(source_dir),
        "repo_root": str(repo_root),
        "project_id": str(project_id),
        "tenant_id": str(tenant_id),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return RuntimeTemplateInstantiation(
        template_key=template_key,
        template_version=template_version,
        source_dir=source_dir,
        project_root=project_root,
        repo_root=repo_root,
        manifest_path=manifest_path,
    )
