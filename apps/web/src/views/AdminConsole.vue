<template>
  <div class="page-stack">
    <section class="premium-card p-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div class="text-sm uppercase tracking-wide text-slate-400">Admin</div>
          <h1 class="mt-1 text-2xl font-semibold text-slate-900">Workspace Operations</h1>
          <div class="mt-1 text-sm text-slate-500">Audited impersonation and workspace-level control surface.</div>
        </div>
        <el-button plain :loading="loading" @click="loadAll">Refresh</el-button>
      </div>
      <div v-if="error" class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{{ error }}</div>
      <div v-if="forbidden" class="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
        Super admin access required.
      </div>
    </section>

    <section class="grid gap-4 xl:grid-cols-[1.1fr,0.9fr]">
      <article class="premium-card p-6">
        <div class="flex items-center justify-between gap-2">
          <div class="text-sm uppercase tracking-wide text-slate-400">Daemon Health</div>
          <span
            class="topbar-chip"
            :style="
              daemonHealth.alert_level === 'warn'
                ? 'border-color: rgba(245, 158, 11, 0.35); color: #b45309;'
                : 'border-color: rgba(16, 185, 129, 0.35); color: #047857;'
            "
          >
            {{ daemonHealth.alert_level === "warn" ? "Warning" : "Healthy" }}
          </span>
        </div>
        <div class="mt-4 grid gap-2 text-sm text-slate-700">
          <div>Last cycle: <span class="font-semibold">{{ formatTime(daemonHealth.last_cycle_at) }}</span></div>
          <div>Window days: <span class="font-semibold">{{ daemonHealth.last_cycle_window_days || "—" }}</span></div>
          <div>Workspaces processed: <span class="font-semibold">{{ daemonHealth.last_cycle_workspaces_processed || 0 }}</span></div>
          <div>Workspace failures: <span class="font-semibold">{{ daemonHealth.last_cycle_workspace_failures || 0 }}</span></div>
          <div>Last error: <span class="font-semibold">{{ formatTime(daemonHealth.last_error_at) }}</span></div>
          <div v-if="(daemonHealth.alert_reasons || []).length">
            Alert reasons:
            <span class="font-semibold">{{ (daemonHealth.alert_reasons || []).join(", ") }}</span>
          </div>
        </div>
      </article>

      <article class="premium-card p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Workspaces</div>
        <div class="mt-3 flex gap-2">
          <el-input v-model="workspaceQuery" placeholder="Search workspace" clearable @keyup.enter="loadWorkspaces" />
          <el-button plain @click="loadWorkspaces">Search</el-button>
        </div>
        <div class="mt-4 grid gap-3">
          <button
            v-for="workspace in workspaces"
            :key="workspace.id"
            class="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-left"
            :class="{ 'ring-2 ring-slate-400': selectedWorkspaceId === workspace.id }"
            @click="selectWorkspace(workspace.id)"
          >
            <div class="text-sm font-semibold text-slate-900">{{ workspace.name || workspace.id }}</div>
            <div class="mt-1 text-xs text-slate-500">{{ workspace.id }}</div>
          </button>
          <div v-if="!workspaces.length" class="premium-empty">No workspaces found.</div>
        </div>
      </article>

      <article class="premium-card p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Impersonation Session</div>
        <div class="mt-3 grid gap-3">
          <el-input v-model="reason" type="textarea" :rows="3" placeholder="Reason (required for audit quality)" />
          <div class="flex items-center gap-2">
            <el-button type="primary" :disabled="!selectedWorkspaceId || actionBusy" :loading="actionBusy" @click="startSession">
              Start
            </el-button>
            <el-button plain :disabled="!activeSessionId || actionBusy" :loading="actionBusy" @click="endSession">End</el-button>
          </div>
          <div class="text-xs text-slate-500">
            Active session: <span class="font-mono">{{ activeSessionId ? activeSessionId.slice(0, 8) : 'none' }}</span>
          </div>
        </div>
      </article>
    </section>

    <section class="grid gap-4 xl:grid-cols-2">
      <article class="premium-card p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Entitlements</div>
        <div class="mt-3 grid gap-3">
          <el-input v-model="entitlementPlan" placeholder="Plan (starter/pro/enterprise)" />
          <el-input v-model="entitlementLimitsJson" type="textarea" :rows="4" placeholder="Limits JSON" />
          <el-input v-model="entitlementFeaturesJson" type="textarea" :rows="4" placeholder="Features JSON" />
          <div class="flex items-center gap-2">
            <el-button plain :disabled="!selectedWorkspaceId || actionBusy" :loading="actionBusy" @click="loadEntitlements">Load</el-button>
            <el-button type="primary" :disabled="!selectedWorkspaceId || actionBusy" :loading="actionBusy" @click="saveEntitlements">Save</el-button>
          </div>
        </div>
      </article>
      <article class="premium-card p-6">
        <div class="flex items-center justify-between gap-2">
          <div class="text-sm uppercase tracking-wide text-slate-400">Usage Snapshot</div>
          <div class="flex items-center gap-2">
            <el-select v-model="usageWindowDays" size="small" style="width: 100px;">
              <el-option :value="7" label="7d" />
              <el-option :value="30" label="30d" />
            </el-select>
            <el-button plain size="small" :loading="usageSyncing" :disabled="!selectedWorkspaceId || usageSyncing" @click="materializeUsage">
              Materialize Usage
            </el-button>
          </div>
        </div>
        <div class="mt-4 grid gap-2 text-sm text-slate-700">
          <div>Runs: <span class="font-semibold">{{ usageTotals.runs_count }}</span></div>
          <div>Deployments: <span class="font-semibold">{{ usageTotals.deployments_count }}</span></div>
          <div>Recoveries: <span class="font-semibold">{{ usageTotals.recoveries_count }}</span></div>
          <div>Tokens: <span class="font-semibold">{{ usageTotals.input_tokens + usageTotals.output_tokens }}</span></div>
          <div>Cost (cents): <span class="font-semibold">{{ usageTotals.total_cost_cents }}</span></div>
        </div>
        <div class="mt-4">
          <div class="text-xs uppercase tracking-wide text-slate-400">Run Trend</div>
          <div class="mt-2 flex items-end gap-1">
            <div
              v-for="point in usageDaily"
              :key="point.usage_date"
              class="w-2 rounded bg-slate-400/70"
              :style="{ height: `${Math.max(4, Math.round(((point.runs_count || 0) / maxRuns) * 56))}px` }"
              :title="`${point.usage_date}: ${point.runs_count} runs`"
            />
          </div>
        </div>
      </article>
    </section>

    <section class="premium-card p-6">
      <div class="flex items-center justify-between gap-2">
        <div class="text-sm uppercase tracking-wide text-slate-400">Workspace Leaderboard</div>
        <div class="flex items-center gap-2">
          <div class="text-xs text-slate-500">Sorted by token burn ({{ usageWindowDays }}d)</div>
          <el-button plain size="small" :loading="anomalySyncing" :disabled="anomalySyncing" @click="materializeAnomalies">
            Materialize Anomalies
          </el-button>
        </div>
      </div>
      <div class="mt-4 grid gap-3">
        <div
          v-for="row in workspaceLeaderboard"
          :key="row.id"
          class="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm"
        >
          <div class="flex items-center justify-between gap-3">
            <button class="font-semibold text-slate-900 hover:underline" @click="selectWorkspace(row.id)">
              {{ row.name }}
            </button>
            <span class="text-xs text-slate-500">tokens {{ row.tokens }}</span>
          </div>
          <div class="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
            <span class="topbar-chip">runs {{ row.runs }}</span>
            <span class="topbar-chip">recoveries {{ row.recoveries }}</span>
            <span class="topbar-chip">cost {{ row.cost }}c</span>
            <span
              v-if="row.burnSpike"
              class="topbar-chip"
              style="border-color: rgba(244, 63, 94, 0.35); color: #be123c;"
            >burn spike</span>
            <span
              v-if="row.failureSpike"
              class="topbar-chip"
              style="border-color: rgba(245, 158, 11, 0.35); color: #b45309;"
            >failure spike</span>
          </div>
        </div>
        <div v-if="!workspaceLeaderboard.length" class="premium-empty">No workspace usage data yet.</div>
      </div>
    </section>

    <section class="premium-card p-6">
      <div class="text-sm uppercase tracking-wide text-slate-400">Historical Spike Events</div>
      <div class="mt-4 grid gap-3">
        <div
          v-for="row in anomalyEvents"
          :key="row.id"
          class="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm"
        >
          <div class="flex items-center justify-between gap-3">
            <span class="font-semibold text-slate-900">{{ row.workspace_id }}</span>
            <span class="text-xs text-slate-500">{{ row.snapshot_date }}</span>
          </div>
          <div class="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
            <span class="topbar-chip">window {{ row.window_days }}d</span>
            <span class="topbar-chip">tokens {{ row.total_tokens }}</span>
            <span class="topbar-chip">recoveries {{ row.recoveries_count }}</span>
            <span v-if="row.burn_spike" class="topbar-chip" style="border-color: rgba(244, 63, 94, 0.35); color: #be123c;">
              burn {{ row.burn_ratio || "spike" }}x
            </span>
            <span v-if="row.failure_spike" class="topbar-chip" style="border-color: rgba(245, 158, 11, 0.35); color: #b45309;">
              failure {{ row.failure_ratio || "spike" }}x
            </span>
          </div>
        </div>
        <div v-if="!anomalyEvents.length" class="premium-empty">No recorded anomaly events.</div>
      </div>
    </section>

    <section class="premium-card p-6">
      <div class="text-sm uppercase tracking-wide text-slate-400">Audit Log</div>
      <div class="mt-4 grid gap-3">
        <div v-for="row in auditLogs" :key="row.id" class="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm">
          <div class="flex items-center justify-between gap-3">
            <span class="font-semibold text-slate-900">{{ row.action }}</span>
            <span class="text-xs text-slate-500">{{ formatTime(row.created_at) }}</span>
          </div>
          <div class="mt-1 text-xs text-slate-500">admin {{ row.admin_user_id }} · workspace {{ row.target_workspace_id || 'n/a' }}</div>
          <div v-if="row.reason" class="mt-2 text-xs text-slate-600">Reason: {{ row.reason }}</div>
        </div>
        <div v-if="!auditLogs.length" class="premium-empty">No admin audit events.</div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { isApiErrorStatus } from "../api/http";
import {
  endAdminImpersonation,
  getAdminWorkspaceEntitlements,
  getAdminWorkspaceUsage,
  listAdminAuditLogs,
  getAdminDaemonHealth,
  listAdminWorkspaces,
  materializeAdminWorkspaceUsage,
  listAdminAnomalies,
  materializeAdminAnomalies,
  patchAdminWorkspaceEntitlements,
  startAdminImpersonation,
  type AdminAuditLogRow,
  type AdminWorkspaceSummary,
  type WorkspaceUsageSummary,
  type WorkspaceAnomalySnapshot,
  type AdminDaemonHealth,
} from "../api/lifecycle";

const loading = ref(false);
const actionBusy = ref(false);
const forbidden = ref(false);
const error = ref("");
const workspaceQuery = ref("");
const reason = ref("");
const selectedWorkspaceId = ref<string | null>(null);
const activeSessionId = ref<string | null>(null);
const entitlementPlan = ref("starter");
const entitlementLimitsJson = ref("{}");
const entitlementFeaturesJson = ref("{}");
const workspaces = ref<AdminWorkspaceSummary[]>([]);
const auditLogs = ref<AdminAuditLogRow[]>([]);
const usageTotals = ref<WorkspaceUsageSummary["totals"]>({
  usage_date: "total",
  runs_count: 0,
  deployments_count: 0,
  recoveries_count: 0,
  input_tokens: 0,
  output_tokens: 0,
  total_cost_cents: 0,
});
const usageDaily = ref<WorkspaceUsageSummary["daily"]>([]);
const usageWindowDays = ref<7 | 30>(30);
const usageSyncing = ref(false);
const anomalySyncing = ref(false);
const anomalySnapshots = ref<WorkspaceAnomalySnapshot[]>([]);
const daemonHealth = ref<AdminDaemonHealth>({
  last_cycle_workspaces_processed: 0,
  last_cycle_workspace_failures: 0,
});
const workspaceUsageIndex = ref<
  Record<
    string,
    {
      id: string;
      name: string;
      runs: number;
      recoveries: number;
      tokens: number;
      cost: number;
      burnSpike: boolean;
      failureSpike: boolean;
    }
  >
>({});

const maxRuns = computed(() => Math.max(1, ...usageDaily.value.map((row) => row.runs_count || 0)));
const workspaceLeaderboard = computed(() =>
  Object.values(workspaceUsageIndex.value).sort((a, b) => b.tokens - a.tokens || b.runs - a.runs)
);
const anomalyEvents = computed(() =>
  anomalySnapshots.value.filter((row) => row.burn_spike || row.failure_spike).slice(0, 20)
);

function formatTime(value?: string | null) {
  if (!value) return "unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function selectWorkspace(id: string) {
  selectedWorkspaceId.value = id;
}

async function loadWorkspaces() {
  const rows = await listAdminWorkspaces({ q: workspaceQuery.value || undefined, limit: 60 });
  workspaces.value = Array.isArray(rows) ? rows : [];
}

function computeAnomalyFlags(daily: WorkspaceUsageSummary["daily"]) {
  if (!Array.isArray(daily) || daily.length < 4) {
    return { burnSpike: false, failureSpike: false };
  }
  const slice = daily.slice().sort((a, b) => String(a.usage_date).localeCompare(String(b.usage_date)));
  const midpoint = Math.floor(slice.length / 2);
  const prior = slice.slice(0, midpoint);
  const recent = slice.slice(midpoint);
  const priorTokens = prior.reduce((sum, row) => sum + (row.input_tokens || 0) + (row.output_tokens || 0), 0);
  const recentTokens = recent.reduce((sum, row) => sum + (row.input_tokens || 0) + (row.output_tokens || 0), 0);
  const priorRuns = Math.max(1, prior.reduce((sum, row) => sum + (row.runs_count || 0), 0));
  const recentRuns = Math.max(1, recent.reduce((sum, row) => sum + (row.runs_count || 0), 0));
  const priorRecoveries = prior.reduce((sum, row) => sum + (row.recoveries_count || 0), 0);
  const recentRecoveries = recent.reduce((sum, row) => sum + (row.recoveries_count || 0), 0);
  const priorRecoveryRate = priorRecoveries / priorRuns;
  const recentRecoveryRate = recentRecoveries / recentRuns;
  return {
    burnSpike: recentTokens > priorTokens * 1.5 && recentTokens - priorTokens > 1000,
    failureSpike: recentRecoveryRate > priorRecoveryRate * 1.5 && recentRecoveries >= 2,
  };
}

async function loadWorkspaceLeaderboard() {
  const items = workspaces.value;
  if (!items.length) {
    workspaceUsageIndex.value = {};
    return;
  }
  const usageRows = await Promise.all(
    items.map(async (workspace) => {
      try {
        const usage = await getAdminWorkspaceUsage(workspace.id, usageWindowDays.value);
        const totals = usage?.totals || {
          runs_count: 0,
          recoveries_count: 0,
          input_tokens: 0,
          output_tokens: 0,
          total_cost_cents: 0,
        };
        const flags = computeAnomalyFlags(Array.isArray(usage?.daily) ? usage.daily : []);
        return {
          id: workspace.id,
          name: workspace.name || workspace.id,
          runs: totals.runs_count || 0,
          recoveries: totals.recoveries_count || 0,
          tokens: (totals.input_tokens || 0) + (totals.output_tokens || 0),
          cost: totals.total_cost_cents || 0,
          burnSpike: flags.burnSpike,
          failureSpike: flags.failureSpike,
        };
      } catch {
        return {
          id: workspace.id,
          name: workspace.name || workspace.id,
          runs: 0,
          recoveries: 0,
          tokens: 0,
          cost: 0,
          burnSpike: false,
          failureSpike: false,
        };
      }
    })
  );
  workspaceUsageIndex.value = Object.fromEntries(usageRows.map((row) => [row.id, row]));
}

async function loadAuditLogs() {
  const rows = await listAdminAuditLogs({ workspace_id: selectedWorkspaceId.value || undefined, limit: 50 });
  auditLogs.value = Array.isArray(rows) ? rows : [];
}

async function loadEntitlements() {
  if (!selectedWorkspaceId.value) return;
  const entitlement = await getAdminWorkspaceEntitlements(selectedWorkspaceId.value);
  entitlementPlan.value = entitlement.plan || "starter";
  entitlementLimitsJson.value = JSON.stringify(entitlement.limits || {}, null, 2);
  entitlementFeaturesJson.value = JSON.stringify(entitlement.features || {}, null, 2);
}

async function loadUsage() {
  if (!selectedWorkspaceId.value) return;
  const usage = await getAdminWorkspaceUsage(selectedWorkspaceId.value, usageWindowDays.value);
  usageTotals.value = usage.totals || usageTotals.value;
  usageDaily.value = Array.isArray(usage.daily) ? usage.daily : [];
}

async function materializeUsage() {
  if (!selectedWorkspaceId.value) return;
  usageSyncing.value = true;
  error.value = "";
  try {
    await materializeAdminWorkspaceUsage(selectedWorkspaceId.value, usageWindowDays.value);
    await Promise.all([loadUsage(), loadAuditLogs()]);
  } catch (err: any) {
    error.value = err?.message || "Failed to materialize usage.";
  } finally {
    usageSyncing.value = false;
  }
}

async function loadAnomalySnapshots() {
  const rows = await listAdminAnomalies({
    days: usageWindowDays.value,
    limit: 100,
    workspace_id: selectedWorkspaceId.value || undefined,
  });
  anomalySnapshots.value = Array.isArray(rows) ? rows : [];
}

async function loadDaemonHealth() {
  daemonHealth.value = await getAdminDaemonHealth();
}

async function materializeAnomalies() {
  anomalySyncing.value = true;
  error.value = "";
  try {
    await materializeAdminAnomalies(usageWindowDays.value);
    await loadAnomalySnapshots();
  } catch (err: any) {
    error.value = err?.message || "Failed to materialize anomalies.";
  } finally {
    anomalySyncing.value = false;
  }
}

async function loadAll() {
  loading.value = true;
  error.value = "";
  forbidden.value = false;
  try {
    await loadWorkspaces();
    await Promise.all([loadWorkspaceLeaderboard(), loadAuditLogs(), loadAnomalySnapshots(), loadDaemonHealth()]);
  } catch (err: any) {
    if (isApiErrorStatus(err, 403)) {
      forbidden.value = true;
      return;
    }
    error.value = err?.message || "Failed to load admin data.";
  } finally {
    loading.value = false;
  }
}

async function saveEntitlements() {
  if (!selectedWorkspaceId.value) return;
  actionBusy.value = true;
  error.value = "";
  try {
    const parsedLimits = JSON.parse(entitlementLimitsJson.value || "{}");
    const parsedFeatures = JSON.parse(entitlementFeaturesJson.value || "{}");
    await patchAdminWorkspaceEntitlements(selectedWorkspaceId.value, {
      plan: entitlementPlan.value,
      limits: parsedLimits,
      features: parsedFeatures,
    });
    await loadAuditLogs();
  } catch (err: any) {
    error.value = err?.message || "Failed to save entitlements.";
  } finally {
    actionBusy.value = false;
  }
}

async function startSession() {
  if (!selectedWorkspaceId.value) return;
  actionBusy.value = true;
  error.value = "";
  try {
    const session = await startAdminImpersonation({
      workspace_id: selectedWorkspaceId.value,
      reason: reason.value?.trim() || null,
      duration_minutes: 60,
    });
    activeSessionId.value = session.id;
    await loadAuditLogs();
  } catch (err: any) {
    error.value = err?.message || "Failed to start impersonation.";
  } finally {
    actionBusy.value = false;
  }
}

async function endSession() {
  if (!activeSessionId.value) return;
  actionBusy.value = true;
  error.value = "";
  try {
    await endAdminImpersonation(activeSessionId.value);
    activeSessionId.value = null;
    await loadAuditLogs();
  } catch (err: any) {
    error.value = err?.message || "Failed to end impersonation.";
  } finally {
    actionBusy.value = false;
  }
}

onMounted(() => {
  void loadAll();
});

watch(selectedWorkspaceId, async (next) => {
  if (!next) return;
  try {
    await Promise.all([loadEntitlements(), loadUsage(), loadAuditLogs()]);
  } catch (err: any) {
    error.value = err?.message || "Failed to load workspace admin state.";
  }
});

watch(usageWindowDays, async () => {
  if (!selectedWorkspaceId.value) return;
  try {
    await Promise.all([loadUsage(), loadWorkspaceLeaderboard(), loadAnomalySnapshots()]);
  } catch (err: any) {
    error.value = err?.message || "Failed to refresh usage window.";
  }
});
</script>
