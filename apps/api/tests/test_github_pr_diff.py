from app.services.vcs.github_app import GitHubAppAdapter


def test_categorize_files():
    files = [
        {"filename": "a.txt", "status": "added"},
        {"filename": "b.txt", "status": "modified"},
        {"filename": "c.txt", "status": "removed"},
        {"filename": "d.txt", "status": "renamed"},
    ]
    result = GitHubAppAdapter._categorize_files(files)
    assert set(result["added"]) == {"a.txt"}
    assert set(result["modified"]) == {"b.txt", "d.txt"}
    assert set(result["removed"]) == {"c.txt"}
    assert set(result["all_files"]) == {"a.txt", "b.txt", "c.txt", "d.txt"}
