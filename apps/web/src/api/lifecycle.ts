const DEFAULT_API_BASE = import.meta.env.DEV
  ? "http://localhost:8000/api/v1"
  : "https://api.prompt2pr.com/api/v1";

const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;

export async function previewImpact(projectId: string, documentId: string, proposedBody: string) {
  const resp = await fetch(`${API_BASE}/store/projects/${projectId}/documents/${documentId}/impact-preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ proposed_body: proposedBody })
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function regenerateTasks(projectId: string, documentId: string, force = false) {
  const resp = await fetch(`${API_BASE}/store/projects/${projectId}/documents/${documentId}/generate-tasks?force=${force}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function listTasks(projectId: string) {
  const resp = await fetch(`${API_BASE}/store/projects/${projectId}/tasks`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function explainTask(projectId: string, taskId: string) {
  const resp = await fetch(`${API_BASE}/store/projects/${projectId}/tasks/${taskId}/explain`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function listActivity(projectId: string) {
  const resp = await fetch(`${API_BASE}/store/projects/${projectId}/activity`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function fetchHealth(projectId: string) {
  const resp = await fetch(`${API_BASE}/store/projects/${projectId}/health`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function fetchLifecycleScore(projectId: string) {
  const resp = await fetch(`${API_BASE}/store/projects/${projectId}/lifecycle-score`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function fetchLifecycleScoreHistory(projectId: string) {
  const resp = await fetch(`${API_BASE}/store/projects/${projectId}/lifecycle-score-history`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}
