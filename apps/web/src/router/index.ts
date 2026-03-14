import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import WorkspaceHome from "../views/WorkspaceHome.vue";
import OperatorDashboard from "../views/OperatorDashboard.vue";
import ProjectOverview from "../views/ProjectOverview.vue";
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

const routes: RouteRecordRaw[] = [
  { path: "/", name: "workspace", component: WorkspaceHome },
  { path: "/projects/:projectId/operator", name: "operator-dashboard", component: OperatorDashboard },
  { path: "/projects/:projectId", name: "project-overview", component: ProjectOverview },
  { path: "/projects/:projectId/requirements", name: "requirements", component: Requirements },
  { path: "/projects/:projectId/run", name: "mission-control", component: MissionControl },
  { path: "/projects/:projectId/map", name: "automation-map", component: AutomationMap },
  { path: "/projects/:projectId/timeline", name: "timeline", component: SdlcTimeline },
  { path: "/projects/:projectId/runs/:runId/debug", name: "run-debug", component: SdlcTimeline },
  { path: "/projects/:projectId/approvals", name: "approvals", component: Approvals },
  { path: "/projects/:projectId/runs", name: "agent-runs", component: AgentRuns },
  { path: "/projects/:projectId/ai-ops", name: "ai-ops", component: AiOpsDashboard },
  { path: "/projects/:projectId/knowledge", name: "knowledge-inbox", component: KnowledgeInbox },
  { path: "/projects/:projectId/knowledge/proposals/:proposalId", name: "knowledge-proposal", component: KnowledgeProposalDetail },
  { path: "/projects/:projectId/knowledge/artifacts/:artifactId", name: "knowledge-artifact", component: KnowledgeArtifactDetail },
  { path: "/projects/:projectId/knowledge/events/:eventId", name: "knowledge-event", component: KnowledgeEventDetail }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

export default router;
