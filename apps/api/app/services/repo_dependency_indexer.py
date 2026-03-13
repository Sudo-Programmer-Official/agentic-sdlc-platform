from __future__ import annotations

import re
from pathlib import Path, PurePosixPath


_IMPORT_RE = re.compile(r"""import\s+[^'"]*['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)""")
_PY_IMPORT_RE = re.compile(r"^\s*(?:from\s+([A-Za-z0-9_\.]+)\s+import|import\s+([A-Za-z0-9_\.]+))", re.MULTILINE)
_IGNORED_PY_MODULES = ("typing", "pathlib", "datetime", "sqlalchemy", "fastapi", "pydantic", "pytest")


def resolve_python_import(repo_root: Path, module: str) -> str | None:
    candidate = (repo_root / module.replace(".", "/")).resolve()
    py_file = candidate.with_suffix(".py")
    if py_file.exists() and py_file.is_file():
        return py_file.relative_to(repo_root).as_posix()
    init_file = candidate / "__init__.py"
    if init_file.exists() and init_file.is_file():
        return init_file.relative_to(repo_root).as_posix()
    return None


def resolve_relative_import(repo_root: Path, source_path: PurePosixPath, target: str) -> str | None:
    source_dir = (repo_root / source_path).parent
    candidate = (source_dir / target).resolve()
    if not str(candidate).startswith(str(repo_root)):
        return None
    suffixes = ["", ".ts", ".tsx", ".js", ".jsx", ".vue", ".py", ".json"]
    for suffix in suffixes:
        direct = candidate if suffix == "" else candidate.with_suffix(suffix)
        if direct.exists() and direct.is_file():
            return direct.relative_to(repo_root).as_posix()
    for index_name in ("index.ts", "index.tsx", "index.js", "index.jsx", "index.vue", "__init__.py"):
        indexed = candidate / index_name
        if indexed.exists() and indexed.is_file():
            return indexed.relative_to(repo_root).as_posix()
    return None


def extract_import_targets(repo_root: Path, relative_path: PurePosixPath, text: str) -> list[str]:
    imports: list[str] = []
    seen: set[str] = set()
    for match in _IMPORT_RE.finditer(text):
        target = match.group(1) or match.group(2)
        if not target:
            continue
        if target.startswith("."):
            resolved = resolve_relative_import(repo_root, relative_path, target)
            if resolved and resolved not in seen:
                seen.add(resolved)
                imports.append(resolved)
    for match in _PY_IMPORT_RE.finditer(text):
        module = match.group(1) or match.group(2)
        if not module or module.startswith(_IGNORED_PY_MODULES):
            continue
        resolved = resolve_python_import(repo_root, module)
        if resolved and resolved not in seen:
            seen.add(resolved)
            imports.append(resolved)
    return imports
