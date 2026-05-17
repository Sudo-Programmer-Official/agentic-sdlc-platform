<template>
  <div class="premium-card mission-panel p-6">
    <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div>
        <div class="text-sm uppercase tracking-wide text-slate-400">Execution Timeline</div>
        <div class="mt-1 text-xs text-slate-500">A visual explanation of why the system is doing what it is doing next.</div>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span v-if="statusSummary" class="topbar-chip" :style="summaryStyle(statusSummary.type)">
          <span class="soft-dot" :class="{ 'pulse-dot': statusSummary.label === 'ACTIVE' }" />
          {{ statusSummary.label }}
        </span>
        <el-radio-group v-model="filterMode" size="small">
          <el-radio-button label="all">All</el-radio-button>
          <el-radio-button label="run">This Run</el-radio-button>
          <el-radio-button label="stage">This Stage</el-radio-button>
        </el-radio-group>
      </div>
    </div>

    <div v-if="statusSummary" class="mission-subcard mt-4 px-4 py-3 text-sm text-slate-600">
      {{ statusSummary.reason }}
    </div>

    <div v-if="steps.length" class="mt-6 mission-scroll-zone">
      <div class="space-y-4">
        <div
          v-for="(step, index) in steps"
          :key="step.timestamp + step.title"
          class="mission-timeline-step relative overflow-hidden p-4 pl-8"
        >
        <div class="absolute left-4 top-0 h-full w-px bg-[var(--border-soft)]" />
        <div
          class="absolute left-[9px] top-5 h-3 w-3 rounded-full"
          :style="stepDotTone(step.state)"
        />
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <div class="text-sm font-semibold text-slate-900">{{ step.title }}</div>
            <div class="mt-1 text-xs uppercase tracking-wide text-slate-400">{{ step.timestamp }}</div>
            <div class="mt-3 text-sm text-slate-600">
              <strong>Why:</strong> {{ step.because }}
            </div>
            <div v-if="step.next" class="mt-2 text-sm text-slate-500">
              <strong>Next:</strong> {{ step.next }}
            </div>
          </div>
          <span class="topbar-chip" :style="stepBadgeTone(step.state)">
            {{ step.state }}
          </span>
        </div>
        <div
          v-if="index < steps.length - 1"
          class="absolute left-[12px] top-[3.2rem] h-[calc(100%-2.4rem)] w-px"
          style="background: linear-gradient(180deg, var(--border-strong), transparent);"
        />
        </div>
      </div>
    </div>

    <div v-else class="premium-empty mt-4">
      <div class="text-sm font-medium text-slate-900">No execution history yet</div>
      <div class="mt-1 text-xs text-slate-500">Timeline events will populate here when a run starts moving through the pipeline.</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";

const props = defineProps<{
  logs: Array<any>;
  tasks: Array<any>;
  currentStage?: string;
  runStatus?: string;
  runId?: string;
}>();

const filterMode = ref<"all" | "run" | "stage">("all");

const filteredLogs = computed(() => {
  const logs = props.logs || [];
  if (filterMode.value === "run" && props.runId) {
    return logs.filter((log) => log.run_id === props.runId);
  }
  if (filterMode.value === "stage" && props.currentStage) {
    return logs.filter((log) => log.stage === props.currentStage);
  }
  return logs;
});

const steps = computed(() => {
  const tasks = props.tasks || [];
  const scopedLogs = filteredLogs.value
    .slice()
    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

  const tasksById = new Map(tasks.map((task) => [task.task_id, task]));
  const parallelGroups = Array.from(new Set(tasks.map((task) => task.parallel_group || "?")));
  const pendingCount = tasks.filter((task) => task.status === "PENDING").length;

  const mapped = scopedLogs.map((log) => {
    const message = log.message || "";
    const details = log.details || {};
    let because = "";
    let next = "";
    let state = "RECORDED";

    if (message === "Run created") {
      because = `Run created for stage ${log.stage} to execute work under governance.`;
      next = "Prepare workspace and begin scheduled tasks.";
      state = "CREATED";
    } else if (message === "Planner bootstrap started") {
      because = "The planner is now narrowing scope and seeding the initial execution DAG.";
      next = "Wait for work items to appear in the queue.";
      state = "RUNNING";
    } else if (message === "Run started") {
      because = "Execution began and agents can now claim work.";
      next = tasks.length ? "Watch the next ready work item start." : "Wait for planner output.";
      state = "RUNNING";
    } else if (message === "Execution handoff decided") {
      const effectiveMode = details.effective_mode || "embedded";
      because = `Bootstrap completed and the run was handed off to the ${effectiveMode} runtime path.`;
      next = effectiveMode === "external" ? "Wait for a worker to claim the next ready item." : "Watch the runtime execute the next ready item.";
      state = "RUNNING";
    } else if (message === "Governance profile elevated") {
      const fromState = String(details.from_repository_state || "EARLY_BUILD");
      const toState = String(details.to_repository_state || "ACTIVE_PRODUCT");
      because = `Repository governance transitioned from ${fromState} to ${toState} as lifecycle maturity increased.`;
      next = "Continue with stricter bounded execution, decomposition, and validation protections.";
      state = "GOVERNANCE";
    } else if (message === "Run completed") {
      because = "All required tasks finished successfully.";
      next = "Review artifacts and move the SDLC stage forward.";
      state = "COMPLETED";
    } else if (message.startsWith("Run failed")) {
      because = "Execution halted to avoid compounding errors.";
      next = "Inspect recovery path or retry with a forked run.";
      state = "FAILED";
    } else if (message === "Run canceled") {
      because = "Execution was manually stopped.";
      next = "Start a new run when ready.";
      state = "STOPPED";
    } else if (message === "Created agent tasks from PLAN.json") {
      because = `Planner decomposed work into ${tasks.length} task(s) across ${parallelGroups.length || 1} execution lane(s).`;
      next = "Execute the next bounded task batch.";
      state = "PLANNED";
    } else if (message.startsWith("Task") && message.endsWith("started")) {
      const taskId = details.task_id || message.split(" ")[1];
      const task = tasksById.get(taskId);
      because = task ? `Dependencies cleared; ${task.title || task.task_id} entered execution.` : "Dependencies cleared; executor picked up work.";
      next = "Wait for outputs or a recovery decision.";
      state = "RUNNING";
    } else if (message.startsWith("Task") && message.endsWith("completed")) {
      const taskId = details.task_id || message.split(" ")[1];
      const task = tasksById.get(taskId);
      because = task ? `${task.title || task.task_id} produced outputs and closed cleanly.` : "Task produced outputs and closed cleanly.";
      next = pendingCount ? "Continue with remaining queued tasks." : "Finalize the run.";
      state = "COMPLETED";
    } else if (message.startsWith("Task") && message.endsWith("failed")) {
      because = "A work item failed and triggered run protection.";
      next = "Observe whether recovery inserts a new fix path.";
      state = "FAILED";
    } else if (message.startsWith("Auto recovery queued") || message.startsWith("Recovery queued")) {
      because = "The recovery engine inserted a deterministic repair path into the DAG.";
      next = "Watch the recovery node execute, then evaluate the retry.";
      state = "RECOVERY";
    } else if (message === "Requirements changed since last approval") {
      because = "Input documents changed, so downstream artifacts are potentially stale.";
      next = "Re-approve or re-plan before continuing.";
      state = "BLOCKED";
    } else {
      because = "Recorded system action for replay and auditability.";
      next = runNextFromStatus();
      state = inferStateFromMessage(message);
    }

    return {
      timestamp: log.timestamp,
      title: message,
      because,
      next,
      state,
    };
  });

  const waitingStep = deriveWaitingStep(tasks, props.runStatus, props.currentStage, props.logs || []);
  if (waitingStep) {
    mapped.push(waitingStep);
  }

  return mapped;
});

const statusSummary = computed(() => {
  const waiting = deriveWaitingStep(props.tasks || [], props.runStatus, props.currentStage, props.logs || []);
  if (waiting) {
    const type = waiting.state === "BLOCKED" ? "danger" : "warning";
    return { label: waiting.state, type, reason: waiting.because };
  }
  if (props.runStatus === "RUNNING") {
    return { label: "ACTIVE", type: "success", reason: "Automation is currently progressing through the runtime." };
  }
  if (props.runStatus === "COMPLETED") {
    return { label: "COMPLETE", type: "success", reason: "Run finished successfully and is ready for review." };
  }
  if (props.runStatus === "FAILED") {
    return { label: "BLOCKED", type: "danger", reason: "Run failed and needs intervention or a fork." };
  }
  return { label: "IDLE", type: "info", reason: "No active execution right now." };
});

function runNextFromStatus() {
  if (props.runStatus === "RUNNING") return "Continue executing ready tasks.";
  if (props.runStatus === "PAUSED") return "Resume to continue execution.";
  if (props.runStatus === "COMPLETED") return "Review outputs and promote the stage.";
  return "Review the latest signals for next action.";
}

function inferStateFromMessage(message: string) {
  if (/complete|done|approved/i.test(message)) return "COMPLETED";
  if (/fail|error/i.test(message)) return "FAILED";
  if (/create|queued|plan/i.test(message)) return "PLANNED";
  return "RECORDED";
}

function deriveWaitingStep(tasks: Array<any>, runStatus?: string, currentStage?: string, logs?: Array<any>) {
  const logMessages = (logs || []).map((log) => log.message);
  const staleDetected = logMessages.includes("Requirements changed since last approval");
  if (staleDetected) {
    return {
      timestamp: "Now",
      title: "Blocked by stale requirements",
      because: "Requirements changed since last approval; downstream work is no longer trustworthy.",
      next: "Re-approve requirements and re-plan work.",
      state: "BLOCKED",
    };
  }

  if (runStatus === "PAUSED") {
    return {
      timestamp: "Now",
      title: "Execution paused",
      because: "The run is paused, so no agents or work items will progress.",
      next: "Resume the run to continue.",
      state: "WAITING",
    };
  }

  if (runStatus === "FAILED") {
    return {
      timestamp: "Now",
      title: "Execution blocked by failure",
      because: "A failed work item stopped the current run to prevent cascading drift.",
      next: "Review the error, replay the run, or create a fork.",
      state: "BLOCKED",
    };
  }

  if (runStatus === "CANCELED") {
    return {
      timestamp: "Now",
      title: "Run canceled",
      because: "Execution was canceled by the operator.",
      next: "Create a new run when ready.",
      state: "WAITING",
    };
  }

  if (runStatus === "QUEUED" && tasks.length === 0) {
    return {
      timestamp: "Now",
      title: "Waiting on planner",
      because: `Planner has not created work items for stage ${currentStage || "current"} yet, so execution cannot start.`,
      next: "Wait for planner bootstrap or retry the run if this state does not clear.",
      state: "WAITING",
    };
  }

  if (runStatus === "RUNNING" && tasks.length === 0) {
    return {
      timestamp: "Now",
      title: "Planner bootstrap in progress",
      because: "The run has started, but the planner is still seeding the initial work items.",
      next: "Wait for the DAG to appear or inspect bootstrap logs if this state lingers.",
      state: "RUNNING",
    };
  }

  return null;
}

function statePalette(state: string) {
  if (state === "RUNNING") {
    return { solid: "var(--warning)", soft: "rgba(245, 158, 11, 0.14)" };
  }
  if (state === "COMPLETED") {
    return { solid: "var(--success)", soft: "rgba(34, 197, 94, 0.14)" };
  }
  if (state === "FAILED" || state === "BLOCKED") {
    return { solid: "var(--danger)", soft: "rgba(239, 68, 68, 0.14)" };
  }
  if (state === "RECOVERY") {
    return { solid: "#8b7dff", soft: "rgba(139, 125, 255, 0.14)" };
  }
  return { solid: "var(--accent)", soft: "rgba(91, 156, 255, 0.14)" };
}

function stepDotTone(state: string) {
  return { background: statePalette(state).solid };
}

function stepBadgeTone(state: string) {
  const palette = statePalette(state);
  return {
    background: palette.soft,
    borderColor: palette.soft,
    color: palette.solid,
  };
}

function summaryStyle(type: string) {
  if (type === "success") return { background: "rgba(34, 197, 94, 0.12)", color: "var(--success)" };
  if (type === "warning") return { background: "rgba(245, 158, 11, 0.12)", color: "var(--warning)" };
  if (type === "danger") return { background: "rgba(239, 68, 68, 0.12)", color: "var(--danger)" };
  return { background: "rgba(91, 156, 255, 0.12)", color: "var(--accent)" };
}
</script>

<style scoped>
.mission-scroll-zone {
  max-height: 32rem;
  overflow-y: auto;
  padding-right: 0.25rem;
}
</style>
