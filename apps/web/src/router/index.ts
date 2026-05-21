import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import { isApiErrorStatus } from "../api/http";
import { fetchProjectMeta, getActiveTenantId, getActiveWorkspaceId, getAuthToken, removeRecentProjectScoped } from "../api/lifecycle";
import { updateProjectContext } from "../state/projectContext";

const routes: RouteRecordRaw[] = [
  { path: "/", name: "public-landing", component: () => import("../views/PublicLanding.vue"), meta: { layout: "minimal" } },
  { path: "/features", name: "public-features", component: () => import("../views/PublicLanding.vue"), meta: { layout: "minimal" } },
  { path: "/pricing", name: "public-pricing", component: () => import("../views/PublicLanding.vue"), meta: { layout: "minimal" } },
  { path: "/docs", name: "public-docs", component: () => import("../views/PublicLanding.vue"), meta: { layout: "minimal" } },
  { path: "/privacy", name: "public-privacy", component: () => import("../views/PrivacyPolicy.vue"), meta: { layout: "minimal" } },
  { path: "/terms", name: "public-terms", component: () => import("../views/TermsOfService.vue"), meta: { layout: "minimal" } },
  { path: "/data-deletion", name: "public-data-deletion", component: () => import("../views/DataDeletion.vue"), meta: { layout: "minimal" } },
  { path: "/security", name: "public-security", component: () => import("../views/SecurityOverview.vue"), meta: { layout: "minimal" } },
  { path: "/workspace", name: "workspace", component: () => import("../views/WorkspaceHome.vue"), meta: { requiresAuth: true } },
  { path: "/workspace/dashboard", name: "workspace-dashboard", component: () => import("../views/WorkspaceDashboard.vue"), meta: { requiresAuth: true } },
  { path: "/admin", name: "admin-console", component: () => import("../views/AdminConsole.vue"), meta: { requiresAuth: true } },
  { path: "/signin", name: "signin", component: () => import("../views/SignIn.vue"), meta: { layout: "minimal" } },
  { path: "/help/run-guide", name: "run-guide", component: () => import("../views/RunGuide.vue"), meta: { requiresAuth: true } },
  { path: "/__e2e__/smoke", name: "e2e-smoke", component: () => import("../views/E2ESmokeHarness.vue"), meta: { layout: "minimal" } },
  { path: "/projects/:projectId/operator", name: "operator-dashboard", component: () => import("../views/OperatorDashboard.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId", name: "project-overview", component: () => import("../views/ProjectOverview.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId/tasks", name: "project-tasks", component: () => import("../views/ProjectOverview.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId/environments", name: "project-environment-center", component: () => import("../views/ProjectEnvironmentCenter.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId/requirements", name: "requirements", component: () => import("../views/Requirements.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId/run", name: "mission-control", component: () => import("../views/MissionControl.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId/map", name: "automation-map", component: () => import("../views/AutomationMap.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId/timeline", name: "timeline", component: () => import("../views/SdlcTimeline.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId/runs/:runId/debug", name: "run-debug", component: () => import("../views/SdlcTimeline.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId/approvals", name: "approvals", component: () => import("../views/Approvals.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId/runs", name: "agent-runs", component: () => import("../views/AgentRuns.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId/ai-ops", name: "ai-ops", component: () => import("../views/AiOpsDashboard.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId/knowledge", name: "knowledge-inbox", component: () => import("../views/KnowledgeInbox.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId/knowledge/proposals/:proposalId", name: "knowledge-proposal", component: () => import("../views/KnowledgeProposalDetail.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId/knowledge/artifacts/:artifactId", name: "knowledge-artifact", component: () => import("../views/KnowledgeArtifactDetail.vue"), meta: { requiresAuth: true } },
  { path: "/projects/:projectId/knowledge/events/:eventId", name: "knowledge-event", component: () => import("../views/KnowledgeEventDetail.vue"), meta: { requiresAuth: true } }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

const validatedProjectIds = new Set<string>();
let validatedTenantId: string | null = null;
let validatedWorkspaceId: string | null = null;

function removeRecentProject(projectId: string) {
  removeRecentProjectScoped(projectId);
}

function clearProjectContext() {
  updateProjectContext({
    projectId: "",
    projectName: "No project selected",
    stage: "UNKNOWN",
    runStatus: "IDLE",
    latestRunId: "",
    activeAgents: 0,
    updatedAt: null,
    hasActiveRun: false,
    architectureRefreshNeeded: false,
    planRefreshNeeded: false,
    testRefreshNeeded: false,
  });
}

router.beforeEach(async (to) => {
  const isSignedIn = Boolean(getAuthToken());
  const requiresAuth = Boolean(to.meta?.requiresAuth);
  if (requiresAuth && !isSignedIn) {
    return { path: "/signin", query: { redirect: to.fullPath } };
  }
  if (to.path === "/signin" && isSignedIn) {
    const redirectPath = typeof to.query.redirect === "string" && to.query.redirect ? to.query.redirect : "/workspace";
    return { path: redirectPath };
  }

  const activeTenantId = getActiveTenantId();
  const activeWorkspaceId = getActiveWorkspaceId();
  if (validatedTenantId !== activeTenantId || validatedWorkspaceId !== activeWorkspaceId) {
    validatedProjectIds.clear();
    validatedTenantId = activeTenantId;
    validatedWorkspaceId = activeWorkspaceId;
    clearProjectContext();
  }

  const rawProjectId = to.params.projectId;
  const projectId = Array.isArray(rawProjectId) ? rawProjectId[0] : rawProjectId;

  if (!projectId) {
    return true;
  }

  if (!activeTenantId) {
    validatedProjectIds.delete(projectId);
    clearProjectContext();
    return {
      path: "/workspace",
      query: { tenantRequired: "1", requestedProject: projectId },
    };
  }

  if (validatedProjectIds.has(projectId)) {
    return true;
  }

  try {
    await fetchProjectMeta(projectId);
    validatedProjectIds.add(projectId);
    return true;
  } catch (error) {
    if (!isApiErrorStatus(error, 404)) {
      return true;
    }

    validatedProjectIds.delete(projectId);
    removeRecentProject(projectId);
    clearProjectContext();
    return {
      path: "/workspace",
      query: { missingProject: projectId },
    };
  }
});

export default router;
