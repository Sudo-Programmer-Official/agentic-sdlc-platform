import { parseApiResponse } from "./http";

const DEFAULT_API_BASE = import.meta.env.DEV
  ? "http://localhost:8000/api/v1"
  : "https://api.prompt2pr.com/api/v1";

const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;

export type KnowledgeInboxFilters = {
  project_id?: string;
  repository_id?: string;
  review_status?: string;
  change_type?: string;
  artifact_type?: string;
  risk_level?: string;
};

export type KnowledgeDecisionPayload = {
  review_notes?: string | null;
};

export type KnowledgeEditApprovePayload = KnowledgeDecisionPayload & {
  edited_content: string;
};

export type KnowledgeManualSyncPayload = {
  project_id: string;
  title?: string | null;
  branch_name?: string | null;
  commit_sha?: string | null;
};

function buildQuery(params: Record<string, string | boolean | null | undefined>) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key, String(value));
  });
  const suffix = query.toString();
  return suffix ? `?${suffix}` : "";
}

export async function triggerKnowledgeManualSync(payload: KnowledgeManualSyncPayload) {
  const resp = await fetch(`${API_BASE}/knowledge/events/manual-sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchKnowledgeInbox(filters: KnowledgeInboxFilters) {
  const resp = await fetch(`${API_BASE}/knowledge/inbox${buildQuery(filters)}`);
  return parseApiResponse(resp);
}

export async function fetchKnowledgeProposals(params: {
  project_id?: string;
  repository_id?: string;
  review_status?: string;
} = {}) {
  const resp = await fetch(`${API_BASE}/knowledge/proposals${buildQuery(params)}`);
  return parseApiResponse(resp);
}

export async function fetchKnowledgeProposal(projectId: string, proposalId: string) {
  const resp = await fetch(`${API_BASE}/knowledge/proposals/${proposalId}${buildQuery({ project_id: projectId })}`);
  return parseApiResponse(resp);
}

export async function approveKnowledgeProposal(projectId: string, proposalId: string, payload: KnowledgeDecisionPayload = {}) {
  const resp = await fetch(`${API_BASE}/knowledge/proposals/${proposalId}/approve${buildQuery({ project_id: projectId })}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function editAndApproveKnowledgeProposal(projectId: string, proposalId: string, payload: KnowledgeEditApprovePayload) {
  const resp = await fetch(
    `${API_BASE}/knowledge/proposals/${proposalId}/edit-and-approve${buildQuery({ project_id: projectId })}`,
    {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    }
  );
  return parseApiResponse(resp);
}

export async function rejectKnowledgeProposal(projectId: string, proposalId: string, payload: KnowledgeDecisionPayload = {}) {
  const resp = await fetch(`${API_BASE}/knowledge/proposals/${proposalId}/reject${buildQuery({ project_id: projectId })}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function deferKnowledgeProposal(projectId: string, proposalId: string, payload: KnowledgeDecisionPayload = {}) {
  const resp = await fetch(`${API_BASE}/knowledge/proposals/${proposalId}/defer${buildQuery({ project_id: projectId })}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(resp);
}

export async function fetchKnowledgeArtifacts(params: {
  project_id?: string;
  repository_id?: string;
  query?: string;
  include_drafts?: boolean;
} = {}) {
  const resp = await fetch(`${API_BASE}/knowledge/artifacts${buildQuery(params)}`);
  return parseApiResponse(resp);
}

export async function fetchKnowledgeArtifact(projectId: string, artifactId: string) {
  const resp = await fetch(`${API_BASE}/knowledge/artifacts/${artifactId}${buildQuery({ project_id: projectId })}`);
  return parseApiResponse(resp);
}

export async function fetchKnowledgeEvent(projectId: string, eventId: string) {
  const resp = await fetch(`${API_BASE}/knowledge/events/${eventId}${buildQuery({ project_id: projectId })}`);
  return parseApiResponse(resp);
}
