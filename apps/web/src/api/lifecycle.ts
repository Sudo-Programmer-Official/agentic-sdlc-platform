const DEFAULT_API_BASE = import.meta.env.DEV
  ? "http://localhost:8000/api/v1"
  : "https://api.prompt2pr.com/api/v1";

const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;

export type CreateTaskPayload = {
  title: string;
  description?: string | null;
  category?: string;
  stage?: string;
  status?: string;
  assignee?: string | null;
  source?: string;
  document_id?: string | null;
  created_by?: string | null;
};

export type CreateDocumentPayload = {
  type: string;
  title: string;
  body: string;
  source?: string;
  created_by?: string | null;
};

export async function previewImpact(projectId: string, documentId: string, proposedBody: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/documents/${documentId}/impact-preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ proposed_body: proposedBody })
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function regenerateTasks(projectId: string, documentId: string, force = false) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/documents/${documentId}/generate-tasks?force=${force}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function listTasks(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/tasks`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function createTask(projectId: string, payload: CreateTaskPayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function explainTask(projectId: string, taskId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/tasks/${taskId}/explain`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function listActivity(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/activity`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function fetchProjectMeta(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function updateProjectStage(projectId: string, toStage: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/stage`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to_stage: toStage })
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function listDocuments(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/documents`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function createDocument(projectId: string, payload: CreateDocumentPayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

// Runs
export async function listRuns(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/runs`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function createRun(projectId: string, executor = "dummy") {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ executor }),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function updateRunStatus(runId: string, status: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status })
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function fetchHealth(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/health`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function fetchLifecycleScore(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/lifecycle-score`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function fetchLifecycleScoreHistory(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/lifecycle-score-history`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

// Work items / DAG / events
export async function listWorkItems(projectId: string, runId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/runs/${runId}/work-items`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function getWorkDag(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/work-dag`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function listRunEvents(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/events`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}
