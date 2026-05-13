<template>
  <div class="app-shell">
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
        <div class="text-base font-semibold" style="color: var(--text-strong);">Approval Required</div>
      </template>
      <div class="text-sm leading-6" style="color: var(--text-muted);">
        Run {{ operatorApprovalRunIdShort }} is waiting for operator confirmation before patch mutation.
        Open Approvals to confirm and continue.
      </div>
      <template #footer>
        <div class="flex items-center justify-end gap-2">
          <el-button @click="operatorApprovalDialogVisible = false">Later</el-button>
          <el-button @click="openExactRunFromDialog">Go to Exact Run</el-button>
          <el-button type="primary" @click="openApprovalsFromDialog">Open Approvals</el-button>
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

import { listApprovals, listRuns } from "./api/lifecycle";
import AiOperatorPanel from "./components/AiOperatorPanel.vue";
import AppIcon from "./components/AppIcon.vue";
import TopBar from "./components/TopBar.vue";
import { projectContext } from "./state/projectContext";

const route = useRoute();
const router = useRouter();
const activePath = computed(() => route.path);

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
const runIssueDialogVisible = ref(false);
const runIssueRunId = ref("");
const approvalAttentionRequired = ref(false);
let approvalMonitorTimer: number | null = null;
let lastAlertSignature = "";

const operatorApprovalRunIdShort = computed(() =>
  operatorApprovalRunId.value ? operatorApprovalRunId.value.slice(0, 8) : "—"
);
const runIssueRunIdShort = computed(() => (runIssueRunId.value ? runIssueRunId.value.slice(0, 8) : "—"));

const navItems = computed(() => [
  {
    key: "workspace",
    label: "Workspace",
    hint: "Projects, system state, quick launch",
    icon: "workspace",
    path: "/",
    disabled: false,
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
  const projectId = projectContext.projectId;
  if (!projectId) {
    approvalAttentionRequired.value = false;
    runIssueRunId.value = "";
    return;
  }
  try {
    const [approvals, runs] = await Promise.all([listApprovals(projectId), listRuns(projectId)]);
    const pendingApprovals = Array.isArray(approvals)
      ? approvals.filter((item: any) => String(item?.status || "").toUpperCase() === "PENDING")
      : [];
    const pausedOperatorRun = Array.isArray(runs)
      ? runs.find((run: any) => {
          const status = String(run?.status || "").toUpperCase();
          const reason = String(run?.summary?.operator_confirmation_pause?.reason || "").toLowerCase();
          const failedError = String(run?.summary?.resume_state?.failed_error || "").toLowerCase();
          return (
            status === "PAUSED" &&
            (reason === "operator_confirmation_required" || failedError.includes("operator confirmation"))
          );
        })
      : null;

    const latestRun = Array.isArray(runs) && runs.length ? runs[0] : null;
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
    } else {
      const runId = String(pausedOperatorRun.id || "");
      operatorApprovalRunId.value = runId;
      const signature = `${projectId}:approval:${runId}:${pendingApprovals.length}`;
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
  } catch {
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

function openExactRunFromDialog() {
  operatorApprovalDialogVisible.value = false;
  if (!projectContext.projectId || !operatorApprovalRunId.value) return;
  router.push(`/projects/${projectContext.projectId}/runs/${operatorApprovalRunId.value}/debug`);
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
  startApprovalMonitor();
});

onBeforeUnmount(() => {
  stopApprovalMonitor();
});
</script>
