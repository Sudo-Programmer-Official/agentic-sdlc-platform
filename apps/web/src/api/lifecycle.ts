import { isApiErrorStatus, parseApiResponse } from "./http";

const DEFAULT_API_BASE = import.meta.env.DEV
  ? "http://localhost:8000/api/v1"
  : "https://api.prompt2pr.com/api/v1";

const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;
const TENANT_ID_STORAGE_KEY = "agentic.activeTenantId";
const WORKSPACE_ID_STORAGE_KEY = "agentic.activeWorkspaceId";
const WORKSPACE_META_STORAGE_KEY = "agentic.activeWorkspaceMeta";
const AUTH_TOKEN_STORAGE_KEY = "agentic.authToken";
const CORRELATION_ID_STORAGE_KEY = "agentic.correlationId";
const ACTION_REQUEST_KEY_STORAGE_KEY = "agentic.actionRequestKeys";

export function setActiveTenantId(tenantId: string | null) {
  if (typeof window === "undefined") return;
  if (!tenantId) {
    localStorage.removeItem(TENANT_ID_STORAGE_KEY);
    window.dispatchEvent(new CustomEvent("agentic:tenant-changed", { detail: { tenantId: null } }));
    return;
  }
  localStorage.setItem(TENANT_ID_STORAGE_KEY, tenantId);
  window.dispatchEvent(new CustomEvent("agentic:tenant-changed", { detail: { tenantId } }));
}

export function setActiveWorkspaceId(workspaceId: string | null) {
  if (typeof window === "undefined") return;
  if (!workspaceId) {
    localStorage.removeItem(WORKSPACE_ID_STORAGE_KEY);
    window.dispatchEvent(new CustomEvent("agentic:workspace-changed", { detail: { workspaceId: null } }));
    return;
  }
  localStorage.setItem(WORKSPACE_ID_STORAGE_KEY, workspaceId);
  window.dispatchEvent(new CustomEvent("agentic:workspace-changed", { detail: { workspaceId } }));
}

export type ActiveWorkspaceMeta = {
  id: string;
  name: string;
};

export function setActiveWorkspaceMeta(workspace: ActiveWorkspaceMeta | null) {
  if (typeof window === "undefined") return;
  if (!workspace?.id) {
    localStorage.removeItem(WORKSPACE_META_STORAGE_KEY);
    return;
  }
  localStorage.setItem(WORKSPACE_META_STORAGE_KEY, JSON.stringify({ id: workspace.id, name: workspace.name || "Workspace" }));
}

export function getActiveWorkspaceMeta(): ActiveWorkspaceMeta | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(WORKSPACE_META_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.id || typeof parsed.id !== "string") return null;
    return {
      id: parsed.id,
      name: typeof parsed.name === "string" && parsed.name.trim() ? parsed.name.trim() : "Workspace",
    };
  } catch {
    return null;
  }
}

export function getActiveTenantId(): string | null {
  if (typeof window === "undefined") return null;
  const value = localStorage.getItem(TENANT_ID_STORAGE_KEY);
  return value && value.trim() ? value.trim() : null;
}

export function getActiveWorkspaceId(): string | null {
  if (typeof window === "undefined") return null;
  const value = localStorage.getItem(WORKSPACE_ID_STORAGE_KEY);
  return value && value.trim() ? value.trim() : null;
}

export function setAuthToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (!token) {
    localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    return;
  }
  localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
}

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  const value = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
  return value && value.trim() ? value.trim() : null;
}

function decodeJwtPayload(token: string): Record<string, any> | null {
  try {
    const parts = token.split(".");
    if (parts.length < 2) return null;
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4 || 4)) % 4);
    const json = atob(padded);
    const parsed = JSON.parse(json);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function getAuthSubject(): string | null {
  const token = getAuthToken();
  if (!token) return null;
  const payload = decodeJwtPayload(token);
  if (!payload) return null;
  const candidate = payload.uid || payload.sub || payload.user_id || payload.email;
  if (typeof candidate !== "string") return null;
  const normalized = candidate.trim();
  return normalized || null;
}

function recentProjectsStorageKey(): string {
  const tenantId = getActiveTenantId();
  if (tenantId) return `agentic.recentProjects.tenant.${tenantId}`;
  const subject = getAuthSubject();
  if (subject) return `agentic.recentProjects.user.${subject}`;
  return "agentic.recentProjects.anon";
}

export type RecentProjectRecord = { id: string; name?: string };

export function loadRecentProjectsScoped(): RecentProjectRecord[] {
  if (typeof window === "undefined") return [];
  try {
    const scopedRaw = localStorage.getItem(recentProjectsStorageKey());
    if (scopedRaw) {
      const parsed = JSON.parse(scopedRaw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter((item) => item?.id && typeof item.id === "string");
    }
    const legacyRaw = localStorage.getItem("recentProjects");
    if (!legacyRaw) return [];
    const legacy = JSON.parse(legacyRaw);
    if (!Array.isArray(legacy)) return [];
    return legacy.filter((item) => item?.id && typeof item.id === "string");
  } catch {
    return [];
  }
}

export function saveRecentProjectsScoped(projects: RecentProjectRecord[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(recentProjectsStorageKey(), JSON.stringify(projects));
  } catch {
    // ignore storage errors
  }
}

export function removeRecentProjectScoped(projectId: string) {
  if (typeof window === "undefined") return;
  try {
    const current = loadRecentProjectsScoped();
    const filtered = current.filter((item) => item.id !== projectId);
    saveRecentProjectsScoped(filtered);
  } catch {
    // ignore storage errors
  }
}

function randomId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function getOrCreateActionRequestKey(action: string, scope: string, ttlMs = 45_000): string {
  const actionName = String(action || "").trim().toLowerCase() || "action";
  const scoped = String(scope || "").trim() || "global";
  const identity = `${actionName}:${scoped}`;
  const now = Date.now();
  if (typeof window === "undefined") return `${identity}:${randomId()}`;
  try {
    const raw = localStorage.getItem(ACTION_REQUEST_KEY_STORAGE_KEY);
    const store = raw ? (JSON.parse(raw) as Record<string, { key?: string; ts?: number }>) : {};
    const existing = store[identity];
    if (existing?.key && typeof existing.ts === "number" && now - existing.ts < ttlMs) {
      return existing.key;
    }
    const key = `${identity}:${randomId()}`;
    store[identity] = { key, ts: now };
    localStorage.setItem(ACTION_REQUEST_KEY_STORAGE_KEY, JSON.stringify(store));
    return key;
  } catch {
    return `${identity}:${randomId()}`;
  }
}

function getOrCreateCorrelationId(): string {
  if (typeof window === "undefined") return crypto.randomUUID();
  const value = window.localStorage.getItem(CORRELATION_ID_STORAGE_KEY);
  if (value && value.trim()) return value.trim();
  const correlationId = crypto.randomUUID();
  window.localStorage.setItem(CORRELATION_ID_STORAGE_KEY, correlationId);
  return correlationId;
}

export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers || {});
  const tenantId = getActiveTenantId();
  const workspaceId = getActiveWorkspaceId();
  const authToken = getAuthToken();
  const correlationId = getOrCreateCorrelationId();
  if (tenantId && !headers.has("X-Tenant-Id")) headers.set("X-Tenant-Id", tenantId);
  if (workspaceId && !headers.has("X-Workspace-Id")) headers.set("X-Workspace-Id", workspaceId);
  if (authToken && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${authToken}`);
  if (!headers.has("X-Correlation-Id")) headers.set("X-Correlation-Id", correlationId);
  const response = await fetch(input, { ...init, headers });
  if (response.status === 401 || response.status === 403) {
    setAuthToken(null);
    setActiveTenantId(null);
    setActiveWorkspaceId(null);
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/signin")) {
      const redirect = `${window.location.pathname}${window.location.search}`;
      window.location.assign(`/signin?redirect=${encodeURIComponent(redirect)}&reason=session_expired`);
    }
  }
  return response;
}

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
    derivation_confidence: "LOW",
    derived_from: [],
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

export type RepoBootstrapPayload = {
  provider?: string;
  repo_url?: string | null;
  repo_full_name?: string | null;
  default_branch?: string | null;
  installation_id?: number | null;
  auth_strategy?: string | null;
  readme_title?: string | null;
  commit_message?: string | null;
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

export type ProjectDeploymentCreatePayload = {
  provider?: string;
  target?: string;
  run_id?: string | null;
  request_key?: string | null;
  repository_url?: string | null;
  repository_full_name?: string | null;
  branch_name?: string | null;
  created_by?: string | null;
  env_overrides?: Record<string, string> | null;
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

export type Workspace = {
  id: string;
  tenant_id: string;
  name: string;
  created_at: string;
};

export type ProjectCreatePayload = {
  name: string;
  description?: string | null;
  starter_blueprint_enabled?: boolean;
  starter_blueprint_key?: string;
  starter_stack_preset_key?: string;
  starter_deployment_profile?: string;
};

export async function previewImpact(projectId: string, documentId: string, proposedBody: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/documents/${documentId}/impact-preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ proposed_body: proposedBody })
  });
  return parseApiResponse(resp);
}

export async function regenerateTasks(projectId: string, documentId: string, force = false) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/documents/${documentId}/generate-tasks?force=${force}`, {
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
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/tasks${suffix}`);
  return parseApiResponse(resp);
}

export async function fetchRunRecommendations(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/run-recommendations`);
  return parseApiResponse(resp);
}

export async function listImprovementRequests(projectId: string, limit = 50) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/improvement-requests?limit=${encodeURIComponent(String(limit))}`);
  return parseApiResponse(resp);
}

export async function fetchFoundationReadiness(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/foundation-readiness`);
  try {
    return await parseApiResponse(resp);
  } catch (err) {
    if (isApiErrorStatus(err, 404)) return createEmptyFoundationReadiness((err as any)?.message);
    throw err;
  }
}

export async function listStackPresets(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/stack-presets`);
  return parseApiResponse(resp);
}

export async function fetchProjectBlueprint(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/blueprint`);
  return parseApiResponse(resp);
}

export async function fetchLatestGenesisRun(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/genesis-runs/latest`);
  return parseApiResponse(resp);
}

export async function createProjectBlueprint(projectId: string, payload: ProjectBlueprintPayload) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/blueprint`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function createTask(projectId: string, payload: CreateTaskPayload) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function explainTask(projectId: string, taskId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/tasks/${taskId}/explain`);
  return parseApiResponse(resp);
}

export async function listActivity(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/activity`);
  return parseApiResponse(resp);
}

export async function fetchProjectMeta(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}`);
  return parseApiResponse(resp);
}

export async function fetchProjects() {
  const resp = await apiFetch(`${API_BASE}/projects`);
  return parseApiResponse(resp);
}

export type FirstLoginBootstrapPayload = {
  tenant_name?: string | null;
  workspace_name?: string | null;
  force_new_tenant?: boolean;
};

export type FirstLoginBootstrapOut = {
  user_id: string;
  tenant_id: string;
  tenant_name: string;
  workspace_id: string;
  workspace_name: string;
  tenant_member_role: string;
  workspace_member_role: string;
  created_tenant: boolean;
  created_workspace: boolean;
  created_tenant_member: boolean;
  created_workspace_member: boolean;
};

export async function bootstrapFirstLogin(
  token: string,
  payload: FirstLoginBootstrapPayload = {}
): Promise<FirstLoginBootstrapOut> {
  const headers = new Headers({ "Content-Type": "application/json", Authorization: `Bearer ${token}` });
  const correlationId = getOrCreateCorrelationId();
  if (!headers.has("X-Correlation-Id")) headers.set("X-Correlation-Id", correlationId);
  const resp = await fetch(`${API_BASE}/auth/bootstrap-first-login`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp) as Promise<FirstLoginBootstrapOut>;
}

export async function createProject(payload: ProjectCreatePayload) {
  const resp = await apiFetch(`${API_BASE}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchWorkspaces() {
  const resp = await apiFetch(`${API_BASE}/workspaces`);
  return parseApiResponse(resp);
}

export async function switchWorkspace(workspaceId: string) {
  const resp = await apiFetch(`${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/switch`);
  return parseApiResponse(resp);
}

export type AdminWorkspaceSummary = {
  id: string;
  name: string;
  tenant_id?: string;
  member_count?: number;
  project_count?: number;
  created_at?: string | null;
};

export type AdminImpersonationSession = {
  id: string;
  admin_user_id: string;
  target_workspace_id: string;
  reason?: string | null;
  started_at?: string | null;
  expires_at?: string | null;
  ended_at?: string | null;
  ended_by?: string | null;
  is_active: boolean;
};

export type AdminAuditLogRow = {
  id: string;
  admin_user_id: string;
  target_workspace_id?: string | null;
  action: string;
  reason?: string | null;
  duration_seconds?: number | null;
  created_at?: string | null;
  extra_metadata?: Record<string, any> | null;
};

export type WorkspaceEntitlement = {
  id: string;
  tenant_id: string;
  workspace_id: string;
  plan: string;
  limits: Record<string, any>;
  features: Record<string, any>;
  effective_from?: string | null;
  updated_at?: string | null;
};

export type WorkspaceUsageSummary = {
  workspace_id: string;
  days: number;
  totals: {
    usage_date: string;
    runs_count: number;
    deployments_count: number;
    recoveries_count: number;
    input_tokens: number;
    output_tokens: number;
    total_cost_cents: number;
  };
  daily: Array<{
    usage_date: string;
    runs_count: number;
    deployments_count: number;
    recoveries_count: number;
    input_tokens: number;
    output_tokens: number;
    total_cost_cents: number;
  }>;
};

export type WorkspaceAnomalySnapshot = {
  id: string;
  tenant_id: string;
  workspace_id: string;
  snapshot_date: string;
  window_days: number;
  runs_count: number;
  recoveries_count: number;
  total_tokens: number;
  total_cost_cents: number;
  burn_spike: boolean;
  failure_spike: boolean;
  burn_ratio?: string | null;
  failure_ratio?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type AdminDaemonHealth = {
  last_cycle_at?: string | null;
  last_cycle_window_days?: number | null;
  last_cycle_workspaces_processed: number;
  last_cycle_workspace_failures: number;
  last_error_at?: string | null;
  last_error_workspace_id?: string | null;
  alert_level?: "healthy" | "warn";
  alert_reasons?: string[];
};

export async function listAdminWorkspaces(query?: { q?: string; limit?: number }) {
  const search = new URLSearchParams();
  if (query?.q) search.set("q", query.q);
  if (query?.limit) search.set("limit", String(query.limit));
  const qs = search.toString();
  const resp = await apiFetch(`${API_BASE}/admin/workspaces${qs ? `?${qs}` : ""}`);
  return parseApiResponse(resp) as Promise<AdminWorkspaceSummary[]>;
}

export async function startAdminImpersonation(payload: {
  workspace_id: string;
  reason?: string | null;
  duration_minutes?: number;
}) {
  const resp = await apiFetch(`${API_BASE}/admin/impersonation/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp) as Promise<AdminImpersonationSession>;
}

export async function endAdminImpersonation(sessionId: string) {
  const resp = await apiFetch(`${API_BASE}/admin/impersonation/${encodeURIComponent(sessionId)}/end`, {
    method: "POST",
  });
  return parseApiResponse(resp) as Promise<AdminImpersonationSession>;
}

export async function listAdminAuditLogs(query?: { workspace_id?: string; limit?: number }) {
  const search = new URLSearchParams();
  if (query?.workspace_id) search.set("workspace_id", query.workspace_id);
  if (query?.limit) search.set("limit", String(query.limit));
  const qs = search.toString();
  const resp = await apiFetch(`${API_BASE}/admin/audit-logs${qs ? `?${qs}` : ""}`);
  return parseApiResponse(resp) as Promise<AdminAuditLogRow[]>;
}

export async function getAdminWorkspaceEntitlements(workspaceId: string) {
  const resp = await apiFetch(`${API_BASE}/admin/workspaces/${encodeURIComponent(workspaceId)}/entitlements`);
  return parseApiResponse(resp) as Promise<WorkspaceEntitlement>;
}

export async function patchAdminWorkspaceEntitlements(
  workspaceId: string,
  payload: {
    plan?: string;
    limits?: Record<string, any>;
    features?: Record<string, any>;
  }
) {
  const resp = await apiFetch(`${API_BASE}/admin/workspaces/${encodeURIComponent(workspaceId)}/entitlements`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp) as Promise<WorkspaceEntitlement>;
}

export async function getAdminWorkspaceUsage(workspaceId: string, days = 30) {
  const resp = await apiFetch(
    `${API_BASE}/admin/workspaces/${encodeURIComponent(workspaceId)}/usage?days=${encodeURIComponent(String(days))}`
  );
  return parseApiResponse(resp) as Promise<WorkspaceUsageSummary>;
}

export async function getWorkspaceUsage(workspaceId: string, days = 30) {
  const resp = await apiFetch(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/usage?days=${encodeURIComponent(String(days))}`
  );
  return parseApiResponse(resp) as Promise<WorkspaceUsageSummary>;
}

export type EnvironmentProfileRow = {
  environment: string;
  variables_configured: number;
  variables_total: number;
  validation_passed: number;
  validation_total: number;
  sync_healthy: number;
  sync_total: number;
};

export type ProjectEnvironmentCenter = {
  project_id: string;
  workspace_id?: string | null;
  environments: EnvironmentProfileRow[];
};

export type ProjectEnvironmentVariableRow = {
  id: string;
  tenant_id: string;
  workspace_id?: string | null;
  project_id: string;
  environment: string;
  var_key: string;
  value_kind: string;
  vault_ref?: string | null;
  has_value: boolean;
  required: boolean;
  source?: string | null;
  validation_regex?: string | null;
  updated_by?: string | null;
  created_at: string;
  updated_at: string;
};

export type EnvironmentValidationResultRow = {
  id: string;
  project_id: string;
  environment: string;
  check_key: string;
  status: string;
  message?: string | null;
  checked_at: string;
};

export type EnvironmentSyncStatusRow = {
  id: string;
  project_id: string;
  environment: string;
  provider: string;
  status: string;
  message?: string | null;
  drift_detected: boolean;
  last_synced_at?: string | null;
  updated_at: string;
};

export type EnvironmentChecklistSummary = {
  project_id: string;
  workspace_id?: string | null;
  score_pct: number;
  total: number;
  completed: number;
  environments: Array<{
    environment: string;
    total: number;
    completed: number;
    platform_total: number;
    platform_completed: number;
    user_pending: number;
    score_pct: number;
  }>;
  items: Array<{
    id: string;
    environment: string;
    item_key: string;
    label: string;
    owner: "platform" | "user" | string;
    status: string;
    required: boolean;
    note?: string | null;
  }>;
};

export type EnvironmentTemplateVar = {
  key: string;
  required: boolean;
  scope: string;
  source: string;
  validation_regex?: string | null;
};

export type EnvironmentTemplate = {
  key: string;
  name: string;
  description: string;
  deployment_targets: string[];
  provider_mappings: Record<string, string>;
  variables: EnvironmentTemplateVar[];
};

export type DeploymentReadinessContract = {
  project_id: string;
  environment: "PREVIEW" | "STAGING" | "PRODUCTION" | string;
  score_pct: number;
  safe_to_preview: boolean;
  safe_to_production: boolean;
  blockers: string[];
  warnings: string[];
  recommended_actions: string[];
  confidence_score: number;
  categories: Record<string, { blockers: string[]; warnings: string[] }>;
  evidence: Record<string, any>;
};

export type ComponentCapabilityContractRow = {
  id: string;
  tenant_id: string;
  workspace_id?: string | null;
  project_id: string;
  environment: string;
  capability: string;
  contract_json: Record<string, any>;
  status: string;
  approved_by?: string | null;
  approved_at?: string | null;
  created_by?: string | null;
  updated_by?: string | null;
  created_at: string;
  updated_at: string;
};

export async function getProjectEnvironmentCenter(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/environments`);
  return parseApiResponse(resp) as Promise<ProjectEnvironmentCenter>;
}

export async function getProjectEnvironmentChecklists(projectId: string, reseed = false) {
  const resp = await apiFetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/environment-checklists?reseed=${reseed ? "true" : "false"}`
  );
  return parseApiResponse(resp) as Promise<EnvironmentChecklistSummary>;
}

export async function getWorkspaceEnvironmentChecklists(workspaceId: string, reseed = false) {
  const resp = await apiFetch(
    `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/environment-checklists?reseed=${reseed ? "true" : "false"}`
  );
  return parseApiResponse(resp) as Promise<EnvironmentChecklistSummary[]>;
}

export async function listProjectEnvironmentVariables(projectId: string, environment: string) {
  const resp = await apiFetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/environments/${encodeURIComponent(environment)}/variables`
  );
  return parseApiResponse(resp) as Promise<ProjectEnvironmentVariableRow[]>;
}

export async function upsertProjectEnvironmentVariable(
  projectId: string,
  environment: string,
  varKey: string,
  payload: {
    value_kind?: "secret" | "plain";
    plain_value?: string | null;
    vault_ref?: string | null;
    required?: boolean;
    source?: string | null;
    validation_regex?: string | null;
  }
) {
  const resp = await apiFetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/environments/${encodeURIComponent(environment)}/variables/${encodeURIComponent(varKey)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  return parseApiResponse(resp) as Promise<ProjectEnvironmentVariableRow>;
}

export async function writeProjectEnvironmentVariableSecret(
  projectId: string,
  environment: string,
  varKey: string,
  value: string
) {
  const resp = await apiFetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/environments/${encodeURIComponent(environment)}/variables/${encodeURIComponent(varKey)}/secret`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    }
  );
  return parseApiResponse(resp) as Promise<ProjectEnvironmentVariableRow>;
}

export async function validateProjectEnvironment(
  projectId: string,
  environment: string,
  payload: { checks?: string[]; reason?: string | null } = {}
) {
  const resp = await apiFetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/environments/${encodeURIComponent(environment)}/validate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  return parseApiResponse(resp) as Promise<EnvironmentValidationResultRow[]>;
}

export async function syncProjectEnvironment(
  projectId: string,
  environment: string,
  provider: "vercel" | "render" | "railway",
  payload: { reason?: string | null } = {}
) {
  const resp = await apiFetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/environments/${encodeURIComponent(environment)}/sync/${encodeURIComponent(provider)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  return parseApiResponse(resp) as Promise<EnvironmentSyncStatusRow>;
}

export async function listProjectEnvironmentTemplates(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/environment-templates`);
  return parseApiResponse(resp) as Promise<EnvironmentTemplate[]>;
}

export async function applyProjectEnvironmentTemplate(
  projectId: string,
  templateKey: string,
  payload: { environment: "PREVIEW" | "STAGING" | "PRODUCTION"; include_optional?: boolean }
) {
  const resp = await apiFetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/environment-templates/${encodeURIComponent(templateKey)}/apply`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  return parseApiResponse(resp) as Promise<ProjectEnvironmentVariableRow[]>;
}

export async function fetchProjectDeploymentReadiness(
  projectId: string,
  environment?: "PREVIEW" | "STAGING" | "PRODUCTION"
) {
  const query = environment ? `?environment=${encodeURIComponent(environment)}` : "";
  const resp = await apiFetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/deployment-readiness${query}`);
  return parseApiResponse(resp) as Promise<DeploymentReadinessContract>;
}

export async function listProjectComponentCapabilityContracts(
  projectId: string,
  environment: "PREVIEW" | "STAGING" | "PRODUCTION"
) {
  const resp = await apiFetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/component-capability-contracts?environment=${encodeURIComponent(environment)}`
  );
  return parseApiResponse(resp) as Promise<ComponentCapabilityContractRow[]>;
}

export async function upsertProjectComponentCapabilityContract(
  projectId: string,
  payload: {
    environment: "PREVIEW" | "STAGING" | "PRODUCTION";
    capability: string;
    contract_json: Record<string, any>;
  }
) {
  const resp = await apiFetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/component-capability-contracts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp) as Promise<ComponentCapabilityContractRow>;
}

export async function approveProjectComponentCapabilityContract(
  projectId: string,
  payload: {
    environment: "PREVIEW" | "STAGING" | "PRODUCTION";
    capability: string;
    approved_by?: string | null;
  }
) {
  const resp = await apiFetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/component-capability-contracts/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp) as Promise<ComponentCapabilityContractRow>;
}

export async function materializeAdminWorkspaceUsage(workspaceId: string, days = 30) {
  const resp = await apiFetch(
    `${API_BASE}/admin/workspaces/${encodeURIComponent(workspaceId)}/usage/materialize?days=${encodeURIComponent(String(days))}`,
    { method: "POST" }
  );
  return parseApiResponse(resp);
}

export async function materializeAdminAnomalies(days = 30) {
  const resp = await apiFetch(`${API_BASE}/admin/anomalies/materialize?days=${encodeURIComponent(String(days))}`, {
    method: "POST",
  });
  return parseApiResponse(resp) as Promise<WorkspaceAnomalySnapshot[]>;
}

export async function listAdminAnomalies(params?: { workspace_id?: string; days?: number; limit?: number }) {
  const search = new URLSearchParams();
  if (params?.workspace_id) search.set("workspace_id", params.workspace_id);
  if (params?.days) search.set("days", String(params.days));
  if (params?.limit) search.set("limit", String(params.limit));
  const qs = search.toString();
  const resp = await apiFetch(`${API_BASE}/admin/anomalies${qs ? `?${qs}` : ""}`);
  return parseApiResponse(resp) as Promise<WorkspaceAnomalySnapshot[]>;
}

export async function getAdminDaemonHealth() {
  const resp = await apiFetch(`${API_BASE}/admin/daemon-health`);
  return parseApiResponse(resp) as Promise<AdminDaemonHealth>;
}

export async function fetchMissionControlOverview(
  projectId: string,
  options: { includeHeavy?: boolean; forceRefresh?: boolean } = {}
) {
  const search = new URLSearchParams();
  if (options.includeHeavy) search.set("include_heavy", "true");
  if (options.forceRefresh) search.set("force_refresh", "true");
  const qs = search.toString();
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/mission-control/overview${qs ? `?${qs}` : ""}`);
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
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/memory/timeline${qs ? `?${qs}` : ""}`);
  return parseApiResponse(resp);
}

export async function backfillProjectMemoryTimeline(projectId: string, limit = 200) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/memory/timeline/backfill?limit=${encodeURIComponent(String(limit))}`, {
    method: "POST",
  });
  return parseApiResponse(resp);
}

export async function materializeProjectMemorySummaries(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/memory/summaries/materialize`, {
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
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/memory/summaries${qs ? `?${qs}` : ""}`);
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
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/memory/explain${qs ? `?${qs}` : ""}`);
  return parseApiResponse(resp);
}

export async function fetchProjectUnderstanding(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/memory/project-understanding`);
  return parseApiResponse(resp);
}

export async function fetchRepoMap(projectId: string, limit = 180) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/repo-map?limit=${encodeURIComponent(String(limit))}`);
  try {
    return await parseApiResponse(resp);
  } catch (err) {
    if (isApiErrorStatus(err, 409)) return createEmptyRepoMap((err as any)?.message);
    throw err;
  }
}

export async function updateProjectStage(projectId: string, toStage: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/stage`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to_stage: toStage })
  });
  return parseApiResponse(resp);
}

export async function listDocuments(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/documents`);
  return parseApiResponse(resp);
}

export async function createDocument(projectId: string, payload: CreateDocumentPayload) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchProjectRepo(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/repo`);
  try {
    return await parseApiResponse(resp);
  } catch (err) {
    if (isApiErrorStatus(err, 404)) return null;
    throw err;
  }
}

export async function connectProjectRepo(projectId: string, payload: ConnectRepoPayload) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/connect-repo`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function preflightProjectRepo(projectId: string, payload: RepoPreflightPayload) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/repo/preflight`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function bootstrapProjectRepo(projectId: string, payload: RepoBootstrapPayload) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/repo/bootstrap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchProjectPreviewProfile(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/preview-profile`);
  try {
    return await parseApiResponse(resp);
  } catch (err) {
    if (isApiErrorStatus(err, 404)) return createEmptyProjectPreviewProfile((err as any)?.message);
    throw err;
  }
}

export async function fetchProjectArchitectureProfile(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/architecture-profile`);
  return parseApiResponse(resp);
}

export async function fetchProjectArchitectureProfileSummary(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/architecture-profile/summary`);
  try {
    return await parseApiResponse(resp);
  } catch (err) {
    if (isApiErrorStatus(err, 404)) return createEmptyArchitectureProfileSummary((err as any)?.message);
    throw err;
  }
}

export async function saveProjectArchitectureProfile(projectId: string, payload: ArchitectureProfileUpsertPayload) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/architecture-profile`, {
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
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/architecture-profile/bootstrap`, {
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
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/architecture-profile/derive`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchProjectContract(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/project-contract`);
  return parseApiResponse(resp);
}

export async function fetchProjectContractSummary(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/project-contract/summary`);
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
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/project-contract`, {
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
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/project-contract`, {
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
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/project-contract/bootstrap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchDesignContract(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/design-contract`);
  if (resp.status !== 404) return parseApiResponse(resp);
  const legacyResp = await apiFetch(`${API_BASE}/projects/${projectId}/project-contract`);
  const legacy = await parseApiResponse(legacyResp);
  const contract = legacy?.contract_json?.design_contract;
  if (contract && typeof contract === "object") return contract;
  return {
    experience_blueprint: "premium_saas",
    identity: { name: "Project", tone: "technical_minimal_premium", personality: "confident_operational_clean" },
    tokens: {},
    token_registry: { colors: {}, spacing: {}, radius: {}, motion: {}, elevation: {} },
    allowed_components: [],
    typography: { heading_font: "Inter", body_font: "Inter", radius_scale: "soft", density: "comfortable" },
    components: {},
    layout: { spacing: "airy", container_width: "wide", visual_weight: "balanced", hero_style: "immersive" },
  };
}

export async function saveDesignContract(projectId: string, payload: {
  experience_blueprint?: string;
  identity?: {
    name?: string;
    tone?: string;
    personality?: string;
  };
  tokens?: Record<string, string>;
  token_registry?: {
    colors?: Record<string, string>;
    spacing?: Record<string, string>;
    radius?: Record<string, string>;
    motion?: Record<string, string>;
    elevation?: Record<string, string>;
  };
  allowed_components?: string[];
  typography?: {
    heading_font?: string;
    body_font?: string;
    radius_scale?: string;
    density?: string;
  };
  components?: Record<string, any>;
  layout?: {
    spacing?: string;
    container_width?: string;
    visual_weight?: string;
    hero_style?: string;
  };
  updated_by?: string | null;
}) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/design-contract`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (resp.status !== 404) return parseApiResponse(resp);

  let existing: any = null;
  const legacyResp = await apiFetch(`${API_BASE}/projects/${projectId}/project-contract`);
  if (legacyResp.ok) {
    existing = await parseApiResponse(legacyResp);
  }
  const contractJson = existing?.contract_json && typeof existing.contract_json === "object"
    ? { ...existing.contract_json }
    : {};
  contractJson.design_contract = {
    ...(contractJson.design_contract && typeof contractJson.design_contract === "object"
      ? contractJson.design_contract
      : {}),
    ...payload,
  };
  const fallbackSaveResp = await apiFetch(`${API_BASE}/projects/${projectId}/project-contract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      status: existing?.status || "DRAFT",
      source: existing?.source || "MANUAL",
      summary: existing?.summary || "Design contract updated via compatibility fallback.",
      contract_json: contractJson,
      updated_by: payload.updated_by || null,
    }),
  });
  return parseApiResponse(fallbackSaveResp);
}

export async function fetchGitHubConnectInfo(): Promise<GitHubConnectInfo> {
  const resp = await apiFetch(`${API_BASE}/integrations/github/connect`);
  return parseApiResponse(resp);
}

export async function listGitHubInstallationRepositories(
  installationId: number
): Promise<GitHubInstallationRepository[]> {
  const resp = await apiFetch(`${API_BASE}/integrations/github/installations/${installationId}/repositories`);
  return parseApiResponse(resp);
}

export async function saveProjectPreviewProfile(projectId: string, payload: PreviewProfilePayload) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/preview-profile`, {
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
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/approvals${suffix}`);
  return parseApiResponse(resp);
}

export async function createApproval(projectId: string, payload: CreateApprovalPayload) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/approvals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

// Runs
export async function listRuns(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/runs`, {
    cache: "no-store",
  });
  return parseApiResponse(resp);
}

export async function createRun(
  projectId: string,
  executor = "codex",
  taskId?: string | null,
  runKind?: string | null,
  options: { request_key?: string; force_rerun?: boolean } = {}
) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      executor,
      task_id: taskId || null,
      run_kind: runKind || null,
      request_key: options.request_key || null,
      force_rerun: Boolean(options.force_rerun),
    }),
  });
  return parseApiResponse(resp);
}

export async function fetchTaskRerunPreflight(projectId: string, taskId: string) {
  let resp = await apiFetch(`${API_BASE}/projects/${projectId}/tasks/${taskId}/rerun-preflight`, {
    cache: "no-store",
  });
  if (resp.status === 404) {
    resp = await apiFetch(`${API_BASE}/store/projects/${projectId}/tasks/${taskId}/rerun-preflight`, {
      cache: "no-store",
    });
  }
  return parseApiResponse(resp);
}

export async function createTaskRerunNoopAttempt(projectId: string, taskId: string) {
  let resp = await apiFetch(`${API_BASE}/projects/${projectId}/tasks/${taskId}/rerun-noop-attempt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (resp.status === 404) {
    resp = await apiFetch(`${API_BASE}/store/projects/${projectId}/tasks/${taskId}/rerun-noop-attempt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
  }
  return parseApiResponse(resp);
}

export async function createVisionRun(payload: VisionRunCreatePayload) {
  const resp = await apiFetch(`${API_BASE}/tasks/vision-run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function updateRunStatus(runId: string, status: string) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status })
  });
  return parseApiResponse(resp);
}

export async function resumeRun(runId: string, payload: { start_now?: boolean } = {}) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start_now: payload.start_now ?? true }),
  });
  return parseApiResponse(resp);
}

export async function unblockRun(runId: string) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/unblock`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return parseApiResponse(resp);
}

export async function confirmAndContinueRun(runId: string) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/confirm-and-continue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return parseApiResponse(resp);
}

export async function retryRunPush(runId: string, payload: { auth_strategy?: string } = {}) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/retry-push`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function discardRun(runId: string) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/discard`, {
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
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/budget/extend`, {
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
    request_key?: string;
  } = {}
) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/fork`, {
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
    request_key?: string;
  } = {}
) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/create-pr`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchRunPreview(runId: string) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/preview`);
  return parseApiResponse(resp);
}

export async function launchRunPreview(
  runId: string,
  payload: {
    reuse_if_healthy?: boolean;
  } = {}
) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function deleteRunPreview(runId: string) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/preview`, {
    method: "DELETE",
  });
  return parseApiResponse(resp);
}

export async function createProjectDeployment(projectId: string, payload: ProjectDeploymentCreatePayload) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/deployments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function listProjectDeployments(projectId: string, limit = 20) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/deployments?limit=${encodeURIComponent(String(limit))}`);
  return parseApiResponse(resp);
}

export async function listDeploymentEvents(deploymentId: string, limit = 60) {
  const resp = await apiFetch(`${API_BASE}/deployments/${deploymentId}/events?limit=${encodeURIComponent(String(limit))}`);
  return parseApiResponse(resp);
}

export async function listDeploymentConnectors(provider?: string) {
  const qs = provider ? `?provider=${encodeURIComponent(provider)}` : "";
  const resp = await apiFetch(`${API_BASE}/deployment-connectors${qs}`);
  return parseApiResponse(resp);
}

export type CapabilityDefinition = {
  id: string;
  capability_key: string;
  category: string;
  required: boolean;
  supported_providers?: string[];
  description?: string | null;
};

export type CapabilityIntegration = {
  id: string;
  project_id: string;
  provider: string;
  label: string;
  environment: "LOCAL_DEV" | "PREVIEW" | "STAGING" | "PRODUCTION";
  status: string;
  capabilities?: string[];
  health_status: string;
  credentials_vault_ref?: string | null;
  failure_reason?: string | null;
};

export type CapabilityBinding = {
  id: string;
  project_id: string;
  environment: "LOCAL_DEV" | "PREVIEW" | "STAGING" | "PRODUCTION";
  capability_key: string;
  integration_id: string;
  target?: string | null;
  status: string;
};

export async function listCapabilities(requiredOnly = false): Promise<CapabilityDefinition[]> {
  const qs = requiredOnly ? "?required_only=true" : "";
  const resp = await apiFetch(`${API_BASE}/capabilities${qs}`);
  return parseApiResponse(resp);
}

export async function listCapabilityIntegrations(projectId: string, environment: string): Promise<CapabilityIntegration[]> {
  const qs = `?environment=${encodeURIComponent(environment)}`;
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/capability-integrations${qs}`);
  return parseApiResponse(resp);
}

export async function upsertCapabilityIntegration(projectId: string, payload: Record<string, any>): Promise<CapabilityIntegration> {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/capability-integrations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function listCapabilityBindings(projectId: string, environment: string): Promise<CapabilityBinding[]> {
  const qs = `?environment=${encodeURIComponent(environment)}`;
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/capability-bindings${qs}`);
  return parseApiResponse(resp);
}

export async function upsertCapabilityBinding(projectId: string, payload: Record<string, any>): Promise<CapabilityBinding> {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/capability-bindings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchCapabilityGovernanceCheck(projectId: string, environment: string) {
  const qs = `?environment=${encodeURIComponent(environment)}`;
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/capability-governance-check${qs}`);
  return parseApiResponse(resp);
}

export async function retryProjectDeployment(deploymentId: string, payload: { force?: boolean } = {}) {
  const resp = await apiFetch(`${API_BASE}/deployments/${deploymentId}/retry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function rollbackProjectDeployment(
  deploymentId: string,
  payload: { reason?: string; trigger?: string; request_key?: string; created_by?: string } = {}
) {
  const resp = await apiFetch(`${API_BASE}/deployments/${deploymentId}/rollback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function promoteProjectDeployment(
  deploymentId: string,
  payload: { target_environment: "STAGING" | "PRODUCTION"; reason?: string; request_key?: string; created_by?: string }
) {
  const resp = await apiFetch(`${API_BASE}/deployments/${deploymentId}/promote`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function preflightProjectDeployment(
  projectId: string,
  payload: {
    provider: string;
    environment?: "PREVIEW" | "STAGING" | "PRODUCTION";
    deployment_strategy?: string;
    repository_url?: string | null;
    repository_full_name?: string | null;
    branch_name?: string | null;
  }
) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/deployments/preflight`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchProjectDeploymentIntelligence(projectId: string, limit = 80) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/deployments/intelligence?limit=${encodeURIComponent(String(limit))}`);
  return parseApiResponse(resp);
}

export async function compareRuns(runA: string, runB: string) {
  const resp = await apiFetch(
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
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/strategies`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchRunStrategies(runId: string) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/strategies`);
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
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/timeline`);
  return parseApiResponse(resp);
}

export async function fetchRunNarrative(runId: string) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/narrative`);
  return parseApiResponse(resp);
}

export async function fetchRunExecutionConsole(runId: string) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/execution-console`);
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
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/runs/memory?${query.toString()}`);
  return parseApiResponse(resp);
}

export async function fetchHealth(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/health`);
  return parseApiResponse(resp);
}

export async function fetchLifecycleScore(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/lifecycle-score`);
  return parseApiResponse(resp);
}

export async function fetchLifecycleScoreHistory(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/lifecycle-score-history`);
  return parseApiResponse(resp);
}

// Work items / DAG / events
export async function listWorkItems(projectId: string, runId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/runs/${runId}/work-items`);
  return parseApiResponse(resp);
}

export async function getWorkDag(runId: string) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/work-dag`);
  return parseApiResponse(resp);
}

export async function listRunEvents(runId: string) {
  const resp = await apiFetch(`${API_BASE}/runs/${runId}/events`);
  return parseApiResponse(resp);
}

export async function listAgents() {
  const resp = await apiFetch(`${API_BASE}/agents`);
  return parseApiResponse(resp);
}

export async function listArtifacts(projectId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/artifacts`);
  return parseApiResponse(resp);
}

export async function explainArtifact(projectId: string, artifactId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/artifacts/${artifactId}/explain`);
  return parseApiResponse(resp);
}

export async function fetchArtifactDiff(projectId: string, artifactId: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/artifacts/${artifactId}/diff`);
  return parseApiResponse(resp);
}

export async function fetchArtifactContextByUri(projectId: string, uri: string) {
  const resp = await apiFetch(`${API_BASE}/projects/${projectId}/artifacts/context?uri=${encodeURIComponent(uri)}`);
  return parseApiResponse(resp);
}

export async function sendOperatorMessage(payload: OperatorMessagePayload) {
  const resp = await apiFetch(`${API_BASE}/ai/operator`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp) as Promise<OperatorResponse>;
}
