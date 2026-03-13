from __future__ import annotations

import ast
from pathlib import Path


FORBIDDEN_IMPORT_PREFIXES = {
    "app.operator",
    "app.services.run_memory",
    "app.services.run_comparison",
    "app.services.run_summary_builder",
    "app.services.strategy_planner",
    "app.services.strategy_selection",
    "app.services.repo_map",
    "app.services.run_timeline",
    "app.services.artifact_diff",
    "app.services.mission_control_overview",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _execution_plane_files() -> list[Path]:
    root = _project_root()
    runtime_files = sorted((root / "app" / "runtime").rglob("*.py"))
    service_files = [
        root / "app" / "services" / "workspace_supervisor.py",
    ]
    return [path for path in [*runtime_files, *service_files] if path.exists()]


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module
            if module:
                imports.add(module)
    return imports


def test_execution_plane_does_not_import_intelligence_services():
    offenders: list[str] = []
    for path in _execution_plane_files():
        imports = _imports_for(path)
        for module in imports:
            if any(module == forbidden or module.startswith(f"{forbidden}.") for forbidden in FORBIDDEN_IMPORT_PREFIXES):
                offenders.append(f"{path}: {module}")
    assert offenders == []
