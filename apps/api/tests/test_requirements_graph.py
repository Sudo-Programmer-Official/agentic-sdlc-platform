from fastapi.testclient import TestClient

from app.main import create_app


def _advance(client: TestClient, project_id: str, to_stage: str, expect: int = 200):
    resp = client.post(f"/api/v1/projects/{project_id}/advance", json={"to_stage": to_stage})
    assert resp.status_code == expect
    return resp


def _approve_stage(client: TestClient, project_id: str, stage: str):
    req = client.post(
        f"/api/v1/projects/{project_id}/approvals",
        json={"stage": stage, "requested_by": "tester"},
    )
    assert req.status_code == 200
    approval_id = req.json()["id"]
    decision = client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "APPROVED", "decided_by": "tester"},
    )
    assert decision.status_code == 200


def test_requirements_graph_flow_and_gating():
    client = TestClient(create_app())

    # 1) create project
    create_resp = client.post("/api/v1/projects", json={"name": "ReqProj", "description": "demo"})
    assert create_resp.status_code == 200
    project_id = create_resp.json()["id"]

    # 2) ingest PRD (stub extraction)
    prd_text = "Must allow login\nSystem should be secure and reliable"
    prd_resp = client.post(f"/api/v1/projects/{project_id}/prd", json={"text": prd_text})
    assert prd_resp.status_code == 200
    graph = prd_resp.json()
    assert graph["status"] == "DRAFT"
    assert len(graph["nodes"]) >= 2
    assert len(graph["edges"]) >= 1

    # 3) update graph draft
    nodes = graph["nodes"]
    nodes[0]["text"] = "Must allow SSO login"
    update_resp = client.put(
        f"/api/v1/projects/{project_id}/requirements-graph",
        json={"nodes": nodes, "edges": graph["edges"]},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] in ["DRAFT", "STALE"]

    # 4) approve graph
    approve_resp = client.post(
        f"/api/v1/projects/{project_id}/requirements-graph/approve",
        json={"approved_by": "tester"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "APPROVED"

    # 5) advance to REQUIREMENTS_DRAFTED then APPROVED (approval gate)
    _advance(client, project_id, "REQUIREMENTS_DRAFTED")
    _approve_stage(client, project_id, "REQUIREMENTS_DRAFTED")
    _advance(client, project_id, "REQUIREMENTS_APPROVED")

    # 6) update after approval -> stale
    graph_after = client.get(f"/api/v1/projects/{project_id}/requirements-graph").json()
    graph_after["nodes"][0]["text"] = "Must allow passwordless login"
    stale_resp = client.put(
        f"/api/v1/projects/{project_id}/requirements-graph",
        json={"nodes": graph_after["nodes"], "edges": graph_after["edges"]},
    )
    assert stale_resp.status_code == 200
    assert stale_resp.json()["status"] == "STALE"

    # 7) advancing to DESIGN_DRAFTED should be blocked (stale requirements)
    _advance(client, project_id, "DESIGN_DRAFTED", expect=409)
