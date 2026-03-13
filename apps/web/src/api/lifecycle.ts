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

export type ConnectRepoPayload = {
  provider?: string;
  repo_url: string;
  repo_full_name?: string | null;
  default_branch?: string;
  installation_id?: number | null;
  created_by?: string | null;
};

export type PreviewProfilePayload = {
  enabled?: boolean;
  mode?: string;
  frontend_root?: string | null;
  backend_root?: string | null;
  compose_file?: string | null;
  frontend_build_command?: string | null;
  backend_build_command?: string | null;
  frontend_start_command?: string | null;
  backend_start_command?: string | null;
  frontend_healthcheck_path?: string | null;
  backend_healthcheck_path?: string | null;
  frontend_port?: number | null;
  backend_port?: number | null;
  env_overrides?: Record<string, string>;
  ttl_hours?: number;
  max_previews_per_project?: number | null;
  created_by?: string | null;
};

export type CreateApprovalPayload = {
  target_type: string;
  target_id: string;
  status?: string;
  decided_by?: string | null;
  comment?: string | null;
};

export type OperatorMessagePayload = {
  project_id: string;
  message: string;
  context?: {
    run_id?: string;
    artifact_id?: string;
  };
};

export type OperatorReference = {
  type: string;
  label: string;
  id?: string | null;
  path?: string | null;
  url?: string | null;
  meta?: Record<string, any> | null;
};

export type OperatorAction = {
  label: string;
  type: string;
  target_id?: string | null;
  path?: string | null;
  url?: string | null;
  prompt?: string | null;
  meta?: Record<string, any> | null;
};

export type OperatorResponse = {
  answer: string;
  intent: string;
  status: string;
  references: OperatorReference[];
  actions: OperatorAction[];
  grounding_tools: string[];
  facts: string[];
  tool_results: Record<string, any>;
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

export async function fetchMissionControlOverview(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/mission-control/overview`);
  return parseResponse(resp);
}

export async function fetchRepoMap(projectId: string, limit = 180) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/repo-map?limit=${encodeURIComponent(String(limit))}`);
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

export async function fetchProjectRepo(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/repo`);
  return parseResponse(resp);
}

export async function connectProjectRepo(projectId: string, payload: ConnectRepoPayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/connect-repo`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(resp);
}

export async function fetchProjectPreviewProfile(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/preview-profile`);
  return parseResponse(resp);
}

export async function saveProjectPreviewProfile(projectId: string, payload: PreviewProfilePayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/preview-profile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(resp);
}

export async function listApprovals(
  projectId: string,
  filters: {
    target_type?: string;
    target_id?: string;
  } = {}
) {
  const query = new URLSearchParams();
  if (filters.target_type) query.set("target_type", filters.target_type);
  if (filters.target_id) query.set("target_id", filters.target_id);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const resp = await fetch(`${API_BASE}/projects/${projectId}/approvals${suffix}`);
  return parseResponse(resp);
}

export async function createApproval(projectId: string, payload: CreateApprovalPayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/approvals`, {
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

export async function createRunPullRequest(
  runId: string,
  payload: {
    artifact_id?: string;
    title?: string;
    body?: string;
    branch_name?: string;
  } = {}
) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/create-pr`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(resp);
}

export async function fetchRunPreview(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/preview`);
  return parseResponse(resp);
}

export async function launchRunPreview(
  runId: string,
  payload: {
    reuse_if_healthy?: boolean;
  } = {}
) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(resp);
}

export async function deleteRunPreview(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/preview`, {
    method: "DELETE",
  });
  return parseResponse(resp);
}

export async function compareRuns(runA: string, runB: string) {
  const resp = await fetch(
    `${API_BASE}/runs/compare?run_a=${encodeURIComponent(runA)}&run_b=${encodeURIComponent(runB)}`
  );
  return parseResponse(resp);
}

export async function createRunStrategies(
  runId: string,
  payload: {
    goal?: string;
    error?: string;
    files?: string[];
    executor?: string;
    start_now?: boolean;
    limit?: number;
  } = {}
) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/strategies`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(resp);
}

export async function fetchRunStrategies(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/strategies`);
  return parseResponse(resp);
}

export async function fetchRunTimeline(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/timeline`);
  return parseResponse(resp);
}

export async function fetchRunNarrative(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/narrative`);
  return parseResponse(resp);
}

export async function findSimilarRuns(
  projectId: string,
  payload: {
    goal?: string;
    error?: string;
    files?: string[];
    limit?: number;
  }
) {
  const query = new URLSearchParams();
  if (payload.goal) query.set("goal", payload.goal);
  if (payload.error) query.set("error", payload.error);
  for (const file of payload.files || []) {
    if (file) query.append("file", file);
  }
  if (payload.limit) query.set("limit", String(payload.limit));
  const resp = await fetch(`${API_BASE}/projects/${projectId}/runs/memory?${query.toString()}`);
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

export async function listAgents() {
  const resp = await fetch(`${API_BASE}/agents`);
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

export async function fetchArtifactDiff(projectId: string, artifactId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/artifacts/${artifactId}/diff`);
  return parseResponse(resp);
}

export async function fetchArtifactContextByUri(projectId: string, uri: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/artifacts/context?uri=${encodeURIComponent(uri)}`);
  return parseResponse(resp);
}

export async function sendOperatorMessage(payload: OperatorMessagePayload) {
  const resp = await fetch(`${API_BASE}/ai/operator`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(resp) as Promise<OperatorResponse>;
}
