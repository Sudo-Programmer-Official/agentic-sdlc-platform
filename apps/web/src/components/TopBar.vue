<template>
  <div class="flex flex-col gap-4 p-4 lg:flex-row lg:items-center lg:justify-between">
    <div class="min-w-0 flex-1">
      <div class="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.28em]" style="color: var(--text-soft);">
        <span>{{ headerLabel }}</span>
        <span v-if="envText" class="topbar-chip">
          <AppIcon name="status" size="sm" />
          {{ envText }}
        </span>
      </div>
      <div class="mt-2 flex flex-wrap items-center gap-3">
        <div class="truncate text-2xl font-semibold" style="color: var(--text-strong);">
          {{ titleText }}
        </div>
        <div v-if="projectContext.projectId" class="status-ring" :style="runIndicatorStyle">
          <span class="soft-dot" :class="{ 'pulse-dot': projectContext.runStatus === 'RUNNING' }" />
          {{ projectContext.runStatus }}
        </div>
      </div>
      <div class="mt-2 flex flex-wrap items-center gap-2 text-xs" style="color: var(--text-muted);">
        <span>Project ID {{ projectContext.projectId || "—" }}</span>
        <span v-if="projectContext.updatedAt">Updated {{ projectContext.updatedAt }}</span>
        <el-popover
          v-if="versionText"
          v-model:visible="versionPopoverOpen"
          placement="bottom-start"
          trigger="click"
          :width="400"
        >
          <template #reference>
            <button type="button" class="topbar-chip">
              Build {{ versionText }}
            </button>
          </template>
          <div class="space-y-3">
            <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Build History</div>
            <div
              v-for="entry in versionHistory"
              :key="entry.version || entry.sha || entry.built_at"
              class="rounded-2xl border p-3"
              style="border-color: var(--border-soft); background: var(--surface-soft);"
            >
              <div class="flex items-start justify-between gap-3">
                <div>
                  <div class="font-medium" style="color: var(--text-strong);">
                    {{ entry.version || entry.short_sha || "Unknown build" }}
                  </div>
                  <div class="mt-1 text-[11px]" style="color: var(--text-muted);">{{ formatBuildEntry(entry) }}</div>
                </div>
                <a
                  v-if="entry.run_url"
                  :href="entry.run_url"
                  target="_blank"
                  rel="noreferrer"
                  class="text-[11px] font-medium underline"
                  style="color: var(--accent);"
                >
                  Run
                </a>
              </div>
              <div v-if="entry.title" class="mt-2 text-xs" style="color: var(--text-muted);">{{ entry.title }}</div>
            </div>
            <div v-if="!versionHistory.length" class="premium-empty">No build history available.</div>
          </div>
        </el-popover>
      </div>
    </div>

    <div class="flex flex-col gap-3 lg:min-w-[48rem] lg:flex-row lg:items-center lg:justify-end">
      <label class="search-shell lg:w-[24rem]">
        <AppIcon name="search" />
        <input
          v-model="searchText"
          type="text"
          placeholder="Search project ID, route, or command"
          @keydown.enter.prevent="runSearch"
        />
      </label>

      <el-select
        v-model="selectedProject"
        class="min-w-[220px]"
        placeholder="Switch project"
        filterable
        clearable
        @change="switchProject"
      >
        <el-option
          v-for="project in recentProjects"
          :key="project.id"
          :label="projectLabel(project)"
          :value="project.id"
        />
      </el-select>

      <div class="flex items-center gap-2">
        <button type="button" class="utility-button" @click="toggleTheme()" :title="themeButtonLabel">
          <AppIcon :name="uiTheme.mode === 'dark' ? 'sun' : 'moon'" />
        </button>

        <el-popover placement="bottom-end" trigger="click" :width="340">
          <template #reference>
            <button type="button" class="utility-button" title="Notifications">
              <AppIcon name="bell" />
            </button>
          </template>
          <div class="space-y-3">
            <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Signals</div>
            <div
              v-for="signal in notificationItems"
              :key="signal.title"
              class="rounded-2xl border p-3"
              style="border-color: var(--border-soft); background: var(--surface-soft);"
            >
              <div class="text-sm font-semibold" style="color: var(--text-strong);">{{ signal.title }}</div>
              <div class="mt-1 text-xs" style="color: var(--text-muted);">{{ signal.body }}</div>
            </div>
            <div v-if="!notificationItems.length" class="premium-empty">
              No active notifications.
            </div>
          </div>
        </el-popover>

        <el-popover placement="bottom-end" trigger="click" :width="300">
          <template #reference>
            <button type="button" class="brand-avatar" title="User menu">A</button>
          </template>
          <div class="space-y-3">
            <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Operator</div>
            <div class="rounded-2xl border p-3" style="border-color: var(--border-soft); background: var(--surface-soft);">
              <div class="text-sm font-semibold" style="color: var(--text-strong);">Abhishek</div>
              <div class="mt-1 text-xs" style="color: var(--text-muted);">
                {{ projectContext.projectName || "No project selected" }}
              </div>
            </div>
            <button type="button" class="topbar-chip" @click="goHome">Workspace</button>
            <button v-if="showEnterMc" type="button" class="topbar-chip" @click="goToRun">Enter Mission Control</button>
            <button v-if="showStop" type="button" class="topbar-chip" @click="pauseRun" :disabled="!canPause || pausing">
              {{ pausing ? "Stopping…" : "Emergency Stop" }}
            </button>
          </div>
        </el-popover>
      </div>
    </div>
  </div>

  <div v-if="error" class="mt-2 text-xs text-rose-600">{{ error }}</div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppIcon from "./AppIcon.vue";
import { projectContext, updateProjectContext } from "../state/projectContext";
import { toggleTheme, uiTheme } from "../state/uiTheme";

const DEFAULT_API_BASE = import.meta.env.DEV
  ? "http://localhost:8000/api/v1"
  : "https://api.prompt2pr.com/api/v1";

const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;
const router = useRouter();
const route = useRoute();

const error = ref("");
const pausing = ref(false);
const searchText = ref("");
const versionText = ref<string | null>(null);
const envText = ref<string | null>(null);
const versionHistory = ref<BuildEntry[]>([]);
const versionPopoverOpen = ref(false);

type RecentProject = { id: string; name: string };
type BuildEntry = {
  version?: string | null;
  sha?: string | null;
  short_sha?: string | null;
  branch?: string | null;
  built_at?: string | null;
  run_number?: number | null;
  run_attempt?: number | null;
  run_url?: string | null;
  title?: string | null;
};

const recentProjects = ref<RecentProject[]>(loadRecentProjects());
const selectedProject = ref(projectContext.projectId);

const canPause = computed(() => Boolean(projectContext.latestRunId) && projectContext.runStatus === "RUNNING");
const hasProject = computed(() => Boolean(projectContext.projectId));
const hasRun = computed(() => Boolean(projectContext.latestRunId));
const inMissionControl = computed(() => route.name === "mission-control");

const headerLabel = computed(() => {
  if (!hasProject.value) return "Workspace";
  return inMissionControl.value ? "Mission Control" : "Autonomous Engineering";
});

const titleText = computed(() => {
  if (!hasProject.value) return "Governed AI execution for software delivery";
  return projectContext.projectName || "Project";
});

const showStop = computed(() => inMissionControl.value && projectContext.runStatus !== "IDLE");
const showEnterMc = computed(() => hasProject.value && !inMissionControl.value && hasRun.value);

const notificationItems = computed(() => {
  const items: Array<{ title: string; body: string }> = [];
  if (projectContext.hasActiveRun) {
    items.push({
      title: "Automation active",
      body: `Run ${projectContext.latestRunId.slice(0, 8)} is ${projectContext.runStatus.toLowerCase()}.`,
    });
  }
  if (projectContext.architectureRefreshNeeded || projectContext.planRefreshNeeded || projectContext.testRefreshNeeded) {
    items.push({
      title: "Refresh recommended",
      body: [
        projectContext.architectureRefreshNeeded ? "architecture" : null,
        projectContext.planRefreshNeeded ? "plan" : null,
        projectContext.testRefreshNeeded ? "tests" : null,
      ]
        .filter(Boolean)
        .join(", "),
    });
  }
  if (!items.length) {
    items.push({
      title: "System ready",
      body: "No blocking alerts. You can continue with planning or execution.",
    });
  }
  return items;
});

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

const themeButtonLabel = computed(() => (uiTheme.mode === "dark" ? "Switch to light mode" : "Switch to dark mode"));

watch(
  () => projectContext.projectId,
  (id) => {
    selectedProject.value = id;
    if (!id) return;
    const name = projectContext.projectName || "Project";
    const existingIndex = recentProjects.value.findIndex((item) => item.id === id);
    if (existingIndex >= 0) {
      recentProjects.value.splice(existingIndex, 1);
    }
    recentProjects.value.unshift({ id, name });
    recentProjects.value = recentProjects.value.slice(0, 8);
    saveRecentProjects(recentProjects.value);
  }
);

function projectLabel(project: RecentProject) {
  return `${project.name} (${project.id.slice(0, 8)})`;
}

function switchProject(id: string | number | null) {
  if (!id) return;
  router.push(`/projects/${id}`);
}

function goHome() {
  router.push("/");
}

function goToRun() {
  if (!projectContext.projectId || !projectContext.latestRunId) return;
  router.push(`/projects/${projectContext.projectId}/run`);
}

async function pauseRun() {
  if (!projectContext.latestRunId) return;
  error.value = "";
  pausing.value = true;
  try {
    const response = await fetch(`${API_BASE}/runs/${projectContext.latestRunId}/pause`, {
      method: "POST",
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    updateProjectContext({
      runStatus: "PAUSED",
      updatedAt: new Date().toISOString(),
    });
  } catch (err: any) {
    error.value = err?.message || "Failed to pause run.";
  } finally {
    pausing.value = false;
  }
}

function runSearch() {
  const query = searchText.value.trim();
  if (!query) return;
  const lowered = query.toLowerCase();
  if (lowered === "workspace") {
    router.push("/");
  } else if ((lowered === "mission control" || lowered === "mission") && projectContext.projectId) {
    router.push(`/projects/${projectContext.projectId}/run`);
  } else if ((lowered === "automation map" || lowered === "map" || lowered === "system graph") && projectContext.projectId) {
    router.push(`/projects/${projectContext.projectId}/map`);
  } else if (lowered === "requirements" && projectContext.projectId) {
    router.push(`/projects/${projectContext.projectId}/requirements`);
  } else if (lowered === "timeline" && projectContext.projectId) {
    router.push(`/projects/${projectContext.projectId}/timeline`);
  } else if (lowered === "approvals" && projectContext.projectId) {
    router.push(`/projects/${projectContext.projectId}/approvals`);
  } else if (lowered.length >= 8) {
    const match = recentProjects.value.find(
      (project) =>
        project.id.toLowerCase().includes(lowered) ||
        project.name.toLowerCase().includes(lowered)
    );
    if (match) {
      router.push(`/projects/${match.id}`);
    }
  }
  searchText.value = "";
}

async function hydrateRecentProjectsFromApi() {
  try {
    const resp = await fetch(`${API_BASE}/projects`);
    if (!resp.ok) return;
    const data: { id: string; name: string }[] = await resp.json();
    const merged = [...data, ...recentProjects.value]
      .filter((p) => p && p.id)
      .reduce<RecentProject[]>((acc, p) => {
        if (!acc.find((x) => x.id === p.id)) acc.push({ id: p.id, name: p.name || "Project" });
        return acc;
      }, []);
    recentProjects.value = merged.slice(0, 12);
    saveRecentProjects(recentProjects.value);
  } catch {
    // ignore fetch errors; local recent list still works
  }
}

onMounted(() => {
  void hydrateRecentProjectsFromApi();
  void fetchVersionInfo();
});

function loadRecentProjects(): RecentProject[] {
  try {
    const stored = localStorage.getItem("recentProjects");
    if (!stored) return [];
    const parsed = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item) => item?.id);
  } catch {
    return [];
  }
}

function saveRecentProjects(projects: RecentProject[]) {
  try {
    localStorage.setItem("recentProjects", JSON.stringify(projects));
  } catch {
    // ignore storage errors
  }
}

async function fetchVersionInfo() {
  const apiHost = API_BASE.replace(/\/api\/v1$/, "");
  try {
    const history = await fetch(`${apiHost}/version/history`).then((r) => r.json());
    versionText.value = history?.current?.version || history?.history?.[0]?.version || null;
    versionHistory.value = Array.isArray(history?.history) ? history.history : [];
  } catch {
    versionText.value = null;
    versionHistory.value = [];
    try {
      const ver = await fetch(`${apiHost}/version`).then((r) => r.json());
      versionText.value = ver?.version || null;
      versionHistory.value = ver?.version ? [ver] : [];
    } catch {
      versionText.value = null;
      versionHistory.value = [];
    }
  }
  try {
    const detail = await fetch(`${API_BASE}/health/detail`).then((r) => r.json());
    envText.value = detail?.environment || null;
    if (!versionText.value && detail?.version) versionText.value = detail.version;
  } catch {
    envText.value = null;
  }
}

function formatBuildEntry(entry: BuildEntry) {
  const parts: string[] = [];
  if (entry.branch) parts.push(entry.branch);
  if (entry.short_sha) parts.push(entry.short_sha);
  if (entry.built_at) {
    const parsed = new Date(entry.built_at);
    parts.push(Number.isNaN(parsed.getTime()) ? entry.built_at : parsed.toLocaleString());
  }
  return parts.join(" · ");
}
</script>
