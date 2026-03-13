const DEFAULT_API_BASE = import.meta.env.DEV
  ? "http://localhost:8000/api/v1"
  : "https://api.prompt2pr.com/api/v1";

const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;

async function parseResponse(resp: Response) {
  if (resp.ok) return resp.json();

  let payload: any = null;
  try {
    payload = await resp.json();
  } catch {
    payload = null;
  }

  const detail = payload?.detail;
  const error = payload?.error;
  const errorId = payload?.error_id;

  let message = "Request failed";
  if (typeof detail === "string" && detail) {
    message = detail;
  } else if (Array.isArray(detail) && detail.length) {
    message = detail.map((item) => item?.msg || JSON.stringify(item)).join(", ");
  } else if (typeof error === "string" && error) {
    message = errorId ? `${error} (${errorId})` : error;
  } else {
    const text = await resp.text().catch(() => "");
    if (text) message = text;
  }

  throw new Error(message);
}

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
  return parseResponse(resp);
}

export async function regenerateTasks(projectId: string, documentId: string, force = false) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/documents/${documentId}/generate-tasks?force=${force}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return parseResponse(resp);
}

export async function listTasks(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/tasks`);
  return parseResponse(resp);
}

export async function createTask(projectId: string, payload: CreateTaskPayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(resp);
}

export async function explainTask(projectId: string, taskId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/tasks/${taskId}/explain`);
  return parseResponse(resp);
}

export async function listActivity(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/activity`);
  return parseResponse(resp);
}

export async function fetchProjectMeta(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}`);
  return parseResponse(resp);
}

export async function updateProjectStage(projectId: string, toStage: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/stage`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to_stage: toStage })
  });
  return parseResponse(resp);
}

export async function listDocuments(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/documents`);
  return parseResponse(resp);
}

export async function createDocument(projectId: string, payload: CreateDocumentPayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(resp);
}

// Runs
export async function listRuns(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/runs`);
  return parseResponse(resp);
}

export async function createRun(projectId: string, executor = "dummy") {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ executor }),
  });
  return parseResponse(resp);
}

export async function updateRunStatus(runId: string, status: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status })
  });
  return parseResponse(resp);
}

export async function forkRun(
  runId: string,
  payload: {
    executor?: string;
    branch_name?: string;
    start_now?: boolean;
    summary_overrides?: Record<string, any>;
  } = {}
) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/fork`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(resp);
}

export async function fetchHealth(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/health`);
  return parseResponse(resp);
}

export async function fetchLifecycleScore(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/lifecycle-score`);
  return parseResponse(resp);
}

export async function fetchLifecycleScoreHistory(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/lifecycle-score-history`);
  return parseResponse(resp);
}

// Work items / DAG / events
export async function listWorkItems(projectId: string, runId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/runs/${runId}/work-items`);
  return parseResponse(resp);
}

export async function getWorkDag(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/work-dag`);
  return parseResponse(resp);
}

export async function listRunEvents(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/events`);
  return parseResponse(resp);
}

export async function listArtifacts(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/artifacts`);
  return parseResponse(resp);
}

export async function explainArtifact(projectId: string, artifactId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/artifacts/${artifactId}/explain`);
  return parseResponse(resp);
}

export async function fetchArtifactContextByUri(projectId: string, uri: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/artifacts/context?uri=${encodeURIComponent(uri)}`);
  return parseResponse(resp);
}
