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
    if any(keyword in text for keyword in FRONTEND_KEYWORDS) and not any(keyword in text for keyword in BACKEND_KEYWORDS):
        return ["index.html"]
    return []


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
    has_frontend = any(keyword in text for keyword in FRONTEND_KEYWORDS)
    has_backend = any(keyword in text for keyword in BACKEND_KEYWORDS)
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


def _payload_for_stage(stage_name: str, task_payload: dict[str, str | list[str]]) -> dict:
    if not task_payload:
        return {"blocking": False} if stage_name == "WRITE_TESTS" else {}

    task_title = task_payload["task_title"]
    stage_titles = {
        "PLAN_DAG": task_title,
        "CODE_BACKEND": f"Implement backend for {task_title}",
        "CODE_FRONTEND": f"Implement frontend for {task_title}",
        "WRITE_TESTS": f"Add tests for {task_title}",
        "REVIEW_DIFF": f"Review changes for {task_title}",
        "RUN_TESTS": f"Validate {task_title}",
        "REVIEW_INTEGRATION": f"Confirm integration for {task_title}",
    }
    payload = dict(task_payload)
    task_source = str(payload.get("task_source") or "").strip().lower()
    is_foundation = task_source in {"genesis", "genesis_setup"} or task_source.startswith("genesis.")
    stage_required = stage_name in {"PLAN_DAG", "CODE_BACKEND", "CODE_FRONTEND", "RUN_TESTS"}
    stage_criticality = "FOUNDATION" if is_foundation and stage_required else ("FEATURE" if stage_required else "OPTIONAL")
    payload["title"] = stage_titles.get(stage_name, task_title)
    payload["required"] = bool(stage_required)
    payload["criticality"] = stage_criticality
    scoped_files = [
        path for path in (payload.get("expected_files") or [])
        if isinstance(path, str) and path.strip()
    ]
    if stage_name in {"CODE_BACKEND", "CODE_FRONTEND"} and scoped_files and not payload.get("target_files"):
        payload["target_files"] = list(scoped_files)
        payload["files"] = list(scoped_files)
    if stage_name in {"WRITE_TESTS", "RUN_TESTS"}:
        related_files = list(scoped_files)
        test_files = _infer_test_files(related_files)
        if test_files:
            payload["related_files"] = related_files
            payload["target_files"] = test_files
            payload["files"] = test_files
            payload["expected_files"] = test_files
    if stage_name == "WRITE_TESTS":
        payload["blocking"] = False
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
    if surface != "frontend":
        nodes.append(("CODE_BACKEND", "code"))
    if surface != "backend":
        nodes.append(("CODE_FRONTEND", "code"))
    nodes.extend(
        [
            ("WRITE_TESTS", "test"),
            ("REVIEW_DIFF", "review"),
            ("RUN_TESTS", "test_run"),
            ("REVIEW_INTEGRATION", "review"),
        ]
    )
    default_caps = {
        "plan": ["plan"],
        "code": ["code"],
        "test": ["test"],
        "test_run": ["test"],
        "review": ["review"],
        "fix_test_failure": ["code"],
    }

    created: List[WorkItem] = []
    for idx, (stage_name, capability_key) in enumerate(nodes):
        exec_name = executor
        if stage_name == "RUN_TESTS" and executor not in {"dummy", "test"}:
            exec_name = "test"
        wi = WorkItem(
            project_id=project_id,
            tenant_id=tenant_id or uuid.UUID(int=0),
            run_id=run_id,
            type=stage_name,
            key=stage_name,
            priority=10 - idx,
            executor=exec_name,
            required_capabilities=default_caps.get(capability_key, []),
            payload=_payload_for_stage(stage_name, task_payload),
        )
        session.add(wi)
        created.append(wi)
    await session.flush()
    for wi in created:
        await link_run_to_work_item(session, wi)

    # edges
    key_to_id = {wi.key: wi.id for wi in created}
    edges: list[tuple[str, str]] = []
    code_nodes = [stage for stage in ("CODE_BACKEND", "CODE_FRONTEND") if stage in key_to_id]
    for code_stage in code_nodes:
        edges.append(("PLAN_DAG", code_stage))
        edges.append((code_stage, "WRITE_TESTS"))
    if not code_nodes:
        edges.append(("PLAN_DAG", "WRITE_TESTS"))
    edges.extend(
        [
            ("WRITE_TESTS", "REVIEW_DIFF"),
            ("REVIEW_DIFF", "RUN_TESTS"),
            ("RUN_TESTS", "REVIEW_INTEGRATION"),
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
