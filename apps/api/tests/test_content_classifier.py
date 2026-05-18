from app.services.content_registry import classify_change_request, normalize_environment


def test_classify_change_request_content_vs_structural():
    assert classify_change_request("Change pricing title to Enterprise Plus") == "CONTENT"
    assert classify_change_request("Add animated pricing comparison section") == "STRUCTURAL"
    assert classify_change_request("   ") == "UNKNOWN"


def test_normalize_environment():
    assert normalize_environment("preview") == "PREVIEW"
    assert normalize_environment("STAGING") == "STAGING"
