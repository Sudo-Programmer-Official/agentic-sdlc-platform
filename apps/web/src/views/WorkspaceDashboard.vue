<template>
  <div class="page-stack">
    <section class="premium-card p-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div class="text-sm uppercase tracking-wide text-slate-400">Workspace Dashboard</div>
          <h1 class="mt-1 text-2xl font-semibold text-slate-900">Operational Control Center</h1>
          <div class="mt-1 text-sm text-slate-500">Cross-project health, runtime pressure, and failure hotspots.</div>
        </div>
        <el-button plain :loading="loading" @click="loadWorkspaceSignals">Refresh</el-button>
      </div>
      <div v-if="error" class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-600">
        {{ error }}
      </div>
    </section>

    <section class="surface-grid md:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="Workspace Health" :value="workspaceHealth.label" :detail="workspaceHealth.detail" :tone="workspaceHealth.tone">
        <template #icon><AppIcon name="status" /></template>
      </MetricCard>
      <MetricCard label="Projects" :value="projectCount" detail="Projects in selected workspace.">
        <template #icon><AppIcon name="workspace" /></template>
      </MetricCard>
      <MetricCard label="Active Runs" :value="activeRuns" detail="RUNNING or QUEUED executions.">
        <template #icon><AppIcon name="mission" /></template>
      </MetricCard>
      <MetricCard label="Failed Runs" :value="failedRuns" detail="Failures across recent runs.">
        <template #icon><AppIcon name="warning" /></template>
      </MetricCard>
      <MetricCard label="Readiness Avg" :value="`${readinessAvgScore}/100`" detail="Production readiness average across projects.">
        <template #icon><AppIcon name="spark" /></template>
      </MetricCard>
      <MetricCard label="Unstable Projects" :value="unstableProjects" detail="Projects with recent failures.">
        <template #icon><AppIcon name="status" /></template>
      </MetricCard>
      <MetricCard label="Deploy Trust" :value="workspaceDeployTrust.tier" :detail="workspaceDeployTrust.detail" :tone="workspaceDeployTrust.tone">
        <template #icon><AppIcon name="spark" /></template>
      </MetricCard>
    </section>

    <section class="grid gap-4 xl:grid-cols-[1.1fr,0.9fr]">
      <article class="premium-card p-6 xl:col-span-2">
        <div class="flex items-center justify-between gap-3">
          <div class="text-sm uppercase tracking-wide text-slate-400">{{ trendWindowLabel }} Trends</div>
          <el-segmented
            v-model="trendWindowDays"
            :options="trendWindowOptions"
            size="small"
          />
        </div>
        <div class="mt-4 grid gap-4 md:grid-cols-3">
          <div class="trend-card">
            <div class="trend-card__title">Failures</div>
            <div class="trend-bars" :style="trendGridStyle">
              <span
                v-for="point in failureTrend"
                :key="`f-${point.day}`"
                class="trend-bar trend-bar--danger"
                :style="{ height: `${barHeight(point.value, maxFailure)}px` }"
                :title="`${point.day}: ${point.value}`"
              />
            </div>
            <div class="trend-total">{{ totalFailureTrend }}</div>
          </div>
          <div class="trend-card">
            <div class="trend-card__title">Recoveries</div>
            <div class="trend-bars" :style="trendGridStyle">
              <span
                v-for="point in recoveryTrend"
                :key="`r-${point.day}`"
                class="trend-bar trend-bar--warning"
                :style="{ height: `${barHeight(point.value, maxRecovery)}px` }"
                :title="`${point.day}: ${point.value}`"
              />
            </div>
            <div class="trend-total">{{ totalRecoveryTrend }}</div>
          </div>
          <div class="trend-card">
            <div class="trend-card__title">Deploy Health %</div>
            <div class="trend-bars" :style="trendGridStyle">
              <span
                v-for="point in deployHealthTrend"
                :key="`d-${point.day}`"
                class="trend-bar trend-bar--success"
                :style="{ height: `${barHeight(point.value, 100)}px` }"
                :title="`${point.day}: ${point.value}%`"
              />
            </div>
            <div class="trend-total">{{ avgDeployHealthTrend }}%</div>
          </div>
        </div>
      </article>

      <article class="premium-card p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Usage + Cost ({{ usageWindowDays }}d)</div>
        <div class="mt-4 grid gap-2 text-sm">
          <div class="flex items-center justify-between"><span class="text-slate-500">Token burn</span><span class="font-semibold text-slate-900">{{ usageTokens.toLocaleString() }}</span></div>
          <div class="flex items-center justify-between"><span class="text-slate-500">Deployments</span><span class="font-semibold text-slate-900">{{ usageDeployments }}</span></div>
          <div class="flex items-center justify-between"><span class="text-slate-500">Recoveries</span><span class="font-semibold text-slate-900">{{ usageRecoveries }}</span></div>
          <div class="flex items-center justify-between"><span class="text-slate-500">AI cost (est.)</span><span class="font-semibold text-slate-900">${{ usageCostUsd }}</span></div>
        </div>
      </article>

      <article class="premium-card p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Recommended Actions</div>
        <div v-if="recommendedActions.length" class="mt-4 grid gap-2">
          <button
            v-for="(action, index) in recommendedActions"
            :key="`action-${index}`"
            class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-100"
            @click="openProject(action.projectId)"
          >
            {{ action.label }}
          </button>
        </div>
        <div v-else class="premium-empty mt-4">No urgent actions. Workspace looks stable.</div>
      </article>

      <article class="premium-card p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Connector Hub</div>
        <div class="mt-4 grid gap-2 text-sm">
          <div class="flex items-center justify-between"><span class="text-slate-500">GitHub project links</span><span class="font-semibold text-slate-900">{{ githubLinkedProjects }}/{{ projectCount }}</span></div>
          <div class="flex items-center justify-between"><span class="text-slate-500">Deployment connectors</span><span class="font-semibold text-slate-900">{{ deploymentConnectorCount }}</span></div>
          <div class="flex items-center justify-between"><span class="text-slate-500">Vercel connectors</span><span class="font-semibold text-slate-900">{{ vercelConnectorCount }}</span></div>
          <div class="flex items-center justify-between"><span class="text-slate-500">Render connectors</span><span class="font-semibold text-slate-900">{{ renderConnectorCount }}</span></div>
        </div>
        <div class="mt-3 text-xs text-slate-500">
          {{ connectorHealthSummary }}
        </div>
      </article>

      <article class="premium-card p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Environment Readiness</div>
        <div class="mt-2 text-sm font-semibold text-slate-900">{{ workspaceEnvironmentReadiness.scorePct }}% workspace baseline</div>
        <div class="mt-3 grid gap-1 text-xs text-slate-600">
          <div v-for="env in workspaceEnvironmentReadiness.environments" :key="env.environment" class="flex items-center justify-between">
            <span>{{ env.environment }}</span>
            <span>{{ env.scorePct }}% · user blockers {{ env.userPending }}</span>
          </div>
        </div>
        <div class="mt-2 text-xs text-slate-500">
          Managed by platform: orchestration/recovery. User-owned: credentials, domains, integrations, approvals.
        </div>
      </article>

      <article class="premium-card p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Project Stability</div>
        <div v-if="projectHealthRows.length" class="mt-4 grid gap-3">
          <div
            v-for="row in projectHealthRows"
            :key="row.id"
            class="rounded-2xl border border-slate-200 bg-slate-50 p-4"
          >
            <div class="flex items-center justify-between gap-3">
              <button class="text-left text-sm font-semibold text-slate-900 hover:underline" @click="openProject(row.id)">
                {{ row.name }}
              </button>
              <span class="topbar-chip">{{ row.statusLabel }}</span>
            </div>
            <div class="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
              <span class="topbar-chip">active {{ row.active }}</span>
              <span class="topbar-chip">failed {{ row.failed }}</span>
              <span class="topbar-chip">completed {{ row.completed }}</span>
              <span class="topbar-chip">readiness {{ row.readinessScore }}/100</span>
            </div>
          </div>
        </div>
        <div v-else class="premium-empty mt-4">No projects found for this workspace.</div>
      </article>

      <article class="premium-card p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Operational Feed</div>
        <div v-if="operationalFeed.length" class="mt-4 grid gap-3">
          <div
            v-for="entry in operationalFeed"
            :key="entry.key"
            class="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm"
          >
            <div class="flex items-center justify-between gap-2">
              <button class="font-mono text-xs text-slate-600 hover:underline" @click="openRun(entry.projectId, entry.runId)">
                {{ entry.runId.slice(0, 8) }}
              </button>
              <span class="topbar-chip">{{ entry.eventLabel }}</span>
            </div>
            <div class="mt-2 text-xs text-slate-500">{{ projectNameFor(entry.projectId) }} · {{ entry.whenLabel }}</div>
          </div>
        </div>
        <div v-else class="premium-empty mt-4">No operational events yet.</div>
      </article>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import AppIcon from "../components/AppIcon.vue";
import MetricCard from "../components/MetricCard.vue";
import { buildDeploymentTrustSummary, clampPercent } from "../composables/deploymentTrust";
import { buildEnvironmentReadiness } from "../composables/environmentReadiness";
import { fetchFoundationReadiness, fetchProjectRepo, fetchProjects, getActiveTenantId, getActiveWorkspaceId, getWorkspaceUsage, getWorkspaceEnvironmentChecklists, listDeploymentConnectors, listRuns } from "../api/lifecycle";

type ProjectRow = { id: string; name: string };
type RunRow = {
  id: string;
  project_id: string;
  status: string;
  created_at?: string | null;
  summary?: Record<string, any> | null;
};

const router = useRouter();
const loading = ref(false);
const error = ref("");
const TREND_WINDOW_STORAGE_KEY = "agentic.workspaceDashboard.trendWindowDays";
const trendWindowDays = ref<7 | 14 | 30>(7);
const projects = ref<ProjectRow[]>([]);
const runsByProject = ref<Record<string, RunRow[]>>({});
const readinessByProject = ref<Record<string, number>>({});
const repoLinkedByProject = ref<Record<string, boolean>>({});
const deploymentConnectors = ref<any[]>([]);
const workspaceChecklistSummaries = ref<any[]>([]);
const usageWindowDays = ref(30);
const usageSummary = ref<any | null>(null);
const trendWindowOptions = [
  { label: "7d", value: 7 },
  { label: "14d", value: 14 },
  { label: "30d", value: 30 },
];

const projectCount = computed(() => projects.value.length);
const allRuns = computed(() => Object.values(runsByProject.value).flat());
const activeRuns = computed(() =>
  allRuns.value.filter((run) => {
    const status = String(run.status || "").toUpperCase();
    return status === "RUNNING" || status === "QUEUED";
  }).length
);
const failedRuns = computed(() => allRuns.value.filter((run) => String(run.status || "").toUpperCase() === "FAILED").length);
const unstableProjects = computed(() =>
  Object.values(runsByProject.value).filter((runs) => runs.some((run) => String(run.status || "").toUpperCase() === "FAILED")).length
);
const usageTokens = computed(() => Number(usageSummary.value?.totals?.input_tokens || 0) + Number(usageSummary.value?.totals?.output_tokens || 0));
const usageDeployments = computed(() => Number(usageSummary.value?.totals?.deployments_count || 0));
const usageRecoveries = computed(() => Number(usageSummary.value?.totals?.recoveries_count || 0));
const usageCostUsd = computed(() => (Number(usageSummary.value?.totals?.total_cost_cents || 0) / 100).toFixed(2));
const readinessAvgScore = computed(() => {
  const scores = Object.values(readinessByProject.value);
  if (!scores.length) return 0;
  return Math.round(scores.reduce((acc, score) => acc + score, 0) / scores.length);
});
const githubLinkedProjects = computed(() => Object.values(repoLinkedByProject.value).filter(Boolean).length);
const deploymentConnectorCount = computed(() => deploymentConnectors.value.length);
const vercelConnectorCount = computed(() =>
  deploymentConnectors.value.filter((connector) => String(connector?.provider || "").toLowerCase() === "vercel").length
);
const renderConnectorCount = computed(() =>
  deploymentConnectors.value.filter((connector) => String(connector?.provider || "").toLowerCase() === "render").length
);
const connectorHealthSummary = computed(() => {
  if (!projectCount.value) return "Create the first project to attach workspace connectors.";
  if (!githubLinkedProjects.value) return "No project is linked to GitHub yet.";
  if (!deploymentConnectorCount.value) return "No deployment connector configured yet.";
  if (!vercelConnectorCount.value && !renderConnectorCount.value) return "Deployment connectors exist but provider coverage is missing.";
  return "Connector ownership looks healthy for this workspace.";
});
const trendWindowLabel = computed(() => `${trendWindowDays.value}-Day`);
const trendGridStyle = computed(() => ({
  gridTemplateColumns: `repeat(${trendWindowDays.value}, minmax(0, 1fr))`,
}));
const trendDays = computed(() => {
  const days: string[] = [];
  const now = new Date();
  for (let i = trendWindowDays.value - 1; i >= 0; i -= 1) {
    const day = new Date(now);
    day.setDate(now.getDate() - i);
    days.push(day.toISOString().slice(0, 10));
  }
  return days;
});
const dayRuns = computed(() => {
  const bucket: Record<string, RunRow[]> = Object.fromEntries(trendDays.value.map((day) => [day, []]));
  allRuns.value.forEach((run) => {
    const day = (run.created_at || "").slice(0, 10);
    if (!day || !bucket[day]) return;
    bucket[day].push(run);
  });
  return bucket;
});
const failureTrend = computed(() =>
  trendDays.value.map((day) => ({
    day,
    value: (dayRuns.value[day] || []).filter((run) => String(run.status || "").toUpperCase() === "FAILED").length,
  }))
);
const recoveryTrend = computed(() =>
  trendDays.value.map((day) => ({
    day,
    value: (dayRuns.value[day] || []).filter((run) => {
      const summary = run.summary || {};
      return Boolean(
        summary?.resume_state ||
          summary?.last_resume_checkpoint_id ||
          summary?.last_resume_workspace_rehydrated ||
          summary?.recovery
      );
    }).length,
  }))
);
const deployHealthTrend = computed(() =>
  trendDays.value.map((day) => {
    const runs = dayRuns.value[day] || [];
    const completed = runs.filter((run) => String(run.status || "").toUpperCase() === "COMPLETED").length;
    const failed = runs.filter((run) => String(run.status || "").toUpperCase() === "FAILED").length;
    const denom = completed + failed;
    const health = denom > 0 ? Math.round((completed / denom) * 100) : 100;
    return { day, value: health };
  })
);
const maxFailure = computed(() => Math.max(1, ...failureTrend.value.map((point) => point.value)));
const maxRecovery = computed(() => Math.max(1, ...recoveryTrend.value.map((point) => point.value)));
const totalFailureTrend = computed(() => failureTrend.value.reduce((acc, point) => acc + point.value, 0));
const totalRecoveryTrend = computed(() => recoveryTrend.value.reduce((acc, point) => acc + point.value, 0));
const avgDeployHealthTrend = computed(() => {
  const points = deployHealthTrend.value;
  if (!points.length) return 100;
  return Math.round(points.reduce((acc, point) => acc + point.value, 0) / points.length);
});

const projectHealthRows = computed(() => {
  return projects.value.map((project) => {
    const runs = runsByProject.value[project.id] || [];
    const active = runs.filter((run) => ["RUNNING", "QUEUED"].includes(String(run.status || "").toUpperCase())).length;
    const failed = runs.filter((run) => String(run.status || "").toUpperCase() === "FAILED").length;
    const completed = runs.filter((run) => String(run.status || "").toUpperCase() === "COMPLETED").length;
    const statusLabel = failed > 0 ? "Unstable" : active > 0 ? "Active" : "Stable";
    const readinessScore = readinessByProject.value[project.id] ?? 0;
    return {
      id: project.id,
      name: project.name || "Project",
      active,
      failed,
      completed,
      readinessScore,
      statusLabel,
    };
  });
});

const recentRuns = computed(() => allRuns.value.slice(0, 10));
const operationalFeed = computed(() =>
  allRuns.value
    .slice()
    .sort((a, b) => Date.parse(String(b.created_at || "")) - Date.parse(String(a.created_at || "")))
    .slice(0, 12)
    .map((run) => {
      const status = String(run.status || "").toUpperCase();
      const eventLabel =
        status === "FAILED" ? "Failure"
          : status === "RUNNING" ? "Run Active"
            : status === "QUEUED" ? "Run Queued"
              : status === "COMPLETED" ? "Run Completed"
                : status;
      const ts = Date.parse(String(run.created_at || ""));
      return {
        key: `${run.project_id}:${run.id}`,
        projectId: run.project_id,
        runId: run.id,
        eventLabel,
        whenLabel: Number.isFinite(ts) ? new Date(ts).toLocaleString() : "unknown time",
      };
    })
);
const workspaceHealth = computed(() => {
  const critical = failedRuns.value >= 5 || unstableProjects.value >= 3;
  const warning = !critical && (failedRuns.value >= 1 || activeRuns.value >= 6 || usageRecoveries.value >= 3);
  if (critical) return { label: "Critical", detail: "High failure pressure and instability detected.", tone: "danger" as const };
  if (warning) return { label: "Warning", detail: "Needs operator attention across active projects.", tone: "warning" as const };
  return { label: "Healthy", detail: "Runtime, deployment, and recovery signals are stable.", tone: "success" as const };
});
const workspaceDeployTrust = computed(() => {
  const deployHealth = avgDeployHealthTrend.value;
  const blockers = totalFailureTrend.value + usageRecoveries.value;
  const summary = buildDeploymentTrustSummary({
    confidencePct: deployHealth < 65 || blockers >= 12 ? Math.min(deployHealth, 55) : clampPercent(deployHealth),
    blockerSignals: [
      blockers >= 5 ? `${blockers} combined failure/recovery blockers` : "",
      totalFailureTrend.value > 0 ? `${totalFailureTrend.value} failures in selected trend window` : "",
    ],
    evidence: `${deployHealth}% deploy health trend across ${trendWindowDays.value} days`,
  });
  return {
    tier: summary.tier,
    tone: summary.tone,
    detail: summary.blockers.length ? `${summary.evidence} (${summary.blockers[0]}).` : `${summary.evidence}.`,
  };
});
const workspaceEnvironmentReadiness = computed(() => {
  if (workspaceChecklistSummaries.value.length) {
    const environments = ["PREVIEW", "STAGING", "PRODUCTION"].map((env) => {
      const matches = workspaceChecklistSummaries.value
        .map((item: any) => (Array.isArray(item?.environments) ? item.environments : []).find((row: any) => String(row?.environment || "").toUpperCase() === env))
        .filter(Boolean);
      const total = matches.reduce((acc: number, row: any) => acc + Number(row?.total || 0), 0);
      const completed = matches.reduce((acc: number, row: any) => acc + Number(row?.completed || 0), 0);
      const userPending = matches.reduce((acc: number, row: any) => acc + Number(row?.user_pending || 0), 0);
      const scorePct = total > 0 ? Math.round((completed / total) * 100) : 0;
      return { environment: env, scorePct, userPending };
    });
    const total = workspaceChecklistSummaries.value.reduce((acc: number, row: any) => acc + Number(row?.total || 0), 0);
    const completed = workspaceChecklistSummaries.value.reduce((acc: number, row: any) => acc + Number(row?.completed || 0), 0);
    const scorePct = total > 0 ? Math.round((completed / total) * 100) : 0;
    return { scorePct, environments };
  }
  const repoCoverageOk = projectCount.value > 0 && githubLinkedProjects.value === projectCount.value;
  const readinessGap = Math.max(0, 80 - readinessAvgScore.value);
  const syntheticMissing = readinessGap >= 20 ? ["architecture", "preview", "auth"] : readinessGap > 0 ? ["preview"] : [];
  return buildEnvironmentReadiness({
    hasRepo: repoCoverageOk,
    hasDeploymentConnector: deploymentConnectorCount.value > 0,
    deploymentProviders: deploymentConnectors.value.map((row: any) => String(row?.provider || "").toLowerCase()),
    foundationMissing: syntheticMissing,
    previewReady: avgDeployHealthTrend.value >= 75,
  });
});
const recommendedActions = computed(() => {
  const actions: Array<{ label: string; projectId: string }> = [];
  for (const row of projectHealthRows.value) {
    if (row.failed >= 2) actions.push({ label: `${row.name}: investigate repeated failed runs`, projectId: row.id });
    else if (row.active >= 3) actions.push({ label: `${row.name}: monitor high active run concurrency`, projectId: row.id });
  }
    if (usageDeployments.value === 0 && projectCount.value > 0) {
      const first = projects.value[0];
      if (first) actions.push({ label: "No deployments yet in workspace; configure first production path", projectId: first.id });
    }
    if (projectCount.value > 0 && githubLinkedProjects.value === 0) {
      const first = projects.value[0];
      if (first) actions.push({ label: "Workspace missing GitHub project links; connect repository on first project", projectId: first.id });
    }
    if (projectCount.value > 0 && deploymentConnectorCount.value === 0) {
      const first = projects.value[0];
      if (first) actions.push({ label: "Workspace missing deployment connectors; configure Vercel or Render connector", projectId: first.id });
    }
    const lowReadiness = projectHealthRows.value.find((row) => row.readinessScore < 60);
    if (lowReadiness) {
      actions.push({
        label: `${lowReadiness.name}: improve production readiness (${lowReadiness.readinessScore}/100)`,
        projectId: lowReadiness.id,
      });
    }
  return actions.slice(0, 6);
});

function scoreReadiness(readiness: any): number {
  const status = String(readiness?.status || "MISSING").toUpperCase();
  const missing = Array.isArray(readiness?.missing_prerequisites) ? readiness.missing_prerequisites.length : 0;
  let score = status === "READY" ? 86 : status === "PARTIAL" ? 62 : 35;
  score -= missing * 8;
  return Math.max(0, Math.min(100, Math.round(score)));
}

function projectNameFor(projectId: string) {
  return projects.value.find((project) => project.id === projectId)?.name || "Project";
}

async function loadWorkspaceSignals() {
  if (!getActiveTenantId()) {
    error.value = "Select a tenant before viewing workspace dashboard.";
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const projectRows = await fetchProjects();
    const normalizedProjects = Array.isArray(projectRows)
      ? projectRows.map((project: any) => ({ id: String(project.id), name: project.name || "Project" }))
      : [];
    projects.value = normalizedProjects;
    const workspaceId = getActiveWorkspaceId();
    if (workspaceId) {
      try {
        usageSummary.value = await getWorkspaceUsage(workspaceId, usageWindowDays.value);
      } catch {
        usageSummary.value = null;
      }
    } else {
      usageSummary.value = null;
    }

    const runEntries = await Promise.all(
      normalizedProjects.map(async (project) => {
        try {
          const runs = await listRuns(project.id);
          const normalizedRuns = Array.isArray(runs)
            ? runs.map((run: any) => ({
                id: String(run.id),
                project_id: String(run.project_id || project.id),
                status: String(run.status || "UNKNOWN"),
                created_at: typeof run.created_at === "string" ? run.created_at : null,
                summary: run.summary && typeof run.summary === "object" ? run.summary : null,
              }))
            : [];
          return [project.id, normalizedRuns] as const;
        } catch {
          return [project.id, []] as const;
        }
      })
    );
    runsByProject.value = Object.fromEntries(runEntries);

    const repoEntries = await Promise.all(
      normalizedProjects.map(async (project) => {
        try {
          const repo = await fetchProjectRepo(project.id);
          const linked = Boolean(repo?.repo_url || repo?.repo_full_name);
          return [project.id, linked] as const;
        } catch {
          return [project.id, false] as const;
        }
      })
    );
    repoLinkedByProject.value = Object.fromEntries(repoEntries);

    const readinessEntries = await Promise.all(
      normalizedProjects.map(async (project) => {
        try {
          const readiness = await fetchFoundationReadiness(project.id);
          return [project.id, scoreReadiness(readiness)] as const;
        } catch {
          return [project.id, 0] as const;
        }
      })
    );
    readinessByProject.value = Object.fromEntries(readinessEntries);
    try {
      const connectors = await listDeploymentConnectors();
      deploymentConnectors.value = Array.isArray(connectors) ? connectors : [];
    } catch {
      deploymentConnectors.value = [];
    }
    if (workspaceId) {
      try {
        const checklistRows = await getWorkspaceEnvironmentChecklists(workspaceId, false);
        workspaceChecklistSummaries.value = Array.isArray(checklistRows) ? checklistRows : [];
      } catch {
        workspaceChecklistSummaries.value = [];
      }
    } else {
      workspaceChecklistSummaries.value = [];
    }
  } catch (err: any) {
    error.value = err?.message || "Failed to load workspace dashboard.";
  } finally {
    loading.value = false;
  }
}

function openProject(projectId: string) {
  router.push(`/projects/${projectId}`);
}

function openRun(projectId: string, runId: string) {
  router.push(`/projects/${projectId}/runs/${runId}/debug`);
}

onMounted(() => {
  try {
    const saved = window.localStorage.getItem(TREND_WINDOW_STORAGE_KEY);
    if (saved === "7" || saved === "14" || saved === "30") {
      trendWindowDays.value = Number(saved) as 7 | 14 | 30;
    }
  } catch {
    // Ignore storage read failures.
  }
  void loadWorkspaceSignals();
});

watch(
  () => trendWindowDays.value,
  (value) => {
    try {
      window.localStorage.setItem(TREND_WINDOW_STORAGE_KEY, String(value));
    } catch {
      // Ignore storage write failures.
    }
  }
);

function barHeight(value: number, maxValue: number) {
  if (!maxValue || maxValue <= 0) return 8;
  return Math.max(8, Math.round((value / maxValue) * 56));
}
</script>

<style scoped>
.trend-card {
  border: 1px solid var(--border-soft);
  border-radius: 14px;
  background: var(--surface-soft);
  padding: 0.8rem;
}

.trend-card__title {
  font-size: 0.72rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-soft);
}

.trend-bars {
  margin-top: 0.8rem;
  height: 62px;
  display: grid;
  align-items: end;
  gap: 0.35rem;
}

.trend-bar {
  border-radius: 6px 6px 3px 3px;
}

.trend-bar--danger {
  background: rgba(239, 68, 68, 0.72);
}

.trend-bar--warning {
  background: rgba(245, 158, 11, 0.72);
}

.trend-bar--success {
  background: rgba(34, 197, 94, 0.72);
}

.trend-total {
  margin-top: 0.55rem;
  font-size: 0.82rem;
  color: var(--text-muted);
}
</style>
