<template>
  <div class="space-y-6">
    <section class="premium-hero">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="max-w-3xl space-y-3">
          <div class="topbar-chip">
            <AppIcon name="approvals" size="sm" />
            Governance Layer
          </div>
          <div>
            <h1 class="text-3xl font-semibold" style="color: var(--text-strong);">Approvals</h1>
            <p class="mt-2 text-sm leading-6" style="color: var(--text-muted);">
              Review pending decisions, inspect approval history, and keep patch-to-PR flow governed instead of implicit.
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
      <MetricCard
        label="Approval Queue"
        :value="String(pendingCount)"
        helper="Awaiting operator action"
        tone="warning"
      />
      <MetricCard
        label="Approved"
        :value="String(approvedCount)"
        helper="Changes cleared to continue"
        tone="success"
      />
      <MetricCard
        label="Rejected"
        :value="String(rejectedCount)"
        helper="Changes intentionally blocked"
        tone="danger"
      />
      <MetricCard
        label="Coverage"
        :value="projectName || 'No project'"
        helper="Active governance scope"
        tone="neutral"
      />
    </section>

    <section class="grid gap-4 xl:grid-cols-[1.35fr,0.95fr]">
      <div class="premium-card">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Approval Queue</div>
            <div class="mt-1 text-sm" style="color: var(--text-muted);">
              Filter by decision state or target type. The newest entries appear first.
            </div>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <el-select v-model="statusFilter" size="small" style="width: 160px">
              <el-option label="All statuses" value="ALL" />
              <el-option label="Pending" value="PENDING" />
              <el-option label="Approved" value="APPROVED" />
              <el-option label="Rejected" value="REJECTED" />
            </el-select>
            <el-select v-model="typeFilter" size="small" style="width: 160px">
              <el-option label="All targets" value="ALL" />
              <el-option label="Artifact" value="artifact" />
              <el-option label="Task" value="task" />
              <el-option label="Document" value="document" />
            </el-select>
          </div>
        </div>

        <div v-if="error" class="mt-4 rounded-2xl border px-4 py-3 text-sm" style="border-color: rgba(239, 68, 68, 0.2); background: rgba(239, 68, 68, 0.08); color: var(--danger);">
          {{ error }}
        </div>

        <div v-if="filteredApprovals.length" class="mt-4 grid gap-3">
          <article
            v-for="approval in filteredApprovals"
            :key="approval.id"
            class="rounded-2xl border p-4 transition-transform duration-200 hover:-translate-y-[1px]"
            style="border-color: var(--border-soft); background: var(--surface-soft);"
          >
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <div class="topbar-chip">{{ approval.target_type }}</div>
                  <div class="status-ring" :style="approvalStatusStyle(approval.status)">
                    <span class="soft-dot" />
                    {{ approval.status }}
                  </div>
                </div>
                <div class="mt-3 text-sm font-medium break-all" style="color: var(--text-strong);">
                  {{ approval.target_id }}
                </div>
                <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs" style="color: var(--text-muted);">
                  <span>Created {{ formatTimestamp(approval.created_at) }}</span>
                  <span>Updated {{ formatTimestamp(approval.updated_at) }}</span>
                  <span>Decided by {{ approval.decided_by || "—" }}</span>
                </div>
                <div v-if="approval.comment" class="mt-3 rounded-xl px-3 py-2 text-sm" style="background: var(--surface); color: var(--text-muted);">
                  {{ approval.comment }}
                </div>
              </div>
              <div class="flex flex-col items-end gap-2">
                <div class="text-[11px] uppercase tracking-[0.22em]" style="color: var(--text-soft);">
                  {{ approvalLabel(approval) }}
                </div>
                <div v-if="approval.status === 'PENDING'" class="flex flex-wrap items-center gap-2">
                  <el-button
                    size="small"
                    type="success"
                    plain
                    :loading="decisionLoadingId === approval.id && decisionLoadingAction === 'APPROVED'"
                    @click="decideAndContinue(approval, 'APPROVED')"
                  >
                    Approve & Continue
                  </el-button>
                  <el-button
                    size="small"
                    type="danger"
                    plain
                    :loading="decisionLoadingId === approval.id && decisionLoadingAction === 'REJECTED'"
                    @click="decideAndContinue(approval, 'REJECTED')"
                  >
                    Reject
                  </el-button>
                </div>
                <button
                  v-if="approval.target_type === 'artifact' && approval.target_id"
                  type="button"
                  class="utility-button"
                  @click="goToMissionControl"
                >
                  Review In Mission Control
                </button>
              </div>
            </div>
          </article>
        </div>

        <div v-else class="mt-4 premium-empty">
          <div v-if="approvals.length" class="space-y-2">
            <div>No approvals match the current filter.</div>
            <div class="text-xs" style="color: var(--text-soft);">
              Try <strong>All statuses</strong> and <strong>All targets</strong>.
            </div>
          </div>
          <div v-else class="space-y-3">
            <div class="font-medium" style="color: var(--text-strong);">No approval records yet for this project.</div>
            <div class="text-xs" style="color: var(--text-soft);">
              This page shows explicit governance decisions (artifact/task/document approvals) once a run or review creates them.
            </div>
            <div class="flex flex-wrap items-center justify-center gap-2">
              <el-button size="small" @click="goToRequirements">Open Requirements</el-button>
              <el-button size="small" plain @click="goToMissionControl">Open Mission Control</el-button>
            </div>
          </div>
        </div>
      </div>

      <div class="space-y-4">
        <div class="premium-card">
          <div class="flex items-center gap-2">
            <AppIcon name="status" />
            <div>
              <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Policy Snapshot</div>
              <div class="mt-1 text-sm" style="color: var(--text-muted);">
                Current governance posture for the active project.
              </div>
            </div>
          </div>
          <div class="mt-4 space-y-3 text-sm">
            <div class="rounded-2xl border p-3" style="border-color: var(--border-soft); background: var(--surface-soft);">
              <div class="text-xs uppercase tracking-[0.2em]" style="color: var(--text-soft);">Current Stage</div>
              <div class="mt-2 font-medium" style="color: var(--text-strong);">{{ projectStage || "—" }}</div>
            </div>
            <div class="rounded-2xl border p-3" style="border-color: var(--border-soft); background: var(--surface-soft);">
              <div class="text-xs uppercase tracking-[0.2em]" style="color: var(--text-soft);">Pending Actions</div>
              <div class="mt-2 font-medium" style="color: var(--text-strong);">{{ pendingCount }}</div>
              <div class="mt-1 text-xs" style="color: var(--text-muted);">
                Patch-to-PR remains blocked until pending approvals are resolved.
              </div>
            </div>
          </div>
        </div>

        <div class="premium-card">
          <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Recent Decisions</div>
          <div v-if="recentDecisions.length" class="mt-4 space-y-3">
            <div
              v-for="approval in recentDecisions"
              :key="approval.id"
              class="rounded-2xl border p-3"
              style="border-color: var(--border-soft); background: var(--surface-soft);"
            >
              <div class="flex items-center justify-between gap-3">
                <div class="text-sm font-medium" style="color: var(--text-strong);">{{ approval.target_type }}</div>
                <div class="status-ring" :style="approvalStatusStyle(approval.status)">
                  <span class="soft-dot" />
                  {{ approval.status }}
                </div>
              </div>
              <div class="mt-2 text-xs break-all" style="color: var(--text-muted);">
                {{ approval.target_id }}
              </div>
              <div class="mt-2 text-[11px]" style="color: var(--text-soft);">
                {{ approval.decided_by || "system" }} · {{ formatTimestamp(approval.updated_at) }}
              </div>
            </div>
          </div>
          <div v-else class="mt-4 premium-empty">
            No approval decisions recorded yet.
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";

import AppIcon from "../components/AppIcon.vue";
import MetricCard from "../components/MetricCard.vue";
import { createApproval, fetchProjectMeta, listApprovals, listRuns, resumeRun } from "../api/lifecycle";
import { updateProjectContext } from "../state/projectContext";

type ApprovalRecord = {
  id: string;
  target_type: string;
  target_id: string;
  status: string;
  decided_by?: string | null;
  decided_at?: string | null;
  comment?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const error = ref("");
const projectName = ref("");
const projectStage = ref("");
const approvals = ref<ApprovalRecord[]>([]);
const statusFilter = ref("ALL");
const typeFilter = ref("ALL");
const decisionLoadingId = ref("");
const decisionLoadingAction = ref<"APPROVED" | "REJECTED" | "">("");

const projectId = computed(() => String(route.params.projectId || ""));

const filteredApprovals = computed(() =>
  approvals.value.filter((approval) => {
    const statusOk = statusFilter.value === "ALL" || approval.status === statusFilter.value;
    const typeOk = typeFilter.value === "ALL" || approval.target_type === typeFilter.value;
    return statusOk && typeOk;
  })
);

const pendingCount = computed(() => approvals.value.filter((item) => item.status === "PENDING").length);
const approvedCount = computed(() => approvals.value.filter((item) => item.status === "APPROVED").length);
const rejectedCount = computed(() => approvals.value.filter((item) => item.status === "REJECTED").length);
const recentDecisions = computed(() =>
  approvals.value.filter((item) => item.status !== "PENDING").slice(0, 4)
);

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
    const [project, approvalRows] = await Promise.all([
      fetchProjectMeta(projectId.value),
      listApprovals(projectId.value),
    ]);
    projectName.value = project?.name || "Project";
    projectStage.value = project?.status || project?.stage || "UNKNOWN";
    approvals.value = Array.isArray(approvalRows)
      ? [...approvalRows].sort((a, b) => sortDescending(a.updated_at || a.created_at, b.updated_at || b.created_at))
      : [];
    updateProjectContext({
      projectId: projectId.value,
      projectName: projectName.value,
      stage: projectStage.value,
      updatedAt: new Date().toISOString(),
    });
  } catch (err: any) {
    error.value = err?.message || "Failed to load approvals.";
  } finally {
    loading.value = false;
  }
}

async function decideAndContinue(approval: ApprovalRecord, decision: "APPROVED" | "REJECTED") {
  if (!projectId.value) return;
  decisionLoadingId.value = approval.id;
  decisionLoadingAction.value = decision;
  error.value = "";
  try {
    await createApproval(projectId.value, {
      target_type: approval.target_type,
      target_id: approval.target_id,
      status: decision,
      decided_by: "ui-user",
      comment:
        decision === "APPROVED"
          ? "Approved by operator from Approvals surface."
          : "Rejected by operator from Approvals surface.",
    });

    if (decision === "APPROVED") {
      await attemptAutoResume();
      ElMessage.success("Approval recorded. Runtime continuation attempted.");
    } else {
      ElMessage.warning("Rejection recorded.");
    }
    await loadPage();
  } catch (err: any) {
    error.value = err?.message || `Failed to ${decision.toLowerCase()} approval.`;
  } finally {
    decisionLoadingId.value = "";
    decisionLoadingAction.value = "";
  }
}

async function attemptAutoResume() {
  if (!projectId.value) return;
  const runs = await listRuns(projectId.value);
  const ordered = Array.isArray(runs)
    ? [...runs].sort((a, b) => {
        const aTs = Date.parse(String(a?.updated_at || a?.started_at || a?.created_at || "")) || 0;
        const bTs = Date.parse(String(b?.updated_at || b?.started_at || b?.created_at || "")) || 0;
        return bTs - aTs;
      })
    : [];
  const resumablePaused = ordered.find((run: any) => {
    const status = String(run?.status || "").toUpperCase();
    const canResume = Boolean(run?.summary?.resume_state?.can_resume);
    return status === "PAUSED" && canResume;
  });
  if (!resumablePaused?.id) return;
  await resumeRun(String(resumablePaused.id), { start_now: true });
}

function goToMissionControl() {
  if (!projectId.value) return;
  router.push(`/projects/${projectId.value}/run`);
}

function goToRequirements() {
  if (!projectId.value) return;
  router.push(`/projects/${projectId.value}/requirements`);
}

function approvalStatusStyle(status?: string | null) {
  switch ((status || "").toUpperCase()) {
    case "APPROVED":
      return { background: "rgba(34, 197, 94, 0.12)", color: "var(--success)" };
    case "REJECTED":
      return { background: "rgba(239, 68, 68, 0.12)", color: "var(--danger)" };
    default:
      return { background: "rgba(245, 158, 11, 0.12)", color: "var(--warning)" };
  }
}

function approvalLabel(approval: ApprovalRecord) {
  if (approval.status === "PENDING") return "Awaiting operator decision";
  if (approval.status === "APPROVED") return "Cleared for next action";
  return "Blocked until revised";
}

function formatTimestamp(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString();
}

function sortDescending(a?: string | null, b?: string | null) {
  const first = a ? new Date(a).getTime() : 0;
  const second = b ? new Date(b).getTime() : 0;
  return second - first;
}
</script>
