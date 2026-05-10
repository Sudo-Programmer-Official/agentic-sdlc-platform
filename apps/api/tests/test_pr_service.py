from app.services.pr_service import _sanitize_patch_for_pr


def test_sanitize_patch_for_pr_removes_pycache_binary_chunk():
    diff = (
        "diff --git a/__pycache__/test_index_html.cpython-312-pytest-9.0.2.pyc b/__pycache__/test_index_html.cpython-312-pytest-9.0.2.pyc\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "GIT binary patch\n"
        "literal 4\n"
        "Oc$@)A0000\n"
        "diff --git a/index.html b/index.html\n"
        "--- a/index.html\n"
        "+++ b/index.html\n"
        "@@ -1 +1 @@\n"
        "-<main>Old</main>\n"
        "+<main>New</main>\n"
    )

    sanitized, removed = _sanitize_patch_for_pr(diff)

    assert "__pycache__/test_index_html.cpython-312-pytest-9.0.2.pyc" in removed
    assert "GIT binary patch" not in sanitized
    assert "diff --git a/index.html b/index.html" in sanitized


def test_sanitize_patch_for_pr_empty_when_only_forbidden_files():
    diff = (
        "diff --git a/__pycache__/x.pyc b/__pycache__/x.pyc\n"
        "--- a/__pycache__/x.pyc\n"
        "+++ b/__pycache__/x.pyc\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )

    sanitized, removed = _sanitize_patch_for_pr(diff)

    assert sanitized.strip() == ""
    assert removed == ["__pycache__/x.pyc"]
