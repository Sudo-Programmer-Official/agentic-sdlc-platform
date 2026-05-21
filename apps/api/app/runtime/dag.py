from __future__ import annotations

import logging
import re
import uuid
from pathlib import PurePosixPath
from typing import Any, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkItem, WorkItemEdge
from app.services.runtime_lineage import link_run_to_work_item

log = logging.getLogger("app.runtime")
PATH_HINT_PATTERN = re.compile(r"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.[A-Za-z0-9]{1,12})(?![\w./-])")
FRONTEND_SUFFIXES = {".html", ".css", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue", ".svelte"}
BACKEND_SUFFIXES = {".py", ".rb", ".go", ".rs", ".java", ".kt", ".php", ".cs", ".scala"}
TEXT_HINT_SUFFIXES = (
    FRONTEND_SUFFIXES
    | BACKEND_SUFFIXES
    | {".json", ".md", ".txt", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".sh", ".sql", ".xml"}
)
FRONTEND_KEYWORDS = {
    "homepage",
    "landing page",
    "hero section",
    "testimonials",
    "testimonial",
    "footer",
    "navbar",
    "navigation",
    "section",
    "layout",
    "responsive",
    "portfolio",
    "ui",
    "frontend",
    "css",
    "style",
    "dashboard",
}
BACKEND_KEYWORDS = {
    "backend",
    "api",
    "endpoint",
    "route",
    "service",
    "database",
    "model",
    "server",
    "webhook",
    "auth",
    "analytics event tracking",
    "utm",
    "tracking",
    "crm",
    "integration",
    "provider",
    "submission",
    "form submission",
}
DEFAULT_BACKEND_CAPABILITIES = [
    "lead_capture_storage",
    "crm_sync",
    "notification_dispatch",
    "analytics_event_stream",
]
INTENT_CAPABILITY_MAP = {
    "auth": "auth_identity",
    "payments": "payments_billing",
    "payment": "payments_billing",
    "crm sync": "crm_sync",
    "crm_sync": "crm_sync",
    "crm": "crm_sync",
    "email": "notification_dispatch",
    "notifications": "notification_dispatch",
    "webhooks": "webhook_dispatch",
    "webhook": "webhook_dispatch",
    "storage": "object_storage",
    "ai chat": "ai_chat_runtime",
    "ai agents": "ai_agent_orchestration",
    "analytics": "analytics_event_stream",
    "file uploads": "object_storage",
}
BACKEND_GENERATION_STAGES = (
    "GENERATE_ROUTE",
    "GENERATE_SERVICE",
    "GENERATE_REPOSITORY",
    "GENERATE_CAPABILITY_BINDING",
)
FRONTEND_PACKAGE_HINTS = ("web", "frontend", "ui", "client")
BACKEND_PACKAGE_HINTS = ("api", "backend", "server", "service")
SHELL_INFRA_FILES = {
    "apps/web/src/App.vue",
    "apps/web/src/layouts/PageShell.vue",
    "apps/web/src/pages/LandingPage.vue",
}
LANDING_ZONES = {
    "hero",
    "features",
    "testimonials",
    "pricing",
    "cta",
    "faq",
    "lead_capture",
}
POLISH_HINTS = {
    "polish",
    "beautiful",
    "improve ui",
    "improve ux",
    "spacing",
    "typography",
    "responsive",
    "refine",
    "visual",
    "theme",
}
FEATURE_CREATION_HINTS = {
    "add ",
    "create ",
    "new ",
    "build ",
    "integrate ",
    "section",
    "component",
}


class TaskScopeError(ValueError):
    """Raised when a task-scoped run cannot determine a safe file envelope."""


def _looks_like_text_file_hint(path: str) -> bool:
    pure = PurePosixPath(path)
    name = pure.name
    if not name:
        return False
    # Reject punctuation artifacts from prose such as "overall..along".
    if ".." in name:
        return False
    suffix = pure.suffix.lower()
    if suffix in TEXT_HINT_SUFFIXES:
        return True
    # Allow uncommon extensions only when a directory prefix exists.
    return len(pure.parts) > 1 and bool(suffix) and len(suffix) <= 13


def _normalized_paths(values: list[str], *, from_text: bool = False) -> list[str]:
    normalized: list[str] = []
    for value in values:
        candidate = value.strip().strip("`'\".,:;()[]{}")
        candidate = candidate.lstrip("./")
        if not candidate or candidate.startswith(("http://", "https://")):
            continue
        normalized_path = str(PurePosixPath(candidate))
        if from_text and not _looks_like_text_file_hint(normalized_path):
            continue
        normalized.append(normalized_path)
    return list(dict.fromkeys(path for path in normalized if path))


def _string_list_from_summary(run_summary: dict[str, Any] | None, *keys: str) -> list[str]:
    if not isinstance(run_summary, dict):
        return []
    values: list[str] = []
    for key in keys:
        raw = run_summary.get(key)
        if isinstance(raw, str) and raw.strip():
            values.append(raw.strip())
        elif isinstance(raw, list):
            values.extend(item for item in raw if isinstance(item, str) and item.strip())
    return _normalized_paths(values)


def _task_payload_from_summary(run_summary: dict | None) -> dict[str, Any]:
    if not isinstance(run_summary, dict):
        return {}
    task_id = run_summary.get("task_id")
    task_title = (run_summary.get("task_title") or "").strip()
    if not task_id or not task_title:
        return {}
    payload = {
        "task_id": str(task_id),
        "source_task_id": str(task_id),
        "task_title": task_title,
        "goal": str(run_summary.get("goal") or task_title),
    }
    description = (run_summary.get("task_description") or "").strip()
    if description:
        payload["task_description"] = description
    source = (run_summary.get("task_source") or "").strip()
    if source:
        payload["task_source"] = source
    architecture_profile = run_summary.get("architecture_profile")
    if isinstance(architecture_profile, dict):
        payload["architecture_profile"] = dict(architecture_profile)
    project_intent = run_summary.get("project_intent")
    if isinstance(project_intent, dict):
        payload["project_intent"] = dict(project_intent)
    target_files = _string_list_from_summary(run_summary, "target_files")
    if target_files:
        normalized_target_files = list(dict.fromkeys(target_files))
        payload["target_files"] = normalized_target_files
        payload["files"] = normalized_target_files
    edit_budget = run_summary.get("edit_budget")
    if isinstance(edit_budget, dict):
        payload["edit_budget"] = dict(edit_budget)
    related_files = _string_list_from_summary(run_summary, "expected_files", "files", "related_files")
    expected_files = list(dict.fromkeys(related_files + _expected_files_from_text(task_title, payload["goal"], description)))
    if target_files:
        expected_files = list(dict.fromkeys(target_files + expected_files))
    if not expected_files:
        expected_files = _infer_frontend_entry_files(task_title, payload["goal"], description)
    if expected_files:
        payload["expected_files"] = expected_files
    if related_files:
        payload["related_files"] = related_files
    return payload


def _expected_files_from_text(*values: str | None) -> list[str]:
    return _normalized_paths(
        [
            match
            for value in values
            if value
            for match in PATH_HINT_PATTERN.findall(value)
        ],
        from_text=True,
    )


def _infer_frontend_entry_files(*values: str | None) -> list[str]:
    text = " ".join(value.strip().lower() for value in values if isinstance(value, str) and value.strip())
    if not text:
        return []
    if any(_text_has_keyword(text, keyword) for keyword in FRONTEND_KEYWORDS) and not any(
        _text_has_keyword(text, keyword) for keyword in BACKEND_KEYWORDS
    ):
        return ["index.html"]
    return []


def _text_has_keyword(text: str, keyword: str) -> bool:
    candidate = str(keyword or "").strip().lower()
    if not text or not candidate:
        return False
    return re.search(rf"\b{re.escape(candidate)}\b", text) is not None


def _architecture_packages(task_payload: dict[str, Any]) -> list[str]:
    architecture = task_payload.get("architecture_profile")
    if not isinstance(architecture, dict):
        return []
    packages = architecture.get("packages")
    if not isinstance(packages, list):
        return []
    return [str(item).strip().strip("/") for item in packages if isinstance(item, str) and item.strip()]


def _project_intent(task_payload: dict[str, Any]) -> dict[str, Any]:
    value = task_payload.get("project_intent")
    return value if isinstance(value, dict) else {}


def _infer_frontend_root(task_payload: dict[str, Any]) -> str:
    intent = _project_intent(task_payload)
    explicit = str(intent.get("frontend_root") or "").strip().lstrip("./")
    if explicit:
        return explicit
    frontend_stack = str(intent.get("frontend_stack") or "").strip().lower()
    if frontend_stack:
        if str(intent.get("repo_layout") or "").strip().lower() == "monorepo":
            return "apps/web"
        if any(token in frontend_stack for token in ("next", "nuxt", "react", "vue")):
            return "web"
    packages = _architecture_packages(task_payload)
    if not packages:
        layout = str(intent.get("repo_layout") or "").strip().lower()
        return "apps/web" if layout == "monorepo" else ""
    normalized = [value.lstrip("./") for value in packages]
    ranked = sorted(
        normalized,
        key=lambda value: (
            0 if value.startswith("apps/web") else 1,
            0 if any(hint in value.lower() for hint in FRONTEND_PACKAGE_HINTS) else 1,
            len(value),
        ),
    )
    candidate = ranked[0]
    if any(hint in candidate.lower() for hint in FRONTEND_PACKAGE_HINTS):
        return candidate
    return ""


def _component_driven_frontend_scope(task_payload: dict[str, Any], *, frontend_root: str) -> list[str]:
    text = " ".join(
        value.strip().lower()
        for value in (
            task_payload.get("task_title"),
            task_payload.get("goal"),
            task_payload.get("task_description"),
        )
        if isinstance(value, str) and value.strip()
    )
    if not frontend_root:
        return ["index.html"]
    component_path = "components/landing/CTASection.vue"
    page_path = "pages/LandingPage.vue"
    if "hero" in text:
        component_path = "components/landing/HeroSection.vue"
    elif "pricing" in text:
        component_path = "components/landing/PricingSection.vue"
    elif "testimonial" in text:
        component_path = "components/landing/TestimonialsSection.vue"
    elif "lead capture form" in text or ("lead" in text and "form" in text):
        component_path = "components/forms/LeadCaptureForm.vue"
    elif "cta" in text:
        component_path = "components/landing/CTASection.vue"
    elif "dashboard" in text or "admin" in text:
        component_path = "pages/AdminDashboard.vue"
        page_path = "pages/AdminDashboard.vue"
    if frontend_root.startswith("apps/") or frontend_root.startswith("packages/"):
        base = PurePosixPath(frontend_root) / "src"
        scope = [
            str(base / page_path),
            str(base / "styles" / "landing.css"),
            str(PurePosixPath(frontend_root) / "index.html"),
        ]
        scope.insert(1, str(base / component_path))
        return list(dict.fromkeys(scope))
    return ["index.html"]


def _canonicalize_frontend_scoped_paths(paths: list[str], *, frontend_root: str) -> list[str]:
    if not frontend_root:
        return list(dict.fromkeys(paths))
    base_src = str(PurePosixPath(frontend_root) / "src")
    base_root = str(PurePosixPath(frontend_root))
    canonical: list[str] = []
    for raw in paths:
        path = str(PurePosixPath(raw or ""))
        if not path:
            continue
        lower = path.lower()
        if path.startswith(base_src) or path.startswith(base_root + "/"):
            canonical.append(path)
            continue
        # Drop root-level frontend component/page files when monorepo root is known.
        if lower.endswith(".vue") or "/components/" in lower or "/pages/" in lower:
            continue
        canonical.append(path)
    return list(dict.fromkeys(canonical))


def _infer_backend_root(task_payload: dict[str, Any]) -> str:
    intent = _project_intent(task_payload)
    explicit = str(intent.get("backend_root") or "").strip().lstrip("./")
    if explicit:
        return explicit
    backend_stack = str(intent.get("backend_stack") or "").strip().lower()
    if backend_stack:
        if str(intent.get("repo_layout") or "").strip().lower() == "monorepo":
            return "apps/api"
        if any(token in backend_stack for token in ("fastapi", "django", "flask", "express", "nest", "rails")):
            return "api"
    packages = _architecture_packages(task_payload)
    if not packages:
        layout = str(intent.get("repo_layout") or "").strip().lower()
        return "apps/api" if layout == "monorepo" else ""
    normalized = [value.lstrip("./") for value in packages]
    ranked = sorted(
        normalized,
        key=lambda value: (
            0 if value.startswith("apps/api") else 1,
            0 if any(hint in value.lower() for hint in BACKEND_PACKAGE_HINTS) else 1,
            len(value),
        ),
    )
    candidate = ranked[0]
    if any(hint in candidate.lower() for hint in BACKEND_PACKAGE_HINTS):
        return candidate
    return ""


def _module_driven_backend_scope(task_payload: dict[str, Any], *, backend_root: str) -> list[str]:
    text = " ".join(
        value.strip().lower()
        for value in (
            task_payload.get("task_title"),
            task_payload.get("goal"),
            task_payload.get("task_description"),
        )
        if isinstance(value, str) and value.strip()
    )
    module_hint = "feature"
    module_map = (
        ("form submission", "form_submission"),
        ("lead submission", "lead_capture"),
        ("lead capture", "lead_capture"),
        ("utm", "utm_tracking"),
        ("analytics", "analytics_tracking"),
        ("crm", "crm_sync"),
        ("webhook", "webhook_retry"),
        ("auth", "auth_identity"),
        ("billing", "billing"),
        ("user", "user"),
        ("project", "project"),
    )
    for token, mapped in module_map:
        if token in text:
            module_hint = mapped
            break
    module = _safe_module_slug(module_hint)
    if backend_root.startswith("apps/"):
        base = PurePosixPath(backend_root)
        app_base = base / "app"
        return [
            str(app_base / "routes" / f"{module}.py"),
            str(app_base / "services" / f"{module}_service.py"),
            str(app_base / "repositories" / f"{module}_repository.py"),
            str(app_base / "schemas" / f"{module}_schema.py"),
            str(app_base / "main.py"),
        ]
    return ["app.py"]


def _infer_topology_zone(task_payload: dict[str, Any]) -> str:
    text = " ".join(
        value.strip().lower()
        for value in (
            task_payload.get("task_title"),
            task_payload.get("goal"),
            task_payload.get("task_description"),
        )
        if isinstance(value, str) and value.strip()
    )
    zone_map = {
        "hubspot": "crm_sync",
        "crm": "crm_sync",
        "auth": "auth",
        "billing": "billing",
        "payment": "billing",
        "analytics": "analytics",
        "notification": "notifications",
        "email": "notifications",
        "webhook": "integrations",
        "queue": "workers",
        "worker": "workers",
    }
    for token, zone in zone_map.items():
        if token in text:
            return zone
    return "core_api"


def _selected_backend_capabilities(task_payload: dict[str, Any]) -> list[str]:
    intent = _project_intent(task_payload)
    raw = intent.get("capabilities")
    if not isinstance(raw, list):
        return list(DEFAULT_BACKEND_CAPABILITIES)
    selected: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        normalized = item.strip().lower()
        if not normalized:
            continue
        mapped = INTENT_CAPABILITY_MAP.get(normalized, _safe_module_slug(normalized))
        selected.append(mapped)
    selected = list(dict.fromkeys(selected))
    return selected[:6] or list(DEFAULT_BACKEND_CAPABILITIES)


def _infer_test_files(expected_files: list[str]) -> list[str]:
    tests: list[str] = []
    for value in expected_files:
        path = PurePosixPath(value)
        name = path.name
        if name.startswith("test_") and path.suffix == ".py":
            tests.append(str(path))
            continue
        if path.suffix == ".py":
            tests.append(str(path.with_name(f"test_{path.stem}.py")))
            continue
        if path.suffix in FRONTEND_SUFFIXES:
            tests.append(str(path.with_name(f"test_{name.replace('.', '_')}.py")))
    return list(dict.fromkeys(tests))


def _is_test_path(value: str) -> bool:
    path = PurePosixPath(value)
    name = path.name.lower()
    parts = [part.lower() for part in path.parts]
    return "tests" in parts or name.startswith("test_") or name.endswith("_test.py") or ".test." in name


def _change_surface(task_payload: dict[str, Any]) -> str:
    expected_files = [
        path for path in (task_payload.get("expected_files") or [])
        if isinstance(path, str) and path.strip()
    ]
    if expected_files:
        suffixes = {PurePosixPath(path).suffix.lower() for path in expected_files}
        if suffixes and suffixes.issubset(FRONTEND_SUFFIXES):
            return "frontend"
        if suffixes and suffixes.issubset(BACKEND_SUFFIXES):
            return "backend"

    text = " ".join(
        value.strip().lower()
        for value in (
            task_payload.get("task_title"),
            task_payload.get("goal"),
            task_payload.get("task_description"),
        )
        if isinstance(value, str) and value.strip()
    )
    if not text:
        return "mixed"
    has_frontend = any(_text_has_keyword(text, keyword) for keyword in FRONTEND_KEYWORDS)
    has_backend = any(_text_has_keyword(text, keyword) for keyword in BACKEND_KEYWORDS)
    if has_frontend and not has_backend:
        return "frontend"
    if has_backend and not has_frontend:
        return "backend"
    return "mixed"


def _default_scope_for_surface(surface: str) -> list[str]:
    if surface == "frontend":
        return ["index.html"]
    if surface == "backend":
        return ["app.py"]
    return ["index.html", "app.py"]


def _payload_for_stage(stage_name: str, task_payload: dict[str, Any]) -> dict:
    if not task_payload:
        return {"blocking": False} if stage_name == "WRITE_TESTS" else {}

    task_title = task_payload["task_title"]
    stage_titles = {
        "PLAN_DAG": task_title,
        "PLAN_BACKEND_TOPOLOGY": f"Plan backend topology for {task_title}",
        "CODE_BACKEND": f"Implement backend for {task_title}",
        "GENERATE_ROUTE": f"Generate route module for {task_title}",
        "GENERATE_SERVICE": f"Generate service module for {task_title}",
        "GENERATE_REPOSITORY": f"Generate repository module for {task_title}",
        "GENERATE_CAPABILITY_BINDING": f"Generate capability binding module for {task_title}",
        "CODE_FRONTEND": f"Implement frontend for {task_title}",
        "GENESIS_FOUNDATION": f"Establish frontend foundation for {task_title}",
        "FOUNDATION_VALIDATE": f"Validate foundation prerequisites for {task_title}",
        "FRAMEWORK_VALIDATE": f"Validate framework syntax for {task_title}",
        "WRITE_TESTS": f"Add tests for {task_title}",
        "REVIEW_DIFF": f"Review changes for {task_title}",
        "RUN_TESTS": f"Validate {task_title}",
        "PREVIEW_VALIDATE": f"Validate preview readiness for {task_title}",
        "REVIEW_INTEGRATION": f"Confirm integration for {task_title}",
    }
    payload = dict(task_payload)
    task_source = str(payload.get("task_source") or "").strip().lower()
    is_foundation = task_source in {"genesis", "genesis_setup"} or task_source.startswith("genesis.")
    stage_required = stage_name in {
        "PLAN_DAG",
        "PLAN_BACKEND_TOPOLOGY",
        *BACKEND_GENERATION_STAGES,
        "CODE_FRONTEND",
        "GENESIS_FOUNDATION",
        "FOUNDATION_VALIDATE",
        "FRAMEWORK_VALIDATE",
    }
    stage_criticality = "FOUNDATION" if is_foundation and stage_required else ("FEATURE" if stage_required else "OPTIONAL")
    payload["title"] = stage_titles.get(stage_name, task_title)
    payload["required"] = bool(stage_required)
    payload["criticality"] = stage_criticality
    scoped_files = [
        path for path in (payload.get("expected_files") or [])
        if isinstance(path, str) and path.strip()
    ]
    fallback_surface_scope = set(scoped_files).issubset({"index.html", "app.py"})
    if stage_name in {"GENESIS_FOUNDATION", "FOUNDATION_VALIDATE", "CODE_FRONTEND", "FRAMEWORK_VALIDATE"}:
        frontend_scoped = [
            path
            for path in scoped_files
            if PurePosixPath(path).suffix.lower() in FRONTEND_SUFFIXES and not _is_test_path(path)
        ]
        if fallback_surface_scope:
            frontend_scoped = []
        if not frontend_scoped:
            frontend_root = _infer_frontend_root(payload)
            frontend_scoped = _component_driven_frontend_scope(payload, frontend_root=frontend_root)
        if not frontend_scoped:
            frontend_scoped = _infer_frontend_entry_files(
                str(payload.get("task_title") or ""),
                str(payload.get("goal") or ""),
                str(payload.get("task_description") or ""),
            )
        if not frontend_scoped:
            frontend_scoped = ["index.html"]
        payload["expected_files"] = list(dict.fromkeys(frontend_scoped))
        payload["target_files"] = list(payload["expected_files"])
        payload["files"] = list(payload["expected_files"])
        payload["package_affinity"] = _infer_frontend_root(payload) or "frontend"
        payload["layer_affinity"] = "component"
        payload["topology_zone"] = _infer_topology_zone(payload)
        scoped_files = list(payload["expected_files"])
    if stage_name == "GENESIS_FOUNDATION":
        payload["expected_files"] = [
            "apps/web/src/App.vue",
            "apps/web/src/layouts/PageShell.vue",
            "apps/web/src/components/layout/Navbar.vue",
            "apps/web/src/components/layout/Footer.vue",
            "apps/web/src/components/layout/MobileNav.vue",
            "apps/web/src/components/ui/SectionContainer.vue",
            "apps/web/src/components/ui/ContentGrid.vue",
            "apps/web/src/components/ui/Stack.vue",
            "apps/web/src/components/ui/SectionHeading.vue",
            "apps/web/src/components/ui/PrimaryButton.vue",
            "apps/web/src/components/zones/HeroZone.vue",
            "apps/web/src/components/zones/FeatureZone.vue",
            "apps/web/src/components/zones/TestimonialsZone.vue",
            "apps/web/src/components/zones/CTAZone.vue",
            "apps/web/src/pages/LandingPage.vue",
            "runtime-contracts/component-manifest.json",
            "runtime-contracts/topology_hash.json",
        ]
        payload["target_files"] = list(payload["expected_files"])
        payload["files"] = list(payload["expected_files"])
        payload["package_affinity"] = _infer_frontend_root(payload) or "apps/web"
        payload["layer_affinity"] = "component"
        payload["topology_zone"] = "marketing_site"
        payload["task_source"] = str(payload.get("task_source") or "genesis_setup")
    if stage_name == "CODE_BACKEND":
        backend_scoped = [
            path
            for path in scoped_files
            if PurePosixPath(path).suffix.lower() in BACKEND_SUFFIXES and not _is_test_path(path)
        ]
        if fallback_surface_scope:
            backend_scoped = []
        if not backend_scoped:
            backend_root = _infer_backend_root(payload)
            backend_scoped = _module_driven_backend_scope(payload, backend_root=backend_root)
        if not backend_scoped:
            backend_scoped = ["app.py"]
        payload["expected_files"] = list(dict.fromkeys(backend_scoped))
        payload["target_files"] = list(payload["expected_files"])
        payload["files"] = list(payload["expected_files"])
        payload["package_affinity"] = _infer_backend_root(payload) or "backend"
        payload["layer_affinity"] = "service"
        payload["topology_zone"] = _infer_topology_zone(payload)
        scoped_files = list(payload["expected_files"])
    if stage_name in {"CODE_BACKEND", "CODE_FRONTEND", *BACKEND_GENERATION_STAGES} and scoped_files and not payload.get("target_files"):
        payload["target_files"] = list(scoped_files)
        payload["files"] = list(scoped_files)
    if stage_name in {"PLAN_BACKEND_TOPOLOGY", "CODE_BACKEND"}:
        topology_plan = _derive_backend_topology_plan(payload)
        if topology_plan:
            payload["backend_topology_plan"] = topology_plan
            planned_files = list(dict.fromkeys(topology_plan.get("planned_files") or []))
            if planned_files:
                payload["expected_files"] = planned_files
                if stage_name == "CODE_BACKEND":
                    payload["target_files"] = planned_files
                    payload["files"] = planned_files
    if stage_name in {"WRITE_TESTS", "RUN_TESTS"}:
        related_files = list(scoped_files)
        test_files = _infer_test_files(related_files)
        if test_files:
            payload["related_files"] = related_files
            payload["target_files"] = test_files
            payload["files"] = test_files
            payload["expected_files"] = test_files
    if stage_name in {"WRITE_TESTS", "RUN_TESTS", "PREVIEW_VALIDATE", "REVIEW_DIFF", "REVIEW_INTEGRATION"}:
        payload["blocking"] = False
    if stage_name in BACKEND_GENERATION_STAGES:
        topology = payload.get("backend_topology_plan") if isinstance(payload.get("backend_topology_plan"), dict) else {}
        key_to_paths = {
            "GENERATE_ROUTE": topology.get("routes") or [],
            "GENERATE_SERVICE": topology.get("services") or [],
            "GENERATE_REPOSITORY": topology.get("repositories") or [],
            "GENERATE_CAPABILITY_BINDING": topology.get("capability_modules") or [],
        }
        layer_affinity_map = {
            "GENERATE_ROUTE": "route",
            "GENERATE_SERVICE": "service",
            "GENERATE_REPOSITORY": "repository",
            "GENERATE_CAPABILITY_BINDING": "capability",
        }
        scoped = [path for path in key_to_paths.get(stage_name, []) if isinstance(path, str) and path.strip()]
        if not scoped:
            backend_root = _infer_backend_root(payload)
            derived_scope = _module_driven_backend_scope(payload, backend_root=backend_root)
            layer_hints = {
                "GENERATE_ROUTE": "/routes/",
                "GENERATE_SERVICE": "/services/",
                "GENERATE_REPOSITORY": "/repositories/",
                "GENERATE_CAPABILITY_BINDING": "/capabilities/",
            }
            scoped = [
                path for path in derived_scope
                if layer_hints.get(stage_name, "") in path
            ]
        if scoped:
            payload["target_files"] = scoped
            payload["files"] = scoped
            payload["expected_files"] = scoped
        payload["package_affinity"] = _infer_backend_root(payload) or "backend"
        payload["layer_affinity"] = layer_affinity_map.get(stage_name, "service")
        payload["topology_zone"] = _infer_topology_zone(payload)
    mutation_class = _mutation_class_for_stage(stage_name, payload, is_foundation=is_foundation)
    payload["mutation_class"] = mutation_class
    authority = _mutation_authority_contract(
        mutation_class=mutation_class,
        stage_name=stage_name,
        payload=payload,
    )
    payload.update(authority)
    if stage_name == "PREVIEW_VALIDATE":
        payload["visual_quality_gate"] = [
            "bounded_svg_icons",
            "responsive_layout",
            "max_width_containers",
            "spacing_rhythm",
            "typography_hierarchy",
            "no_overflow",
            "no_raw_unbounded_elements",
        ]
    return payload


def _mutation_class_for_stage(stage_name: str, payload: dict[str, Any], *, is_foundation: bool) -> str:
    if stage_name.startswith("FIX_"):
        return "RECOVERY"
    if stage_name in {"PLAN_DAG", "PLAN_BACKEND_TOPOLOGY", "FOUNDATION_VALIDATE", "FRAMEWORK_VALIDATE", "WRITE_TESTS", "REVIEW_DIFF", "RUN_TESTS", "PREVIEW_VALIDATE", "REVIEW_INTEGRATION"}:
        return "FEATURE"
    if stage_name == "GENESIS_FOUNDATION" or (stage_name == "CODE_FRONTEND" and is_foundation):
        return "FOUNDATION"
    if stage_name == "CODE_FRONTEND":
        text = " ".join(
            str(payload.get(key) or "").strip().lower()
            for key in ("task_title", "goal", "task_description", "title")
        )
        if any(hint in text for hint in POLISH_HINTS):
            has_explicit_feature_creation = any(
                hint in text for hint in {"add ", "create ", "new "}
            ) and any(hint in text for hint in {"section", "component"})
            if not has_explicit_feature_creation:
                return "POLISH"
        if any(hint in text for hint in FEATURE_CREATION_HINTS):
            return "FEATURE"
        return "FEATURE"
    if stage_name in {"CODE_BACKEND", *BACKEND_GENERATION_STAGES}:
        return "FEATURE"
    return "FEATURE"


def _mutation_authority_contract(*, mutation_class: str, stage_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    expected_files = [
        str(path).strip()
        for path in (payload.get("expected_files") or [])
        if isinstance(path, str) and str(path).strip()
    ]
    allowed_zones: list[str] = []
    text = " ".join(
        str(payload.get(key) or "").strip().lower()
        for key in ("task_title", "goal", "task_description", "title", "topology_zone")
    )
    for zone in LANDING_ZONES:
        if zone in text:
            allowed_zones.append(zone)
    if mutation_class == "FOUNDATION":
        allowed_zones = sorted(LANDING_ZONES)
    if mutation_class == "FEATURE" and not allowed_zones:
        allowed_zones = ["hero"]
    if mutation_class in {"POLISH", "RECOVERY"}:
        allowed_zones = sorted(set(allowed_zones) or LANDING_ZONES)

    base = {
        "allowed_operations": ["note", "apply_patch", "write_file"],
        "forbidden_operations": [],
        "allowed_files": list(dict.fromkeys(expected_files)),
        "protected_files": sorted(SHELL_INFRA_FILES),
        "allowed_zones": allowed_zones,
        "forbidden_zones": sorted(set(LANDING_ZONES) - set(allowed_zones)),
    }
    if mutation_class == "FOUNDATION":
        base["forbidden_operations"] = ["delete_file"]
        return base
    if mutation_class == "FEATURE":
        base["forbidden_operations"] = ["delete_file", "rewrite_shell", "replace_landing_page"]
        base["zone_composer_required"] = True
        base["zone_markers"] = [f"<!-- zone:{zone}:start --> ... <!-- zone:{zone}:end -->" for zone in allowed_zones]
        return base
    if mutation_class == "POLISH":
        base["forbidden_operations"] = ["delete_file", "rewrite_shell", "replace_landing_page", "create_unrelated_pages"]
        base["allowed_operations"] = ["note", "apply_patch"]
        base["zone_composer_required"] = True
        base["style_only_mutation"] = True
        return base
    if mutation_class == "RECOVERY":
        base["forbidden_operations"] = ["delete_file", "rewrite_shell", "replace_landing_page", "mutate_architecture"]
        base["allowed_operations"] = ["note", "apply_patch"]
        base["zone_composer_required"] = True
        base["repair_only"] = True
        return base
    return base


def _safe_module_slug(value: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return token or "feature"


def _derive_backend_topology_plan(task_payload: dict[str, Any]) -> dict[str, Any]:
    expected = [
        path for path in (task_payload.get("expected_files") or [])
        if isinstance(path, str) and path.strip() and PurePosixPath(path).suffix.lower() in BACKEND_SUFFIXES
    ]
    if not expected:
        return {}
    first = PurePosixPath(expected[0])
    if first.suffix.lower() != ".py":
        return {}
    # Keep generated modules adjacent to the scoped backend file so the planner is deterministic.
    base_dir = first.parent if str(first.parent) not in {"", "."} else PurePosixPath("apps/api/app")
    stem = _safe_module_slug(first.stem)
    routes_file = str(base_dir / "routes" / f"{stem}.py")
    service_file = str(base_dir / "services" / f"{stem}_service.py")
    repository_file = str(base_dir / "repositories" / f"{stem}_repository.py")
    schema_file = str(base_dir / "schemas" / f"{stem}_schema.py")
    selected_capabilities = _selected_backend_capabilities(task_payload)
    capability_files = [
        str(base_dir / "capabilities" / f"{cap}_binding.py")
        for cap in selected_capabilities[: max(1, min(4, len(selected_capabilities)))]
    ]
    planned_files = [routes_file, service_file, repository_file, schema_file, *capability_files]
    capability_bindings = {cap: "runtime_resolver" for cap in selected_capabilities}
    dependency_graph = {
        "route_to_service": {routes_file: [service_file]},
        "service_to_repository": {service_file: [repository_file]},
        "service_to_capabilities": {service_file: selected_capabilities},
    }
    composition_contract = {
        "routes_allowed": ["request_validation", "auth_enforcement", "service_delegation", "response_formatting"],
        "routes_blocked": ["db_logic", "capability_resolution", "retry_logic", "business_orchestration"],
        "services_allowed": ["business_orchestration", "capability_usage", "repository_delegation", "retry_logic"],
        "repositories_allowed": ["persistence_only"],
        "repositories_blocked": ["route_handlers", "capability_resolution", "business_orchestration"],
        "capability_modules_allowed": ["external_integrations_only", "provider_adapter_calls", "payload_mapping"],
        "capability_modules_blocked": ["route_handlers", "direct_db_access", "business_orchestration"],
    }
    return {
        "planner_stage": "PLAN_BACKEND_TOPOLOGY_V1",
        "module": stem,
        "planned_files": planned_files,
        "routes": [routes_file],
        "services": [service_file],
        "repositories": [repository_file],
        "capability_modules": capability_files,
        "schemas": [schema_file],
        "allowed_capabilities": selected_capabilities,
        "capability_bindings": capability_bindings,
        "dependency_graph": dependency_graph,
        "composition_contract": composition_contract,
    }


def _package_scope_matches(path: str, package_affinity: str) -> bool:
    normalized_path = str(PurePosixPath(path or ""))
    normalized_package = str(PurePosixPath(package_affinity or ""))
    if not normalized_package:
        return True
    return normalized_path == normalized_package or normalized_path.startswith(f"{normalized_package}/")


def _layer_matches(path: str, layer_affinity: str) -> bool:
    normalized_path = str(PurePosixPath(path or "")).lower()
    layer = str(layer_affinity or "").strip().lower()
    if not layer:
        return True
    if layer == "component":
        return any(token in normalized_path for token in ("/components/", "/sections/", "/pages/"))
    if layer == "route":
        return "/routes/" in normalized_path
    if layer == "service":
        return "/services/" in normalized_path
    if layer == "repository":
        return "/repositories/" in normalized_path
    if layer == "capability":
        return "/capabilities/" in normalized_path
    return True


def _targeting_terms(task_payload: dict[str, Any]) -> set[str]:
    text = " ".join(
        value.strip().lower()
        for value in (
            task_payload.get("task_title"),
            task_payload.get("goal"),
            task_payload.get("task_description"),
            task_payload.get("topology_zone"),
        )
        if isinstance(value, str) and value.strip()
    )
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text)
        if len(token) >= 3
    }


def _path_identity_terms(path: str) -> set[str]:
    pure = PurePosixPath(path or "")
    stem = pure.stem
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", stem).lower()
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", raw)
        if token and len(token) >= 2
    }
    aliases: set[str] = set(tokens)
    if {"cta", "section"}.issubset(tokens):
        aliases.add("cta")
    if {"hero", "section"}.issubset(tokens):
        aliases.add("hero")
    if {"pricing", "section"}.issubset(tokens):
        aliases.add("pricing")
    if {"testimonials", "section"}.issubset(tokens):
        aliases.add("testimonials")
    if {"lead", "capture", "form"}.issubset(tokens):
        aliases.update({"lead", "capture", "form"})
    if {"utm", "tracking", "service"}.issubset(tokens):
        aliases.update({"utm", "tracking"})
    if {"form", "submission", "service"}.issubset(tokens):
        aliases.update({"form", "submission"})
    return aliases


async def _enrich_payload_with_repo_targeting(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    tenant_id: uuid.UUID,
    stage_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.models import RepoEdge, RepoFile

    if stage_name not in {"CODE_FRONTEND", "CODE_BACKEND", *BACKEND_GENERATION_STAGES}:
        return payload
    package_affinity = str(payload.get("package_affinity") or "").strip()
    layer_affinity = str(payload.get("layer_affinity") or "").strip()
    existing_targets = [
        str(path).strip()
        for path in (payload.get("target_files") or [])
        if isinstance(path, str) and str(path).strip()
    ]
    if not package_affinity:
        return payload

    repo_files = (
        await session.execute(
            select(RepoFile).where(
                RepoFile.project_id == project_id,
                RepoFile.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    if not repo_files:
        payload["targeting_strategy"] = "architecture_affinity_fallback"
        payload["targeting_evidence"] = {
            "package_affinity": package_affinity,
            "layer_affinity": layer_affinity or None,
            "topology_zone": payload.get("topology_zone"),
            "neighbor_files": [],
            "repo_index_used": False,
        }
        return payload

    candidate_rows = [
        row for row in repo_files
        if _package_scope_matches(row.path, package_affinity) and _layer_matches(row.path, layer_affinity)
    ]
    if not candidate_rows:
        payload["targeting_strategy"] = "architecture_affinity_fallback"
        payload["targeting_evidence"] = {
            "package_affinity": package_affinity,
            "layer_affinity": layer_affinity or None,
            "topology_zone": payload.get("topology_zone"),
            "neighbor_files": [],
            "repo_index_used": True,
        }
        return payload

    edge_rows = (
        await session.execute(
            select(RepoEdge.source_file_id, RepoEdge.target_file_id).where(
                RepoEdge.project_id == project_id,
                RepoEdge.tenant_id == tenant_id,
            )
        )
    ).all()
    adjacency: dict[uuid.UUID, set[uuid.UUID]] = {}
    for src_id, dst_id in edge_rows:
        adjacency.setdefault(src_id, set()).add(dst_id)
        adjacency.setdefault(dst_id, set()).add(src_id)
    file_by_id = {row.id: row for row in repo_files}
    terms = _targeting_terms(payload)
    path_targets = {str(PurePosixPath(path)).lower() for path in existing_targets}
    scored: list[tuple[int, list[str], RepoFile]] = []
    for row in candidate_rows:
        score = 0
        reasons: list[str] = []
        normalized = row.path.lower()
        identity_terms = _path_identity_terms(row.path)
        if normalized in path_targets:
            score += 8
            reasons.append("explicit_scope")
        matched_terms = [term for term in terms if term in normalized or term in str(row.summary or "").lower()]
        if matched_terms:
            score += min(4, len(matched_terms))
            reasons.extend(f"semantic:{term}" for term in matched_terms[:3])
        exact_identity_terms = [term for term in terms if term in identity_terms]
        if exact_identity_terms:
            score += min(6, len(exact_identity_terms) * 2)
            reasons.extend(f"identity:{term}" for term in exact_identity_terms[:3])
        feature_terms = {
            str(item).strip().lower()
            for item in (row.features or [])
            if isinstance(item, str) and str(item).strip()
        }
        zone = str(payload.get("topology_zone") or "").strip().lower()
        if zone and any(zone in feature or feature in zone for feature in feature_terms):
            score += 3
            reasons.append("topology_zone")
        if layer_affinity and _layer_matches(row.path, layer_affinity):
            score += 2
            reasons.append("layer_affinity")
        if stage_name == "CODE_FRONTEND":
            if any(token in normalized for token in ("/components/", "/sections/")):
                score += 2
                reasons.append("component_shell_bias")
            elif "/pages/" in normalized:
                score -= 1
                reasons.append("page_shell_penalty")
        scored.append((score, list(dict.fromkeys(reasons)), row))
    scored.sort(key=lambda item: (item[0], item[2].path), reverse=True)
    positive_rows = [row for score, _reasons, row in scored if score > 0]
    if stage_name == "CODE_FRONTEND":
        preserve_page_shells = any(term in terms for term in {"dashboard", "admin"})
        if not preserve_page_shells:
            component_rows = [
                row for row in positive_rows
                if any(token in row.path.lower() for token in ("/components/", "/sections/"))
            ]
            if component_rows:
                positive_rows = component_rows
    reused = positive_rows[:2]
    if not reused:
        reused = [scored[0][2]]
    reason_map = {
        row.path: reasons
        for score, reasons, row in scored
    }

    neighbor_paths: list[str] = []
    if stage_name == "CODE_FRONTEND":
        for row in reused[:1]:
            for neighbor_id in adjacency.get(row.id, set()):
                neighbor = file_by_id.get(neighbor_id)
                if neighbor is None:
                    continue
                if not _package_scope_matches(neighbor.path, package_affinity):
                    continue
                if any(token in neighbor.path.lower() for token in ("/pages/", "/layouts/")):
                    neighbor_paths.append(neighbor.path)
        if neighbor_paths:
            payload["related_files"] = list(dict.fromkeys([*neighbor_paths, *(payload.get("related_files") or [])]))

    matching_existing_targets = [
        path for path in existing_targets
        if _package_scope_matches(path, package_affinity) and _layer_matches(path, layer_affinity)
    ]
    selected_paths = list(dict.fromkeys([row.path for row in reused] + matching_existing_targets))
    if stage_name == "CODE_FRONTEND":
        selected_paths = _canonicalize_frontend_scoped_paths(
            selected_paths,
            frontend_root=package_affinity or "",
        )
        if not selected_paths:
            selected_paths = _component_driven_frontend_scope(payload, frontend_root=package_affinity or "")
    payload["target_files"] = selected_paths
    payload["files"] = list(selected_paths)
    payload["expected_files"] = list(dict.fromkeys(selected_paths + [*payload.get("expected_files", [])]))
    payload["targeting_strategy"] = "repo_graph_neighbor_expansion" if neighbor_paths else "repo_index_reuse"
    payload["targeting_evidence"] = {
        "package_affinity": package_affinity,
        "layer_affinity": layer_affinity or None,
        "topology_zone": payload.get("topology_zone"),
        "selected_existing_files": [row.path for row in reused],
        "selected_existing_reason_map": {row.path: reason_map.get(row.path, []) for row in reused},
        "top_ranked_candidates": [
            {
                "path": row.path,
                "score": score,
                "reasons": reasons,
            }
            for score, reasons, row in scored[:5]
        ],
        "neighbor_files": list(dict.fromkeys(neighbor_paths)),
        "repo_index_used": True,
    }
    if stage_name == "CODE_FRONTEND":
        payload["component_reuse_preferred"] = True
    if stage_name in {"CODE_BACKEND", *BACKEND_GENERATION_STAGES}:
        payload["module_reuse_preferred"] = True
    return payload


async def generate_template_dag(
    session: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    executor: str = "dummy",
    tenant_id: uuid.UUID | None = None,
    run_summary: dict | None = None,
) -> int:
    """Generate a small deterministic DAG for the run if none exists."""
    from sqlalchemy import select

    count = await session.scalar(select(WorkItem.id).where(WorkItem.run_id == run_id).limit(1))
    if count:
        return 0

    task_payload = _task_payload_from_summary(run_summary)
    surface = _change_surface(task_payload)
    if task_payload.get("task_id") and not task_payload.get("expected_files"):
        fallback_scope = _default_scope_for_surface(surface)
        task_payload["expected_files"] = fallback_scope
        log.warning(
            "Task-scoped run missing explicit file scope; applying fallback task_id=%s scope=%s",
            task_payload.get("task_id"),
            fallback_scope,
        )

    nodes = [("PLAN_DAG", "plan")]
    task_source = str(task_payload.get("task_source") or "").strip().lower()
    repository_state = str(task_payload.get("repository_state") or "").strip().upper()
    needs_genesis_foundation = surface != "backend" and (
        task_source in {"genesis", "genesis_setup", "foundation_setup", "base_task"}
        or task_source.startswith("genesis.")
        or repository_state in {"GENESIS", "EARLY_BUILD"}
    )
    if surface != "frontend":
        nodes.append(("PLAN_BACKEND_TOPOLOGY", "plan_backend_topology"))
        nodes.append(("GENERATE_ROUTE", "code"))
        nodes.append(("GENERATE_SERVICE", "code"))
        nodes.append(("GENERATE_REPOSITORY", "code"))
        nodes.append(("GENERATE_CAPABILITY_BINDING", "code"))
    if surface != "backend":
        if needs_genesis_foundation:
            nodes.append(("GENESIS_FOUNDATION", "test_run"))
        nodes.append(("FOUNDATION_VALIDATE", "test_run"))
        nodes.append(("CODE_FRONTEND", "code"))
    nodes.extend(
        [
            ("FRAMEWORK_VALIDATE", "test_run"),
            ("WRITE_TESTS", "test"),
            ("REVIEW_DIFF", "review"),
            ("RUN_TESTS", "test_run"),
            ("PREVIEW_VALIDATE", "test_run"),
            ("REVIEW_INTEGRATION", "review"),
        ]
    )
    default_caps = {
        "plan": ["plan"],
        # Keep topology planning executable by standard worker profiles.
        "plan_backend_topology": ["plan"],
        "code": ["code"],
        "test": ["test"],
        "test_run": ["test"],
        "review": ["review"],
        "fix_test_failure": ["code"],
    }

    created: List[WorkItem] = []
    for idx, (stage_name, capability_key) in enumerate(nodes):
        exec_name = executor
        if stage_name in {"GENESIS_FOUNDATION", "FOUNDATION_VALIDATE", "FRAMEWORK_VALIDATE", "RUN_TESTS", "PREVIEW_VALIDATE"} and executor not in {"dummy", "test"}:
            exec_name = "test"
        stage_payload = _payload_for_stage(stage_name, task_payload)
        stage_payload = await _enrich_payload_with_repo_targeting(
            session,
            project_id=project_id,
            tenant_id=tenant_id or uuid.UUID(int=0),
            stage_name=stage_name,
            payload=stage_payload,
        )
        wi = WorkItem(
            project_id=project_id,
            tenant_id=tenant_id or uuid.UUID(int=0),
            run_id=run_id,
            type=stage_name,
            key=stage_name,
            priority=10 - idx,
            executor=exec_name,
            required_capabilities=default_caps.get(capability_key, []),
            payload=stage_payload,
        )
        session.add(wi)
        created.append(wi)
    await session.flush()
    for wi in created:
        await link_run_to_work_item(session, wi)

    # edges
    key_to_id = {wi.key: wi.id for wi in created}
    edges: list[tuple[str, str]] = []
    code_nodes = [stage for stage in ("CODE_BACKEND", "GENESIS_FOUNDATION", "CODE_FRONTEND", *BACKEND_GENERATION_STAGES) if stage in key_to_id]
    for code_stage in code_nodes:
        if code_stage in BACKEND_GENERATION_STAGES and "PLAN_BACKEND_TOPOLOGY" in key_to_id:
            edges.append(("PLAN_DAG", "PLAN_BACKEND_TOPOLOGY"))
            if code_stage == "GENERATE_ROUTE":
                edges.append(("PLAN_BACKEND_TOPOLOGY", "GENERATE_ROUTE"))
            elif code_stage == "GENERATE_SERVICE":
                edges.append(("GENERATE_ROUTE", "GENERATE_SERVICE"))
            elif code_stage == "GENERATE_REPOSITORY":
                edges.append(("GENERATE_SERVICE", "GENERATE_REPOSITORY"))
            elif code_stage == "GENERATE_CAPABILITY_BINDING":
                edges.append(("GENERATE_REPOSITORY", "GENERATE_CAPABILITY_BINDING"))
        else:
            edges.append(("PLAN_DAG", code_stage))
        if code_stage == "GENESIS_FOUNDATION" and "CODE_FRONTEND" in key_to_id:
            if "FOUNDATION_VALIDATE" in key_to_id:
                edges.append(("GENESIS_FOUNDATION", "FOUNDATION_VALIDATE"))
            else:
                edges.append(("GENESIS_FOUNDATION", "CODE_FRONTEND"))
        if code_stage == "CODE_FRONTEND" and "FOUNDATION_VALIDATE" in key_to_id:
            edges.append(("FOUNDATION_VALIDATE", "CODE_FRONTEND"))
        edges.append((code_stage, "FRAMEWORK_VALIDATE"))
    if "FOUNDATION_VALIDATE" in key_to_id:
        edges.append(("PLAN_DAG", "FOUNDATION_VALIDATE"))
    if not code_nodes:
        edges.append(("PLAN_DAG", "FRAMEWORK_VALIDATE"))
    edges.extend(
        [
            ("FRAMEWORK_VALIDATE", "WRITE_TESTS"),
            ("WRITE_TESTS", "REVIEW_DIFF"),
            ("REVIEW_DIFF", "RUN_TESTS"),
            ("RUN_TESTS", "PREVIEW_VALIDATE"),
            ("PREVIEW_VALIDATE", "REVIEW_INTEGRATION"),
        ]
    )
    dependents_count: dict[uuid.UUID, int] = {}
    for src, dst in edges:
        session.add(
            WorkItemEdge(
                tenant_id=tenant_id or uuid.UUID(int=0),
                run_id=run_id,
                from_work_item_id=key_to_id[src],
                to_work_item_id=key_to_id[dst],
            )
        )
        dependents_count[key_to_id[dst]] = dependents_count.get(key_to_id[dst], 0) + 1
    # Update depends_on_count
    for wi in created:
        wi.depends_on_count = dependents_count.get(wi.id, 0)
        session.add(wi)
    await session.flush()
    log.info(
        "Generated work DAG run_id=%s project_id=%s task_id=%s work_item_count=%s",
        run_id,
        project_id,
        task_payload.get("task_id"),
        len(created),
    )
    return len(created)
