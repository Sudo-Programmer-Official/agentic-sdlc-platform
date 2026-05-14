<template>
  <div class="page-stack">
    <section class="premium-hero">
      <div class="premium-hero__eyebrow">Deterministic Replay</div>
      <h1 class="premium-hero__title">Audit the engineering flight recorder.</h1>
      <p class="premium-hero__copy">
        Reconstruct a run step by step, inspect recovery decisions, and understand how a patch moved from automation to review.
      </p>
      <div class="mt-6 flex flex-wrap gap-3">
        <el-button :loading="loading" @click="loadPage">Refresh Timeline</el-button>
        <el-button
          v-if="selectedRunNeedsOperatorConfirmation"
          type="primary"
          :loading="resumeLoading"
          @click="confirmAndResumeRun"
        >
          Confirm & Resume Run
        </el-button>
        <el-button
          v-if="selectedRunNeedsOperatorConfirmation"
          plain
          @click="openApprovals"
        >
          Open Approvals
        </el-button>
        <el-button :disabled="!selectedRunId" plain @click="goToMissionControl">Back to Mission Control</el-button>
      </div>
      <div
        v-if="selectedRunNeedsOperatorConfirmation"
        class="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
      >
        This run is paused for operator confirmation before patch mutation.
        Use <strong>Confirm & Resume Run</strong> to continue immediately.
      </div>
      <div
        v-if="actionError"
        class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700"
      >
        {{ actionError }}
      </div>
    </section>

    <section class="premium-card p-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div class="text-sm uppercase tracking-wide text-slate-400">SDLC Pipeline</div>
          <div class="mt-1 text-xs text-slate-500">Current project stage highlighted across the delivery path.</div>
        </div>
        <span class="topbar-chip">{{ project?.status || "UNKNOWN" }}</span>
      </div>
      <div class="mt-6 grid gap-3 md:grid-cols-6">
        <div
          v-for="stage in stageFlow"
          :key="stage"
          class="rounded-2xl border p-4 text-center"
          :style="stageStyle(stage)"
        >
          <div class="text-xs uppercase tracking-wide">{{ stage }}</div>
          <div class="mt-2 text-[11px]" :style="{ color: stage === project?.status ? 'inherit' : 'var(--text-soft)' }">
            {{ stageHint(stage) }}
          </div>
        </div>
      </div>
    </section>

    <section class="surface-grid md:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="Project" :value="project?.name || '—'" :detail="`Stage: ${project?.status || 'UNKNOWN'}`" />
      <MetricCard label="Run" :value="selectedRunId || '—'" :detail="selectedRun?.executor || '—'" />
      <MetricCard label="Outcome" :value="selectedRun?.status || 'IDLE'" :detail="formatElapsed(timeline?.summary?.elapsed_seconds)" />
      <MetricCard label="Recoveries" :value="timeline?.summary?.recovery_count ?? 0" :detail="`Artifacts ${timeline?.summary?.artifact_count ?? 0}`" />
    </section>

    <section class="grid gap-4 xl:grid-cols-[0.9fr,1.1fr]">
      <div class="premium-card p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Replay Controls</div>
        <div class="mt-4 space-y-3">
          <label class="space-y-1 text-sm text-slate-700">
            <span class="block font-medium text-slate-800">Run</span>
            <select
              v-model="selectedRunId"
              class="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              @change="loadTimeline"
            >
              <option v-for="run in runs" :key="run.id" :value="run.id">
                {{ runOptionLabel(run) }}
              </option>
            </select>
          </label>
          <div class="mission-subcard p-4 text-sm text-slate-600">
            <div><strong>Goal:</strong> {{ timeline?.summary?.goal_text || "—" }}</div>
            <div class="mt-2"><strong>Primary error:</strong> {{ timeline?.summary?.primary_error || "—" }}</div>
            <div class="mt-2"><strong>PR:</strong> {{ timeline?.summary?.pull_request_url || "—" }}</div>
          </div>
          <div v-if="timeline?.summary?.changed_files?.length" class="mission-subcard p-4 text-sm text-slate-600">
            <strong>Changed files:</strong> {{ timeline.summary.changed_files.join(", ") }}
          </div>
        </div>
      </div>

      <div class="premium-card p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Run Replay</div>
            <div class="mt-1 text-xs text-slate-500">Every recorded step across execution, healing, artifacts, and PR output.</div>
          </div>
          <span class="topbar-chip" v-if="timeline?.steps?.length">{{ timeline.steps.length }} steps</span>
        </div>

        <div v-if="error" class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          {{ error }}
        </div>

        <div v-if="loading" class="premium-empty mt-4">Loading replay timeline…</div>

        <div v-else-if="timeline?.steps?.length" class="mt-6 space-y-4">
          <div
            v-for="step in timeline.steps"
            :key="step.id"
            class="mission-subcard p-4"
          >
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="text-sm font-semibold text-slate-900">{{ step.title }}</div>
                <div class="mt-1 text-xs uppercase tracking-wide text-slate-400">{{ formatTimestamp(step.ts) }}</div>
                <div v-if="step.message" class="mt-3 text-sm text-slate-600">{{ step.message }}</div>
                <div class="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
                  <div v-if="step.work_item_key"><strong>Work item:</strong> {{ step.work_item_key }}</div>
                  <div v-if="step.artifact_type"><strong>Artifact:</strong> {{ step.artifact_type }}</div>
                  <div v-if="step.event_type"><strong>Event:</strong> {{ step.event_type }}</div>
                  <div v-if="step.changed_files?.length"><strong>Files:</strong> {{ step.changed_files.join(", ") }}</div>
                </div>
              </div>
              <span class="topbar-chip" :style="timelineStatusStyle(step.status)">{{ step.status }}</span>
            </div>
          </div>
        </div>

        <div v-else class="premium-empty mt-4">No replay data available yet.</div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import MetricCard from "../components/MetricCard.vue";
import { fetchProjectMeta, fetchRunTimeline, listRuns, resumeRun } from "../api/lifecycle";

const route = useRoute();
const router = useRouter();

const project = ref<any | null>(null);
const runs = ref<any[]>([]);
const timeline = ref<any | null>(null);
const loading = ref(false);
const resumeLoading = ref(false);
const error = ref("");
const actionError = ref("");
const selectedRunId = ref("");

const stageFlow = ["INTAKE", "PLAN", "RUN", "EVALUATE", "APPROVE", "DELIVER"];

const projectId = computed(() => (route.params.projectId as string) || "");
const requestedRunId = computed(() => ((route.params.runId as string) || (route.query.run as string) || ""));
const selectedRun = computed(() => runs.value.find((run) => run.id === selectedRunId.value) || runs.value[0] || null);
const selectedRunNeedsOperatorConfirmation = computed(() => {
  const run = selectedRun.value;
  if (!run) return false;
  const status = String(run.status || "").toUpperCase();
  const reason = String(run?.summary?.operator_confirmation_pause?.reason || "").toLowerCase();
  const failedError = String(run?.summary?.resume_state?.failed_error || "").toLowerCase();
  return status === "PAUSED" && (
    reason === "operator_confirmation_required" || failedError.includes("operator confirmation")
  );
});

watch(
  [projectId, requestedRunId],
  () => {
    if (!projectId.value) {
      error.value = "Project ID is required.";
      return;
    }
    void loadPage();
  },
  { immediate: true }
);

async function loadPage() {
  if (!projectId.value) return;
  loading.value = true;
  error.value = "";
  try {
    const [projectMeta, runList] = await Promise.all([
      fetchProjectMeta(projectId.value),
      listRuns(projectId.value),
    ]);
    project.value = projectMeta;
    runs.value = Array.isArray(runList) ? runList : [];
    selectedRunId.value = requestedRunId.value || runs.value[0]?.id || "";
    await loadTimeline();
  } catch (err: any) {
    error.value = err?.message || "Failed to load timeline.";
  } finally {
    loading.value = false;
  }
}

async function loadTimeline() {
  if (!selectedRunId.value) {
    timeline.value = null;
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    timeline.value = await fetchRunTimeline(selectedRunId.value);
    if (route.name === "run-debug") {
      const expectedPath = `/projects/${projectId.value}/runs/${selectedRunId.value}/debug`;
      if (route.path !== expectedPath) {
        await router.replace(expectedPath);
      }
    } else if (route.query.run !== selectedRunId.value) {
      await router.replace({
        path: `/projects/${projectId.value}/timeline`,
        query: { ...route.query, run: selectedRunId.value },
      });
    }
  } catch (err: any) {
    error.value = err?.message || "Failed to load replay timeline.";
  } finally {
    loading.value = false;
  }
}

async function confirmAndResumeRun() {
  if (!selectedRunId.value) return;
  resumeLoading.value = true;
  actionError.value = "";
  try {
    await resumeRun(selectedRunId.value, { start_now: true });
    await loadPage();
  } catch (err: any) {
    actionError.value = err?.message || "Failed to resume run.";
  } finally {
    resumeLoading.value = false;
  }
}

function openApprovals() {
  if (!projectId.value) return;
  router.push(`/projects/${projectId.value}/approvals`);
}

function goToMissionControl() {
  if (!projectId.value) return;
  router.push(`/projects/${projectId.value}/run`);
}

function formatTimestamp(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString();
}

function formatElapsed(seconds?: number | null) {
  if (typeof seconds !== "number") return "—";
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}m ${remainder}s`;
}

function runOptionLabel(run: any) {
  return `${String(run.id).slice(0, 8)} · ${run.status} · ${run.executor}`;
}

function stageStyle(stage: string) {
  const current = (project.value?.status || "").toUpperCase();
  if (stage === current) {
    return { background: "rgba(91, 156, 255, 0.12)", borderColor: "rgba(91, 156, 255, 0.22)", color: "var(--accent)" };
  }
  return { background: "var(--surface-soft)", borderColor: "var(--border-soft)", color: "var(--text-muted)" };
}

function stageHint(stage: string) {
  if (stage === "INTAKE") return "Capture goals";
  if (stage === "PLAN") return "Shape the DAG";
  if (stage === "RUN") return "Execute and heal";
  if (stage === "EVALUATE") return "Compare and explain";
  if (stage === "APPROVE") return "Human review gate";
  return "PR / delivery";
}

function timelineStatusStyle(status?: string | null) {
  switch ((status || "").toLowerCase()) {
    case "success":
      return { background: "rgba(34, 197, 94, 0.12)", color: "var(--success)" };
    case "failed":
      return { background: "rgba(239, 68, 68, 0.12)", color: "var(--danger)" };
    case "recovery":
      return { background: "rgba(245, 158, 11, 0.12)", color: "var(--warning)" };
    case "running":
      return { background: "rgba(91, 156, 255, 0.12)", color: "var(--accent)" };
    default:
      return { background: "var(--surface-soft)", color: "var(--text-muted)" };
  }
}
</script>
