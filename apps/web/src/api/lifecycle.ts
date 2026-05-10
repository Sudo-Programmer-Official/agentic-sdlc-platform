import { isApiErrorStatus, parseApiResponse } from "./http";

const DEFAULT_API_BASE = import.meta.env.DEV
  ? "http://localhost:8000/api/v1"
  : "https://api.prompt2pr.com/api/v1";

const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;

export function createEmptyRepoMap(message = "No local repo workspace is available yet. Start a repo-backed run first.") {
  return {
    source_type: "workspace",
    repo_root: "",
    repo_full_name: null,
    branch_name: null,
    total_files: 0,
    indexed_symbols: 0,
    dependency_edges: 0,
    test_links: 0,
    snapshot_indexed_at: null,
    directories: [],
    top_features: [],
    files: [],
    ready: false,
    setup_state: "WORKSPACE_REQUIRED",
    message,
  };
}

export function createEmptyProjectPreviewProfile(
  message = "Using default static-web-monorepo preview contract. Edit it if this project needs a different architecture."
) {
  return {
    configured: false,
    message,
    enabled: true,
    mode: "local",
    frontend_root: null,
    backend_root: null,
    compose_file: null,
    frontend_build_command: null,
    backend_build_command: null,
    frontend_start_command: "python3 -m http.server $PORT --bind $HOST",
    backend_start_command: null,
    frontend_healthcheck_path: "/",
    backend_healthcheck_path: "/",
    frontend_port: null,
    backend_port: null,
    env_overrides: {},
    ttl_hours: 24,
    max_previews_per_project: null,
    created_by: null,
    created_at: null,
    updated_at: null,
  };
}

export function createEmptyArchitectureProfileSummary(message = "No architecture profile saved yet.") {
  return {
    profile_exists: false,
    profile_id: null,
    status: "MISSING",
    source: "INFERRED",
    version: null,
    summary: message,
    repo_full_name: null,
    repo_default_branch: null,
    repo_layout_label: "Repository",
    monorepo: false,
    package_count: 0,
    packages: [],
    boundary_count: 0,
    protected_zone_count: 0,
    protected_zones: [],
    safe_zone_count: 0,
    safe_zones: [],
    command_coverage_count: 0,
    commands: [],
    validation_recipe_count: 0,
    derived_ready: false,
    last_derived_at: null,
    execution_slice: [],
    validation_recipes: [],
    protected_zones_touched: [],
    safe_zones_touched: [],
    assumptions_used: [],
  };
}

export function createEmptyFoundationReadiness(message = "Foundation readiness has not been evaluated yet.") {
  return {
    status: "MISSING",
    mode: "new_bootstrap",
    repo_connected: false,
    architecture_profile_present: false,
    checks: [],
    missing_prerequisites: [],
    recommended_next_step: message,
  };
}

export type CreateTaskPayload = {
  title: string;
  description?: string | null;
  category?: string;
  stage?: string;
  status?: string;
  assignee?: string | null;
  source?: string;
  source_type?: string;
  source_node_id?: string | null;
  requirement_id?: string | null;
  derived_from_requirement_ids?: string[];
  capability_id?: string | null;
  capability_label?: string | null;
  architecture_slice?: string | null;
  impact_zone?: string[];
  provenance?: Record<string, any>;
  document_id?: string | null;
  created_by?: string | null;
  branch_strategy?: "auto" | "new" | "existing";
  base_branch?: string | null;
  branch_name?: string | null;
};

export type VisionRunScreenshotPayload = {
  filename: string;
  content_type: string;
  data_base64: string;
};

export type VisionRunCreatePayload = {
  project_id: string;
  goal_text: string;
  screenshots: VisionRunScreenshotPayload[];
  page_url?: string | null;
  preferred_executor?: string;
  auto_start?: boolean;
  auto_deploy?: boolean;
  metadata?: Record<string, any>;
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
  auth_strategy?: string;
  created_by?: string | null;
};

export type RepoPreflightPayload = {
  provider?: string;
  repo_url?: string | null;
  repo_full_name?: string | null;
  default_branch?: string | null;
  installation_id?: number | null;
  auth_strategy?: string | null;
  clone?: boolean;
};

export type GitHubConnectInfo = {
  enabled: boolean;
  app_slug?: string | null;
  allowed_org?: string | null;
  install_url?: string | null;
  runtime_git_auth_mode?: string | null;
};

export type GitHubInstallationRepository = {
  id: number;
  name: string;
  full_name: string;
  clone_url?: string | null;
  ssh_url?: string | null;
  html_url?: string | null;
  default_branch?: string | null;
  private?: boolean;
  owner_login?: string | null;
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

export type ProjectBlueprintPayload = {
  blueprint_key?: string;
  stack_preset_key?: string;
  deployment_profile?: string;
  readiness_enforced?: boolean;
  created_by?: string | null;
};

export type ArchitectureProfileUpsertPayload = {
  status?: string;
  source?: string;
  summary?: string | null;
  profile_json?: Record<string, any>;
  created_by?: string | null;
  updated_by?: string | null;
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
  return parseApiResponse(resp);
}

export async function regenerateTasks(projectId: string, documentId: string, force = false) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/documents/${documentId}/generate-tasks?force=${force}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return parseApiResponse(resp);
}

export async function listTasks(
  projectId: string,
  options: {
    active_only?: boolean;
    latest_per_title?: boolean;
    include_deleted?: boolean;
  } = {}
) {
  const query = new URLSearchParams();
  if (options.active_only !== undefined) query.set("active_only", String(Boolean(options.active_only)));
  if (options.latest_per_title !== undefined) query.set("latest_per_title", String(Boolean(options.latest_per_title)));
  if (options.include_deleted !== undefined) query.set("include_deleted", String(Boolean(options.include_deleted)));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const resp = await fetch(`${API_BASE}/projects/${projectId}/tasks${suffix}`);
  return parseApiResponse(resp);
}

export async function listImprovementRequests(projectId: string, limit = 50) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/improvement-requests?limit=${encodeURIComponent(String(limit))}`);
  return parseApiResponse(resp);
}

export async function fetchFoundationReadiness(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/foundation-readiness`);
  try {
    return await parseApiResponse(resp);
  } catch (err) {
    if (isApiErrorStatus(err, 404)) return createEmptyFoundationReadiness((err as any)?.message);
    throw err;
  }
}

export async function listStackPresets(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/stack-presets`);
  return parseApiResponse(resp);
}

export async function fetchProjectBlueprint(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/blueprint`);
  return parseApiResponse(resp);
}

export async function fetchLatestGenesisRun(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/genesis-runs/latest`);
  return parseApiResponse(resp);
}

export async function createProjectBlueprint(projectId: string, payload: ProjectBlueprintPayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/blueprint`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function createTask(projectId: string, payload: CreateTaskPayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function explainTask(projectId: string, taskId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/tasks/${taskId}/explain`);
  return parseApiResponse(resp);
}

export async function listActivity(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/activity`);
  return parseApiResponse(resp);
}

export async function fetchProjectMeta(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}`);
  return parseApiResponse(resp);
}

export async function fetchMissionControlOverview(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/mission-control/overview`);
  return parseApiResponse(resp);
}

export async function fetchProjectMemoryTimeline(
  projectId: string,
  params: {
    limit?: number;
    domain?: string;
    severity?: string;
    requirement_id?: string;
    run_id?: string;
  } = {}
) {
  const search = new URLSearchParams();
  if (params.limit) search.set("limit", String(params.limit));
  if (params.domain) search.set("domain", params.domain);
  if (params.severity) search.set("severity", params.severity);
  if (params.requirement_id) search.set("requirement_id", params.requirement_id);
  if (params.run_id) search.set("run_id", params.run_id);
  const qs = search.toString();
  const resp = await fetch(`${API_BASE}/projects/${projectId}/memory/timeline${qs ? `?${qs}` : ""}`);
  return parseApiResponse(resp);
}

export async function backfillProjectMemoryTimeline(projectId: string, limit = 200) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/memory/timeline/backfill?limit=${encodeURIComponent(String(limit))}`, {
    method: "POST",
  });
  return parseApiResponse(resp);
}

export async function materializeProjectMemorySummaries(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/memory/summaries/materialize`, {
    method: "POST",
  });
  return parseApiResponse(resp);
}

export async function fetchProjectMemorySummaries(
  projectId: string,
  params: {
    summary_type?: string;
    limit?: number;
  } = {}
) {
  const search = new URLSearchParams();
  if (params.summary_type) search.set("summary_type", params.summary_type);
  if (params.limit) search.set("limit", String(params.limit));
  const qs = search.toString();
  const resp = await fetch(`${API_BASE}/projects/${projectId}/memory/summaries${qs ? `?${qs}` : ""}`);
  return parseApiResponse(resp);
}

export async function explainProjectMemory(
  projectId: string,
  params: {
    requirement_id?: string;
    run_id?: string;
    limit?: number;
  } = {}
) {
  const search = new URLSearchParams();
  if (params.requirement_id) search.set("requirement_id", params.requirement_id);
  if (params.run_id) search.set("run_id", params.run_id);
  if (params.limit) search.set("limit", String(params.limit));
  const qs = search.toString();
  const resp = await fetch(`${API_BASE}/projects/${projectId}/memory/explain${qs ? `?${qs}` : ""}`);
  return parseApiResponse(resp);
}

export async function fetchProjectUnderstanding(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/memory/project-understanding`);
  return parseApiResponse(resp);
}

export async function fetchRepoMap(projectId: string, limit = 180) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/repo-map?limit=${encodeURIComponent(String(limit))}`);
  try {
    return await parseApiResponse(resp);
  } catch (err) {
    if (isApiErrorStatus(err, 409)) return createEmptyRepoMap((err as any)?.message);
    throw err;
  }
}

export async function updateProjectStage(projectId: string, toStage: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/stage`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to_stage: toStage })
  });
  return parseApiResponse(resp);
}

export async function listDocuments(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/documents`);
  return parseApiResponse(resp);
}

export async function createDocument(projectId: string, payload: CreateDocumentPayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchProjectRepo(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/repo`);
  try {
    return await parseApiResponse(resp);
  } catch (err) {
    if (isApiErrorStatus(err, 404)) return null;
    throw err;
  }
}

export async function connectProjectRepo(projectId: string, payload: ConnectRepoPayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/connect-repo`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function preflightProjectRepo(projectId: string, payload: RepoPreflightPayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/repo/preflight`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchProjectPreviewProfile(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/preview-profile`);
  try {
    return await parseApiResponse(resp);
  } catch (err) {
    if (isApiErrorStatus(err, 404)) return createEmptyProjectPreviewProfile((err as any)?.message);
    throw err;
  }
}

export async function fetchProjectArchitectureProfile(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/architecture-profile`);
  return parseApiResponse(resp);
}

export async function fetchProjectArchitectureProfileSummary(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/architecture-profile/summary`);
  try {
    return await parseApiResponse(resp);
  } catch (err) {
    if (isApiErrorStatus(err, 404)) return createEmptyArchitectureProfileSummary((err as any)?.message);
    throw err;
  }
}

export async function saveProjectArchitectureProfile(projectId: string, payload: ArchitectureProfileUpsertPayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/architecture-profile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function bootstrapProjectArchitectureProfile(
  projectId: string,
  payload: {
    refresh_repo_map?: boolean;
    created_by?: string | null;
  } = {}
) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/architecture-profile/bootstrap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function deriveProjectArchitectureProfile(
  projectId: string,
  payload: {
    refresh_repo_map?: boolean;
    bootstrap_if_missing?: boolean;
    updated_by?: string | null;
  } = {}
) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/architecture-profile/derive`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchProjectContract(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/project-contract`);
  return parseApiResponse(resp);
}

export async function fetchProjectContractSummary(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/project-contract/summary`);
  try {
    return await parseApiResponse(resp);
  } catch (err) {
    if (isApiErrorStatus(err, 404)) return null;
    throw err;
  }
}

export async function saveProjectContract(projectId: string, payload: {
  status?: string;
  source?: string;
  summary?: string | null;
  contract_json?: Record<string, any>;
  created_by?: string | null;
  updated_by?: string | null;
}) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/project-contract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function patchProjectContract(projectId: string, payload: {
  summary?: string | null;
  sections?: Record<string, any>;
  updated_by?: string | null;
}) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/project-contract`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function bootstrapProjectContract(
  projectId: string,
  payload: {
    created_by?: string | null;
  } = {}
) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/project-contract/bootstrap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchGitHubConnectInfo(): Promise<GitHubConnectInfo> {
  const resp = await fetch(`${API_BASE}/integrations/github/connect`);
  return parseApiResponse(resp);
}

export async function listGitHubInstallationRepositories(
  installationId: number
): Promise<GitHubInstallationRepository[]> {
  const resp = await fetch(`${API_BASE}/integrations/github/installations/${installationId}/repositories`);
  return parseApiResponse(resp);
}

export async function saveProjectPreviewProfile(projectId: string, payload: PreviewProfilePayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/preview-profile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
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
  return parseApiResponse(resp);
}

export async function createApproval(projectId: string, payload: CreateApprovalPayload) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/approvals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

// Runs
export async function listRuns(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/runs`);
  return parseApiResponse(resp);
}

export async function createRun(projectId: string, executor = "codex", taskId?: string | null, runKind?: string | null) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ executor, task_id: taskId || null, run_kind: runKind || null }),
  });
  return parseApiResponse(resp);
}

export async function createVisionRun(payload: VisionRunCreatePayload) {
  const resp = await fetch(`${API_BASE}/tasks/vision-run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function updateRunStatus(runId: string, status: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status })
  });
  return parseApiResponse(resp);
}

export async function resumeRun(runId: string, payload: { start_now?: boolean } = {}) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start_now: payload.start_now ?? true }),
  });
  return parseApiResponse(resp);
}

export async function unblockRun(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/unblock`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return parseApiResponse(resp);
}

export async function retryRunPush(runId: string, payload: { auth_strategy?: string } = {}) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/retry-push`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function discardRun(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/discard`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return parseApiResponse(resp);
}

export async function extendRunBudget(
  runId: string,
  payload: {
    additional_tokens: number;
    additional_cost_cents: number;
    auto_resume?: boolean;
    reason?: string | null;
  }
) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/budget/extend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
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
  return parseApiResponse(resp);
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
  return parseApiResponse(resp);
}

export async function fetchRunPreview(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/preview`);
  return parseApiResponse(resp);
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
  return parseApiResponse(resp);
}

export async function deleteRunPreview(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/preview`, {
    method: "DELETE",
  });
  return parseApiResponse(resp);
}

export async function compareRuns(runA: string, runB: string) {
  const resp = await fetch(
    `${API_BASE}/runs/compare?run_a=${encodeURIComponent(runA)}&run_b=${encodeURIComponent(runB)}`
  );
  return parseApiResponse(resp);
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
    mode?: string;
    feedback_text?: string;
    feedback_source?: string;
  } = {}
) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/strategies`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchRunStrategies(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/strategies`);
  return parseApiResponse(resp);
}

export async function reportRunIssue(
  runId: string,
  payload: {
    issue: string;
    files?: string[];
    goal?: string;
    executor?: string;
    start_now?: boolean;
    feedback_source?: string;
  }
) {
  return createRunStrategies(runId, {
    goal: payload.goal,
    error: payload.issue,
    files: payload.files || [],
    executor: payload.executor,
    start_now: payload.start_now,
    limit: 1,
    mode: "feedback",
    feedback_text: payload.issue,
    feedback_source: payload.feedback_source || "user",
  });
}

export async function fetchRunTimeline(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/timeline`);
  return parseApiResponse(resp);
}

export async function fetchRunNarrative(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/narrative`);
  return parseApiResponse(resp);
}

export async function fetchRunExecutionConsole(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/execution-console`);
  return parseApiResponse(resp);
}

export function hasRunMemorySearchContext(payload: {
  goal?: string;
  error?: string;
  files?: string[];
}) {
  const goal = typeof payload.goal === "string" ? payload.goal.trim() : "";
  const error = typeof payload.error === "string" ? payload.error.trim() : "";
  const files = Array.isArray(payload.files) ? payload.files.filter((file) => typeof file === "string" && file.trim()) : [];
  return Boolean(goal || error || files.length);
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
  const goal = typeof payload.goal === "string" ? payload.goal.trim() : "";
  const error = typeof payload.error === "string" ? payload.error.trim() : "";
  const files = Array.isArray(payload.files) ? payload.files.filter((file) => typeof file === "string" && file.trim()) : [];

  if (!hasRunMemorySearchContext({ goal, error, files })) {
    return {
      matches: [],
      limit: payload.limit || 0,
      query: { goal: goal || null, error: error || null, files },
    };
  }

  const query = new URLSearchParams();
  if (goal) query.set("goal", goal);
  if (error) query.set("error", error);
  for (const file of files) {
    query.append("file", file);
  }
  if (payload.limit) query.set("limit", String(payload.limit));
  const resp = await fetch(`${API_BASE}/projects/${projectId}/runs/memory?${query.toString()}`);
  return parseApiResponse(resp);
}

export async function fetchHealth(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/health`);
  return parseApiResponse(resp);
}

export async function fetchLifecycleScore(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/lifecycle-score`);
  return parseApiResponse(resp);
}

export async function fetchLifecycleScoreHistory(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/lifecycle-score-history`);
  return parseApiResponse(resp);
}

// Work items / DAG / events
export async function listWorkItems(projectId: string, runId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/runs/${runId}/work-items`);
  return parseApiResponse(resp);
}

export async function getWorkDag(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/work-dag`);
  return parseApiResponse(resp);
}

export async function listRunEvents(runId: string) {
  const resp = await fetch(`${API_BASE}/runs/${runId}/events`);
  return parseApiResponse(resp);
}

export async function listAgents() {
  const resp = await fetch(`${API_BASE}/agents`);
  return parseApiResponse(resp);
}

export async function listArtifacts(projectId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/artifacts`);
  return parseApiResponse(resp);
}

export async function explainArtifact(projectId: string, artifactId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/artifacts/${artifactId}/explain`);
  return parseApiResponse(resp);
}

export async function fetchArtifactDiff(projectId: string, artifactId: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/artifacts/${artifactId}/diff`);
  return parseApiResponse(resp);
}

export async function fetchArtifactContextByUri(projectId: string, uri: string) {
  const resp = await fetch(`${API_BASE}/projects/${projectId}/artifacts/context?uri=${encodeURIComponent(uri)}`);
  return parseApiResponse(resp);
}

export async function sendOperatorMessage(payload: OperatorMessagePayload) {
  const resp = await fetch(`${API_BASE}/ai/operator`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp) as Promise<OperatorResponse>;
}
