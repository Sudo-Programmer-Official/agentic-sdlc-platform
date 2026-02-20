const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api/v1";

async function handle<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const msg = await resp.text();
    throw new Error(msg || `Request failed (${resp.status})`);
  }
  return resp.json() as Promise<T>;
}

export async function fetchGraph(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/requirements-graph`);
  return handle(resp);
}

export async function updateGraph(projectId: string, payload: any) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/requirements-graph`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return handle(resp);
}

export async function approveGraph(projectId: string, approvedBy = "ui-user") {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/requirements-graph/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved_by: approvedBy })
  });
  return handle(resp);
}

export async function ingestPrd(projectId: string, text: string, source = "typed", format = "markdown") {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/prd`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, source, format })
  });
  return handle(resp);
}

export async function fetchProjectSummary(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/summary`);
  return handle(resp);
}

export async function fetchPlanHistory(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/plan/history`);
  return handle(resp);
}
