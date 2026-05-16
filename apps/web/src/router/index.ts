import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import { isApiErrorStatus } from "../api/http";
import { fetchProjectMeta, getActiveTenantId, getActiveWorkspaceId, getAuthToken, removeRecentProjectScoped } from "../api/lifecycle";
import { updateProjectContext } from "../state/projectContext";
import WorkspaceHome from "../views/WorkspaceHome.vue";
import PublicLanding from "../views/PublicLanding.vue";
import PrivacyPolicy from "../views/PrivacyPolicy.vue";
import TermsOfService from "../views/TermsOfService.vue";
import DataDeletion from "../views/DataDeletion.vue";
import SecurityOverview from "../views/SecurityOverview.vue";
import WorkspaceDashboard from "../views/WorkspaceDashboard.vue";
import AdminConsole from "../views/AdminConsole.vue";
import OperatorDashboard from "../views/OperatorDashboard.vue";
import ProjectOverview from "../views/ProjectOverview.vue";
import ProjectEnvironmentCenter from "../views/ProjectEnvironmentCenter.vue";
import MissionControl from "../views/MissionControl.vue";
import AutomationMap from "../views/AutomationMap.vue";
import SdlcTimeline from "../views/SdlcTimeline.vue";
import Approvals from "../views/Approvals.vue";
import AgentRuns from "../views/AgentRuns.vue";
import Requirements from "../views/Requirements.vue";
import KnowledgeInbox from "../views/KnowledgeInbox.vue";
import KnowledgeProposalDetail from "../views/KnowledgeProposalDetail.vue";
import KnowledgeArtifactDetail from "../views/KnowledgeArtifactDetail.vue";
import KnowledgeEventDetail from "../views/KnowledgeEventDetail.vue";
import AiOpsDashboard from "../views/AiOpsDashboard.vue";
import SignIn from "../views/SignIn.vue";
import E2ESmokeHarness from "../views/E2ESmokeHarness.vue";

const routes: RouteRecordRaw[] = [
  { path: "/", name: "public-landing", component: PublicLanding, meta: { layout: "minimal" } },
  { path: "/features", name: "public-features", component: PublicLanding, meta: { layout: "minimal" } },
  { path: "/pricing", name: "public-pricing", component: PublicLanding, meta: { layout: "minimal" } },
  { path: "/docs", name: "public-docs", component: PublicLanding, meta: { layout: "minimal" } },
  { path: "/privacy", name: "public-privacy", component: PrivacyPolicy, meta: { layout: "minimal" } },
  { path: "/terms", name: "public-terms", component: TermsOfService, meta: { layout: "minimal" } },
  { path: "/data-deletion", name: "public-data-deletion", component: DataDeletion, meta: { layout: "minimal" } },
  { path: "/security", name: "public-security", component: SecurityOverview, meta: { layout: "minimal" } },
  { path: "/workspace", name: "workspace", component: WorkspaceHome, meta: { requiresAuth: true } },
  { path: "/workspace/dashboard", name: "workspace-dashboard", component: WorkspaceDashboard, meta: { requiresAuth: true } },
  { path: "/admin", name: "admin-console", component: AdminConsole, meta: { requiresAuth: true } },
  { path: "/signin", name: "signin", component: SignIn, meta: { layout: "minimal" } },
  { path: "/__e2e__/smoke", name: "e2e-smoke", component: E2ESmokeHarness, meta: { layout: "minimal" } },
  { path: "/projects/:projectId/operator", name: "operator-dashboard", component: OperatorDashboard, meta: { requiresAuth: true } },
  { path: "/projects/:projectId", name: "project-overview", component: ProjectOverview, meta: { requiresAuth: true } },
  { path: "/projects/:projectId/environments", name: "project-environment-center", component: ProjectEnvironmentCenter, meta: { requiresAuth: true } },
  { path: "/projects/:projectId/requirements", name: "requirements", component: Requirements, meta: { requiresAuth: true } },
  { path: "/projects/:projectId/run", name: "mission-control", component: MissionControl, meta: { requiresAuth: true } },
  { path: "/projects/:projectId/map", name: "automation-map", component: AutomationMap, meta: { requiresAuth: true } },
  { path: "/projects/:projectId/timeline", name: "timeline", component: SdlcTimeline, meta: { requiresAuth: true } },
  { path: "/projects/:projectId/runs/:runId/debug", name: "run-debug", component: SdlcTimeline, meta: { requiresAuth: true } },
  { path: "/projects/:projectId/approvals", name: "approvals", component: Approvals, meta: { requiresAuth: true } },
  { path: "/projects/:projectId/runs", name: "agent-runs", component: AgentRuns, meta: { requiresAuth: true } },
  { path: "/projects/:projectId/ai-ops", name: "ai-ops", component: AiOpsDashboard, meta: { requiresAuth: true } },
  { path: "/projects/:projectId/knowledge", name: "knowledge-inbox", component: KnowledgeInbox, meta: { requiresAuth: true } },
  { path: "/projects/:projectId/knowledge/proposals/:proposalId", name: "knowledge-proposal", component: KnowledgeProposalDetail, meta: { requiresAuth: true } },
  { path: "/projects/:projectId/knowledge/artifacts/:artifactId", name: "knowledge-artifact", component: KnowledgeArtifactDetail, meta: { requiresAuth: true } },
  { path: "/projects/:projectId/knowledge/events/:eventId", name: "knowledge-event", component: KnowledgeEventDetail, meta: { requiresAuth: true } }
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
