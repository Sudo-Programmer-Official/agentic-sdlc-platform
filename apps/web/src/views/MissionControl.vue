<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">Mission Control</h1>
      <p class="text-slate-600">
        Monitor the SDLC stage, control execution, and keep full audit visibility.
      </p>
    </div>

    <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div class="text-sm uppercase tracking-wide text-slate-400">Project Controls</div>
          <div class="text-xs text-slate-500">
            Refresh status, execute bounded tasks, or switch projects.
          </div>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-xs uppercase tracking-wide text-slate-400">Advanced Mode</span>
          <el-switch v-model="advancedMode" />
        </div>
      </div>
      <div class="mt-4 flex flex-wrap items-center gap-3">
        <div class="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
          Project ID
          <span class="ml-2 font-mono text-slate-900">{{ projectId || "—" }}</span>
        </div>
        <el-button :loading="loading" @click="loadAll">Refresh Overview</el-button>
        <el-button :disabled="!summary?.latest_run" @click="executeTasks">
          Execute Tasks
        </el-button>
        <el-button @click="goToOverview">Switch Project</el-button>
        <span v-if="error" class="text-sm text-rose-600">{{ error }}</span>
      </div>
    </div>

    <div v-if="summary" class="grid gap-4 md:grid-cols-4">
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Stage</div>
        <div class="mt-2 flex items-center gap-2 text-lg font-semibold text-slate-900">
          <StageBadge :label="summary.current_stage" />
          <span>{{ summary.current_stage }}</span>
        </div>
        <div class="mt-1 text-xs text-slate-500">Project: {{ summary.name }}</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Agents</div>
        <div class="mt-3 flex items-center gap-4">
          <div>
            <div class="text-xl font-semibold text-slate-900">{{ agentSnapshot.active }}</div>
            <div class="text-xs uppercase text-slate-400">Active</div>
          </div>
          <div>
            <div class="text-xl font-semibold text-slate-900">{{ agentSnapshot.idle }}</div>
            <div class="text-xs uppercase text-slate-400">Idle</div>
          </div>
          <div>
            <div class="text-xl font-semibold text-slate-900">{{ agentSnapshot.blocked }}</div>
            <div class="text-xs uppercase text-slate-400">Blocked</div>
          </div>
        </div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Tasks</div>
        <div class="mt-2 text-lg font-semibold text-slate-900">
          {{ summary.task_counts.running }} running
        </div>
        <div class="mt-1 text-xs text-slate-500">
          {{ summary.task_counts.pending }} pending · {{ summary.task_counts.done }} done
        </div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Changes</div>
        <div class="mt-2 text-lg font-semibold text-slate-900">
          {{ changeSnapshot.open }} open
        </div>
        <div class="mt-1 text-xs text-slate-500">
          {{ changeSnapshot.accepted }} accepted · {{ changeSnapshot.rejected }} rejected
        </div>
      </div>
    </div>

    <div v-if="summary" class="grid gap-4 lg:grid-cols-2">
      <AgentPanel :agents="agentRows" />
      <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div class="text-sm uppercase tracking-wide text-slate-400">Metrics Snapshot</div>
        <div v-if="metrics" class="mt-4 grid gap-3 sm:grid-cols-2">
          <div class="rounded-lg bg-slate-50 p-4">
            <div class="text-xs uppercase text-slate-400">Total Runs</div>
            <div class="mt-1 text-xl font-semibold text-slate-900">{{ metrics.total_runs }}</div>
          </div>
          <div class="rounded-lg bg-slate-50 p-4">
            <div class="text-xs uppercase text-slate-400">Active Runs</div>
            <div class="mt-1 text-xl font-semibold text-slate-900">{{ metrics.active_runs }}</div>
          </div>
          <div class="rounded-lg bg-slate-50 p-4">
            <div class="text-xs uppercase text-slate-400">Stale Stages</div>
            <div class="mt-1 text-xl font-semibold text-slate-900">{{ metrics.stale_count }}</div>
          </div>
          <div class="rounded-lg bg-slate-50 p-4">
            <div class="text-xs uppercase text-slate-400">Open Changes</div>
            <div class="mt-1 text-xl font-semibold text-slate-900">{{ metrics.open_changes }}</div>
          </div>
        </div>
        <div v-else class="mt-4 text-sm text-slate-500">No metrics yet.</div>
      </div>
    </div>

    <div v-if="summary">
      <ExecutionTimeline
        :logs="auditLogs"
        :tasks="tasks"
        :current-stage="summary.current_stage"
        :run-status="summary.latest_run?.status || 'IDLE'"
        :run-id="summary.latest_run?.run_id"
      />
    </div>

    <div v-if="advancedMode && summary" class="grid gap-4 xl:grid-cols-2">
      <TaskTable :tasks="tasks" />
      <ChangePanel
        :changes="changes"
        @create="createChangeRequest"
        @accept="acceptChange"
        @reject="rejectChange"
      />
    </div>

    <div v-if="advancedMode && summary">
      <AuditTimeline :logs="auditLogs" />
    </div>

    <div v-if="!summary && !loading" class="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">
      Select a project to view Mission Control data.
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AgentPanel from "../components/AgentPanel.vue";
import AuditTimeline from "../components/AuditTimeline.vue";
import ChangePanel from "../components/ChangePanel.vue";
import ExecutionTimeline from "../components/ExecutionTimeline.vue";
import StageBadge from "../components/StageBadge.vue";
import TaskTable from "../components/TaskTable.vue";
import { updateProjectContext } from "../state/projectContext";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api/v1";

const route = useRoute();
const router = useRouter();

const summary = ref<any | null>(null);
const metrics = ref<any | null>(null);
const tasks = ref<any[]>([]);
const auditLogs = ref<any[]>([]);
const changes = ref<any[]>([]);
const loading = ref(false);
const error = ref("");
const advancedMode = ref(false);

const projectId = computed(() => (route.params.projectId as string) || "");

const agentSnapshot = computed(() => {
  const byAgent: Record<string, { running: number; pending: number; failed: number }> = {};
  tasks.value.forEach((task) => {
    const entry = byAgent[task.agent] || { running: 0, pending: 0, failed: 0 };
    if (task.status === "RUNNING") entry.running += 1;
    else if (task.status === "FAILED" || task.status === "CANCELED") entry.failed += 1;
    else entry.pending += 1;
    byAgent[task.agent] = entry;
  });

  const agents = Object.values(byAgent);
  const active = agents.filter((agent) => agent.running > 0).length;
  const blocked = agents.filter((agent) => agent.failed > 0).length;
  const idle = Math.max(agents.length - active - blocked, 0);
  return { active, idle, blocked };
});

const agentRows = computed(() => {
  const rows: Array<{ name: string; status: string; taskCount: number }> = [];
  const agentMap: Record<string, { running: number; pending: number; failed: number; total: number }> = {};
  tasks.value.forEach((task) => {
    const entry = agentMap[task.agent] || { running: 0, pending: 0, failed: 0, total: 0 };
    if (task.status === "RUNNING") entry.running += 1;
    else if (task.status === "FAILED" || task.status === "CANCELED") entry.failed += 1;
    else entry.pending += 1;
    entry.total += 1;
    agentMap[task.agent] = entry;
  });
  Object.entries(agentMap).forEach(([name, stats]) => {
    let status = "Idle";
    if (stats.running > 0) status = "Running";
    else if (stats.failed > 0) status = "Blocked";
    rows.push({ name, status, taskCount: stats.total });
  });
  return rows;
});

const changeSnapshot = computed(() => {
  const open = changes.value.filter((change) => change.status === "OPEN").length;
  const accepted = changes.value.filter((change) => change.status === "ACCEPTED").length;
  const rejected = changes.value.filter((change) => change.status === "REJECTED").length;
  return { open, accepted, rejected };
});

watch(
  agentSnapshot,
  (snapshot) => {
    updateProjectContext({
      activeAgents: snapshot.active,
      updatedAt: new Date().toISOString()
    });
  },
  { deep: true }
);

watch(
  projectId,
  () => {
    resetState();
    if (projectId.value) {
      primeContext();
      loadAll();
    } else {
      error.value = "No project selected.";
    }
  },
  { immediate: true }
);

function resetState() {
  summary.value = null;
  metrics.value = null;
  tasks.value = [];
  auditLogs.value = [];
  changes.value = [];
  error.value = "";
}

function primeContext() {
  updateProjectContext({
    projectId: projectId.value,
    projectName: "Loading project...",
    stage: "UNKNOWN",
    runStatus: "IDLE",
    latestRunId: "",
    activeAgents: 0,
    updatedAt: new Date().toISOString()
  });
}

function syncContext() {
  if (!summary.value) return;
  updateProjectContext({
    projectId: summary.value.project_id || projectId.value,
    projectName: summary.value.name || "Project",
    stage: summary.value.current_stage || "UNKNOWN",
    runStatus: summary.value.latest_run?.status || "IDLE",
    latestRunId: summary.value.latest_run?.run_id || "",
    activeAgents: agentSnapshot.value.active,
    updatedAt: new Date().toISOString()
  });
}

async function loadSummary() {
  if (!projectId.value.trim()) {
    error.value = "Project ID is required.";
    return;
  }
  const response = await fetch(`${API_BASE}/projects/${projectId.value}/summary`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  summary.value = await response.json();
}

async function loadMetrics() {
  const response = await fetch(`${API_BASE}/projects/${projectId.value}/metrics`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  metrics.value = await response.json();
}

async function loadTasks(runId: string) {
  const response = await fetch(`${API_BASE}/runs/${runId}/tasks`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  tasks.value = await response.json();
}

async function loadAuditLogs() {
  const response = await fetch(`${API_BASE}/projects/${projectId.value}/audit-logs`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  auditLogs.value = await response.json();
}

async function loadChanges() {
  const response = await fetch(`${API_BASE}/projects/${projectId.value}/changes`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  changes.value = await response.json();
}

async function loadAll() {
  if (!projectId.value.trim()) {
    error.value = "Project ID is required.";
    return;
  }
  error.value = "";
  loading.value = true;
  try {
    await loadSummary();
    await Promise.all([loadMetrics(), loadChanges(), loadAuditLogs()]);
    if (summary.value?.latest_run?.run_id) {
      await loadTasks(summary.value.latest_run.run_id);
    } else {
      tasks.value = [];
    }
    syncContext();
  } catch (err: any) {
    error.value = err?.message || "Failed to load project data.";
  } finally {
    loading.value = false;
  }
}

async function createChangeRequest(payload: {
  summary: string;
  source: string;
  affected_area: string;
  severity: string;
  suggested_stage: string;
}) {
  if (!projectId.value.trim() || !payload.summary.trim()) {
    error.value = "Project ID and summary are required.";
    return;
  }
  error.value = "";
  try {
    const response = await fetch(`${API_BASE}/projects/${projectId.value}/changes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    await loadChanges();
  } catch (err: any) {
    error.value = err?.message || "Failed to create change request.";
  }
}

async function acceptChange(changeId: string) {
  try {
    const response = await fetch(`${API_BASE}/changes/${changeId}/accept`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    await loadAll();
  } catch (err: any) {
    error.value = err?.message || "Failed to accept change.";
  }
}

async function rejectChange(changeId: string) {
  try {
    const response = await fetch(`${API_BASE}/changes/${changeId}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    await loadChanges();
  } catch (err: any) {
    error.value = err?.message || "Failed to reject change.";
  }
}

async function executeTasks() {
  if (!summary.value?.latest_run?.run_id) {
    return;
  }
  try {
    const runId = summary.value.latest_run.run_id;
    const response = await fetch(`${API_BASE}/runs/${runId}/execute?max_parallel_tasks=2`, {
      method: "POST"
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    await loadAll();
  } catch (err: any) {
    error.value = err?.message || "Failed to execute tasks.";
  }
}

function goToOverview() {
  router.push("/");
}
</script>
