<template>
  <div v-if="isMinimalLayoutRoute" class="app-main">
    <router-view />
  </div>
  <div v-else class="app-shell">
    <aside class="app-sidebar">
      <div class="brand">
        <div class="brand-mark">
          <span class="brand-mark__orb" />
          <span>Agentic SDLC</span>
        </div>
        <div class="brand-copy">
          Mission Control for governed autonomous engineering execution.
        </div>
      </div>

      <div class="sidebar-group">
        <div class="sidebar-group__label">Navigation</div>
        <router-link
          v-for="item in navItems"
          :key="item.key"
          :to="item.disabled ? route.path : item.path"
          class="sidebar-link"
          :class="{
            'is-active': activePath === item.path,
            'is-disabled': item.disabled,
            'is-attention': item.key === 'approvals' && approvalAttentionRequired,
          }"
        >
          <span class="sidebar-link__icon">
            <AppIcon :name="item.icon" />
          </span>
          <span class="sidebar-link__meta">
            <span class="sidebar-link__label">{{ item.label }}</span>
            <div class="sidebar-link__hint">{{ item.hint }}</div>
          </span>
        </router-link>
      </div>

      <div class="sidebar-footer">
        <div class="sidebar-status-card">
          <div class="sidebar-status-card__label">Active Project</div>
          <div class="sidebar-status-card__value">{{ projectContext.projectName || "No project selected" }}</div>
          <div class="mt-2 flex items-center gap-2 text-xs" style="color: var(--text-soft);">
            <span class="soft-dot" :class="{ 'pulse-dot': projectContext.hasActiveRun }" />
            <span>{{ projectContext.hasActiveRun ? "Automation active" : "Ready to start" }}</span>
          </div>
        </div>

        <div class="sidebar-status-card">
          <div class="sidebar-status-card__label">Run Snapshot</div>
          <div class="mt-2 flex items-center justify-between">
            <span class="text-sm" style="color: var(--text-muted);">{{ projectContext.stage }}</span>
            <span class="status-ring" :style="runIndicatorStyle">{{ projectContext.runStatus }}</span>
          </div>
          <div class="mt-3 text-xs" style="color: var(--text-soft);">
            Latest run {{ projectContext.latestRunId ? projectContext.latestRunId.slice(0, 8) : "—" }}
          </div>
        </div>
      </div>
    </aside>

    <section class="app-content">
      <header class="app-header">
        <div class="topbar-shell">
          <TopBar />
        </div>
        <div class="context-rail">
          <div class="context-rail__item">
            <span class="context-rail__label">Workspace</span>
            <span class="context-rail__value">{{ workspaceLabel }}</span>
          </div>
          <div class="context-rail__sep">→</div>
          <div class="context-rail__item">
            <span class="context-rail__label">Project</span>
            <span class="context-rail__value">{{ projectLabel }}</span>
          </div>
          <div class="context-rail__sep">→</div>
          <div class="context-rail__item">
            <span class="context-rail__label">Environment</span>
            <span class="context-rail__value">{{ environmentLabel }}</span>
          </div>
          <div class="context-rail__sep">→</div>
          <div class="context-rail__item">
            <span class="context-rail__label">Active Run</span>
            <span class="context-rail__value">{{ activeRunLabel }}</span>
          </div>
        </div>
      </header>
      <main class="app-main">
        <router-view />
      </main>
    </section>

    <AiOperatorPanel />

    <el-dialog
      v-model="operatorApprovalDialogVisible"
      width="min(560px, 92vw)"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <template #header>
        <div class="text-base font-semibold" style="color: var(--text-strong);">{{ operatorDialogTitle }}</div>
      </template>
      <div class="text-sm leading-6" style="color: var(--text-muted);">
        {{ operatorDialogMessage }}
      </div>
      <template #footer>
        <div class="flex items-center justify-end gap-2">
          <el-button @click="operatorApprovalDialogVisible = false">Later</el-button>
          <el-button
            v-if="operatorDialogKind === 'operator_confirmation'"
            type="success"
            :loading="operatorConfirmLoading"
            :disabled="!operatorApprovalRunId"
            @click="confirmAndContinueFromDialog"
          >
            Confirm & Continue
          </el-button>
          <el-button @click="openExactRunFromDialog">Go to Exact Run</el-button>
          <el-button type="primary" @click="openOperatorActionFromDialog">{{ operatorDialogPrimaryLabel }}</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="runIssueDialogVisible"
      width="min(560px, 92vw)"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <template #header>
        <div class="text-base font-semibold" style="color: var(--text-strong);">Run Needs Attention</div>
      </template>
      <div class="text-sm leading-6" style="color: var(--text-muted);">
        Run {{ runIssueRunIdShort }} did not pause for approval. It completed in a degraded/stalled state.
        Open run details to see the exact failure and retry guidance.
      </div>
      <template #footer>
        <div class="flex items-center justify-end gap-2">
          <el-button @click="runIssueDialogVisible = false">Later</el-button>
          <el-button type="primary" @click="openRunIssueFromDialog">Go to Run Details</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { isApiErrorStatus } from "./api/http";
import { confirmAndContinueRun, getActiveTenantId, getActiveWorkspaceId, getActiveWorkspaceMeta, listApprovals, listRuns, listRunEvents, listWorkItems, resumeRun, unblockRun } from "./api/lifecycle";
import AiOperatorPanel from "./components/AiOperatorPanel.vue";
import AppIcon from "./components/AppIcon.vue";
import TopBar from "./components/TopBar.vue";
import { projectContext } from "./state/projectContext";

const route = useRoute();
const router = useRouter();
const isMinimalLayoutRoute = computed(() => {
  return String(route.meta?.layout || "") === "minimal";
});
const activePath = computed(() => route.path);
const activeWorkspaceId = ref<string | null>(getActiveWorkspaceId());
const activeWorkspaceName = ref<string | null>(getActiveWorkspaceMeta()?.name || null);

const projectPath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}` : "/"));
const operatorPath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/operator` : "/"));
const requirementsPath = computed(() =>
  projectContext.projectId ? `/projects/${projectContext.projectId}/requirements` : "/"
);
const missionControlPath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/run` : "/"));
const automationMapPath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/map` : "/"));
const timelinePath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/timeline` : "/"));
const approvalsPath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/approvals` : "/"));
const runsPath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/runs` : "/"));
const aiOpsPath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/ai-ops` : "/"));
const knowledgePath = computed(() => (projectContext.projectId ? `/projects/${projectContext.projectId}/knowledge` : "/"));

const operatorApprovalDialogVisible = ref(false);
const operatorApprovalRunId = ref("");
const operatorDialogKind = ref<"operator_confirmation" | "approval_queue">("operator_confirmation");
const operatorConfirmLoading = ref(false);
const runIssueDialogVisible = ref(false);
const runIssueRunId = ref("");
const approvalAttentionRequired = ref(false);
let approvalMonitorTimer: number | null = null;
let lastAlertSignature = "";

function resetOperatorAttentionState() {
  operatorApprovalDialogVisible.value = false;
  operatorApprovalRunId.value = "";
  operatorDialogKind.value = "operator_confirmation";
  runIssueDialogVisible.value = false;
  runIssueRunId.value = "";
  approvalAttentionRequired.value = false;
}

const operatorApprovalRunIdShort = computed(() =>
  operatorApprovalRunId.value ? operatorApprovalRunId.value.slice(0, 8) : "—"
);
const operatorDialogTitle = computed(() =>
  operatorDialogKind.value === "approval_queue" ? "Approval Required" : "Operator Confirmation Required"
);
const operatorDialogPrimaryLabel = computed(() =>
  operatorDialogKind.value === "approval_queue" ? "Open Approvals" : "Go to Exact Run"
);
const operatorDialogMessage = computed(() => {
  if (operatorDialogKind.value === "approval_queue") {
    return `Run ${operatorApprovalRunIdShort.value} is waiting on approval queue decisions. Open Approvals to confirm and continue.`;
  }
  return `Run ${operatorApprovalRunIdShort.value} is paused for operator confirmation before patch mutation. Open the exact run to confirm and continue.`;
});
const runIssueRunIdShort = computed(() => (runIssueRunId.value ? runIssueRunId.value.slice(0, 8) : "—"));
const workspaceLabel = computed(() => {
  const name = activeWorkspaceName.value;
  if (name && name.trim()) return name;
  const id = activeWorkspaceId.value;
  if (!id) return "No workspace selected";
  return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
});
const projectLabel = computed(() => projectContext.projectName || "No project selected");
const environmentLabel = computed(() => (import.meta.env.DEV ? "Local" : "Production"));
const activeRunLabel = computed(() => {
  if (!projectContext.latestRunId) return "No active run";
  const shortId = projectContext.latestRunId.slice(0, 8);
  return `${shortId} (${projectContext.runStatus || "UNKNOWN"})`;
});
const refreshWorkspace = () => {
  activeWorkspaceId.value = getActiveWorkspaceId();
  activeWorkspaceName.value = getActiveWorkspaceMeta()?.name || null;
};

const navItems = computed(() => [
  {
    key: "workspace",
    label: "Workspace",
    hint: "Projects, system state, quick launch",
    icon: "workspace",
    path: "/workspace",
    disabled: false,
  },
  {
    key: "workspace-dashboard",
    label: "Workspace Dashboard",
    hint: "Cross-project operational control center",
    icon: "status",
    path: "/workspace/dashboard",
    disabled: !getActiveTenantId(),
  },
  {
    key: "admin-console",
    label: "Admin Console",
    hint: "Workspace operations and audit controls",
    icon: "status",
    path: "/admin",
    disabled: !getActiveTenantId(),
  },
  {
    key: "operator",
    label: "Operator Dashboard",
    hint: "Tasks, runs, narrative, repo map",
    icon: "operator",
    path: operatorPath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "project",
    label: "Project Overview",
    hint: "Lifecycle health and operator actions",
    icon: "project",
    path: projectPath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "requirements",
    label: "Requirements",
    hint: "PRDs, graph health, approvals",
    icon: "requirements",
    path: requirementsPath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "mission",
    label: "Mission Control",
    hint: "Live runtime, impact, replay, PRs",
    icon: "mission",
    path: missionControlPath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "map",
    label: "Automation Map",
    hint: "System graph for intake, runs, artifacts, delivery",
    icon: "map",
    path: automationMapPath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "timeline",
    label: "SDLC Timeline",
    hint: "Deterministic run replay",
    icon: "timeline",
    path: timelinePath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "approvals",
    label: "Approvals",
    hint: "Review gates and governance",
    icon: "approvals",
    path: approvalsPath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "ai-ops",
    label: "AI Ops",
    hint: "Spend, retries, context and approval burn patterns",
    icon: "operator",
    path: aiOpsPath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "knowledge",
    label: "Knowledge",
    hint: "Engineering memory and documentation verification",
    icon: "knowledge",
    path: knowledgePath.value,
    disabled: !projectContext.projectId,
  },
  {
    key: "runs",
    label: "Agent Runs",
    hint: "Execution history and operators",
    icon: "runs",
    path: runsPath.value,
    disabled: !projectContext.projectId,
  },
]);

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

function playApprovalChime() {
  try {
    const Ctx = (window as any).AudioContext || (window as any).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.08, ctx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.22);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.24);
    osc.onended = () => {
      void ctx.close();
    };
  } catch {
    // Best effort only when browser audio policy allows it.
  }
}

async function checkOperatorApprovalState() {
  if (!getActiveTenantId()) {
    resetOperatorAttentionState();
    return;
  }
  const projectId = projectContext.projectId;
  if (!projectId) {
    resetOperatorAttentionState();
    return;
  }
  try {
    const [approvals, runs] = await Promise.all([listApprovals(projectId), listRuns(projectId)]);
    const pendingApprovals = Array.isArray(approvals)
      ? approvals.filter((item: any) => String(item?.status || "").toUpperCase() === "PENDING")
      : [];
    const latestRun = Array.isArray(runs) && runs.length ? runs[0] : null;
    const latestRunNeedsOperatorConfirmation = (() => {
      const status = String(latestRun?.status || "").toUpperCase();
      const reason = String(latestRun?.summary?.operator_confirmation_pause?.reason || "").toLowerCase();
      const failedError = String(latestRun?.summary?.resume_state?.failed_error || "").toLowerCase();
      const hasOperatorMarker =
        reason === "operator_confirmation_required" || failedError.includes("operator confirmation");
      return (
        (status === "PAUSED" && hasOperatorMarker) ||
        // Fallback: surface operator action even if backend pause transition lags.
        (hasOperatorMarker && ["RUNNING", "QUEUED", "COMPLETED", "CANCELED"].includes(status))
      );
    })();
    let fallbackEventOperatorConfirmation = false;
    if (!latestRunNeedsOperatorConfirmation && latestRun?.id) {
      try {
        const events = await listRunEvents(String(latestRun.id));
        const rows = Array.isArray(events) ? events : [];
        fallbackEventOperatorConfirmation = rows.some((evt: any) => {
          const eventType = String(evt?.event_type || "").toUpperCase();
          if (eventType !== "WORK_ITEM_FAILED") return false;
          const payload = evt?.payload || {};
          const error = String(payload?.error || "").toLowerCase();
          const message = String(payload?.message || evt?.message || "").toLowerCase();
          return (
            error.includes("operator_confirmation_required") ||
            message.includes("operator confirmation") ||
            message.includes("requires operator confirmation")
          );
        });
      } catch {
        // Keep monitor resilient during transient event API failures.
      }
    }
    let fallbackWorkItemOperatorConfirmation = false;
    if (!latestRunNeedsOperatorConfirmation && !fallbackEventOperatorConfirmation && latestRun?.id) {
      try {
        const items = await listWorkItems(projectId, String(latestRun.id));
        const rows = Array.isArray(items) ? items : [];
        fallbackWorkItemOperatorConfirmation = rows.some((item: any) => {
          const status = String(item?.status || "").toUpperCase();
          if (status !== "FAILED") return false;
          const result = item?.result || {};
          const approvalRequired = result?.approval_required === true;
          const stopReason = String(result?.stop_reason || "").toLowerCase();
          const error = String(result?.error || "").toLowerCase();
          const message = String(result?.message || item?.last_error || "").toLowerCase();
          const hasOperatorMarker =
            error.includes("operator_confirmation_required") ||
            message.includes("operator confirmation") ||
            message.includes("requires operator confirmation");
          return approvalRequired && stopReason === "human_review_required" && hasOperatorMarker;
        });
      } catch {
        // Keep monitor resilient during transient work-item API failures.
      }
    }
    const pausedOperatorRun =
      (latestRunNeedsOperatorConfirmation || fallbackEventOperatorConfirmation || fallbackWorkItemOperatorConfirmation)
        ? latestRun
        : null;

    const latestStatus = String(latestRun?.status || "").toUpperCase();
    const latestGoalState = String(latestRun?.summary?.goal_state || "").toUpperCase();
    const latestDegradedReason = String(latestRun?.summary?.degraded_reason || "").toLowerCase();
    const isStalledOrDegraded =
      latestStatus === "COMPLETED" &&
      (latestGoalState === "CONCLUDED_UNRESOLVABLE" ||
        latestDegradedReason.includes("stalled") ||
        latestDegradedReason.includes("no_progress"));

    const hasOperatorAction = Boolean(pausedOperatorRun || pendingApprovals.length);
    approvalAttentionRequired.value = hasOperatorAction;
    // Approval dialog should only open for an actual paused run that needs operator confirmation.
    if (!pausedOperatorRun) {
      operatorApprovalRunId.value = "";
      if (!pendingApprovals.length) {
        operatorDialogKind.value = "operator_confirmation";
      }
    } else {
      const runId = String(pausedOperatorRun.id || "");
      operatorApprovalRunId.value = runId;
      operatorDialogKind.value = pendingApprovals.length ? "approval_queue" : "operator_confirmation";
      const signature = `${projectId}:approval:${runId}:${operatorDialogKind.value}:${pendingApprovals.length}`;
      if (signature !== lastAlertSignature) {
        operatorApprovalDialogVisible.value = true;
        playApprovalChime();
        lastAlertSignature = signature;
      }
    }

    if (!hasOperatorAction && isStalledOrDegraded && latestRun?.id) {
      const runId = String(latestRun.id);
      runIssueRunId.value = runId;
      const signature = `${projectId}:issue:${runId}:${latestGoalState}:${latestDegradedReason}`;
      if (signature !== lastAlertSignature) {
        runIssueDialogVisible.value = true;
        lastAlertSignature = signature;
      }
    } else if (!isStalledOrDegraded) {
      runIssueRunId.value = "";
    }
  } catch (error) {
    if (isApiErrorStatus(error, 401) || isApiErrorStatus(error, 403)) {
      resetOperatorAttentionState();
      return;
    }
    // Keep UX stable during transient API errors.
  }
}

function stopApprovalMonitor() {
  if (approvalMonitorTimer !== null) {
    window.clearInterval(approvalMonitorTimer);
    approvalMonitorTimer = null;
  }
}

function startApprovalMonitor() {
  stopApprovalMonitor();
  void checkOperatorApprovalState();
  approvalMonitorTimer = window.setInterval(() => {
    void checkOperatorApprovalState();
  }, 7000);
}

function openApprovalsFromDialog() {
  operatorApprovalDialogVisible.value = false;
  if (!projectContext.projectId) return;
  router.push(`/projects/${projectContext.projectId}/approvals`);
}

function openOperatorActionFromDialog() {
  if (operatorDialogKind.value === "approval_queue") {
    openApprovalsFromDialog();
    return;
  }
  openExactRunFromDialog();
}

function openExactRunFromDialog() {
  operatorApprovalDialogVisible.value = false;
  if (!projectContext.projectId || !operatorApprovalRunId.value) return;
  router.push(`/projects/${projectContext.projectId}/runs/${operatorApprovalRunId.value}/debug`);
}

async function confirmAndContinueFromDialog() {
  if (!operatorApprovalRunId.value) return;
  operatorConfirmLoading.value = true;
  try {
    await confirmAndContinueRun(operatorApprovalRunId.value);
    operatorApprovalDialogVisible.value = false;
    await checkOperatorApprovalState();
  } catch {
    try {
      await unblockRun(operatorApprovalRunId.value);
      operatorApprovalDialogVisible.value = false;
      await checkOperatorApprovalState();
    } catch {
      try {
      await resumeRun(operatorApprovalRunId.value, { start_now: true });
      operatorApprovalDialogVisible.value = false;
      await checkOperatorApprovalState();
      } catch {
        // Keep dialog open if all confirmation continuation paths fail.
      }
    }
  } finally {
    operatorConfirmLoading.value = false;
  }
}

function openRunIssueFromDialog() {
  runIssueDialogVisible.value = false;
  if (!projectContext.projectId || !runIssueRunId.value) return;
  router.push(`/projects/${projectContext.projectId}/runs/${runIssueRunId.value}/debug`);
}

watch(
  () => projectContext.projectId,
  () => {
    lastAlertSignature = "";
    startApprovalMonitor();
  }
);

onMounted(() => {
  window.addEventListener("agentic:tenant-changed", resetOperatorAttentionState as EventListener);
  window.addEventListener("agentic:workspace-changed", refreshWorkspace as EventListener);
  startApprovalMonitor();
});

onBeforeUnmount(() => {
  stopApprovalMonitor();
  window.removeEventListener("agentic:tenant-changed", resetOperatorAttentionState as EventListener);
  window.removeEventListener("agentic:workspace-changed", refreshWorkspace as EventListener);
});
</script>

<style scoped>
.context-rail {
  margin: 0 0.75rem 0.5rem;
  padding: 0.6rem 0.8rem;
  border: 1px solid var(--border-soft);
  border-radius: 14px;
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--surface-2) 92%, transparent),
    color-mix(in srgb, var(--surface-soft) 88%, transparent)
  );
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.context-rail__item {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.context-rail__label {
  font-size: 0.68rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-soft);
}

.context-rail__value {
  font-size: 0.82rem;
  color: var(--text-strong);
}

.context-rail__sep {
  font-size: 0.76rem;
  color: var(--text-soft);
}
</style>
