from fastapi.testclient import TestClient

from app.main import create_app


def test_project_summary_with_planner_tasks():
    client = TestClient(create_app())

    create_resp = client.post("/api/v1/store/projects", json={"name": "Demo Project", "description": "Summary test"})
    assert create_resp.status_code == 201
    project = create_resp.json()
    project_id = project["id"]

    task_resp_1 = client.post(
        f"/api/v1/store/projects/{project_id}/tasks",
        json={"title": "task 1", "description": "summary task"},
    )
    assert task_resp_1.status_code == 201
    task_resp_2 = client.post(
        f"/api/v1/store/projects/{project_id}/tasks",
        json={"title": "task 2", "description": "summary task"},
    )
    assert task_resp_2.status_code == 201

    run_resp = client.post(f"/api/v1/store/projects/{project_id}/runs", json={"executor": "dummy"})
    assert run_resp.status_code == 201
    run_id = run_resp.json()["id"]

    summary_resp = client.get(f"/api/v1/store/projects/{project_id}/summary")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()

    assert summary["project_id"] == project_id
    assert summary["latest_run"]["run_id"] == run_id

    task_counts = summary["task_counts"]
    total_tasks = sum(task_counts.values())
    assert total_tasks > 0
    assert task_counts["pending"] > 0
