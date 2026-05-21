from pathlib import Path
import uuid

from app.services.preview_runtime import (
    PreviewProjectType,
    PreviewStrategy,
    resolve_preview_runtime_contract,
)
from app.services.runtime_template_instantiation import instantiate_runtime_template


def test_classify_static_html(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.html").write_text("<!doctype html><html><body>Hello</body></html>", encoding="utf-8")

    contract = resolve_preview_runtime_contract(repo_root=repo, configured_frontend_root=repo)
    assert contract.project_type == PreviewProjectType.STATIC_HTML
    assert contract.strategy == PreviewStrategy.STATIC_SERVER


def test_classify_vite_app(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.html").write_text(
        "<!doctype html><html><body><script type='module' src='/src/main.ts'></script></body></html>",
        encoding="utf-8",
    )
    (repo / "package.json").write_text(
        '{"name":"app","scripts":{"dev":"vite"},"devDependencies":{"vite":"^5.0.0"}}',
        encoding="utf-8",
    )

    contract = resolve_preview_runtime_contract(repo_root=repo, configured_frontend_root=repo)
    assert contract.project_type == PreviewProjectType.VITE_APP
    assert contract.strategy == PreviewStrategy.VITE_DEV


def test_classify_monorepo_vite(tmp_path: Path):
    repo = tmp_path / "repo"
    app_web = repo / "apps" / "web"
    app_web.mkdir(parents=True)
    (repo / "pnpm-workspace.yaml").write_text("packages:\n  - apps/*\n", encoding="utf-8")
    (app_web / "index.html").write_text(
        "<!doctype html><html><body><script type='module' src='/src/main.ts'></script></body></html>",
        encoding="utf-8",
    )
    (app_web / "package.json").write_text('{"scripts":{"dev":"vite"}}', encoding="utf-8")

    contract = resolve_preview_runtime_contract(repo_root=repo, configured_frontend_root=repo)
    assert contract.project_type == PreviewProjectType.MONOREPO
    assert contract.strategy == PreviewStrategy.VITE_DEV
    assert contract.frontend_root == app_web


def test_classify_monorepo_vite_fastapi(tmp_path: Path):
    repo = tmp_path / "repo"
    app_web = repo / "apps" / "web"
    app_api = repo / "apps" / "api"
    app_web.mkdir(parents=True)
    (app_api / "app").mkdir(parents=True)
    (repo / "pnpm-workspace.yaml").write_text("packages:\n  - apps/*\n", encoding="utf-8")
    (app_web / "index.html").write_text(
        "<!doctype html><html><body><script type='module' src='/src/main.ts'></script></body></html>",
        encoding="utf-8",
    )
    (app_web / "package.json").write_text('{"scripts":{"dev":"vite"},"devDependencies":{"vite":"^5.0.0"}}', encoding="utf-8")
    (app_api / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (app_api / "main.py").write_text("from app.main import app\n", encoding="utf-8")
    (app_api / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")

    contract = resolve_preview_runtime_contract(repo_root=repo, configured_frontend_root=repo)
    assert contract.project_type == PreviewProjectType.MONOREPO_VITE_FASTAPI
    assert contract.strategy == PreviewStrategy.VITE_DEV
    assert contract.frontend_root == app_web


def test_classify_monorepo_vite_fastapi_prefers_apps_web_root(tmp_path: Path):
    repo = tmp_path / "repo"
    app_web = repo / "apps" / "web"
    stray_root = repo / "web"
    app_api = repo / "apps" / "api"
    app_web.mkdir(parents=True)
    stray_root.mkdir(parents=True)
    (app_api / "app").mkdir(parents=True)
    (app_web / "index.html").write_text(
        "<!doctype html><html><body><script type='module' src='/src/main.ts'></script></body></html>",
        encoding="utf-8",
    )
    (app_web / "package.json").write_text('{"scripts":{"dev":"vite"},"devDependencies":{"vite":"^5.0.0"}}', encoding="utf-8")
    (stray_root / "index.html").write_text(
        "<!doctype html><html><body><script type='module' src='/src/main.ts'></script></body></html>",
        encoding="utf-8",
    )
    (stray_root / "package.json").write_text('{"scripts":{"dev":"vite"},"devDependencies":{"vite":"^5.0.0"}}', encoding="utf-8")
    (app_api / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (app_api / "main.py").write_text("from app.main import app\n", encoding="utf-8")
    (app_api / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")

    contract = resolve_preview_runtime_contract(repo_root=repo, configured_frontend_root=repo)
    assert contract.project_type == PreviewProjectType.MONOREPO_VITE_FASTAPI
    assert contract.frontend_root == app_web


def test_classify_backend_only(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='api'\n", encoding="utf-8")

    contract = resolve_preview_runtime_contract(repo_root=repo, configured_frontend_root=repo)
    assert contract.project_type == PreviewProjectType.BACKEND_ONLY
    assert contract.strategy == PreviewStrategy.DISABLED


def test_vite_marker_without_package_or_src_falls_back_to_static(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.html").write_text(
        "<!doctype html><html><body><script type='module' src='/src/main.ts'></script></body></html>",
        encoding="utf-8",
    )

    contract = resolve_preview_runtime_contract(repo_root=repo, configured_frontend_root=repo)
    assert contract.project_type == PreviewProjectType.STATIC_HTML
    assert contract.strategy == PreviewStrategy.STATIC_SERVER


def test_real_fullstack_template_is_preview_classifiable(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_BASE_DIR", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    instantiation = instantiate_runtime_template(project_id=uuid.uuid4(), tenant_id=uuid.uuid4())
    contract = resolve_preview_runtime_contract(
        repo_root=instantiation.repo_root,
        configured_frontend_root=instantiation.repo_root,
    )
    assert contract.project_type == PreviewProjectType.MONOREPO_VITE_FASTAPI
    assert contract.strategy == PreviewStrategy.VITE_DEV
    assert (instantiation.repo_root / "apps" / "web" / "package.json").exists()
    assert (instantiation.repo_root / "apps" / "api" / "main.py").exists()
