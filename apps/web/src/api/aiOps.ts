import { parseApiResponse } from "./http";
import { apiFetch } from "./lifecycle";

const DEFAULT_API_BASE = import.meta.env.DEV
  ? "http://localhost:8000/api/v1"
  : "https://api.prompt2pr.com/api/v1";

const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;

function buildQuery(params: Record<string, string | null | undefined>) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (!value) return;
    query.set(key, value);
  });
  const suffix = query.toString();
  return suffix ? `?${suffix}` : "";
}

export async function fetchAiOpsDashboard(params: { project_id?: string; repository_id?: string } = {}) {
  const resp = await apiFetch(`${API_BASE}/ai/ops/dashboard${buildQuery(params)}`);
  return parseApiResponse(resp);
}
