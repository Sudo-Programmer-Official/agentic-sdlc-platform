const DEFAULT_API_BASE = import.meta.env.DEV
  ? "http://localhost:8000/api/v1"
  : "https://api.prompt2pr.com/api/v1";

const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;

async function handle<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let payload: any = null;
    try {
      payload = await resp.json();
    } catch {
      payload = null;
    }

    const detail = payload?.detail;
    if (typeof detail === "string" && detail) {
      throw new Error(detail);
    }
    if (Array.isArray(detail) && detail.length) {
      throw new Error(detail.map((item) => item?.msg || JSON.stringify(item)).join(", "));
    }
    if (payload?.error) {
      throw new Error(payload.error_id ? `${payload.error} (${payload.error_id})` : payload.error);
    }

    const msg = await resp.text().catch(() => "");
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
