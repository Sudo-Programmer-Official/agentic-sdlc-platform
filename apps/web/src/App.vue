<template>
  <div class="app-shell">
    <aside class="app-sidebar">
      <div class="brand">
        <div class="brand-mark">
          <span class="brand-mark__orb" />
          <span>Agentic SDLC</span>
        </div>
        <div class="brand-copy">
          Mission Control for governed autonomous engineering execution.
        </div>
      </div>

      <div class="sidebar-group">
        <div class="sidebar-group__label">Navigation</div>
        <router-link
          v-for="item in navItems"
          :key="item.key"
          :to="item.disabled ? route.path : item.path"
          class="sidebar-link"
          :class="{
            'is-active': activePath === item.path,
            'is-disabled': item.disabled,
          }"
        >
          <span class="sidebar-link__icon">
            <AppIcon :name="item.icon" />
          </span>
          <span class="sidebar-link__meta">
            <span class="sidebar-link__label">{{ item.label }}</span>
            <div class="sidebar-link__hint">{{ item.hint }}</div>
          </span>
        </router-link>
      </div>

      <div class="sidebar-footer">
        <div class="sidebar-status-card">
          <div class="sidebar-status-card__label">Active Project</div>
          <div class="sidebar-status-card__value">{{ projectContext.projectName || "No project selected" }}</div>
          <div class="mt-2 flex items-center gap-2 text-xs" style="color: var(--text-soft);">
            <span class="soft-dot" :class="{ 'pulse-dot': projectContext.hasActiveRun }" />
            <span>{{ projectContext.hasActiveRun ? "Automation active" : "Ready to start" }}</span>
          </div>
        </div>

        <div class="sidebar-status-card">
          <div class="sidebar-status-card__label">Run Snapshot</div>
          <div class="mt-2 flex items-center justify-between">
            <span class="text-sm" style="color: var(--text-muted);">{{ projectContext.stage }}</span>
            <span class="status-ring" :style="runIndicatorStyle">{{ projectContext.runStatus }}</span>
          </div>
          <div class="mt-3 text-xs" style="color: var(--text-soft);">
            Latest run {{ projectContext.latestRunId ? projectContext.latestRunId.slice(0, 8) : "—" }}
          </div>
        </div>
      </div>
    </aside>

    <section class="app-content">
      <header class="app-header">
        <div class="topbar-shell">
          <TopBar />
        </div>
      </header>
      <main class="app-main">
        <router-view />
      </main>
    </section>

    <AiOperatorPanel />
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

import AiOperatorPanel from "./components/AiOperatorPanel.vue";
import AppIcon from "./components/AppIcon.vue";
import TopBar from "./components/TopBar.vue";
import { projectContext } from "./state/projectContext";

const route = useRoute();
const activePath = computed(() => route.path);

const projectPath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}` : "/"));
const operatorPath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/operator` : "/"));
const requirementsPath = computed(() =>
  projectContext.projectId ? `/projects/${projectContext.projectId}/requirements` : "/"
);
const missionControlPath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/run` : "/"));
const automationMapPath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/map` : "/"));
const timelinePath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/timeline` : "/"));
const approvalsPath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/approvals` : "/"));
const runsPath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/runs` : "/"));
const aiOpsPath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/ai-ops` : "/"));
const knowledgePath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/knowledge` : "/"));

const navItems = computed(() => [
  {
    key: "workspace",
    label: "Workspace",
    hint: "Projects, system state, quick launch",
    icon: "workspace",
    path: "/",
    disabled: false,
  },
  {
    key: "operator",
    label: "Operator Dashboard",
    hint: "Tasks, runs, narrative, repo map",
    icon: "operator",
    path: operatorPath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "project",
    label: "Project Overview",
    hint: "Lifecycle health and operator actions",
    icon: "project",
    path: projectPath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "requirements",
    label: "Requirements",
    hint: "PRDs, graph health, approvals",
    icon: "requirements",
    path: requirementsPath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "mission",
    label: "Mission Control",
    hint: "Live runtime, impact, replay, PRs",
    icon: "mission",
    path: missionControlPath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "map",
    label: "Automation Map",
    hint: "System graph for intake, runs, artifacts, delivery",
    icon: "map",
    path: automationMapPath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "timeline",
    label: "SDLC Timeline",
    hint: "Deterministic run replay",
    icon: "timeline",
    path: timelinePath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "approvals",
    label: "Approvals",
    hint: "Review gates and governance",
    icon: "approvals",
    path: approvalsPath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "ai-ops",
    label: "AI Ops",
    hint: "Spend, retries, context and approval burn patterns",
    icon: "operator",
    path: aiOpsPath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "knowledge",
    label: "Knowledge",
    hint: "Engineering memory and documentation verification",
    icon: "knowledge",
    path: knowledgePath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "runs",
    label: "Agent Runs",
    hint: "Execution history and operators",
    icon: "runs",
    path: runsPath.value,
    disabled: !projectContext.projectId,
  },
]);

const runIndicatorStyle = computed(() => {
  const status = (projectContext.runStatus || "").toUpperCase();
  if (status === "RUNNING" || status === "QUEUED") {
    return { background: "rgba(245, 158, 11, 0.12)", color: "var(--warning)" };
  }
  if (status === "COMPLETED") {
    return { background: "rgba(34, 197, 94, 0.12)", color: "var(--success)" };
  }
  if (status === "FAILED" || status === "CANCELED") {
    return { background: "rgba(239, 68, 68, 0.12)", color: "var(--danger)" };
  }
  return { background: "var(--surface-soft)", color: "var(--text-muted)" };
});
</script>
