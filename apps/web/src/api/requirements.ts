import { isApiErrorStatus, parseApiResponse } from "./http";

const DEFAULT_API_BASE = import.meta.env.DEV
  ? "http://localhost:8000/api/v1"
  : "https://api.prompt2pr.com/api/v1";

const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;

export function createEmptyRequirementsGraph() {
  return {
    status: "DRAFT",
    version: null,
    nodes: [],
    edges: [],
  };
}

export async function fetchGraph(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/requirements-graph`);
  try {
    return await parseApiResponse(resp);
  } catch (err) {
    if (isApiErrorStatus(err, 404)) return createEmptyRequirementsGraph();
    throw err;
  }
}

export async function updateGraph(projectId: string, payload: any) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/requirements-graph`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return parseApiResponse(resp);
}

export async function approveGraph(projectId: string, approvedBy = "ui-user") {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/requirements-graph/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved_by: approvedBy })
  });
  return parseApiResponse(resp);
}

export async function ingestPrd(projectId: string, text: string, source = "typed", format = "markdown") {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/prd`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, source, format })
  });
  return parseApiResponse(resp);
}

export async function fetchProjectSummary(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/summary`);
  return parseApiResponse(resp);
}

export async function fetchPlanHistory(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/plan/history`);
  return parseApiResponse(resp);
}
