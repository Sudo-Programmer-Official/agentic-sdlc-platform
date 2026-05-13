import { isApiErrorStatus, parseApiResponse } from "./http";

const DEFAULT_API_BASE = import.meta.env.DEV
  ? "http://localhost:8000/api/v1"
  : "https://api.prompt2pr.com/api/v1";

const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;

export function createEmptyRequirementsGraph(projectId = "") {
  const timestamp = new Date().toISOString();
  return {
    project_id: projectId,
    status: "DRAFT",
    version: 0,
    created_at: timestamp,
    updated_at: timestamp,
    approved_at: null,
    approved_by: null,
    nodes: [],
    edges: [],
  };
}

export async function fetchGraph(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/requirements-graph`);
  try {
    return await parseApiResponse(resp);
  } catch (err) {
    if (isApiErrorStatus(err, 404)) return createEmptyRequirementsGraph(projectId);
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

export async function fetchRequirementSummary(projectId: string, limit = 50, offset = 0) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  const resp = await fetch(`${API_BASE}/projects/${projectId}/requirements/summary?${params.toString()}`, {
    cache: "no-store",
  });
  return parseApiResponse(resp);
}

export function requirementSummaryExportUrl(projectId: string, format: "csv" | "json" = "csv") {
  const params = new URLSearchParams({ format });
  return `${API_BASE}/projects/${projectId}/requirements/summary/export?${params.toString()}`;
}

export async function fetchRequirementTimeline(projectId: string, requirementId: string, limit = 100, offset = 0) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  const encodedRequirement = encodeURIComponent(requirementId);
  const resp = await fetch(
    `${API_BASE}/projects/${projectId}/requirements/${encodedRequirement}/timeline?${params.toString()}`
  );
  return parseApiResponse(resp);
}
