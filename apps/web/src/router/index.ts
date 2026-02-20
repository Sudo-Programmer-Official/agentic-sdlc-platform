import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import WorkspaceHome from "../views/WorkspaceHome.vue";
import ProjectOverview from "../views/ProjectOverview.vue";
import MissionControl from "../views/MissionControl.vue";
import SdlcTimeline from "../views/SdlcTimeline.vue";
import Approvals from "../views/Approvals.vue";
import AgentRuns from "../views/AgentRuns.vue";
import Requirements from "../views/Requirements.vue";

const routes: RouteRecordRaw[] = [
  { path: "/", name: "workspace", component: WorkspaceHome },
  { path: "/projects/:projectId", name: "project-overview", component: ProjectOverview },
  { path: "/projects/:projectId/requirements", name: "requirements", component: Requirements },
  { path: "/projects/:projectId/run", name: "mission-control", component: MissionControl },
  { path: "/projects/:projectId/timeline", name: "timeline", component: SdlcTimeline },
  { path: "/projects/:projectId/approvals", name: "approvals", component: Approvals },
  { path: "/projects/:projectId/runs", name: "agent-runs", component: AgentRuns }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

export default router;
