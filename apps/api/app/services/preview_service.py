from __future__ import annotations

import json
import hashlib
import os
import re
import shlex
import signal
import socket
import string
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import ProjectPreviewProfile, ProjectRepository, Run
from app.schemas.preview import RunPreviewOut, RunPreviewServiceRef
from app.services.frontend_composition_integrity import (
    reconcile_frontend_runtime_shell,
    validate_frontend_composition_integrity,
)
from app.services.preview_convergence_reconciler import (
    extract_root_module_entry_path,
    looks_like_javascript_content_type,
)
from app.services.preview_runtime import (
    PreviewProjectType,
    PreviewStrategy,
    resolve_preview_runtime_contract,
    resolve_vite_entrypoint,
)
from app.services.workspace_commands import run_workspace_command_async


DEFAULT_PREVIEW_STATUS = "NOT_CONFIGURED"
DEFAULT_STATIC_START_COMMAND = "python3 -m http.server $PORT --bind $HOST"
DEFAULT_VITE_START_COMMAND = "npm run dev -- --host $HOST --port $PORT"
DEFAULT_VITE_NPX_START_COMMAND = "npx vite --host $HOST --port $PORT"
PREVIEW_REPAIR_FRONTEND_ROOT = "repair_frontend_root"
PREVIEW_REPAIR_FRONTEND_ENTRYPOINT = "repair_frontend_entrypoint"


@dataclass(frozen=True)
class _PreviewProcess:
    pid: int
    log_path: str
    url: str
    port: int


@dataclass(frozen=True)
class ResolvedPreviewProfile:
    enabled: bool = True
    mode: str = "local"
    frontend_root: str | None = None
    backend_root: str | None = None
    compose_file: str | None = None
    frontend_build_command: str | None = None
    backend_build_command: str | None = None
    frontend_start_command: str | None = None
    backend_start_command: str | None = None
    frontend_healthcheck_path: str | None = "/"
    backend_healthcheck_path: str | None = "/"
    frontend_port: int | None = None
    backend_port: int | None = None
    env_overrides: dict[str, str] | None = None
    ttl_hours: int = 24
    max_previews_per_project: int | None = None
    created_by: str | None = None


def build_default_preview_profile() -> ResolvedPreviewProfile:
    return ResolvedPreviewProfile(
        enabled=True,
        mode="local",
        frontend_start_command=DEFAULT_STATIC_START_COMMAND,
        backend_healthcheck_path="/health",
        frontend_healthcheck_path="/",
        ttl_hours=get_settings().preview_default_ttl_hours,
        created_by="system:default-static-web-monorepo",
    )


def resolve_preview_profile(
    profile: ProjectPreviewProfile | None,
    *,
    repository_connected: bool,
) -> ProjectPreviewProfile | ResolvedPreviewProfile | None:
    if profile is not None:
        has_start_command = bool(
            (profile.frontend_start_command and profile.frontend_start_command.strip())
            or (profile.backend_start_command and profile.backend_start_command.strip())
        )
        if has_start_command or not repository_connected:
            return profile
        # Backward-compatible fallback: if a profile exists but has no launch commands,
        # keep operator-configured fields and inject the default static frontend launcher.
        return ResolvedPreviewProfile(
            enabled=profile.enabled,
            mode=profile.mode or "local",
            frontend_root=profile.frontend_root,
            backend_root=profile.backend_root,
            compose_file=profile.compose_file,
            frontend_build_command=profile.frontend_build_command,
            backend_build_command=profile.backend_build_command,
            frontend_start_command=DEFAULT_STATIC_START_COMMAND,
            backend_start_command=profile.backend_start_command,
            frontend_healthcheck_path=profile.frontend_healthcheck_path or "/",
            backend_healthcheck_path=profile.backend_healthcheck_path or "/",
            frontend_port=profile.frontend_port,
            backend_port=profile.backend_port,
            env_overrides=profile.env_overrides or {},
            ttl_hours=profile.ttl_hours or get_settings().preview_default_ttl_hours,
            max_previews_per_project=profile.max_previews_per_project,
            created_by=profile.created_by or "system:default-static-web-monorepo",
        )
    if repository_connected:
        return build_default_preview_profile()
    return None


def preview_profile_available(
    profile: ProjectPreviewProfile | None,
    *,
    repository_connected: bool,
) -> bool:
    resolved = resolve_preview_profile(profile, repository_connected=repository_connected)
    return bool(resolved and resolved.enabled)


def _now() -> datetime:
    return datetime.now(UTC)


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _preview_summary(run: Run) -> dict[str, Any]:
    if isinstance(run.summary, dict):
        raw = run.summary.get("preview")
        if isinstance(raw, dict):
            return dict(raw)
    return {}


def _write_preview_summary(run: Run, preview: dict[str, Any]) -> None:
    summary = dict(run.summary or {})
    summary["preview"] = preview
    summary["preview_status"] = preview.get("status")
    preview_url = preview.get("preview_url")
    if isinstance(preview_url, str):
        summary["preview_url"] = preview_url
    else:
        summary.pop("preview_url", None)
    run.summary = summary


def _clear_preview_summary(run: Run) -> None:
    summary = dict(run.summary or {})
    summary.pop("preview", None)
    summary.pop("preview_status", None)
    summary.pop("preview_url", None)
    run.summary = summary


def _workspace_path(run: Run) -> Path:
    if not run.workspace_root:
        raise ValueError("Run workspace is not available.")
    path = Path(run.workspace_root).expanduser().resolve()
    if not path.exists():
        raise ValueError("Run workspace does not exist.")
    return path


def _repo_root(run: Run) -> Path:
    if not run.repo_path:
        raise ValueError("Run repo path is not available.")
    path = Path(run.repo_path).expanduser().resolve()
    if not path.exists():
        raise ValueError("Run repo path does not exist.")
    return path


def _root_path(repo_root: Path, configured: str | None) -> Path:
    if not configured:
        return repo_root
    resolved = (repo_root / configured).resolve()
    if not resolved.exists():
        raise ValueError(f"Preview root does not exist: {configured}")
    return resolved


def _uses_static_frontend_contract(profile: ProjectPreviewProfile | ResolvedPreviewProfile | None) -> bool:
    if profile is None:
        return False
    return (profile.frontend_start_command or "").strip() == DEFAULT_STATIC_START_COMMAND


def _validate_static_frontend_contract(
    frontend_root: Path,
    profile: ProjectPreviewProfile | ResolvedPreviewProfile | None,
) -> None:
    if not _uses_static_frontend_contract(profile):
        return
    entry_file = frontend_root / "index.html"
    if not entry_file.exists():
        raise ValueError("Static preview contract requires index.html at the frontend root")
    try:
        content = entry_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError("Static preview contract could not read index.html") from exc
    lower = content.lower()
    if "<body" not in lower:
        raise ValueError("Static preview contract requires index.html to contain a <body> element")
    if "<html" not in lower and "<!doctype html" not in lower:
        raise ValueError("Static preview contract requires index.html to contain an <html> element or doctype")
    has_vite_entry_marker = "/src/main.ts" in lower or ('type="module"' in lower and 'src="/src/' in lower)
    has_vite_runtime_shape = (
        (frontend_root / "package.json").exists()
        or (frontend_root / "src" / "main.ts").exists()
        or (frontend_root / "src" / "main.js").exists()
    )
    if has_vite_entry_marker and has_vite_runtime_shape:
        raise ValueError(
            "Static preview contract is incompatible with Vite module entrypoints "
            "(for example /src/main.ts). Configure a dev/build preview start command "
            "such as 'npm run dev -- --host $HOST --port $PORT'."
        )


def _validate_vite_frontend_contract(
    *,
    repo_root: Path,
    frontend_root: Path,
    runtime_contract: PreviewRuntimeContract,
) -> None:
    if runtime_contract.strategy != PreviewStrategy.VITE_DEV:
        return
    index_file = frontend_root / "index.html"
    resolved_entrypoint = resolve_vite_entrypoint(frontend_root)
    entry_exists = bool(resolved_entrypoint)
    if runtime_contract.project_type == PreviewProjectType.MONOREPO_VITE_FASTAPI:
        expected_root = (repo_root / "apps" / "web").resolve()
        if frontend_root.resolve() != expected_root:
            raise ValueError(
                "MONOREPO_VITE_FASTAPI preview requires frontend root apps/web, "
                f"but resolved root was {frontend_root.relative_to(repo_root) if frontend_root.is_relative_to(repo_root) else str(frontend_root)}. "
                "Repair preview root mapping before relaunch."
            )
        if not index_file.exists():
            raise ValueError(
                "MONOREPO_VITE_FASTAPI preview requires apps/web/index.html. "
                "Repair the frontend foundation before relaunch."
            )
        if not entry_exists:
            raise ValueError(
                "MONOREPO_VITE_FASTAPI preview requires a valid module entrypoint in apps/web "
                "(for example src/main.ts, src/main.js, src/main.tsx, src/main.jsx, or the /src/* file referenced in index.html). "
                "Repair the frontend entrypoint before relaunch."
            )
    else:
        if not index_file.exists():
            raise ValueError(f"Vite preview requires index.html at frontend root: {frontend_root}")
        if not entry_exists:
            raise ValueError(
                "Vite preview requires a valid module entrypoint "
                "(for example src/main.ts, src/main.js, src/main.tsx, src/main.jsx, or the /src/* file referenced in index.html) "
                f"at frontend root: {frontend_root}"
            )


def _try_autofix_vite_workspace(frontend_root: Path, reason: str | None) -> bool:
    if not reason or "package.json is missing at frontend root" not in reason:
        return False
    src_main_ts = frontend_root / "src" / "main.ts"
    src_main_js = frontend_root / "src" / "main.js"
    if not src_main_ts.exists() and not src_main_js.exists():
        return False
    package_json = frontend_root / "package.json"
    if package_json.exists():
        return False
    package_json.write_text(
        json.dumps(
            {
                "name": "preview-autofix-vite",
                "private": True,
                "scripts": {"dev": "vite"},
                "devDependencies": {"vite": "^5.0.0"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return True


def _repo_template_frontend_root() -> Path:
    repo_root = Path(__file__).resolve().parents[4]
    foundation = repo_root / "runtime-templates" / "frontend-foundation" / "apps" / "web"
    if foundation.exists():
        return foundation
    return repo_root / "runtime-templates" / "fullstack-monorepo" / "apps" / "web"


def _copy_template_file_if_missing(*, template_root: Path, relative_path: str, target_root: Path) -> bool:
    target_path = target_root / relative_path
    if target_path.exists():
        return False
    source_path = template_root / relative_path
    if not source_path.exists():
        return False
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def _repair_frontend_entrypoint(frontend_root: Path) -> dict[str, Any]:
    template_root = _repo_template_frontend_root()
    repaired_files: list[str] = []
    for relative_path in (
        "index.html",
        "package.json",
        "vite.config.ts",
        "src/main.ts",
        "src/App.vue",
        "src/pages/LandingPage.vue",
        "src/layouts/PageShell.vue",
        "src/components/layout/Navbar.vue",
        "src/components/layout/Footer.vue",
        "src/components/layout/MobileNav.vue",
        "src/components/ui/SectionContainer.vue",
        "src/components/ui/ContentGrid.vue",
        "src/components/ui/Stack.vue",
        "src/components/ui/SectionHeading.vue",
        "src/components/ui/PrimaryButton.vue",
        "src/components/zones/HeroZone.vue",
        "src/components/zones/FeatureZone.vue",
        "src/components/zones/TestimonialsZone.vue",
        "src/components/zones/CTAZone.vue",
    ):
        if _copy_template_file_if_missing(template_root=template_root, relative_path=relative_path, target_root=frontend_root):
            repaired_files.append(relative_path)
    return {
        "repair_action_applied": PREVIEW_REPAIR_FRONTEND_ENTRYPOINT,
        "repaired_files": repaired_files,
    }


def _autofix_missing_vite_entrypoint(frontend_root: Path) -> dict[str, Any]:
    repaired_files: list[str] = []
    src_dir = frontend_root / "src"
    app_vue = src_dir / "App.vue"
    main_ts = src_dir / "main.ts"
    main_js = src_dir / "main.js"
    landing_page = src_dir / "pages" / "LandingPage.vue"
    legacy_landing_page = src_dir / "LandingPage.vue"
    app_fallback = "<template>\n  <main>\n    <h1>Landing Page</h1>\n  </main>\n</template>\n"

    def _app_shell_content() -> str:
        if landing_page.exists():
            return (
                "<template>\n  <LandingPage />\n</template>\n\n"
                "<script setup lang=\"ts\">\n"
                'import LandingPage from "./pages/LandingPage.vue";\n'
                "</script>\n"
            )
        if legacy_landing_page.exists():
            return (
                "<template>\n  <LandingPage />\n</template>\n\n"
                "<script setup lang=\"ts\">\n"
                'import LandingPage from "./LandingPage.vue";\n'
                "</script>\n"
            )
        return app_fallback
    # If main entry exists and points to a missing component, repair the missing component deterministically.
    for entry in (main_ts, main_js):
        if not entry.exists():
            continue
        try:
            content = entry.read_text(encoding="utf-8")
        except OSError:
            continue
        if "./App.vue" in content and not app_vue.exists():
            src_dir.mkdir(parents=True, exist_ok=True)
            app_vue.write_text(_app_shell_content(), encoding="utf-8")
            repaired_files.append("src/App.vue")
        if "./pages/LandingPage.vue" in content and not landing_page.exists():
            (src_dir / "pages").mkdir(parents=True, exist_ok=True)
            landing_page.write_text(
                "<template>\n  <main>\n    <h1>Landing Page</h1>\n  </main>\n</template>\n",
                encoding="utf-8",
            )
            repaired_files.append("src/pages/LandingPage.vue")
        if "./LandingPage.vue" in content and not legacy_landing_page.exists():
            legacy_landing_page.write_text(
                "<template>\n  <main>\n    <h1>Landing Page</h1>\n  </main>\n</template>\n",
                encoding="utf-8",
            )
            repaired_files.append("src/LandingPage.vue")
    if main_ts.exists() or main_js.exists():
        return {
            "repair_action_applied": PREVIEW_REPAIR_FRONTEND_ENTRYPOINT if repaired_files else None,
            "repaired_files": repaired_files,
        }
    if not app_vue.exists():
        return {"repair_action_applied": None, "repaired_files": repaired_files}
    src_dir.mkdir(parents=True, exist_ok=True)
    main_ts.write_text(
        'import { createApp } from "vue";\n'
        'import App from "./App.vue";\n\n'
        'createApp(App).mount("#app");\n',
        encoding="utf-8",
    )
    repaired_files.append("src/main.ts")
    return {
        "repair_action_applied": PREVIEW_REPAIR_FRONTEND_ENTRYPOINT,
        "repaired_files": repaired_files,
    }


def _sanitize_stale_vite_entry_for_static(frontend_root: Path, reason: str | None) -> bool:
    if not reason or "falling back to static preview" not in reason.lower():
        return False
    index_file = frontend_root / "index.html"
    if not index_file.exists():
        return False
    try:
        content = index_file.read_text(encoding="utf-8")
    except OSError:
        return False
    sanitized = re.sub(
        r'<script[^>]*type=["\']module["\'][^>]*src=["\']/src/main\.(?:ts|js)["\'][^>]*>\s*</script>',
        "",
        content,
        flags=re.IGNORECASE,
    )
    if sanitized == content:
        return False
    index_file.write_text(sanitized, encoding="utf-8")
    return True


def _sanitize_framework_only_markup_for_static(frontend_root: Path) -> bool:
    index_file = frontend_root / "index.html"
    if not index_file.exists():
        return False
    try:
        content = index_file.read_text(encoding="utf-8")
    except OSError:
        return False
    # If there are framework-only component tags in a static fallback, build a
    # simple readable shell so preview never lands on a blank screen.
    if "<HeroSection" not in content and "<PrimaryButton" not in content and "<template #title>" not in content:
        return False
    title_match = re.search(r"<template\s+#title>\s*<span>(.*?)</span>\s*</template>", content, flags=re.IGNORECASE | re.DOTALL)
    subtitle_match = re.search(
        r"<template\s+#subtitle>\s*<span>(.*?)</span>\s*</template>",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    title = (title_match.group(1).strip() if title_match else "Preview Ready").replace("<", "").replace(">", "")
    subtitle = (subtitle_match.group(1).strip() if subtitle_match else "Static fallback rendered because framework runtime was unavailable.")
    subtitle = subtitle.replace("<", "").replace(">", "")
    fallback_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
    <style>
      body {{
        margin: 0;
        padding: 48px 24px;
        font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
        background: #f8fafc;
        color: #0f172a;
      }}
      .card {{
        max-width: 840px;
        margin: 0 auto;
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 28px;
      }}
      h1 {{ margin: 0 0 12px; font-size: 32px; line-height: 1.2; }}
      p {{ margin: 0; font-size: 18px; line-height: 1.6; color: #334155; }}
    </style>
  </head>
  <body>
    <main class="card">
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </main>
  </body>
</html>
"""
    index_file.write_text(fallback_html, encoding="utf-8")
    return True


def _pick_port(preferred: int | None = None) -> int:
    if preferred:
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _expand_command(command: str, env: dict[str, str]) -> list[str]:
    expanded = string.Template(command).safe_substitute(env)
    parts = shlex.split(expanded)
    if not parts:
        raise ValueError("Preview command is empty.")
    return parts


def _service_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def _service_healthcheck(url: str, path: str | None) -> bool:
    target = f"{url}{path or '/'}"
    try:
        with urlopen(target, timeout=1.5) as response:  # noqa: S310
            status_ok = 200 <= int(response.status) < 500
            if not status_ok:
                return False
            try:
                body = response.read(8192)
            except Exception:
                body = b""
            if body:
                text = body.decode("utf-8", errors="ignore").lower()
                # Guard against malformed slot-rewrite artifacts that render blank previews.
                if "<//" in text:
                    return False
                # Static HTML previews should not contain unresolved framework-only slot tags.
                if "<contentslot" in text and ("<!doctype html" in text or "<html" in text):
                    return False
            return True
    except (URLError, OSError, ValueError):
        return False


async def _ensure_vite_frontend_dependencies(
    *,
    frontend_root: Path,
    logs_dir: Path,
    env_overrides: dict[str, str],
) -> dict[str, Any]:
    package_json = frontend_root / "package.json"
    if not package_json.exists():
        raise ValueError(f"Vite preview requires package.json at frontend root: {frontend_root}")
    node_modules = frontend_root / "node_modules"
    if node_modules.exists():
        return {"install_attempted": False, "install_succeeded": True}
    result = await run_workspace_command_async(
        ["npm", "install", "--no-fund", "--no-audit"],
        cwd=frontend_root,
        log_dir=logs_dir,
        label="preview-frontend-install",
        env=env_overrides,
        timeout_seconds=300,
    )
    if result.status != "SUCCEEDED":
        raise ValueError(result.stderr or result.stdout or "preview-frontend-install failed")
    return {"install_attempted": True, "install_succeeded": True}


def _hydration_marker_path(root: Path, name: str) -> Path:
    return root / ".runtime-hydration" / f"{name}.json"


def _load_hydration_marker(root: Path, name: str) -> dict[str, Any]:
    marker = _hydration_marker_path(root, name)
    if not marker.exists():
        return {}
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_hydration_marker(root: Path, name: str, payload: dict[str, Any]) -> None:
    marker = _hydration_marker_path(root, name)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _file_fingerprint(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _looks_like_missing_pip_package(text: str) -> bool:
    lowered = text.lower()
    return "no module named" in lowered or "modulenotfounderror" in lowered


def _looks_like_invalid_venv(text: str) -> bool:
    lowered = text.lower()
    return "virtual environment" in lowered or "venv" in lowered or "no such file or directory" in lowered


def _looks_like_uvicorn_import_failure(text: str) -> bool:
    lowered = text.lower()
    return "error loading asgi app" in lowered or "could not import module" in lowered or "err_module_not_found" in lowered


def _looks_like_route_boot_failure(text: str) -> bool:
    lowered = text.lower()
    return "include_router" in lowered or ("fastapi" in lowered and "traceback" in lowered)


async def _run_python_validation(
    *,
    command: list[str],
    cwd: Path,
    logs_dir: Path,
    label: str,
    env_overrides: dict[str, str],
    timeout_seconds: int = 120,
) -> tuple[bool, str]:
    result = await run_workspace_command_async(
        command,
        cwd=cwd,
        log_dir=logs_dir,
        label=label,
        env=env_overrides,
        timeout_seconds=timeout_seconds,
    )
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return result.status == "SUCCEEDED", combined


async def _ensure_backend_runtime_dependencies(
    *,
    backend_root: Path,
    logs_dir: Path,
    env_overrides: dict[str, str],
) -> dict[str, Any]:
    requirements_txt = backend_root / "requirements.txt"
    diagnostics: dict[str, Any] = {
        "install_attempted": False,
        "install_succeeded": False,
        "cached_hydration_state": "missing",
        "fastapi_import_ok": False,
        "uvicorn_import_ok": False,
        "app_import_ok": False,
        "diagnostic_code": None,
        "diagnostic_detail": None,
    }
    virtual_env = str(env_overrides.get("VIRTUAL_ENV") or "").strip()
    if virtual_env and not Path(virtual_env).exists():
        diagnostics["diagnostic_code"] = "invalid_venv"
        diagnostics["diagnostic_detail"] = f"Configured virtual environment does not exist: {virtual_env}"
        raise ValueError(diagnostics["diagnostic_detail"])

    fingerprint = _file_fingerprint(requirements_txt)
    marker = _load_hydration_marker(backend_root, "backend")
    cached = bool(fingerprint and marker.get("requirements_fingerprint") == fingerprint)
    diagnostics["cached_hydration_state"] = "hit" if cached else "miss"

    async def _attempt_imports() -> tuple[bool, str]:
        ok_fastapi, fastapi_output = await _run_python_validation(
            command=["python3", "-c", "import fastapi, uvicorn; print('imports-ok')"],
            cwd=backend_root,
            logs_dir=logs_dir,
            label="preview-backend-imports",
            env_overrides=env_overrides,
        )
        diagnostics["fastapi_import_ok"] = ok_fastapi
        diagnostics["uvicorn_import_ok"] = ok_fastapi
        if not ok_fastapi:
            return False, fastapi_output
        ok_app, app_output = await _run_python_validation(
            command=["python3", "-c", "from app.main import app; print(app.title if hasattr(app, 'title') else 'app-import-ok')"],
            cwd=backend_root,
            logs_dir=logs_dir,
            label="preview-backend-app-import",
            env_overrides=env_overrides,
        )
        diagnostics["app_import_ok"] = ok_app
        return ok_app, app_output

    ok_imports, import_output = await _attempt_imports()
    if ok_imports:
        diagnostics["install_succeeded"] = True
        if cached:
            _write_hydration_marker(
                backend_root,
                "backend",
                {"requirements_fingerprint": fingerprint, "validated_at": _now().isoformat()},
            )
        return diagnostics

    if requirements_txt.exists():
        diagnostics["install_attempted"] = True
        install = await run_workspace_command_async(
            ["python3", "-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt"],
            cwd=backend_root,
            log_dir=logs_dir,
            label="preview-backend-install",
            env=env_overrides,
            timeout_seconds=300,
        )
        if install.status != "SUCCEEDED":
            combined_install = "\n".join(part for part in (install.stdout, install.stderr) if part)
            diagnostics["diagnostic_detail"] = combined_install or "preview-backend-install failed"
            if _looks_like_invalid_venv(diagnostics["diagnostic_detail"] or ""):
                diagnostics["diagnostic_code"] = "invalid_venv"
            elif _looks_like_missing_pip_package(diagnostics["diagnostic_detail"] or ""):
                diagnostics["diagnostic_code"] = "missing_pip_package"
            raise ValueError(str(diagnostics["diagnostic_detail"]))
        ok_imports, import_output = await _attempt_imports()
        diagnostics["install_succeeded"] = ok_imports
        diagnostics["cached_hydration_state"] = "repaired"

    if ok_imports:
        _write_hydration_marker(
            backend_root,
            "backend",
            {"requirements_fingerprint": fingerprint, "validated_at": _now().isoformat()},
        )
        return diagnostics

    diagnostics["diagnostic_detail"] = import_output or "Backend import validation failed"
    if _looks_like_missing_pip_package(diagnostics["diagnostic_detail"] or ""):
        diagnostics["diagnostic_code"] = "missing_pip_package"
    elif _looks_like_uvicorn_import_failure(diagnostics["diagnostic_detail"] or ""):
        diagnostics["diagnostic_code"] = "uvicorn_import_failure"
    elif _looks_like_route_boot_failure(diagnostics["diagnostic_detail"] or ""):
        diagnostics["diagnostic_code"] = "fastapi_route_boot_failure"
    else:
        diagnostics["diagnostic_code"] = "backend_import_failure"
    raise ValueError(str(diagnostics["diagnostic_detail"]))


def _probe_backend_runtime(url: str, path: str | None) -> dict[str, Any]:
    probe = _http_probe(url, path or "/health")
    return {
        "health_endpoint_ok": bool(probe.get("ok")),
        "health_probe": probe,
    }


def _http_probe(url: str, path: str) -> dict[str, Any]:
    target = f"{url}{path}"
    try:
        request = Request(target, headers={"Accept": "*/*"})
        with urlopen(request, timeout=2.0) as response:  # noqa: S310
            try:
                body = response.read(8192)
            except Exception:
                body = b""
            return {
                "path": path,
                "url": target,
                "ok": 200 <= int(response.status) < 400,
                "status": int(response.status),
                "content_type": str(response.headers.get("Content-Type") or ""),
                "body_sample": body.decode("utf-8", errors="ignore")[:240],
            }
    except (URLError, OSError, ValueError) as exc:
        return {
            "path": path,
            "url": target,
            "ok": False,
            "status": None,
            "content_type": "",
            "error": str(exc),
            "body_sample": "",
        }


def _collect_vite_preview_diagnostics(url: str) -> dict[str, Any]:
    root_probe = _http_probe(url, "/")
    client_probe = _http_probe(url, "/@vite/client")
    root_sample_raw = str(root_probe.get("body_sample") or "")
    entry_path = extract_root_module_entry_path(root_sample_raw)
    entry_probe = _http_probe(url, entry_path)
    root_sample = root_sample_raw.lower()
    client_sample = str(client_probe.get("body_sample") or "").lower()
    entry_sample = str(entry_probe.get("body_sample") or "").lower()
    root_ok = bool(root_probe.get("ok")) and "<script" in root_sample and "type='module'" in root_sample.replace('"', "'")
    client_ok = bool(client_probe.get("ok")) and looks_like_javascript_content_type(str(client_probe.get("content_type") or "")) and "import" in client_sample
    entry_looks_like_html_fallback = "<!doctype html" in entry_sample or "<html" in entry_sample or "<body" in entry_sample
    entry_ok = (
        bool(entry_probe.get("ok"))
        and looks_like_javascript_content_type(str(entry_probe.get("content_type") or ""))
        and not entry_looks_like_html_fallback
    )
    return {
        "runtime_validation": "vite_dev",
        "root_probe": root_probe,
        "vite_client_probe": client_probe,
        "entry_probe": entry_probe,
        "entry_path": entry_path,
        "root_html_ok": root_ok,
        "vite_client_ok": client_ok,
        "entry_mime_ok": entry_ok,
        "hmr_ws_expected": True,
        "mime_validation_passed": root_ok and client_ok and entry_ok,
    }


def _reconcile_vite_preview_convergence(url: str, stabilization_window_seconds: float = 0.8) -> dict[str, Any]:
    first = _collect_vite_preview_diagnostics(url)
    time.sleep(stabilization_window_seconds)
    second = _collect_vite_preview_diagnostics(url)
    healthy = bool(second.get("mime_validation_passed"))
    failed_checks = ", ".join(
        check
        for check, ok in (
            ("root_html_ok", bool(second.get("root_html_ok"))),
            ("vite_client_ok", bool(second.get("vite_client_ok"))),
            ("entry_mime_ok", bool(second.get("entry_mime_ok"))),
        )
        if not ok
    ) or "unknown"
    entry_probe = second.get("entry_probe") if isinstance(second.get("entry_probe"), dict) else {}
    verification_note = None
    if not healthy:
        verification_note = (
            f"Vite preview started, but module asset validation failed for {second.get('entry_path') or '/src/main.ts'}. "
            f"Observed Content-Type: {str(entry_probe.get('content_type') or 'missing')}. "
            f"Failed checks: {failed_checks}."
        )
    return {
        "healthy": healthy,
        "verification_note": verification_note,
        "preview_launch_state": {"phase": "launch", "probe_count": 1, "checks": first},
        "preview_runtime_state": {
            "phase": "stabilizing",
            "probe_count": 2,
            "checks": second,
            "stabilization_window_seconds": stabilization_window_seconds,
        },
        "preview_terminal_state": {
            "phase": "terminal",
            "status": "READY" if healthy else "FAILED",
            "authoritative": True,
            "failed_checks": failed_checks if not healthy else "",
        },
    }


def _terminate_process_group(pid: int | None) -> None:
    if not pid:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        return


def _stop_preview_processes(preview: dict[str, Any]) -> None:
    for service_key in ("frontend", "backend"):
        service = preview.get(service_key) or {}
        _terminate_process_group(service.get("pid"))


def _start_service_process(
    *,
    command: str,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
    host: str,
    port: int,
) -> _PreviewProcess:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    parts = _expand_command(command, env)
    handle = log_path.open("ab")
    process = subprocess.Popen(  # noqa: S603
        parts,
        cwd=str(cwd),
        env={**os.environ, **env},
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    return _PreviewProcess(
        pid=process.pid,
        log_path=str(log_path),
        url=_service_url(host, port),
        port=port,
    )


def _process_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


async def get_project_preview_profile(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ProjectPreviewProfile | None:
    return await session.scalar(
        select(ProjectPreviewProfile).where(
            ProjectPreviewProfile.project_id == project_id,
            ProjectPreviewProfile.tenant_id == tenant_id,
        )
    )


async def upsert_project_preview_profile(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    tenant_id: uuid.UUID,
    payload: dict[str, Any],
) -> ProjectPreviewProfile:
    profile = await get_project_preview_profile(session, tenant_id=tenant_id, project_id=project_id)
    if profile is None:
        profile = ProjectPreviewProfile(project_id=project_id, tenant_id=tenant_id)
        session.add(profile)
    for field, value in payload.items():
        if hasattr(profile, field):
            setattr(profile, field, value)
    await session.flush()
    return profile


async def _count_active_previews(session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID | None = None) -> int:
    runs = (
        await session.execute(
            select(Run).where(Run.tenant_id == tenant_id)
        )
    ).scalars().all()
    count = 0
    now = _now()
    for run in runs:
        if project_id and run.project_id != project_id:
            continue
        preview = _preview_summary(run)
        expires_at = _coerce_datetime(preview.get("expires_at"))
        if preview.get("status") in {"STARTING", "READY"} and (expires_at is None or expires_at > now):
            count += 1
    return count


async def cleanup_expired_previews(session: AsyncSession, *, tenant_id: uuid.UUID) -> None:
    runs = (await session.execute(select(Run).where(Run.tenant_id == tenant_id))).scalars().all()
    now = _now()
    for run in runs:
        preview = _preview_summary(run)
        if not preview:
            continue
        expires_at = _coerce_datetime(preview.get("expires_at"))
        if expires_at and expires_at <= now:
            _stop_preview_processes(preview)
            preview["status"] = "EXPIRED"
            preview["last_checked_at"] = now.isoformat()
            _write_preview_summary(run, preview)
            session.add(run)
    await session.flush()


def _build_preview_response(
    run: Run,
    *,
    profile: ProjectPreviewProfile | ResolvedPreviewProfile | None,
    repository_connected: bool,
) -> RunPreviewOut:
    preview = _preview_summary(run)
    frontend = preview.get("frontend") if isinstance(preview.get("frontend"), dict) else None
    backend = preview.get("backend") if isinstance(preview.get("backend"), dict) else None
    diagnostics = preview.get("diagnostics") if isinstance(preview.get("diagnostics"), dict) else {}
    return RunPreviewOut(
        run_id=run.id,
        project_id=run.project_id,
        status=str(preview.get("status") or DEFAULT_PREVIEW_STATUS),
        mode=str(preview.get("mode") or (profile.mode if profile else "local")),
        branch_name=run.branch_name,
        reusable=bool(preview.get("reusable")),
        launched_at=_coerce_datetime(preview.get("launched_at")),
        expires_at=_coerce_datetime(preview.get("expires_at")),
        ttl_hours=int(preview.get("ttl_hours") or (profile.ttl_hours if profile else get_settings().preview_default_ttl_hours)),
        preview_url=preview.get("preview_url"),
        frontend=RunPreviewServiceRef.model_validate(frontend) if frontend else None,
        backend=RunPreviewServiceRef.model_validate(backend) if backend else None,
        compose_file=profile.compose_file if profile else None,
        reuse_reason=preview.get("reuse_reason"),
        requires_verification=run.status != "COMPLETED",
        verification_note=(
            "Run must be completed before preview launch."
            if run.status != "COMPLETED"
            else str(preview.get("verification_note") or "") or None
        ),
        profile_configured=profile is not None and profile.enabled,
        repository_connected=repository_connected,
        runtime_classification=str(preview.get("runtime_classification") or "") or None,
        preview_strategy=str(preview.get("preview_strategy") or "") or None,
        active_preview_command=str(preview.get("active_preview_command") or "") or None,
        upstream_preview_port=(
            int(preview.get("upstream_preview_port"))
            if isinstance(preview.get("upstream_preview_port"), int)
            else None
        ),
        frontend_install_status=str(diagnostics.get("frontend_install_status") or "") or None,
        backend_install_status=str(diagnostics.get("backend_install_status") or "") or None,
        runtime_boot_duration_seconds=float(diagnostics.get("runtime_boot_duration_seconds")) if isinstance(diagnostics.get("runtime_boot_duration_seconds"), (int, float)) else None,
        dependency_repair_attempts=int(diagnostics.get("dependency_repair_attempts") or 0),
        cached_hydration_state=diagnostics.get("cached_hydration_state") if isinstance(diagnostics.get("cached_hydration_state"), dict) else {},
        preview_diagnostics=diagnostics,
    )


async def assess_preview_runtime_readiness(
    *,
    repo_root: Path,
    profile: ProjectPreviewProfile | ResolvedPreviewProfile,
) -> dict[str, Any]:
    logs_dir = repo_root / ".runtime-hydration" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    host = get_settings().preview_host
    env_overrides = {str(key): str(value) for key, value in (profile.env_overrides or {}).items()}
    configured_frontend_root = _root_path(repo_root, profile.frontend_root)
    runtime_contract = resolve_preview_runtime_contract(
        repo_root=repo_root,
        configured_frontend_root=configured_frontend_root,
    )
    frontend_root = runtime_contract.frontend_root
    effective_profile: ProjectPreviewProfile | ResolvedPreviewProfile = profile
    if runtime_contract.strategy == PreviewStrategy.VITE_DEV and _uses_static_frontend_contract(profile):
        effective_profile = ResolvedPreviewProfile(
            enabled=profile.enabled,
            mode=profile.mode,
            frontend_root=str(frontend_root.relative_to(repo_root)),
            backend_root=profile.backend_root or (
                "apps/api" if runtime_contract.project_type == PreviewProjectType.MONOREPO_VITE_FASTAPI else None
            ),
            compose_file=profile.compose_file,
            frontend_build_command=profile.frontend_build_command,
            backend_build_command=profile.backend_build_command,
            frontend_start_command=DEFAULT_VITE_START_COMMAND,
            backend_start_command=profile.backend_start_command or (
                "python3 main.py" if runtime_contract.project_type == PreviewProjectType.MONOREPO_VITE_FASTAPI else None
            ),
            frontend_healthcheck_path=profile.frontend_healthcheck_path or "/",
            backend_healthcheck_path=profile.backend_healthcheck_path or "/health",
            frontend_port=profile.frontend_port,
            backend_port=profile.backend_port,
            env_overrides=profile.env_overrides or {},
            ttl_hours=profile.ttl_hours,
            max_previews_per_project=profile.max_previews_per_project,
            created_by=profile.created_by,
        )
    _validate_static_frontend_contract(frontend_root, effective_profile)
    _validate_vite_frontend_contract(
        repo_root=repo_root,
        frontend_root=frontend_root,
        runtime_contract=runtime_contract,
    )
    backend_root = _root_path(repo_root, effective_profile.backend_root)
    frontend_bootstrap: dict[str, Any] = {}
    backend_bootstrap: dict[str, Any] = {}
    if runtime_contract.strategy == PreviewStrategy.VITE_DEV:
        frontend_bootstrap = await _ensure_vite_frontend_dependencies(
            frontend_root=frontend_root,
            logs_dir=logs_dir,
            env_overrides=env_overrides,
        )
    if effective_profile.backend_start_command:
        backend_bootstrap = await _ensure_backend_runtime_dependencies(
            backend_root=backend_root,
            logs_dir=logs_dir,
            env_overrides=env_overrides,
        )

    frontend_process: _PreviewProcess | None = None
    backend_process: _PreviewProcess | None = None
    frontend_ready = False
    backend_ready = False
    diagnostics: dict[str, Any] = {}
    convergence_state: dict[str, Any] = {}
    backend_runtime_diagnostics: dict[str, Any] = {}
    boot_started_at = time.perf_counter()
    try:
        if effective_profile.frontend_start_command:
            frontend_port = _pick_port(effective_profile.frontend_port)
            frontend_process = _start_service_process(
                command=effective_profile.frontend_start_command,
                cwd=frontend_root,
                env={**env_overrides, "PORT": str(frontend_port), "HOST": host},
                log_path=logs_dir / "frontend-runtime-readiness.log",
                host=host,
                port=frontend_port,
            )
        if effective_profile.backend_start_command:
            backend_port = _pick_port(effective_profile.backend_port)
            backend_process = _start_service_process(
                command=effective_profile.backend_start_command,
                cwd=backend_root,
                env={**env_overrides, "PORT": str(backend_port), "HOST": host},
                log_path=logs_dir / "backend-runtime-readiness.log",
                host=host,
                port=backend_port,
            )
        deadline = time.time() + 15
        while time.time() < deadline:
            frontend_ready = True if frontend_process is None else _service_healthcheck(frontend_process.url, effective_profile.frontend_healthcheck_path or "/")
            backend_ready = True if backend_process is None else _service_healthcheck(backend_process.url, effective_profile.backend_healthcheck_path or "/health")
            if frontend_ready and backend_ready:
                break
            time.sleep(0.5)
        if runtime_contract.strategy == PreviewStrategy.VITE_DEV and frontend_process:
            convergence_state = _reconcile_vite_preview_convergence(frontend_process.url)
            diagnostics = (
                convergence_state.get("preview_runtime_state", {}).get("checks", {})
                if isinstance(convergence_state.get("preview_runtime_state"), dict)
                else {}
            )
            frontend_ready = frontend_ready and bool(convergence_state.get("healthy"))
        if backend_process:
            backend_runtime_diagnostics = _probe_backend_runtime(
                backend_process.url,
                effective_profile.backend_healthcheck_path or "/health",
            )
            backend_ready = backend_ready and bool(backend_runtime_diagnostics.get("health_endpoint_ok"))
    finally:
        if frontend_process:
            _terminate_process_group(frontend_process.pid)
        if backend_process:
            _terminate_process_group(backend_process.pid)
    runtime_boot_duration_seconds = round(time.perf_counter() - boot_started_at, 3)
    return {
        "ready": frontend_ready and backend_ready,
        "repository_connected": True,
        "preview_profile_enabled": bool(profile.enabled),
        "preview_profile_resolved": True,
        "dependencies_ready_frontend": bool(frontend_bootstrap.get("install_succeeded", runtime_contract.strategy != PreviewStrategy.VITE_DEV)),
        "dependencies_ready_backend": bool(backend_bootstrap.get("install_succeeded", not bool(effective_profile.backend_start_command))),
        "preview_runtime_ready": frontend_ready,
        "backend_runtime_ready": backend_ready,
        "runtime_classification": runtime_contract.project_type.value,
        "preview_strategy": runtime_contract.strategy.value,
        "frontend_install_status": (
            "installed" if frontend_bootstrap.get("install_attempted") else "cached" if runtime_contract.strategy == PreviewStrategy.VITE_DEV else "not_required"
        ),
        "backend_install_status": (
            "installed" if backend_bootstrap.get("install_attempted") else str(backend_bootstrap.get("cached_hydration_state") or "not_required")
        ),
        "runtime_boot_duration_seconds": runtime_boot_duration_seconds,
        "dependency_repair_attempts": int(bool(frontend_bootstrap.get("install_attempted"))) + int(bool(backend_bootstrap.get("install_attempted"))),
        "cached_hydration_state": {
            "frontend": "hit" if runtime_contract.strategy == PreviewStrategy.VITE_DEV and not frontend_bootstrap.get("install_attempted") else "repaired" if frontend_bootstrap.get("install_attempted") else "not_required",
            "backend": str(backend_bootstrap.get("cached_hydration_state") or "not_required"),
        },
        "frontend_bootstrap": frontend_bootstrap,
        "backend_bootstrap": backend_bootstrap,
        **convergence_state,
        **diagnostics,
        **backend_runtime_diagnostics,
    }


async def get_run_preview(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
) -> RunPreviewOut:
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id))
    if run is None:
        raise ValueError("Run not found")
    profile = await get_project_preview_profile(session, tenant_id=tenant_id, project_id=run.project_id)
    repo = await session.scalar(
        select(ProjectRepository).where(ProjectRepository.project_id == run.project_id, ProjectRepository.tenant_id == tenant_id)
    )
    effective_profile = resolve_preview_profile(profile, repository_connected=repo is not None)
    preview = _preview_summary(run)
    now = _now()
    changed = False
    if preview:
        expires_at = _coerce_datetime(preview.get("expires_at"))
        if expires_at and expires_at <= now and preview.get("status") in {"STARTING", "READY"}:
            _stop_preview_processes(preview)
            preview["status"] = "EXPIRED"
            changed = True
        else:
            for service_key in ("frontend", "backend"):
                service = preview.get(service_key) or {}
                url = service.get("url")
                path = service.get("healthcheck_path")
                pid = service.get("pid")
                if url and preview.get("status") in {"STARTING", "READY"}:
                    healthy = _service_healthcheck(url, path)
                    service["status"] = "READY" if healthy else ("FAILED" if not _process_running(pid) else service.get("status") or "STARTING")
                    if preview.get("status") == "READY" and not healthy and not _process_running(pid):
                        preview["status"] = "FAILED"
                    changed = True
            preview["last_checked_at"] = now.isoformat()
        if changed:
            _write_preview_summary(run, preview)
            session.add(run)
            await session.flush()
    return _build_preview_response(run, profile=effective_profile, repository_connected=repo is not None)


async def launch_run_preview(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    reuse_if_healthy: bool = True,
    repair_action: str | None = None,
) -> RunPreviewOut:
    await cleanup_expired_previews(session, tenant_id=tenant_id)
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id))
    if run is None:
        raise ValueError("Run not found")
    profile = await get_project_preview_profile(session, tenant_id=tenant_id, project_id=run.project_id)
    repo = await session.scalar(
        select(ProjectRepository).where(ProjectRepository.project_id == run.project_id, ProjectRepository.tenant_id == tenant_id)
    )
    effective_profile = resolve_preview_profile(profile, repository_connected=repo is not None)
    if effective_profile is None or not effective_profile.enabled:
        raise ValueError("Project preview profile is not configured")
    if effective_profile.compose_file and not (effective_profile.frontend_start_command or effective_profile.backend_start_command):
        raise ValueError("Compose-only preview profiles are not supported in the local preview launcher yet")
    if run.status != "COMPLETED":
        raise ValueError("Run must be completed before preview launch")
    preview = _preview_summary(run)
    if reuse_if_healthy and preview.get("status") == "READY":
        expires_at = _coerce_datetime(preview.get("expires_at"))
        frontend = preview.get("frontend") or {}
        backend = preview.get("backend") or {}
        services = [service for service in (frontend, backend) if isinstance(service, dict) and service.get("url")]
        if services and (expires_at is None or expires_at > _now()) and all(
            _service_healthcheck(service["url"], service.get("healthcheck_path")) for service in services
        ):
            preview["reuse_reason"] = "healthy_existing_preview"
            preview["reusable"] = True
            _write_preview_summary(run, preview)
            session.add(run)
            await session.flush()
            return _build_preview_response(run, profile=effective_profile, repository_connected=repo is not None)

    project_active = await _count_active_previews(session, tenant_id=tenant_id, project_id=run.project_id)
    global_active = await _count_active_previews(session, tenant_id=tenant_id)
    max_project = effective_profile.max_previews_per_project or get_settings().preview_max_per_project
    max_global = get_settings().preview_max_global
    if project_active >= max_project:
        raise ValueError("Project preview limit reached")
    if global_active >= max_global:
        raise ValueError("Global preview limit reached")

    workspace_root = _workspace_path(run)
    repo_root = _repo_root(run)
    logs_dir = workspace_root / "logs" / "preview"
    logs_dir.mkdir(parents=True, exist_ok=True)
    preview_dir = workspace_root / "context"
    preview_dir.mkdir(parents=True, exist_ok=True)
    host = get_settings().preview_host
    env_overrides = {str(key): str(value) for key, value in (effective_profile.env_overrides or {}).items()}
    ttl_hours = effective_profile.ttl_hours or get_settings().preview_default_ttl_hours
    launched_at = _now()
    expires_at = launched_at + timedelta(hours=ttl_hours)
    frontend_service: dict[str, Any] | None = None
    backend_service: dict[str, Any] | None = None
    diagnostics: dict[str, Any] = {}
    convergence_state: dict[str, Any] = {}
    verification_note: str | None = None
    frontend_bootstrap: dict[str, Any] = {}
    backend_bootstrap: dict[str, Any] = {}
    repair_summary: dict[str, Any] = {}
    composition_meta: dict[str, Any] = {}
    runtime_contract: PreviewRuntimeContract | None = None

    async def _persist_failed_preview(reason: str) -> None:
        nonlocal verification_note
        verification_note = reason
        preview_payload = {
            "status": "FAILED",
            "mode": effective_profile.mode,
            "preview_url": None,
            "frontend": frontend_service,
            "backend": backend_service,
            "ttl_hours": ttl_hours,
            "launched_at": launched_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "reusable": False,
            "reuse_reason": None,
            "last_checked_at": _now().isoformat(),
            "runtime_classification": (
                runtime_contract.project_type.value if runtime_contract is not None else None
            ),
            "preview_strategy": runtime_contract.strategy.value if runtime_contract is not None else None,
            "active_preview_command": (
                effective_profile.frontend_start_command
                if frontend_service is not None
                else effective_profile.backend_start_command
            ),
            "upstream_preview_port": (
                frontend_service.get("port")
                if frontend_service
                else (backend_service.get("port") if backend_service else None)
            ),
            "diagnostics": {
                **(diagnostics if isinstance(diagnostics, dict) else {}),
                **convergence_state,
                "transient_diagnostics": (
                    convergence_state.get("preview_launch_state", {}).get("checks", {})
                    if isinstance(convergence_state.get("preview_launch_state"), dict)
                    else {}
                ),
                "terminal_diagnostics": (
                    convergence_state.get("preview_runtime_state", {}).get("checks", diagnostics)
                    if isinstance(convergence_state.get("preview_runtime_state"), dict)
                    else diagnostics
                ),
                **repair_summary,
                **composition_meta,
                "dependencies_ready_frontend": bool(
                    frontend_bootstrap.get("install_succeeded", runtime_contract is None or runtime_contract.strategy != PreviewStrategy.VITE_DEV)
                ),
                "dependencies_ready_backend": bool(
                    backend_bootstrap.get("install_succeeded", not bool(effective_profile.backend_start_command))
                ),
                "preview_runtime_ready": False,
                "backend_runtime_ready": False,
                "frontend_install_status": (
                    "installed"
                    if frontend_bootstrap.get("install_attempted")
                    else "cached"
                    if runtime_contract is not None and runtime_contract.strategy == PreviewStrategy.VITE_DEV
                    else "not_required"
                ),
                "backend_install_status": (
                    "installed"
                    if backend_bootstrap.get("install_attempted")
                    else str(backend_bootstrap.get("cached_hydration_state") or "not_required")
                ),
                "dependency_repair_attempts": int(bool(frontend_bootstrap.get("install_attempted")))
                + int(bool(backend_bootstrap.get("install_attempted"))),
                "cached_hydration_state": {
                    "frontend": (
                        "hit"
                        if runtime_contract is not None
                        and runtime_contract.strategy == PreviewStrategy.VITE_DEV
                        and not frontend_bootstrap.get("install_attempted")
                        else "repaired"
                        if frontend_bootstrap.get("install_attempted")
                        else "not_required"
                    ),
                    "backend": str(backend_bootstrap.get("cached_hydration_state") or "not_required"),
                },
                "frontend_bootstrap": frontend_bootstrap,
                "backend_bootstrap": backend_bootstrap,
                "diagnostic_detail": reason,
            },
            "verification_note": verification_note,
        }
        _write_preview_summary(run, preview_payload)
        session.add(run)
        await session.flush()
    configured_frontend_root = _root_path(repo_root, effective_profile.frontend_root)
    runtime_contract = resolve_preview_runtime_contract(
        repo_root=repo_root,
        configured_frontend_root=configured_frontend_root,
    )
    frontend_root = runtime_contract.frontend_root
    try:
        if repair_action == PREVIEW_REPAIR_FRONTEND_ROOT:
            expected_root = repo_root / "apps" / "web"
            if not expected_root.exists():
                raise ValueError("Preview root repair requires apps/web to exist.")
            if profile is not None:
                profile.frontend_root = "apps/web"
                session.add(profile)
                await session.flush()
            effective_profile = ResolvedPreviewProfile(
                enabled=effective_profile.enabled,
                mode=effective_profile.mode,
                frontend_root="apps/web",
                backend_root=effective_profile.backend_root,
                compose_file=effective_profile.compose_file,
                frontend_build_command=effective_profile.frontend_build_command,
                backend_build_command=effective_profile.backend_build_command,
                frontend_start_command=effective_profile.frontend_start_command,
                backend_start_command=effective_profile.backend_start_command,
                frontend_healthcheck_path=effective_profile.frontend_healthcheck_path,
                backend_healthcheck_path=effective_profile.backend_healthcheck_path,
                frontend_port=effective_profile.frontend_port,
                backend_port=effective_profile.backend_port,
                env_overrides=effective_profile.env_overrides or {},
                ttl_hours=effective_profile.ttl_hours,
                max_previews_per_project=effective_profile.max_previews_per_project,
                created_by=effective_profile.created_by,
            )
            configured_frontend_root = expected_root
            runtime_contract = resolve_preview_runtime_contract(
                repo_root=repo_root,
                configured_frontend_root=configured_frontend_root,
            )
            frontend_root = runtime_contract.frontend_root
        if (
            runtime_contract.strategy == PreviewStrategy.INVALID
            and get_settings().preview_autofix_vite_missing_package
            and _try_autofix_vite_workspace(frontend_root, runtime_contract.reason)
        ):
            runtime_contract = resolve_preview_runtime_contract(
                repo_root=repo_root,
                configured_frontend_root=configured_frontend_root,
            )
            frontend_root = runtime_contract.frontend_root
        if repair_action == PREVIEW_REPAIR_FRONTEND_ENTRYPOINT:
            repair_summary = _repair_frontend_entrypoint(frontend_root)
            runtime_contract = resolve_preview_runtime_contract(
                repo_root=repo_root,
                configured_frontend_root=frontend_root,
            )
            frontend_root = runtime_contract.frontend_root
        if runtime_contract.strategy == PreviewStrategy.STATIC_SERVER:
            _sanitize_stale_vite_entry_for_static(frontend_root, runtime_contract.reason)
            _sanitize_framework_only_markup_for_static(frontend_root)
        if runtime_contract.strategy == PreviewStrategy.VITE_DEV:
            auto_repair_summary = _autofix_missing_vite_entrypoint(frontend_root)
            if auto_repair_summary.get("repaired_files"):
                repaired = list(repair_summary.get("repaired_files") or [])
                repaired.extend(str(path) for path in auto_repair_summary.get("repaired_files", []))
                repair_summary["repaired_files"] = sorted(set(repaired))
                repair_summary["repair_action_applied"] = auto_repair_summary.get("repair_action_applied")
            if not resolve_vite_entrypoint(frontend_root):
                full_repair_summary = _repair_frontend_entrypoint(frontend_root)
                if full_repair_summary.get("repaired_files"):
                    repaired = list(repair_summary.get("repaired_files") or [])
                    repaired.extend(str(path) for path in full_repair_summary.get("repaired_files", []))
                    repair_summary["repaired_files"] = sorted(set(repaired))
                    repair_summary["repair_action_applied"] = PREVIEW_REPAIR_FRONTEND_ENTRYPOINT
        if runtime_contract.strategy == PreviewStrategy.INVALID:
            raise ValueError(runtime_contract.reason or "Preview runtime classification failed.")
        if runtime_contract.strategy == PreviewStrategy.DISABLED and not effective_profile.backend_start_command:
            raise ValueError(runtime_contract.reason or "No previewable frontend artifact generated.")
        if runtime_contract.strategy == PreviewStrategy.VITE_DEV and _uses_static_frontend_contract(effective_profile):
            effective_profile = ResolvedPreviewProfile(
                enabled=effective_profile.enabled,
                mode=effective_profile.mode,
                frontend_root=str(frontend_root.relative_to(repo_root)),
                backend_root=effective_profile.backend_root or (
                    "apps/api" if runtime_contract.project_type == PreviewProjectType.MONOREPO_VITE_FASTAPI else None
                ),
                compose_file=effective_profile.compose_file,
                frontend_build_command=effective_profile.frontend_build_command,
                backend_build_command=effective_profile.backend_build_command,
                frontend_start_command=DEFAULT_VITE_START_COMMAND,
                backend_start_command=effective_profile.backend_start_command or (
                    "python3 main.py" if runtime_contract.project_type == PreviewProjectType.MONOREPO_VITE_FASTAPI else None
                ),
                frontend_healthcheck_path=effective_profile.frontend_healthcheck_path or "/",
                backend_healthcheck_path=effective_profile.backend_healthcheck_path or "/health",
                frontend_port=effective_profile.frontend_port,
                backend_port=effective_profile.backend_port,
                env_overrides=effective_profile.env_overrides or {},
                ttl_hours=effective_profile.ttl_hours,
                max_previews_per_project=effective_profile.max_previews_per_project,
                created_by=(
                    effective_profile.created_by
                    or (
                        "system:default-monorepo-vite-fastapi-preview"
                        if runtime_contract.project_type == PreviewProjectType.MONOREPO_VITE_FASTAPI
                        else "system:default-static-web-monorepo"
                    )
                ),
            )
        if runtime_contract.strategy == PreviewStrategy.VITE_DEV and not (frontend_root / "node_modules").exists():
            effective_profile = ResolvedPreviewProfile(
                enabled=effective_profile.enabled,
                mode=effective_profile.mode,
                frontend_root=effective_profile.frontend_root,
                backend_root=effective_profile.backend_root,
                compose_file=effective_profile.compose_file,
                frontend_build_command=effective_profile.frontend_build_command,
                backend_build_command=effective_profile.backend_build_command,
                frontend_start_command=DEFAULT_VITE_NPX_START_COMMAND,
                backend_start_command=effective_profile.backend_start_command,
                frontend_healthcheck_path=effective_profile.frontend_healthcheck_path or "/",
                backend_healthcheck_path=effective_profile.backend_healthcheck_path or "/",
                frontend_port=effective_profile.frontend_port,
                backend_port=effective_profile.backend_port,
                env_overrides=effective_profile.env_overrides or {},
                ttl_hours=effective_profile.ttl_hours,
                max_previews_per_project=effective_profile.max_previews_per_project,
                created_by=(effective_profile.created_by or "system:default-vite-dev-preview"),
            )
        _validate_static_frontend_contract(frontend_root, effective_profile)
        _validate_vite_frontend_contract(
            repo_root=repo_root,
            frontend_root=frontend_root,
            runtime_contract=runtime_contract,
        )
        backend_root = _root_path(repo_root, effective_profile.backend_root)

        if preview:
            _stop_preview_processes(preview)
        _clear_preview_summary(run)
        session.add(run)
        await session.flush()

        async def _run_build_if_configured(command: str | None, cwd: Path, label: str) -> None:
            if not command:
                return
            result = await run_workspace_command_async(
                shlex.split(command),
                cwd=cwd,
                log_dir=logs_dir,
                label=label,
                env=env_overrides,
                timeout_seconds=300,
            )
            if result.status != "SUCCEEDED":
                raise ValueError(result.stderr or result.stdout or f"{label} failed")

        await _run_build_if_configured(
            effective_profile.frontend_build_command,
            frontend_root,
            "preview-frontend-build",
        )
        await _run_build_if_configured(
            effective_profile.backend_build_command,
            backend_root,
            "preview-backend-build",
        )
        if runtime_contract.strategy == PreviewStrategy.VITE_DEV:
            frontend_bootstrap = await _ensure_vite_frontend_dependencies(
                frontend_root=frontend_root,
                logs_dir=logs_dir,
                env_overrides=env_overrides,
            )
        if effective_profile.backend_start_command:
            backend_bootstrap = await _ensure_backend_runtime_dependencies(
                backend_root=backend_root,
                logs_dir=logs_dir,
                env_overrides=env_overrides,
            )
        boot_started_at = time.perf_counter()
        if effective_profile.frontend_start_command:
            port = _pick_port(effective_profile.frontend_port)
            env = {
                **env_overrides,
                "PORT": str(port),
                "HOST": host,
                "ENV": "preview",
                "PREVIEW_ENV": "preview",
                "BRANCH_NAME": run.branch_name or "",
            }
            process = _start_service_process(
                command=effective_profile.frontend_start_command,
                cwd=frontend_root,
                env=env,
                log_path=logs_dir / "frontend-preview.log",
                host=host,
                port=port,
            )
            frontend_service = {
                "kind": "frontend",
                "status": "STARTING",
                "url": process.url,
                "pid": process.pid,
                "port": process.port,
                "root": effective_profile.frontend_root,
                "start_command": effective_profile.frontend_start_command,
                "build_command": effective_profile.frontend_build_command,
                "healthcheck_path": effective_profile.frontend_healthcheck_path or "/",
                "log_path": process.log_path,
                "last_error": None,
            }

        if effective_profile.backend_start_command:
            port = _pick_port(effective_profile.backend_port)
            env = {
                **env_overrides,
                "PORT": str(port),
                "HOST": host,
                "ENV": "preview",
                "PREVIEW_ENV": "preview",
                "BRANCH_NAME": run.branch_name or "",
            }
            process = _start_service_process(
                command=effective_profile.backend_start_command,
                cwd=backend_root,
                env=env,
                log_path=logs_dir / "backend-preview.log",
                host=host,
                port=port,
            )
            backend_service = {
                "kind": "backend",
                "status": "STARTING",
                "url": process.url,
                "pid": process.pid,
                "port": process.port,
                "root": effective_profile.backend_root,
                "start_command": effective_profile.backend_start_command,
                "build_command": effective_profile.backend_build_command,
                "healthcheck_path": effective_profile.backend_healthcheck_path or "/",
                "log_path": process.log_path,
                "last_error": None,
            }

        if not frontend_service and not backend_service:
            raise ValueError("Preview profile must define at least one start command")

        deadline = time.time() + 15
        while time.time() < deadline:
            frontend_ready = True
            backend_ready = True
            if frontend_service:
                frontend_ready = _service_healthcheck(frontend_service["url"], frontend_service["healthcheck_path"])
                frontend_service["status"] = "READY" if frontend_ready else "STARTING"
            if backend_service:
                backend_ready = _service_healthcheck(backend_service["url"], backend_service["healthcheck_path"])
                backend_service["status"] = "READY" if backend_ready else "STARTING"
            if frontend_ready and backend_ready:
                break
            time.sleep(0.5)
        else:
            raise ValueError("Preview health checks did not pass")
        diagnostics: dict[str, Any] = {}
        verification_note: str | None = None
        if runtime_contract.strategy == PreviewStrategy.VITE_DEV and frontend_service:
            convergence_state = _reconcile_vite_preview_convergence(frontend_service["url"])
            diagnostics = (
                convergence_state.get("preview_runtime_state", {}).get("checks", {})
                if isinstance(convergence_state.get("preview_runtime_state"), dict)
                else {}
            )
            if not convergence_state.get("healthy"):
                verification_note = str(convergence_state.get("verification_note") or "Preview convergence failed.")
                raise ValueError(verification_note)
        backend_runtime_diagnostics: dict[str, Any] = {}
        if backend_service:
            backend_runtime_diagnostics = _probe_backend_runtime(
                backend_service["url"],
                backend_service.get("healthcheck_path"),
            )
            if not backend_runtime_diagnostics.get("health_endpoint_ok"):
                verification_note = "Backend preview started, but /health validation failed."
                raise ValueError(verification_note)
        shell_repairs = reconcile_frontend_runtime_shell(repo_root=repo_root)
        if shell_repairs:
            repaired_files = repair_summary.get("repaired_files")
            merged = list(repaired_files) if isinstance(repaired_files, list) else []
            merged.extend(shell_repairs)
            repair_summary["repaired_files"] = sorted(set(str(item) for item in merged))
        composition_meta = validate_frontend_composition_integrity(
            repo_root=repo_root,
            payload={},
            recovery_repairs=[
                str(item)
                for item in repair_summary.get("repaired_files", [])
                if isinstance(item, str)
            ],
        )
        if not bool(composition_meta.get("composition_integrity_ok")):
            verification_note = "Preview convergence failed composition integrity checks."
            raise ValueError(verification_note)
        runtime_boot_duration_seconds = round(time.perf_counter() - boot_started_at, 3)
    except Exception as exc:
        if frontend_service:
            _terminate_process_group(frontend_service.get("pid"))
        if backend_service:
            _terminate_process_group(backend_service.get("pid"))
        await _persist_failed_preview(verification_note or str(exc))
        raise

    preview_url = (frontend_service or backend_service or {}).get("url")
    preview_payload = {
        "status": "READY",
        "mode": effective_profile.mode,
        "preview_url": preview_url,
        "frontend": frontend_service,
        "backend": backend_service,
        "ttl_hours": ttl_hours,
        "launched_at": launched_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "reusable": True,
        "reuse_reason": None,
        "last_checked_at": launched_at.isoformat(),
        "runtime_classification": runtime_contract.project_type.value,
        "preview_strategy": runtime_contract.strategy.value,
        "active_preview_command": (
            effective_profile.frontend_start_command
            if frontend_service
            else effective_profile.backend_start_command
        ),
        "upstream_preview_port": frontend_service.get("port") if frontend_service else (backend_service.get("port") if backend_service else None),
        "diagnostics": {
            **(diagnostics if runtime_contract.strategy == PreviewStrategy.VITE_DEV else {}),
            **convergence_state,
            "transient_diagnostics": (
                convergence_state.get("preview_launch_state", {}).get("checks", {})
                if isinstance(convergence_state.get("preview_launch_state"), dict)
                else {}
            ),
            "terminal_diagnostics": (
                convergence_state.get("preview_runtime_state", {}).get("checks", diagnostics)
                if isinstance(convergence_state.get("preview_runtime_state"), dict)
                else diagnostics
            ),
            **repair_summary,
            "dependencies_ready_frontend": bool(frontend_bootstrap.get("install_succeeded", runtime_contract.strategy != PreviewStrategy.VITE_DEV)),
            "dependencies_ready_backend": bool(
                backend_bootstrap.get("install_succeeded", not bool(effective_profile.backend_start_command))
            ),
            "preview_runtime_ready": bool(
                (
                    runtime_contract.strategy != PreviewStrategy.VITE_DEV
                    or bool(convergence_state.get("healthy", diagnostics.get("mime_validation_passed")))
                )
                and (frontend_service is None or frontend_service.get("status") == "READY")
            ),
            "backend_runtime_ready": bool(
                backend_service is None or backend_runtime_diagnostics.get("health_endpoint_ok")
            ),
            "frontend_install_status": (
                "installed"
                if frontend_bootstrap.get("install_attempted")
                else "cached"
                if runtime_contract.strategy == PreviewStrategy.VITE_DEV
                else "not_required"
            ),
            "backend_install_status": (
                "installed"
                if backend_bootstrap.get("install_attempted")
                else str(backend_bootstrap.get("cached_hydration_state") or "not_required")
            ),
            "runtime_boot_duration_seconds": runtime_boot_duration_seconds,
            "dependency_repair_attempts": int(bool(frontend_bootstrap.get("install_attempted"))) + int(bool(backend_bootstrap.get("install_attempted"))),
            "cached_hydration_state": {
                "frontend": "hit" if runtime_contract.strategy == PreviewStrategy.VITE_DEV and not frontend_bootstrap.get("install_attempted") else "repaired" if frontend_bootstrap.get("install_attempted") else "not_required",
                "backend": str(backend_bootstrap.get("cached_hydration_state") or "not_required"),
            },
            "frontend_bootstrap": frontend_bootstrap,
            "backend_bootstrap": backend_bootstrap,
            **backend_runtime_diagnostics,
            **composition_meta,
        },
        "verification_note": None if runtime_contract.strategy == PreviewStrategy.VITE_DEV else verification_note,
    }
    _write_preview_summary(run, preview_payload)
    session.add(run)
    await session.flush()
    preview_dir.mkdir(parents=True, exist_ok=True)
    (preview_dir / "preview.json").write_text(json.dumps(preview_payload, indent=2), encoding="utf-8")
    return _build_preview_response(run, profile=effective_profile, repository_connected=repo is not None)


async def stop_run_preview(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
) -> RunPreviewOut:
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id))
    if run is None:
        raise ValueError("Run not found")
    profile = await get_project_preview_profile(session, tenant_id=tenant_id, project_id=run.project_id)
    repo = await session.scalar(
        select(ProjectRepository).where(ProjectRepository.project_id == run.project_id, ProjectRepository.tenant_id == tenant_id)
    )
    preview = _preview_summary(run)
    if not preview:
        return _build_preview_response(run, profile=profile, repository_connected=repo is not None)

    _stop_preview_processes(preview)
    now = _now()
    preview["status"] = "STOPPED"
    preview["reusable"] = False
    preview["stopped_at"] = now.isoformat()
    preview["last_checked_at"] = now.isoformat()
    _write_preview_summary(run, preview)
    session.add(run)
    await session.flush()
    return _build_preview_response(run, profile=profile, repository_connected=repo is not None)
