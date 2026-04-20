<template>
  <div class="page-stack">
    <section class="premium-hero operator-hero">
      <div class="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
        <div class="max-w-3xl">
          <div class="premium-hero__eyebrow">AI Cost Control</div>
          <h1 class="premium-hero__title">Track spend, retries, context bloat, and human escalations before they become a burn pattern.</h1>
          <p class="premium-hero__copy">
            Every routed AI job lands here, including deterministic `tier_none` workflows. The view is scoped to the active project so routing leaks and expensive loops are visible early.
          </p>
        </div>
        <div class="operator-hero__controls">
          <el-button :loading="loading" @click="loadPage">Refresh</el-button>
        </div>
      </div>
    </section>

    <div v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
      {{ error }}
    </div>

    <section v-if="dashboard" class="surface-grid md:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="Total Jobs" :value="dashboard.summary.total_jobs" :detail="`${dashboard.summary.retry_count} retries recorded`" tone="warning">
        <template #icon><AppIcon name="operator" size="lg" /></template>
      </MetricCard>
      <MetricCard label="Total Cost" :value="formatCost(dashboard.summary.total_cost_cents)" :detail="`Avg ${formatCost(dashboard.summary.cost_per_run)} per routed job`" tone="danger">
        <template #icon><AppIcon name="mission" size="lg" /></template>
      </MetricCard>
      <MetricCard label="Success Rate" :value="formatPercent(dashboard.summary.success_rate)" :detail="`Approval rate ${formatPercent(dashboard.summary.approval_rate)}`" tone="success">
        <template #icon><AppIcon name="status" size="lg" /></template>
      </MetricCard>
      <MetricCard label="Context Packs" :value="dashboard.summary.unique_context_packs" :detail="`Reuse ${formatPercent(dashboard.summary.context_pack_reuse_rate)} · avg ${Math.round(dashboard.summary.average_context_size)} tokens`" tone="neutral">
        <template #icon><AppIcon name="map" size="lg" /></template>
      </MetricCard>
    </section>

    <section v-if="dashboard" class="operator-dashboard-grid">
      <div class="premium-card operator-panel p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Spend Breakdown</div>
            <div class="text-xs text-slate-500">
              Compare routing behavior across tiers, feature scopes, surfaces, and connected repositories.
            </div>
          </div>
          <span class="topbar-chip">{{ formatCost(dashboard.summary.average_cost_per_docs_proposal) }} docs avg</span>
        </div>

        <div class="mt-5 grid gap-4 xl:grid-cols-2 2xl:grid-cols-4">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div class="text-xs uppercase tracking-wide text-slate-400">By Tier</div>
            <div class="mt-4 space-y-3">
              <div v-for="item in dashboard.spend_by_tier" :key="`tier-${item.key}`" class="flex items-center justify-between gap-3 text-sm">
                <div>
                  <div class="font-semibold text-slate-900">{{ item.label }}</div>
                  <div class="text-xs text-slate-500">{{ item.job_count }} jobs</div>
                </div>
                <div class="font-mono text-slate-700">{{ formatCost(item.cost_cents) }}</div>
              </div>
            </div>
          </div>

          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div class="text-xs uppercase tracking-wide text-slate-400">By Feature</div>
            <div class="mt-4 space-y-3">
              <div v-for="item in dashboard.spend_by_feature" :key="`feature-${item.key}`" class="flex items-center justify-between gap-3 text-sm">
                <div>
                  <div class="font-semibold text-slate-900">{{ item.label }}</div>
                  <div class="text-xs text-slate-500">{{ item.job_count }} jobs</div>
                </div>
                <div class="font-mono text-slate-700">{{ formatCost(item.cost_cents) }}</div>
              </div>
            </div>
          </div>

          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div class="text-xs uppercase tracking-wide text-slate-400">By Surface</div>
            <div class="mt-4 space-y-3">
              <div v-for="item in dashboard.spend_by_surface" :key="`surface-${item.key}`" class="flex items-center justify-between gap-3 text-sm">
                <div>
                  <div class="font-semibold text-slate-900">{{ item.label }}</div>
                  <div class="text-xs text-slate-500">{{ item.job_count }} jobs</div>
                </div>
                <div class="font-mono text-slate-700">{{ formatCost(item.cost_cents) }}</div>
              </div>
            </div>
          </div>

          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div class="text-xs uppercase tracking-wide text-slate-400">By Repository</div>
            <div class="mt-4 space-y-3">
              <div v-for="item in dashboard.spend_by_repository" :key="`repo-${item.key}`" class="flex items-center justify-between gap-3 text-sm">
                <div>
                  <div class="font-semibold text-slate-900">{{ item.label }}</div>
                  <div class="text-xs text-slate-500">{{ item.job_count }} jobs</div>
                </div>
                <div class="font-mono text-slate-700">{{ formatCost(item.cost_cents) }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="premium-card operator-panel p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Workflow Metrics</div>
            <div class="text-xs text-slate-500">
              Calls, tokens, retries, and approvals summarized by routed workflow.
            </div>
          </div>
          <span class="topbar-chip">{{ formatCost(dashboard.summary.average_cost_per_successful_pr) }} successful PR avg</span>
        </div>

        <div class="mt-5 overflow-x-auto">
          <table class="min-w-full text-sm">
            <thead class="text-left text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th class="pb-3 pr-4">Workflow</th>
                <th class="pb-3 pr-4">Cost / Run</th>
                <th class="pb-3 pr-4">Calls / Run</th>
                <th class="pb-3 pr-4">Tokens / Run</th>
                <th class="pb-3 pr-4">Retries</th>
                <th class="pb-3 pr-4">Escalation</th>
                <th class="pb-3">Success</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="workflow in dashboard.workflows" :key="workflow.workflow_type" class="border-t border-slate-100 text-slate-700">
                <td class="py-3 pr-4 font-semibold text-slate-900">{{ workflow.workflow_type }}</td>
                <td class="py-3 pr-4 font-mono">{{ formatCost(workflow.cost_per_run) }}</td>
                <td class="py-3 pr-4">{{ workflow.calls_per_run.toFixed(2) }}</td>
                <td class="py-3 pr-4">{{ Math.round(workflow.tokens_per_run) }}</td>
                <td class="py-3 pr-4">{{ workflow.retry_count }}</td>
                <td class="py-3 pr-4">{{ formatPercent(workflow.manual_escalation_rate) }}</td>
                <td class="py-3">{{ formatPercent(workflow.success_rate) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <section v-if="dashboard" class="operator-dashboard-grid">
      <div class="premium-card operator-panel p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Top Retry Offenders</div>
        <div class="mt-4 grid gap-3">
          <div v-for="item in dashboard.top_retry_offenders" :key="item.id" class="operator-row-card">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="font-semibold text-slate-900">{{ item.label }}</span>
                  <span class="topbar-chip">{{ item.selected_model_tier }}</span>
                </div>
                <div class="mt-2 text-sm text-slate-600">
                  {{ item.retry_count }} retries · {{ item.context_size }} context tokens · {{ item.status }}
                </div>
              </div>
              <span class="font-mono text-slate-600">{{ formatCost(item.cost_cents) }}</span>
            </div>
          </div>
          <div v-if="!dashboard.top_retry_offenders.length" class="premium-empty">
            No retry offenders recorded yet.
          </div>
        </div>
      </div>

      <div class="premium-card operator-panel p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Largest Context Offenders</div>
        <div class="mt-4 grid gap-3">
          <div v-for="item in dashboard.largest_context_offenders" :key="item.id" class="operator-row-card">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="font-semibold text-slate-900">{{ item.label }}</span>
                  <span class="topbar-chip">{{ item.selected_model_tier }}</span>
                </div>
                <div class="mt-2 text-sm text-slate-600">
                  {{ item.context_size }} context tokens · {{ item.retry_count }} retries · {{ item.status }}
                </div>
              </div>
              <span class="font-mono text-slate-600">{{ formatCost(item.cost_cents) }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section v-if="dashboard" class="premium-card operator-panel p-6">
      <div class="flex items-center justify-between gap-3">
        <div>
          <div class="text-sm uppercase tracking-wide text-slate-400">Recent Jobs</div>
          <div class="text-xs text-slate-500">
            The latest routed jobs, including deterministic documentation and webhook analysis steps.
          </div>
        </div>
      </div>

      <div class="mt-5 overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead class="text-left text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th class="pb-3 pr-4">Workflow</th>
              <th class="pb-3 pr-4">Feature / Surface</th>
              <th class="pb-3 pr-4">Tier</th>
              <th class="pb-3 pr-4">Cost</th>
              <th class="pb-3 pr-4">Context</th>
              <th class="pb-3 pr-4">Approval</th>
              <th class="pb-3 pr-4">Status</th>
              <th class="pb-3">Created</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in dashboard.recent_jobs" :key="item.id" class="border-t border-slate-100 text-slate-700">
              <td class="py-3 pr-4">
                <div class="font-semibold text-slate-900">{{ item.workflow_type }}</div>
                <div class="text-xs text-slate-500">{{ item.role }}</div>
              </td>
              <td class="py-3 pr-4">
                <div>{{ formatDimension(item.feature_key) }}</div>
                <div class="text-xs text-slate-500">
                  {{ formatDimension(item.surface) }}
                  <span v-if="item.entrypoint">· {{ item.entrypoint }}</span>
                </div>
              </td>
              <td class="py-3 pr-4">{{ item.selected_model_tier }}</td>
              <td class="py-3 pr-4 font-mono">{{ formatCost(item.cost_cents) }}</td>
              <td class="py-3 pr-4">{{ item.context_size }}</td>
              <td class="py-3 pr-4">{{ item.approval_state }}</td>
              <td class="py-3 pr-4">{{ item.status }}</td>
              <td class="py-3">{{ formatDate(item.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";

import AppIcon from "../components/AppIcon.vue";
import MetricCard from "../components/MetricCard.vue";
import { fetchProjectMeta } from "../api/lifecycle";
import { fetchAiOpsDashboard } from "../api/aiOps";
import { updateProjectContext } from "../state/projectContext";

const route = useRoute();
const loading = ref(false);
const error = ref("");
const dashboard = ref<any | null>(null);
const projectId = computed(() => String(route.params.projectId || ""));

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
    const [project, data] = await Promise.all([
      fetchProjectMeta(projectId.value),
      fetchAiOpsDashboard({ project_id: projectId.value }),
    ]);
    dashboard.value = data;
    updateProjectContext({
      projectId: projectId.value,
      projectName: project?.name || "Project",
      stage: project?.status || "UNKNOWN",
      updatedAt: new Date().toISOString(),
    });
  } catch (err: any) {
    error.value = err?.message || "Failed to load the AI ops dashboard.";
  } finally {
    loading.value = false;
  }
}

function formatPercent(value?: number) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function formatCost(value?: number) {
  return `${Number(value || 0).toFixed(2)}c`;
}

function formatDate(value?: string) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString();
}

function formatDimension(value?: string | null) {
  if (!value) return "—";
  return value
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
</script>
