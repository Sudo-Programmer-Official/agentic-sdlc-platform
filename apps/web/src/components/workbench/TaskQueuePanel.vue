<template>
  <section class="workbench-panel">
    <div class="workbench-panel__header">
      <div>
        <div class="workbench-panel__eyebrow">Live Task Queue</div>
        <h2 class="workbench-panel__title">Execution is visible, steerable, and reviewable.</h2>
        <p class="workbench-panel__copy">
          Track every queued, running, completed, and blocked task for the active run. Logs and artifact traces stay attached to each step.
        </p>
      </div>
      <div class="workbench-panel__summary">
        <div class="workbench-panel__summary-value">{{ completedCount }}/{{ tasks.length }}</div>
        <div class="workbench-panel__summary-label">tasks complete</div>
      </div>
    </div>

    <div class="workbench-panel__stats">
      <span class="workbench-chip">Queued {{ queuedCount }}</span>
      <span class="workbench-chip is-running">Running {{ runningCount }}</span>
      <span class="workbench-chip is-success">Completed {{ completedCount }}</span>
      <span class="workbench-chip is-danger">Blocked {{ blockedCount }}</span>
      <span class="workbench-chip is-warning">Warnings {{ warningCount }}</span>
    </div>

    <div v-if="tasks.length" class="task-queue">
      <article v-for="task in tasks" :key="task.id" class="task-card" :class="taskCardClass(task)">
        <div class="task-card__top">
          <div class="task-card__status">
            <span class="soft-dot" :class="taskDotClass(task.rawStatus, task.blocking)" />
            <span>{{ task.rawStatus }}</span>
            <span v-if="task.blocking === false" class="task-card__status-note">Optional</span>
          </div>
          <div class="task-card__progress-wrap">
            <span class="task-card__eta">{{ etaLabel(task) }}</span>
            <span class="task-card__progress">{{ task.progress }}%</span>
          </div>
        </div>
        <div class="task-card__title">{{ task.title }}</div>
        <div class="task-card__meta">{{ task.agent }} · {{ task.executor }}</div>
        <div v-if="task.selectedStrategy || task.effectiveStrategy || task.executionZone || task.driftRiskScore !== null" class="task-card__strategy">
          <span v-if="task.selectedStrategy" class="task-card__strategy-chip">Selected {{ task.selectedStrategy }}</span>
          <span v-if="task.effectiveStrategy && task.effectiveStrategy !== task.selectedStrategy" class="task-card__strategy-chip is-transition">
            Effective {{ task.effectiveStrategy }}
          </span>
          <span v-if="task.executionZone" class="task-card__strategy-chip">{{ task.executionZone }}</span>
          <span
            v-if="task.driftRiskScore !== null"
            class="task-card__strategy-chip"
            :class="driftChipClass(task.driftRiskScore)"
          >
            Drift {{ Math.round((task.driftRiskScore || 0) * 100) }}%
          </span>
          <span
            v-if="task.transitionReason"
            class="task-card__strategy-chip is-transition"
            :title="transitionReasonLabel(task.transitionReason)"
          >
            {{ transitionReasonLabel(task.transitionReason) }}
          </span>
        </div>
        <div class="task-card__bar">
          <span class="task-card__bar-fill" :style="{ width: `${task.progress}%` }" />
        </div>
        <div class="task-card__log">{{ task.logLine }}</div>
        <div v-if="task.changedArtifacts.length" class="task-card__files">
          <span class="task-card__files-label">Artifacts</span>
          <span
            v-for="item in task.changedArtifacts"
            :key="`${task.id}-${item}`"
            class="task-card__file-chip"
          >
            {{ item }}
          </span>
        </div>
        <div class="task-card__foot">
          <span>{{ task.startedAtLabel }}</span>
          <span>{{ task.finishedAtLabel }}</span>
        </div>
      </article>
    </div>
    <div v-else class="workbench-panel__empty">
      No active work items yet. Launch a run to start the operator task queue.
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";

type QueueTask = {
  id: string;
  title: string;
  rawStatus: string;
  blocking?: boolean;
  agent: string;
  executor: string;
  workItemType?: string | null;
  progress: number;
  logLine: string;
  changedArtifacts: string[];
  startedAt?: string | null;
  finishedAt?: string | null;
  startedAtLabel: string;
  finishedAtLabel: string;
  selectedStrategy?: string | null;
  effectiveStrategy?: string | null;
  transitionReason?: string | null;
  driftRiskScore?: number | null;
  executionZone?: string | null;
};

const props = defineProps<{
  tasks: QueueTask[];
  etaProfiles?: Array<{
    work_item_type: string;
    median_seconds: number;
    sample_count?: number;
  }>;
}>();

const queuedCount = computed(() => props.tasks.filter((task) => task.rawStatus === "QUEUED").length);
const runningCount = computed(() => props.tasks.filter((task) => ["RUNNING", "CLAIMED"].includes(task.rawStatus)).length);
const completedCount = computed(() => props.tasks.filter((task) => task.rawStatus === "DONE").length);
const blockedCount = computed(() => props.tasks.filter((task) => task.rawStatus === "FAILED" && task.blocking !== false).length);
const warningCount = computed(() => props.tasks.filter((task) => task.rawStatus === "FAILED" && task.blocking === false).length);

function taskDotClass(status: string, blocking = true) {
  const normalized = status.toUpperCase();
  if (normalized === "DONE") return "pulse-dot is-success";
  if (normalized === "FAILED" && !blocking) return "pulse-dot is-warning";
  if (normalized === "FAILED") return "pulse-dot is-danger";
  if (normalized === "RUNNING" || normalized === "CLAIMED") return "pulse-dot is-warning";
  return "";
}

function taskCardClass(task: QueueTask) {
  if (task.rawStatus === "FAILED" && task.blocking === false) return "is-warning";
  return `is-${task.rawStatus.toLowerCase()}`;
}

function etaLabel(task: QueueTask) {
  const status = String(task.rawStatus || "").toUpperCase();
  const startedAtMs = task.startedAt ? Date.parse(task.startedAt) : NaN;
  const finishedAtMs = task.finishedAt ? Date.parse(task.finishedAt) : NaN;
  const hasStarted = Number.isFinite(startedAtMs);
  const hasFinished = Number.isFinite(finishedAtMs);
  if (hasStarted && hasFinished && finishedAtMs >= startedAtMs) {
    return `Took ${formatSeconds((finishedAtMs - startedAtMs) / 1000)}`;
  }
  if (status === "DONE") return "Completed";
  if (status === "FAILED") return "Needs retry";
  if (status === "QUEUED") return "Starts soon";
  if (!(status === "RUNNING" || status === "CLAIMED")) return "ETA pending";

  const baseline = baselineSeconds(task.workItemType);
  if (!hasStarted) return `~${formatSeconds(baseline)} remaining`;
  const elapsed = Math.max(0, Math.floor((Date.now() - startedAtMs) / 1000));
  const remaining = Math.max(15, baseline - elapsed);
  return `~${formatSeconds(remaining)} remaining`;
}

function baselineSeconds(type?: string | null) {
  const normalized = String(type || "").toUpperCase();
  const profile = (props.etaProfiles || []).find((item) => String(item.work_item_type || "").toUpperCase() === normalized);
  if (profile && Number.isFinite(Number(profile.median_seconds)) && Number(profile.median_seconds) > 0) {
    return Math.max(15, Math.round(Number(profile.median_seconds)));
  }
  if (normalized.includes("PLAN")) return 45;
  if (normalized === "CODE_FRONTEND") return 180;
  if (normalized === "WRITE_TESTS") return 90;
  if (normalized === "RUN_TESTS") return 120;
  if (normalized.includes("REVIEW")) return 70;
  if (normalized.includes("FIX_TEST_FAILURE")) return 150;
  return 90;
}

function formatSeconds(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.round(seconds / 60);
  return `${mins}m`;
}

function driftChipClass(score: number | null | undefined) {
  const value = typeof score === "number" ? score : 0;
  if (value >= 0.75) return "is-drift-high";
  if (value >= 0.45) return "is-drift-medium";
  return "is-drift-low";
}

function transitionReasonLabel(reason: string) {
  const normalized = String(reason || "").trim().toLowerCase();
  if (normalized === "patch_drift_high_risk_static_frontend") return "Patch drift: switched to safer write mode";
  if (normalized === "patch_apply_error") return "Patch apply failed: switched strategy";
  if (normalized === "layout_sensitive_high_drift_risk") return "Layout-sensitive high drift risk";
  return reason;
}
</script>

<style scoped>
.workbench-panel {
  border: 1px solid var(--border-soft);
  border-radius: 24px;
  padding: 1.35rem;
  background:
    radial-gradient(circle at top left, rgba(91, 156, 255, 0.14), transparent 28%),
    linear-gradient(180deg, rgba(18, 22, 31, 0.92), rgba(14, 17, 25, 0.96));
  box-shadow: var(--shadow-elevated);
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

[data-theme="light"] .workbench-panel {
  background:
    radial-gradient(circle at top left, rgba(91, 156, 255, 0.12), transparent 28%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(244, 247, 252, 0.98));
}

.workbench-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.workbench-panel__eyebrow {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.24em;
  color: var(--text-soft);
}

.workbench-panel__title {
  margin: 0.4rem 0 0;
  font-size: 1.15rem;
  font-weight: 700;
}

.workbench-panel__copy {
  margin: 0.55rem 0 0;
  max-width: 40rem;
  font-size: 0.84rem;
  line-height: 1.55;
  color: var(--text-soft);
}

.workbench-panel__summary {
  min-width: 7rem;
  border: 1px solid rgba(91, 156, 255, 0.18);
  border-radius: 18px;
  padding: 0.85rem 0.9rem;
  background: rgba(91, 156, 255, 0.08);
}

.workbench-panel__summary-value {
  font-size: 1.45rem;
  font-weight: 700;
}

.workbench-panel__summary-label {
  margin-top: 0.15rem;
  font-size: 0.74rem;
  color: var(--text-soft);
  text-transform: uppercase;
  letter-spacing: 0.12em;
}

.workbench-panel__stats {
  margin-top: 1rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
}

.workbench-chip {
  border-radius: 999px;
  border: 1px solid var(--border-soft);
  background: rgba(255, 255, 255, 0.04);
  padding: 0.4rem 0.7rem;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.workbench-chip.is-running {
  border-color: rgba(245, 158, 11, 0.2);
  color: var(--warning);
}

.workbench-chip.is-success {
  border-color: rgba(34, 197, 94, 0.2);
  color: var(--success);
}

.workbench-chip.is-danger {
  border-color: rgba(239, 68, 68, 0.2);
  color: var(--danger);
}

.workbench-chip.is-warning {
  border-color: rgba(245, 158, 11, 0.2);
  color: var(--warning);
}

.task-queue {
  margin-top: 1rem;
  display: grid;
  gap: 0.85rem;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 0.25rem;
  scrollbar-width: thin;
}

.task-queue::-webkit-scrollbar {
  width: 10px;
}

.task-queue::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: linear-gradient(180deg, rgba(100, 116, 139, 0.4), rgba(148, 163, 184, 0.45));
}

.task-card {
  border-radius: 20px;
  border: 1px solid var(--border-soft);
  background: rgba(255, 255, 255, 0.03);
  padding: 1rem;
  transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease;
}

.task-card:hover {
  transform: translateY(-1px);
  border-color: rgba(91, 156, 255, 0.24);
  box-shadow: 0 16px 30px rgba(8, 13, 22, 0.18);
}

.task-card.is-warning {
  border-color: rgba(245, 158, 11, 0.24);
}

.task-card__top,
.task-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  font-size: 0.76rem;
  color: var(--text-soft);
}

.task-card__status {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.45rem;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.task-card__status-note {
  border-radius: 999px;
  border: 1px solid rgba(245, 158, 11, 0.18);
  padding: 0.14rem 0.5rem;
  font-size: 0.68rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--warning);
}

.task-card__progress {
  font-family: "JetBrains Mono", ui-monospace, monospace;
}

.task-card__progress-wrap {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}

.task-card__eta {
  border-radius: 999px;
  border: 1px solid var(--border-soft);
  background: rgba(91, 156, 255, 0.12);
  padding: 0.12rem 0.48rem;
  font-size: 0.68rem;
  letter-spacing: 0.03em;
  color: var(--text-soft);
}

.task-card__title {
  margin-top: 0.65rem;
  font-size: 1rem;
  font-weight: 700;
}

.task-card__meta {
  margin-top: 0.2rem;
  font-size: 0.78rem;
  color: var(--text-soft);
}

.task-card__strategy {
  margin-top: 0.5rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.task-card__strategy-chip {
  border-radius: 999px;
  border: 1px solid var(--border-soft);
  background: rgba(148, 163, 184, 0.14);
  padding: 0.18rem 0.52rem;
  font-size: 0.66rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-soft);
}

.task-card__strategy-chip.is-transition {
  border-color: rgba(245, 158, 11, 0.3);
  color: var(--warning);
}

.task-card__strategy-chip.is-drift-low {
  border-color: rgba(34, 197, 94, 0.28);
  color: var(--success);
}

.task-card__strategy-chip.is-drift-medium {
  border-color: rgba(245, 158, 11, 0.3);
  color: var(--warning);
}

.task-card__strategy-chip.is-drift-high {
  border-color: rgba(239, 68, 68, 0.28);
  color: var(--danger);
}

.task-card__bar {
  margin-top: 0.8rem;
  height: 0.42rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  overflow: hidden;
}

.task-card__bar-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, rgba(91, 156, 255, 0.45), rgba(91, 156, 255, 0.95));
}

.task-card__log {
  margin-top: 0.75rem;
  font-size: 0.82rem;
  line-height: 1.5;
  color: var(--text-muted);
}

.task-card__files {
  margin-top: 0.75rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  align-items: center;
}

.task-card__files-label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--text-soft);
}

.task-card__file-chip {
  border-radius: 999px;
  border: 1px solid rgba(91, 156, 255, 0.16);
  background: rgba(91, 156, 255, 0.08);
  padding: 0.28rem 0.56rem;
  font-size: 0.73rem;
  color: var(--text-muted);
}

.workbench-panel__empty {
  margin-top: 1rem;
  border-radius: 18px;
  border: 1px dashed var(--border-soft);
  padding: 1rem;
  color: var(--text-soft);
  font-size: 0.84rem;
}
</style>
