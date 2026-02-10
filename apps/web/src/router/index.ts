import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import ProjectOverview from "../views/ProjectOverview.vue";
import MissionControl from "../views/MissionControl.vue";
import SdlcTimeline from "../views/SdlcTimeline.vue";
import Approvals from "../views/Approvals.vue";
import AgentRuns from "../views/AgentRuns.vue";

const routes: RouteRecordRaw[] = [
  { path: "/", name: "overview", component: ProjectOverview },
  { path: "/projects/:projectId", name: "mission-control", component: MissionControl },
  { path: "/timeline", name: "timeline", component: SdlcTimeline },
  { path: "/approvals", name: "approvals", component: Approvals },
  { path: "/agent-runs", name: "agent-runs", component: AgentRuns }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

export default router;
