<template>
  <div class="mx-auto w-full max-w-5xl space-y-6 p-4 md:p-6">
    <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h1 class="text-2xl font-semibold text-slate-900">Run Guide</h1>
      <p class="mt-2 text-sm text-slate-600">
        Use this page to run tasks in the correct order and resolve common runtime blockers quickly.
      </p>
    </section>

    <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 class="text-lg font-semibold text-slate-900">Recommended Order</h2>
      <div v-if="projectId && recommendation" class="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
        <p class="font-semibold">Recommended Next Action</p>
        <p class="mt-1">
          {{ recommendation.title }}
          <span class="text-xs text-emerald-700">({{ recommendation.task_id.slice(0, 8) }})</span>
        </p>
        <p class="mt-1 text-xs text-emerald-700">{{ recommendation.reason }}</p>
      </div>
      <p v-else-if="projectId && loadError" class="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
        Unable to load run recommendations right now.
      </p>
      <p v-else-if="projectId && loading" class="mt-3 text-sm text-slate-500">Loading recommendations...</p>
      <ol class="mt-3 list-decimal space-y-2 pl-5 text-sm text-slate-700">
        <li>Initialize foundation tasks first (frontend/backend/contracts/requirements/CI/deployment/telemetry).</li>
        <li>Run foundation validation task.</li>
        <li>Start feature capabilities after foundation passes.</li>
      </ol>
      <p class="mt-3 text-xs text-slate-500">
        If a task is missing from pending list, it is usually already completed, failed, canceled, or superseded.
      </p>
      <div v-if="blockedBy.length" class="mt-3">
        <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Current Blockers</p>
        <ul class="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-700">
          <li v-for="blocker in blockedBy" :key="blocker">{{ blocker }}</li>
        </ul>
      </div>
      <div v-if="recoverySuggestions.length" class="mt-3">
        <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Recovery Suggestions</p>
        <ul class="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-700">
          <li v-for="suggestion in recoverySuggestions" :key="suggestion">{{ suggestion }}</li>
        </ul>
      </div>
    </section>

    <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 class="text-lg font-semibold text-slate-900">Task Status Meaning</h2>
      <ul class="mt-3 space-y-2 text-sm text-slate-700">
        <li><strong>PENDING</strong>: queued, not started</li>
        <li><strong>RUNNING</strong>: currently executing</li>
        <li><strong>DONE</strong>: completed successfully</li>
        <li><strong>FAILED</strong>: execution failed and may trigger recovery</li>
        <li><strong>BLOCKED</strong>: paused by governance or operator gate</li>
        <li><strong>CANCELED</strong>: stopped due to upstream failure or manual cancel</li>
        <li><strong>SUPERSEDED</strong>: replaced by a newer recovery/decomposed work item</li>
      </ul>
    </section>

    <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 class="text-lg font-semibold text-slate-900">Common Blockers</h2>
      <ul class="mt-3 space-y-2 text-sm text-slate-700">
        <li><strong>Design token violation</strong>: add/fix token in design contract or use approved tokens only.</li>
        <li><strong>Patch too large</strong>: split into smaller phases or switch to write-file bootstrap strategy.</li>
        <li><strong>Session expired</strong>: sign in again; runtime should resume with preserved redirect.</li>
        <li><strong>Operator confirmation required</strong>: approve or decompose scope before rerun.</li>
      </ul>
    </section>

    <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 class="text-lg font-semibold text-slate-900">Quick Actions</h2>
      <div class="mt-3 flex flex-wrap gap-2">
        <button class="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700" @click="goWorkspace">
          Open Workspace
        </button>
        <button
          class="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700"
          :disabled="!projectId"
          @click="goMissionControl"
        >
          Open Mission Control
        </button>
        <button
          class="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700"
          :disabled="!projectId"
          @click="goProjectOverview"
        >
          Open Project Overview
        </button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { fetchRunRecommendations } from "../api/lifecycle";
import { projectContext } from "../state/projectContext";

const router = useRouter();
const projectId = computed(() => projectContext.projectId || "");
const loading = ref(false);
const loadError = ref(false);
const recommendation = ref<{ task_id: string; title: string; reason: string } | null>(null);
const blockedBy = ref<string[]>([]);
const recoverySuggestions = ref<string[]>([]);

async function loadRecommendations() {
  if (!projectId.value) {
    recommendation.value = null;
    blockedBy.value = [];
    recoverySuggestions.value = [];
    return;
  }
  loading.value = true;
  loadError.value = false;
  try {
    const data = await fetchRunRecommendations(projectId.value);
    const next = data?.recommended_next_task;
    recommendation.value = next
      ? {
          task_id: String(next.task_id || ""),
          title: String(next.title || "Recommended task"),
          reason: String(next.reason || "Runtime-derived recommendation"),
        }
      : null;
    blockedBy.value = Array.isArray(data?.blocked_by) ? data.blocked_by.map((entry: any) => String(entry)) : [];
    recoverySuggestions.value = Array.isArray(data?.recovery_suggestions)
      ? data.recovery_suggestions.map((entry: any) => String(entry))
      : [];
  } catch {
    loadError.value = true;
    recommendation.value = null;
    blockedBy.value = [];
    recoverySuggestions.value = [];
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void loadRecommendations();
});

watch(projectId, () => {
  void loadRecommendations();
});

function goWorkspace() {
  void router.push("/workspace");
}

function goMissionControl() {
  if (!projectId.value) return;
  void router.push(`/projects/${projectId.value}/run`);
}

function goProjectOverview() {
  if (!projectId.value) return;
  void router.push(`/projects/${projectId.value}`);
}
</script>
