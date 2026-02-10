<template>
  <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
    <div>
      <div class="text-xs uppercase tracking-[0.3em] text-slate-400">Mission Control</div>
      <div class="text-2xl font-semibold text-slate-900">
        {{ projectContext.projectName }}
      </div>
      <div class="mt-1 flex flex-wrap gap-3 text-xs text-slate-500">
        <span>Project ID: {{ projectContext.projectId || "—" }}</span>
        <span v-if="projectContext.updatedAt">Updated {{ projectContext.updatedAt }}</span>
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-3">
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
      <div class="flex items-center gap-2 text-xs text-slate-500">
        <span class="uppercase">Stage</span>
        <StageBadge :label="projectContext.stage" />
      </div>
      <div class="flex items-center gap-2 text-xs text-slate-500">
        <span class="uppercase">Run</span>
        <el-tag :type="runTagType" effect="light">{{ projectContext.runStatus }}</el-tag>
      </div>
      <div class="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
        Active agents
        <span class="ml-2 text-sm font-semibold text-slate-900">
          {{ projectContext.activeAgents }}
        </span>
      </div>
      <el-button type="danger" plain :disabled="!canPause" :loading="pausing" @click="pauseRun">
        Emergency Stop
      </el-button>
    </div>
  </div>
  <div v-if="error" class="mt-2 text-xs text-rose-600">{{ error }}</div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";

import StageBadge from "./StageBadge.vue";
import { projectContext, updateProjectContext } from "../state/projectContext";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api/v1";
const error = ref("");
const pausing = ref(false);
const router = useRouter();

type RecentProject = { id: string; name: string };
const recentProjects = ref<RecentProject[]>(loadRecentProjects());
const selectedProject = ref(projectContext.projectId);

const canPause = computed(() =>
  Boolean(projectContext.latestRunId) && projectContext.runStatus === "RUNNING"
);

const runTagType = computed(() => {
  if (projectContext.runStatus === "RUNNING") return "warning";
  if (projectContext.runStatus === "PAUSED") return "info";
  if (projectContext.runStatus === "COMPLETED") return "success";
  if (projectContext.runStatus === "FAILED") return "danger";
  if (projectContext.runStatus === "CANCELED") return "info";
  return "default";
});

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
    recentProjects.value = recentProjects.value.slice(0, 5);
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

async function pauseRun() {
  if (!projectContext.latestRunId) return;
  error.value = "";
  pausing.value = true;
  try {
    const response = await fetch(`${API_BASE}/runs/${projectContext.latestRunId}/pause`, {
      method: "POST"
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    updateProjectContext({
      runStatus: "PAUSED",
      updatedAt: new Date().toISOString()
    });
  } catch (err: any) {
    error.value = err?.message || "Failed to pause run.";
  } finally {
    pausing.value = false;
  }
}

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
</script>
