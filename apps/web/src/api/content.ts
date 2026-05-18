import { apiFetch } from "./lifecycle";
import { parseApiResponse } from "./http";

const DEFAULT_API_BASE = import.meta.env.DEV
  ? "http://localhost:8000/api/v1"
  : "https://api.prompt2pr.com/api/v1";

const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;

export type ContentItem = {
  id: string;
  project_id: string;
  environment: "PREVIEW" | "STAGING" | "PRODUCTION";
  key: string;
  type: string;
  value: any;
  version: number;
  status: string;
  source: string;
  updated_by?: string | null;
  updated_at: string;
};

export async function fetchContentItems(projectId: string, environment = "PREVIEW"): Promise<ContentItem[]> {
  const params = new URLSearchParams({ environment });
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/content-items?${params.toString()}`);
  return parseApiResponse(resp);
}

export async function saveContentItem(
  projectId: string,
  payload: { key: string; type?: string; value: any; source?: string },
  environment = "PREVIEW",
  publish = false
): Promise<ContentItem> {
  const params = new URLSearchParams({ environment, publish: String(publish) });
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/content-items?${params.toString()}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchContentHistory(projectId: string, key: string, environment = "PREVIEW") {
  const params = new URLSearchParams({ environment });
  const encodedKey = encodeURIComponent(key);
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/content-items/history/${encodedKey}?${params.toString()}`);
  return parseApiResponse(resp);
}

export async function rollbackContentItem(projectId: string, key: string, targetVersion: number, environment = "PREVIEW") {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/content-items/rollback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, environment, target_version: targetVersion }),
  });
  return parseApiResponse(resp);
}

export async function publishContent(projectId: string, sourceEnvironment: string, targetEnvironment: string, notes?: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/content-items/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_environment: sourceEnvironment, target_environment: targetEnvironment, notes }),
  });
  return parseApiResponse(resp);
}
