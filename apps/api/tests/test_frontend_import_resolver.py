from pathlib import Path

from app.runtime.frontend_import_resolver import (
    normalize_frontend_imports,
    resolve_frontend_component_import,
)


def _seed_repo(tmp_path: Path) -> Path:
    (tmp_path / "apps/web/src/components/ui").mkdir(parents=True, exist_ok=True)
    (tmp_path / "apps/web/src/pages").mkdir(parents=True, exist_ok=True)
    (tmp_path / "apps/web/src/components/ui/Button.vue").write_text("<template><button /></template>\n", encoding="utf-8")
    (tmp_path / "apps/web/src/components/ui/SectionContainer.vue").write_text("<template><section /></template>\n", encoding="utf-8")
    return tmp_path


def test_resolve_frontend_component_import_repairs_invalid_relative_path(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    resolved = resolve_frontend_component_import(
        repo_root=repo,
        component_name="PrimaryButton",
        importing_file="apps/web/src/pages/LandingPage.vue",
    )
    assert resolved == "../components/ui/Button.vue"


def test_alias_resolves_to_canonical_primitive(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    resolved = resolve_frontend_component_import(
        repo_root=repo,
        component_name="CTAButton",
        importing_file="apps/web/src/pages/LandingPage.vue",
    )
    assert resolved == "../components/ui/Button.vue"


def test_normalize_frontend_imports_rewrites_wrong_path_and_is_idempotent(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    content = (
        "<template>\n"
        "  <main><PrimaryButton /></main>\n"
        "</template>\n"
        "<script setup>\n"
        "import PrimaryButton from \"../../components/PrimaryButton.vue\";\n"
        "</script>\n"
    )
    first = normalize_frontend_imports(
        repo_root=repo,
        importing_file="apps/web/src/pages/LandingPage.vue",
        content=content,
    )
    assert "../components/ui/Button.vue" in first.content
    assert first.import_normalization_repairs >= 1
    second = normalize_frontend_imports(
        repo_root=repo,
        importing_file="apps/web/src/pages/LandingPage.vue",
        content=first.content,
    )
    assert second.import_normalization_repairs == 0


def test_normalize_frontend_imports_injects_missing_canonical_import(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    content = (
        "<template>\n"
        "  <main><SectionContainer /></main>\n"
        "</template>\n"
        "<script setup>\n"
        "const title = 'x'\n"
        "</script>\n"
    )
    out = normalize_frontend_imports(
        repo_root=repo,
        importing_file="apps/web/src/pages/LandingPage.vue",
        content=content,
    )
    assert 'import SectionContainer from "../components/ui/SectionContainer.vue";' in out.content
    assert "SectionContainer:../components/ui/SectionContainer.vue" in out.resolved_component_imports
