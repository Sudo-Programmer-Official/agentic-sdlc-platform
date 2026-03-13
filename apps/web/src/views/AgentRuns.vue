<template>
  <div class="space-y-6">
    <section class="premium-hero">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="max-w-3xl space-y-3">
          <div class="topbar-chip">
            <AppIcon name="runs" size="sm" />
            Execution Intelligence
          </div>
          <div>
            <h1 class="text-3xl font-semibold" style="color: var(--text-strong);">Agent Runs</h1>
            <p class="mt-2 text-sm leading-6" style="color: var(--text-muted);">
              Inspect run quality, replay execution paths, and surface similar historical runs without leaving the control plane.
            </p>
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <button type="button" class="utility-button" @click="goToMissionControl">
            <AppIcon name="mission" />
            Mission Control
          </button>
          <button type="button" class="utility-button" @click="loadPage" :disabled="loading">
            <AppIcon name="spark" />
            {{ loading ? "Refreshing…" : "Refresh" }}
          </button>
        </div>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="Runs Recorded" :value="String(runs.length)" helper="Observed in this project" tone="neutral" />
      <MetricCard label="Active" :value="String(activeRunsCount)" helper="Queued or running" tone="warning" />
      <MetricCard label="Recovered" :value="String(recoveredRunsCount)" helper="Runs with recovery steps" tone="success" />
      <MetricCard
        label="Latest Outcome"
        :value="selectedTimeline?.summary?.status || latestRun?.status || 'IDLE'"
        :helper="selectedTimeline?.summary?.branch_name || latestRun?.branch_name || 'No branch recorded'"
        :tone="latestOutcomeTone"
      />
    </section>

    <section class="grid gap-4 xl:grid-cols-[1.05fr,1.2fr]">
      <div class="premium-card">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Run Ledger</div>
            <div class="mt-1 text-sm" style="color: var(--text-muted);">
              Select a run to inspect its replay summary, changed files, and adjacent learning context.
            </div>
          </div>
          <div class="topbar-chip">{{ runs.length }} total</div>
        </div>

        <div v-if="error" class="mt-4 rounded-2xl border px-4 py-3 text-sm" style="border-color: rgba(239, 68, 68, 0.2); background: rgba(239, 68, 68, 0.08); color: var(--danger);">
          {{ error }}
        </div>

        <div v-if="runs.length" class="mt-4 grid gap-3">
          <button
            v-for="run in runs"
            :key="run.id"
            type="button"
            class="w-full rounded-2xl border p-4 text-left transition-transform duration-200 hover:-translate-y-[1px]"
            :style="runCardStyle(run.id === selectedRunId)"
            @click="selectRun(run.id)"
          >
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <div class="font-mono text-sm" style="color: var(--text-strong);">{{ run.id }}</div>
                  <div class="status-ring" :style="runStatusStyle(run.status)">
                    <span class="soft-dot" :class="{ 'pulse-dot': run.status === 'RUNNING' }" />
                    {{ run.status }}
                  </div>
                </div>
                <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs" style="color: var(--text-muted);">
                  <span>Executor {{ run.executor || "—" }}</span>
                  <span>Branch {{ run.branch_name || "—" }}</span>
                  <span>Workspace {{ run.workspace_status || "PENDING" }}</span>
                </div>
                <div class="mt-2 text-xs" style="color: var(--text-soft);">
                  Started {{ formatTimestamp(run.started_at) }}
                </div>
              </div>
              <div class="text-right text-[11px]" style="color: var(--text-soft);">
                <div>{{ formatTimestamp(run.finished_at) }}</div>
                <div class="mt-1">{{ run.summary?.goal_text || "No goal summary" }}</div>
              </div>
            </div>
          </button>
        </div>

        <div v-else class="mt-4 premium-empty">
          No runs recorded for this project yet.
        </div>
      </div>

      <div class="premium-card">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Run Spotlight</div>
            <div class="mt-1 text-sm" style="color: var(--text-muted);">
              Summary, replay metadata, and PR readiness for the selected run.
            </div>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <button
              v-if="selectedRunId"
              type="button"
              class="utility-button"
              @click="goToReplay"
            >
              <AppIcon name="timeline" />
              Replay
            </button>
            <button
              v-if="projectId"
              type="button"
              class="utility-button"
              @click="goToMissionControl"
            >
              <AppIcon name="mission" />
              Open Control
            </button>
          </div>
        </div>

        <div v-if="selectedTimeline" class="mt-4 space-y-4">
          <div class="grid gap-3 md:grid-cols-2">
            <div class="rounded-2xl border p-4" style="border-color: var(--border-soft); background: var(--surface-soft);">
              <div class="text-xs uppercase tracking-[0.2em]" style="color: var(--text-soft);">Outcome</div>
              <div class="mt-2 flex items-center gap-2">
                <div class="status-ring" :style="runStatusStyle(selectedTimeline.summary.status)">
                  <span class="soft-dot" />
                  {{ selectedTimeline.summary.status }}
                </div>
                <div class="text-sm" style="color: var(--text-muted);">{{ selectedTimeline.summary.executor }}</div>
              </div>
              <div class="mt-3 space-y-1 text-sm" style="color: var(--text-muted);">
                <div><strong style="color: var(--text-strong);">Branch:</strong> {{ selectedTimeline.summary.branch_name || "—" }}</div>
                <div><strong style="color: var(--text-strong);">Workspace:</strong> {{ selectedTimeline.summary.workspace_status }}</div>
                <div><strong style="color: var(--text-strong);">Elapsed:</strong> {{ formatElapsed(selectedTimeline.summary.elapsed_seconds) }}</div>
              </div>
            </div>

            <div class="rounded-2xl border p-4" style="border-color: var(--border-soft); background: var(--surface-soft);">
              <div class="text-xs uppercase tracking-[0.2em]" style="color: var(--text-soft);">Delivery Signal</div>
              <div class="mt-2 text-sm font-medium" style="color: var(--text-strong);">
                {{ selectedTimeline.summary.pull_request_url ? "PR-ready output recorded" : "No PR linked yet" }}
              </div>
              <div class="mt-3 space-y-1 text-sm" style="color: var(--text-muted);">
                <div><strong style="color: var(--text-strong);">Artifacts:</strong> {{ selectedTimeline.summary.artifact_count }}</div>
                <div><strong style="color: var(--text-strong);">Recoveries:</strong> {{ selectedTimeline.summary.recovery_count }}</div>
                <div><strong style="color: var(--text-strong);">Primary error:</strong> {{ selectedTimeline.summary.primary_error || "—" }}</div>
              </div>
            </div>
          </div>

          <div class="rounded-2xl border p-4" style="border-color: var(--border-soft); background: var(--surface-soft);">
            <div class="text-xs uppercase tracking-[0.2em]" style="color: var(--text-soft);">Goal Summary</div>
            <div class="mt-2 text-sm leading-6" style="color: var(--text-muted);">
              {{ selectedTimeline.summary.goal_text || "No goal summary recorded for this run." }}
            </div>
            <div v-if="selectedTimeline.summary.changed_files?.length" class="mt-4 flex flex-wrap gap-2">
              <span
                v-for="file in selectedTimeline.summary.changed_files"
                :key="file"
                class="topbar-chip"
              >
                {{ file }}
              </span>
            </div>
          </div>
        </div>

        <div v-else class="mt-4 premium-empty">
          Select a run to inspect its replay data.
        </div>
      </div>
    </section>

    <section class="grid gap-4 xl:grid-cols-[1.1fr,0.9fr]">
      <div class="premium-card">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Replay Highlights</div>
            <div class="mt-1 text-sm" style="color: var(--text-muted);">
              Deterministic execution trail built from run events, work items, artifacts, and recovery markers.
            </div>
          </div>
          <div class="topbar-chip">{{ selectedTimeline?.steps?.length || 0 }} steps</div>
        </div>

        <div v-if="selectedTimeline?.steps?.length" class="mt-4 space-y-3">
          <div
            v-for="step in selectedTimeline.steps"
            :key="step.id"
            class="rounded-2xl border p-4"
            style="border-color: var(--border-soft); background: var(--surface-soft);"
          >
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <div class="status-ring" :style="timelineStepStyle(step.status)">
                    <span class="soft-dot" :class="{ 'pulse-dot': step.status === 'RUNNING' }" />
                    {{ step.status }}
                  </div>
                  <div class="text-sm font-medium" style="color: var(--text-strong);">{{ step.title }}</div>
                  <div v-if="step.kind" class="topbar-chip">{{ step.kind }}</div>
                </div>
                <div v-if="step.message" class="mt-2 text-sm" style="color: var(--text-muted);">{{ step.message }}</div>
                <div class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs" style="color: var(--text-soft);">
                  <span v-if="step.work_item_type">Work item {{ step.work_item_type }}</span>
                  <span v-if="step.artifact_type">Artifact {{ step.artifact_type }}</span>
                  <span>{{ formatTimestamp(step.ts) }}</span>
                </div>
                <div v-if="step.changed_files?.length" class="mt-3 flex flex-wrap gap-2">
                  <span v-for="file in step.changed_files" :key="`${step.id}-${file}`" class="topbar-chip">{{ file }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="mt-4 premium-empty">
          Replay steps will appear once a run is selected.
        </div>
      </div>

      <div class="space-y-4">
        <div class="premium-card">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Similar Past Runs</div>
              <div class="mt-1 text-sm" style="color: var(--text-muted);">
                Run memory suggestions based on goal, error signature, and changed files.
              </div>
            </div>
            <div class="topbar-chip">{{ similarRuns.length }} matches</div>
          </div>

          <div v-if="memoryError" class="mt-4 rounded-2xl border px-4 py-3 text-sm" style="border-color: rgba(245, 158, 11, 0.2); background: rgba(245, 158, 11, 0.08); color: var(--warning);">
            {{ memoryError }}
          </div>

          <div v-if="similarRuns.length" class="mt-4 space-y-3">
            <div
              v-for="match in similarRuns"
              :key="match.run_id"
              class="rounded-2xl border p-4"
              style="border-color: var(--border-soft); background: var(--surface-soft);"
            >
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-2">
                    <div class="font-mono text-sm" style="color: var(--text-strong);">{{ match.run_id }}</div>
                    <div class="status-ring" :style="runStatusStyle(match.status)">
                      <span class="soft-dot" />
                      {{ match.status }}
                    </div>
                  </div>
                  <div class="mt-2 text-sm" style="color: var(--text-muted);">{{ match.goal || "No goal summary" }}</div>
                  <div class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs" style="color: var(--text-soft);">
                    <span>Score {{ Number(match.score || 0).toFixed(2) }}</span>
                    <span>Recoveries {{ match.recovery_count || 0 }}</span>
                    <span>Elapsed {{ formatElapsed(match.elapsed_seconds) }}</span>
                  </div>
                </div>
                <button type="button" class="utility-button" @click="selectRun(String(match.run_id))">
                  Open
                </button>
              </div>
            </div>
          </div>

          <div v-else class="mt-4 premium-empty">
            Similar run guidance will appear after a replay summary is available.
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppIcon from "../components/AppIcon.vue";
import MetricCard from "../components/MetricCard.vue";
import {
  fetchProjectMeta,
  fetchRunTimeline,
  findSimilarRuns,
  listRuns,
} from "../api/lifecycle";
import { updateProjectContext } from "../state/projectContext";

type RunRecord = {
  id: string;
  status: string;
  executor?: string | null;
  branch_name?: string | null;
  workspace_status?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  summary?: {
    goal_text?: string | null;
  } | null;
};

type RunTimelineResponse = {
  run: RunRecord;
  summary: {
    status: string;
    executor: string;
    branch_name?: string | null;
    workspace_status: string;
    elapsed_seconds?: number | null;
    recovery_count: number;
    artifact_count: number;
    changed_files: string[];
    primary_error?: string | null;
    goal_text?: string | null;
    pull_request_url?: string | null;
  };
  steps: Array<{
    id: string;
    kind?: string | null;
    ts?: string | null;
    title: string;
    status: string;
    message?: string | null;
    work_item_type?: string | null;
    artifact_type?: string | null;
    changed_files?: string[];
  }>;
};

type RunMemoryMatch = {
  run_id: string;
  status: string;
  goal?: string | null;
  score: number;
  recovery_count?: number;
  elapsed_seconds?: number | null;
};

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const error = ref("");
const memoryError = ref("");
const projectName = ref("");
const runs = ref<RunRecord[]>([]);
const selectedRunId = ref("");
const selectedTimeline = ref<RunTimelineResponse | null>(null);
const similarRuns = ref<RunMemoryMatch[]>([]);

const projectId = computed(() => String(route.params.projectId || ""));

const latestRun = computed(() => runs.value[0] || null);
const activeRunsCount = computed(() => runs.value.filter((run) => ["QUEUED", "RUNNING"].includes(run.status)).length);
const recoveredRunsCount = computed(
  () => runs.value.filter((run) => (run as any)?.summary?.recovery_count > 0).length
);
const latestOutcomeTone = computed(() => toneForStatus(selectedTimeline.value?.summary?.status || latestRun.value?.status || "IDLE"));

watch(
  projectId,
  () => {
    void loadPage();
  },
  { immediate: true }
);

async function loadPage() {
  if (!projectId.value) return;
  loading.value = true;
  error.value = "";
  try {
    const [project, runRows] = await Promise.all([
      fetchProjectMeta(projectId.value),
      listRuns(projectId.value),
    ]);
    projectName.value = project?.name || "Project";
    runs.value = Array.isArray(runRows)
      ? [...runRows].sort((a, b) => sortDescending(a.started_at, b.started_at))
      : [];
    updateProjectContext({
      projectId: projectId.value,
      projectName: projectName.value,
      stage: project?.status || project?.stage || "UNKNOWN",
      latestRunId: runs.value[0]?.id || "",
      runStatus: runs.value[0]?.status || "IDLE",
      updatedAt: new Date().toISOString(),
      hasActiveRun: ["QUEUED", "RUNNING", "PAUSED"].includes(runs.value[0]?.status || ""),
    });

    const nextRunId = String(route.params.runId || selectedRunId.value || runs.value[0]?.id || "");
    selectedRunId.value = nextRunId;
    if (nextRunId) {
      await loadRunDetails(nextRunId);
    } else {
      selectedTimeline.value = null;
      similarRuns.value = [];
    }
  } catch (err: any) {
    error.value = err?.message || "Failed to load runs.";
  } finally {
    loading.value = false;
  }
}

async function selectRun(runId: string) {
  selectedRunId.value = runId;
  await loadRunDetails(runId);
}

async function loadRunDetails(runId: string) {
  try {
    selectedTimeline.value = await fetchRunTimeline(runId);
    await loadSimilarRuns();
  } catch (err: any) {
    error.value = err?.message || "Failed to load run details.";
  }
}

async function loadSimilarRuns() {
  if (!projectId.value || !selectedTimeline.value) {
    similarRuns.value = [];
    return;
  }
  memoryError.value = "";
  try {
    const payload = await findSimilarRuns(projectId.value, {
      goal: selectedTimeline.value.summary.goal_text || undefined,
      error: selectedTimeline.value.summary.primary_error || undefined,
      files: selectedTimeline.value.summary.changed_files || [],
      limit: 4,
    });
    similarRuns.value = Array.isArray(payload?.matches)
      ? payload.matches.filter((match: RunMemoryMatch) => String(match.run_id) !== selectedRunId.value)
      : [];
  } catch (err: any) {
    memoryError.value = err?.message || "Failed to load similar runs.";
    similarRuns.value = [];
  }
}

function goToMissionControl() {
  if (!projectId.value) return;
  router.push(`/projects/${projectId.value}/run`);
}

function goToReplay() {
  if (!projectId.value || !selectedRunId.value) return;
  router.push(`/projects/${projectId.value}/runs/${selectedRunId.value}/debug`);
}

function runStatusStyle(status?: string | null) {
  const normalized = (status || "").toUpperCase();
  if (normalized === "COMPLETED") {
    return { background: "rgba(34, 197, 94, 0.12)", color: "var(--success)" };
  }
  if (normalized === "FAILED" || normalized === "CANCELED") {
    return { background: "rgba(239, 68, 68, 0.12)", color: "var(--danger)" };
  }
  if (normalized === "RUNNING" || normalized === "QUEUED" || normalized === "PAUSED") {
    return { background: "rgba(245, 158, 11, 0.12)", color: "var(--warning)" };
  }
  return { background: "var(--surface-soft)", color: "var(--text-muted)" };
}

function timelineStepStyle(status?: string | null) {
  return runStatusStyle(status);
}

function runCardStyle(selected: boolean) {
  if (selected) {
    return {
      borderColor: "rgba(91, 156, 255, 0.45)",
      background: "linear-gradient(180deg, rgba(91, 156, 255, 0.12), rgba(91, 156, 255, 0.04))",
      boxShadow: "0 12px 30px rgba(0, 0, 0, 0.16)",
    };
  }
  return {
    borderColor: "var(--border-soft)",
    background: "var(--surface-soft)",
  };
}

function toneForStatus(status: string) {
  const normalized = String(status || "").toUpperCase();
  if (normalized === "COMPLETED") return "success";
  if (normalized === "FAILED" || normalized === "CANCELED") return "danger";
  if (normalized === "RUNNING" || normalized === "QUEUED" || normalized === "PAUSED") return "warning";
  return "neutral";
}

function formatTimestamp(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString();
}

function formatElapsed(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  if (value < 60) return `${Math.round(value)}s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}m ${seconds}s`;
}

function sortDescending(a?: string | null, b?: string | null) {
  const first = a ? new Date(a).getTime() : 0;
  const second = b ? new Date(b).getTime() : 0;
  return second - first;
}
</script>
