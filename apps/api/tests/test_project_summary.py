from fastapi.testclient import TestClient

from app.main import create_app


def test_project_summary_with_planner_tasks():
    client = TestClient(create_app())

    create_resp = client.post(
        "/api/v1/projects",
        json={"name": "Demo Project", "description": "Summary test"},
    )
    assert create_resp.status_code == 200
    project = create_resp.json()
    project_id = project["id"]

    advance_resp = client.post(
        f"/api/v1/projects/{project_id}/advance",
        json={"to_stage": "REQUIREMENTS_DRAFTED"},
    )
    assert advance_resp.status_code == 200

    approval_resp = client.post(
        f"/api/v1/projects/{project_id}/approvals",
        json={"stage": "REQUIREMENTS_DRAFTED", "requested_by": "tester"},
    )
    assert approval_resp.status_code == 200
    approval_id = approval_resp.json()["id"]

    decision_resp = client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "APPROVED", "decided_by": "tester"},
    )
    assert decision_resp.status_code == 200

    advance_resp = client.post(
        f"/api/v1/projects/{project_id}/advance",
        json={"to_stage": "REQUIREMENTS_APPROVED"},
    )
    assert advance_resp.status_code == 200

    advance_resp = client.post(
        f"/api/v1/projects/{project_id}/advance",
        json={"to_stage": "DESIGN_DRAFTED"},
    )
    assert advance_resp.status_code == 200

    run_resp = client.post(f"/api/v1/projects/{project_id}/runs")
    assert run_resp.status_code == 200
    run_id = run_resp.json()["run_id"]

    start_resp = client.post(f"/api/v1/runs/{run_id}/start")
    assert start_resp.status_code == 200

    summary_resp = client.get(f"/api/v1/projects/{project_id}/summary")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()

    assert summary["project_id"] == project_id
    assert summary["latest_run"]["run_id"] == run_id

    task_counts = summary["task_counts"]
    total_tasks = sum(task_counts.values())
    assert total_tasks > 0
    assert task_counts["pending"] > 0
