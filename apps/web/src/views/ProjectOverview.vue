<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-3xl font-semibold text-slate-900">Project Overview</h1>
        <p class="text-slate-600">Review project state and enter Mission Control when ready.</p>
      </div>
      <el-button type="primary" :disabled="!projectId" @click="goToRun">
        Enter Mission Control
      </el-button>
    </div>

    <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Project</div>
        <div class="mt-2 text-lg font-semibold text-slate-900">{{ projectName || "—" }}</div>
        <div class="text-xs text-slate-500 break-all">ID: {{ projectId || "—" }}</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Stage</div>
        <div class="mt-2 flex items-center gap-2 text-lg font-semibold text-slate-900">
          <StageBadge :label="stage" />
          <span>{{ stage }}</span>
        </div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Runs</div>
        <div class="mt-2 text-lg font-semibold text-slate-900">{{ runSummary }}</div>
        <div class="text-xs text-slate-500">Latest: {{ latestRunText }}</div>
      </div>
    </div>

    <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Plan Freshness</div>
        <div class="mt-2 text-sm font-semibold" :class="planMeta?.plan_fresh ? 'text-emerald-600' : 'text-amber-600'">
          {{ planMeta?.plan_fresh ? 'Fresh' : 'Stale or missing' }}
        </div>
        <div class="text-xs text-slate-500 break-all">Plan SHA: {{ shortSha(planMeta?.plan_requirements_sha) }}</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Requirements</div>
        <div class="mt-2 text-sm font-semibold">Version: {{ planMeta?.requirements_version ?? '—' }}</div>
        <div class="text-xs text-slate-500 break-all">Req SHA: {{ shortSha(planMeta?.requirements_sha) }}</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Plan Metadata</div>
        <div class="mt-2 text-sm font-semibold">Plan ID: {{ planMeta?.plan_id || '—' }}</div>
        <div class="text-xs text-slate-500">Created: {{ planMeta?.plan_created_at || '—' }}</div>
      </div>
    </div>

    <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm" v-if="planHistory.length">
      <div class="flex items-center justify-between">
        <div class="text-sm uppercase tracking-wide text-slate-400">Plan History</div>
        <span class="text-xs text-slate-500">Latest {{ Math.min(planHistory.length, 5) }} shown</span>
      </div>
      <el-table :data="planHistory.slice(-5).reverse()" size="small" class="mt-3">
        <el-table-column prop="version" label="Version" width="90" />
        <el-table-column prop="plan_id" label="Plan ID" />
        <el-table-column label="Req SHA" width="140">
          <template #default="{ row }">
            {{ shortSha(row.requirements_sha) }}
          </template>
        </el-table-column>
        <el-table-column prop="triggered_by" label="Triggered By" width="140" />
        <el-table-column prop="created_at" label="Created At" />
      </el-table>
    </div>

    <div class="grid gap-4 md:grid-cols-3">
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Architecture Refresh</div>
        <div class="mt-2 text-sm font-semibold" :class="architectureRefreshNeeded ? 'text-amber-600' : 'text-slate-700'">
          {{ architectureRefreshNeeded ? 'Needed' : 'Up to date' }}
        </div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Plan Refresh</div>
        <div class="mt-2 text-sm font-semibold" :class="planRefreshNeeded ? 'text-amber-600' : 'text-slate-700'">
          {{ planRefreshNeeded ? 'Needed' : 'Up to date' }}
        </div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Test Refresh</div>
        <div class="mt-2 text-sm font-semibold" :class="testRefreshNeeded ? 'text-amber-600' : 'text-slate-700'">
          {{ testRefreshNeeded ? 'Needed' : 'Up to date' }}
        </div>
      </div>
    </div>

    <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div class="text-sm uppercase tracking-wide text-slate-400">Actions</div>
      <div class="mt-4 flex flex-wrap gap-3">
        <el-button @click="goHome">Switch Project</el-button>
        <el-button :disabled="!projectId" @click="goToRun">Enter Mission Control</el-button>
      </div>
    </div>

    <div class="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
      Tip: Mission Control becomes available when a run is active. You can start a run from the API or future run controls.
    </div>

    <span v-if="error" class="text-sm text-rose-600">{{ error }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import StageBadge from "../components/StageBadge.vue";
import { projectContext } from "../state/projectContext";
import { fetchProjectSummary, fetchPlanHistory } from "../api/requirements";

const route = useRoute();
const router = useRouter();
const error = computed(() => (!projectContext.projectId ? "No project selected." : ""));

const projectId = computed(() => (route.params.projectId as string) || projectContext.projectId);
const projectName = computed(() => projectContext.projectName || "Project");
const stage = computed(() => projectContext.stage || "UNKNOWN");
const runSummary = computed(() => (projectContext.latestRunId ? "Has runs" : "No runs yet"));
const latestRunText = computed(() => projectContext.latestRunId || "None");
const architectureRefreshNeeded = computed(() => projectContext.architectureRefreshNeeded);
const planRefreshNeeded = computed(() => projectContext.planRefreshNeeded);
const testRefreshNeeded = computed(() => projectContext.testRefreshNeeded);
const planMeta = ref<any | null>(null);
const planHistory = ref<any[]>([]);

function goHome() {
  router.push("/");
}

function goToRun() {
  if (!projectId.value) return;
  router.push(`/projects/${projectId.value}/run`);
}

function shortSha(val?: string | null) {
  if (!val) return "—";
  return val.slice(0, 8);
}

onMounted(async () => {
  if (!projectId.value) return;
  try {
    const data = await fetchProjectSummary(projectId.value);
    planMeta.value = {
      plan_id: data.plan_id,
      plan_fresh: data.plan_fresh,
      requirements_sha: data.requirements_sha,
      plan_requirements_sha: data.plan_requirements_sha,
      plan_created_at: data.plan_created_at,
      requirements_version: data.requirements_version,
    };
    const history = await fetchPlanHistory(projectId.value);
    planHistory.value = history.entries || [];
  } catch {
    /* ignore */
  }
});
</script>
