from app.services.repo_intelligence_graph import classify_layer


def test_classify_layer_route_service_repository_capability():
    assert classify_layer("apps/api/app/routes/lead_capture.py", "api_module") == "ROUTE"
    assert classify_layer("apps/api/app/services/lead_capture_service.py", "service_module") == "SERVICE"
    assert classify_layer("apps/api/app/repositories/lead_capture_repository.py", "backend_module") == "REPOSITORY"
    assert classify_layer("apps/api/app/capabilities/crm_sync_binding.py", "backend_module") == "CAPABILITY"


def test_classify_layer_component_test_config_contract_defaults():
    assert classify_layer("apps/web/src/components/LeadForm.vue", "ui_component") == "COMPONENT"
    assert classify_layer("apps/api/tests/test_lead_capture.py", "test_file") == "TEST"
    assert classify_layer("apps/api/pyproject.toml", "config") == "CONFIG"
    assert classify_layer("apps/api/app/schemas/lead_capture_schema.py", "backend_module") == "CONTRACT"
    assert classify_layer("apps/api/app/domain/lead_capture.py", "backend_module") == "MODULE"
