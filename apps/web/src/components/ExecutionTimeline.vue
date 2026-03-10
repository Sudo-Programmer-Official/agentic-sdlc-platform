<template>
  <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
    <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div>
        <div class="text-sm uppercase tracking-wide text-slate-400">Execution Timeline</div>
        <div class="mt-1 text-xs text-slate-500">Why + Next</div>
      </div>
      <el-radio-group v-model="filterMode" size="small">
        <el-radio-button label="all">All</el-radio-button>
        <el-radio-button label="run">This Run</el-radio-button>
        <el-radio-button label="stage">This Stage</el-radio-button>
      </el-radio-group>
    </div>
    <div v-if="statusSummary" class="mt-4 flex flex-wrap items-center gap-2">
      <el-tag :type="statusSummary.type" effect="light">{{ statusSummary.label }}</el-tag>
      <span class="text-xs text-slate-500">{{ statusSummary.reason }}</span>
    </div>
    <el-timeline class="mt-4">
      <el-timeline-item
        v-for="step in steps"
        :key="step.timestamp + step.title"
        :timestamp="step.timestamp"
        placement="top"
      >
        <div class="text-sm font-semibold text-slate-900">{{ step.title }}</div>
        <div class="mt-1 text-xs text-slate-500">Because: {{ step.because }}</div>
        <div v-if="step.next" class="mt-1 text-xs text-slate-400">
          Next: {{ step.next }}
        </div>
      </el-timeline-item>
    </el-timeline>
    <div v-if="steps.length === 0" class="text-sm text-slate-500">
      No execution history yet.
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
    .sort((a, b) => {
      const left = new Date(a.timestamp).getTime();
      const right = new Date(b.timestamp).getTime();
      return left - right;
    });

  const tasksById = new Map(tasks.map((task) => [task.task_id, task]));
  const parallelGroups = Array.from(new Set(tasks.map((task) => task.parallel_group || "?")));
  const pendingCount = tasks.filter((task) => task.status === "PENDING").length;
  const runningCount = tasks.filter((task) => task.status === "RUNNING").length;
  const failedCount = tasks.filter((task) => task.status === "FAILED").length;
  const doneCount = tasks.filter((task) => task.status === "DONE").length;

  const mapped = scopedLogs.map((log) => {
    const message = log.message || "";
    const details = log.details || {};
    let because = "";
    let next = "";

    if (message === "Run created") {
      because = `Run created for stage ${log.stage} to track execution under governance.`;
      next = "Start the run to allow agents to execute.";
    } else if (message === "Run started") {
      because = "Run moved to RUNNING so agents and tasks can execute.";
      next = tasks.length
        ? "Execute tasks or wait for planner output."
        : "Wait for agent output or create tasks.";
    } else if (message === "Run paused") {
      because = "Execution paused by operator to preserve control.";
      next = "Resume when ready to continue.";
    } else if (message === "Run resumed") {
      because = "Run resumed after pause; execution may continue.";
      next = pendingCount ? "Continue executing ready tasks." : "Wait for next action.";
    } else if (message === "Run completed") {
      because = "All tasks or agent work finished successfully.";
      next = "Advance SDLC stage with approval if required.";
    } else if (message.startsWith("Run failed")) {
      because = "An error occurred during execution; run halted to prevent drift.";
      next = "Review failure details, then restart or cancel.";
    } else if (message === "Run canceled") {
      because = "Run was canceled by operator.";
      next = "Create a new run when ready.";
    } else if (message === "Created agent tasks from PLAN.json") {
      const taskCount = details.task_ids?.length ?? tasks.length;
      const groupCount = parallelGroups.length;
      because = groupCount
        ? `Planner decomposed work into ${taskCount} task(s) across ${groupCount} parallel group(s).`
        : `Planner decomposed work into ${taskCount} task(s) with bounded parallel execution.`;
      next = "Execute the next bounded task batch.";
    } else if (message.startsWith("Task") && message.endsWith("started")) {
      const taskId = details.task_id || message.split(" ")[1];
      const task = tasksById.get(taskId);
      const group = task?.parallel_group ? `group ${task.parallel_group}` : "a parallel group";
      because = task
        ? `Dependencies satisfied; scheduled in ${group}.`
        : "Dependencies satisfied; executor scheduled task.";
      next = task?.outputs?.length
        ? `Produce outputs: ${task.outputs.join(", ")}.`
        : "Produce task outputs.";
    } else if (message.startsWith("Task") && message.endsWith("completed")) {
      const taskId = details.task_id || message.split(" ")[1];
      const task = tasksById.get(taskId);
      because = task
        ? `Outputs written; task ${task.task_id} marked DONE.`
        : "Outputs written; task marked DONE.";
      next = pendingCount ? "Continue with next ready tasks." : "Finalize run.";
    } else if (message.startsWith("Task") && message.endsWith("failed")) {
      because = "Task failed; execution halted to prevent cascading errors.";
      next = "Review error, then retry or cancel.";
    } else if (log.tool === "file_write") {
      because = "Agent produced a documented artifact for review.";
      next = "Continue task execution.";
    } else if (message === "Task execution halted (run not RUNNING)") {
      because = "Run status changed; executor stopped safely.";
      next = "Resume the run to continue executing tasks.";
    } else if (message === "Requirements changed since last approval") {
      because = "Document hash mismatch detected; requirements are stale.";
      next = "Re-approve requirements before continuing.";
    } else if (message === "Stages marked stale due to change request") {
      const staleStages = details.stages?.length ? details.stages.join(", ") : "downstream stages";
      because = `Change request accepted; ${staleStages} marked stale.`;
      next = "Re-plan and re-approve affected stages.";
    } else if (message === "Change request accepted") {
      because = "Human accepted a change; workflow routed back to suggested stage.";
      next = "Re-plan work from the suggested stage.";
    } else if (message === "Change request created") {
      because = "New change request logged for review.";
      next = "Accept or reject the change.";
    } else if (message === "Change request rejected") {
      because = "Change request rejected by operator.";
      next = "Continue with current plan.";
    } else if (message === "Captured requirements artifact snapshots") {
      because = "Requirements approved; hashes captured to enforce staleness checks.";
      next = "Proceed to design/planning with approved docs.";
    } else {
      because = "Recorded system action for auditability.";
      next = runNextFromStatus();
    }

    return {
      timestamp: log.timestamp,
      title: message,
      because,
      next
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
    const type = waiting.kind === "BLOCKED" ? "danger" : "warning";
    return { label: waiting.kind, type, reason: waiting.because };
  }
  if (props.runStatus === "RUNNING") {
    return { label: "ACTIVE", type: "success", reason: "Execution is in progress." };
  }
  if (props.runStatus === "COMPLETED") {
    return { label: "COMPLETE", type: "success", reason: "Run finished successfully." };
  }
  if (props.runStatus === "FAILED") {
    return { label: "BLOCKED", type: "danger", reason: "Run failed; review errors." };
  }
  return { label: "IDLE", type: "info", reason: "No active execution right now." };
});

function runNextFromStatus() {
  if (props.runStatus === "RUNNING") {
    return "Continue executing ready tasks.";
  }
  if (props.runStatus === "PAUSED") {
    return "Resume to continue execution.";
  }
  if (props.runStatus === "COMPLETED") {
    return "Advance SDLC stage with approval.";
  }
  return "Review logs for next action.";
}

function deriveWaitingStep(tasks: Array<any>, runStatus?: string, currentStage?: string, logs?: Array<any>) {
  const logMessages = (logs || []).map((log) => log.message);
  const staleDetected = logMessages.includes("Requirements changed since last approval");
  const changeStale = logMessages.includes("Stages marked stale due to change request");
  if (staleDetected || changeStale) {
    return {
      timestamp: "Now",
      title: "Blocked by stale requirements",
      because: "Requirements changed since last approval; downstream work is stale.",
      next: "Re-approve requirements and re-plan work.",
      kind: "BLOCKED"
    };
  }

  if (runStatus === "PAUSED") {
    return {
      timestamp: "Now",
      title: "Execution paused",
      because: "Run is paused; no tasks will start.",
      next: "Resume the run to continue.",
      kind: "WAITING"
    };
  }

  if (runStatus === "FAILED") {
    return {
      timestamp: "Now",
      title: "Execution blocked by failure",
      because: "A task failed; execution halted to prevent cascading errors.",
      next: "Review failure details and retry or cancel.",
      kind: "BLOCKED"
    };
  }

  if (runStatus === "CANCELED") {
    return {
      timestamp: "Now",
      title: "Run canceled",
      because: "Execution was canceled by the operator.",
      next: "Create a new run when ready.",
      kind: "WAITING"
    };
  }

  if (runStatus === "COMPLETED") {
    return null;
  }

  if (runStatus === "PENDING" || runStatus === "IDLE" || !runStatus) {
    const gateStages = new Set(["REQUIREMENTS_DRAFTED", "DESIGN_DRAFTED"]);
    if (currentStage && gateStages.has(currentStage)) {
      return {
        timestamp: "Now",
        title: "Waiting for approval",
        because: `Approval is required to advance from ${currentStage}.`,
        next: "Request approval to proceed.",
        kind: "WAITING"
      };
    }
    return {
      timestamp: "Now",
      title: "No active run",
      because: "No run is currently executing for this stage.",
      next: "Create and start a run to proceed.",
      kind: "WAITING"
    };
  }

  const pending = tasks.filter((task) => task.status === "PENDING");
  const running = tasks.filter((task) => task.status === "RUNNING");
  const failed = tasks.filter((task) => task.status === "FAILED");
  const tasksById = new Map(tasks.map((task) => [task.task_id, task.status]));
  const dependencyCount = (task: any) =>
    Array.isArray(task.depends_on) && task.depends_on.length > 0
      ? task.depends_on.length
      : Number(task.depends_on_count || 0);
  const ready = pending.filter((task) =>
    dependencyCount(task) === 0 ||
    (task.depends_on || []).every((dep: string) => tasksById.get(dep) === "DONE")
  );

  if (failed.length && running.length === 0) {
    return {
      timestamp: "Now",
      title: "Blocked by failed tasks",
      because: `${failed.length} task(s) failed; execution paused.`,
      next: "Review errors and retry failed tasks.",
      kind: "BLOCKED"
    };
  }

  if (pending.length === 0 && running.length === 0) {
    return {
      timestamp: "Now",
      title: "Waiting for tasks",
      because: "No pending tasks are available to execute.",
      next: "Generate tasks from the planner or add new work.",
      kind: "WAITING"
    };
  }

  if (pending.length > 0 && ready.length === 0 && running.length === 0) {
    const blockedDeps = new Set<string>();
    pending.forEach((task) => {
      (task.depends_on || []).forEach((dep: string) => {
        if (tasksById.get(dep) !== "DONE") {
          blockedDeps.add(dep);
        }
      });
    });
    const blockedCount = pending.filter((task) => dependencyCount(task) > 0).length;
    const depsList = Array.from(blockedDeps).slice(0, 3).join(", ");
    return {
      timestamp: "Now",
      title: "Waiting for dependencies",
      because: depsList
        ? `No tasks started because dependencies are incomplete: ${depsList}.`
        : blockedCount === pending.length
          ? "No tasks started because upstream work is still in progress."
          : "No tasks started because dependencies are incomplete.",
      next: "Complete dependency tasks or adjust the plan.",
      kind: "WAITING"
    };
  }

  if (ready.length > 0 && running.length === 0) {
    return {
      timestamp: "Now",
      title: "Ready to execute",
      because: `${ready.length} task(s) are ready but not yet started.`,
      next: "Run the next bounded batch to continue.",
      kind: "WAITING"
    };
  }

  return null;
}
</script>
