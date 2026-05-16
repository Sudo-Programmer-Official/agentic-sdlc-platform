<template>
  <div class="mx-auto max-w-3xl space-y-4 p-6">
    <h1 class="text-2xl font-semibold">E2E Smoke Harness</h1>
    <p class="text-sm text-slate-600">
      Deterministic browser smoke flow for tenant/workspace lifecycle transport.
    </p>

    <label class="block text-sm">
      <span class="mb-1 block font-medium">Project ID</span>
      <input v-model="projectId" class="w-full rounded border border-slate-300 px-3 py-2" />
    </label>

    <div class="flex flex-wrap gap-2">
      <button class="rounded bg-sky-600 px-3 py-2 text-sm text-white" :disabled="busy" @click="runHappyPath">
        Run Happy Path
      </button>
      <button class="rounded bg-emerald-600 px-3 py-2 text-sm text-white" :disabled="busy" @click="runRetryPath">
        Run Retry Path
      </button>
    </div>

    <div class="rounded border border-slate-200 bg-slate-50 p-3 text-sm">
      <div><strong>Status:</strong> {{ status }}</div>
      <div v-if="message"><strong>Message:</strong> {{ message }}</div>
      <div v-if="error" class="text-rose-700"><strong>Error:</strong> {{ error }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import {
  createApproval,
  createRun,
  createRunPullRequest,
  createTask,
  getOrCreateActionRequestKey,
  launchRunPreview,
} from "../api/lifecycle";

const projectId = ref("e2e-project-1");
const busy = ref(false);
const status = ref("idle");
const message = ref("");
const error = ref("");

async function runHappyPath() {
  busy.value = true;
  status.value = "running-happy-path";
  message.value = "";
  error.value = "";
  try {
    const task = await createTask(projectId.value, { title: "E2E smoke task" });
    const run = await createRun(
      projectId.value,
      "codex",
      task?.id || null,
      null,
      { request_key: getOrCreateActionRequestKey("start_run", `e2e:happy:${projectId.value}:${task?.id || "task"}`) }
    );
    await createApproval(projectId.value, {
      target_type: "run",
      target_id: run.id,
      status: "PENDING",
      comment: "E2E smoke approval",
    });
    await launchRunPreview(run.id, { reuse_if_healthy: true });
    await createRunPullRequest(run.id, {
      request_key: getOrCreateActionRequestKey("create_pr", `e2e:happy:create_pr:${run.id}`),
    });
    status.value = "happy-path:success";
    message.value = `task=${task?.id || "na"} run=${run?.id || "na"}`;
  } catch (err: any) {
    status.value = "happy-path:failed";
    error.value = err?.message || "happy path failed";
  } finally {
    busy.value = false;
  }
}

async function runRetryPath() {
  busy.value = true;
  status.value = "running-retry-path";
  message.value = "";
  error.value = "";
  try {
    const requestKey = getOrCreateActionRequestKey("start_run", `e2e:retry:${projectId.value}`, 60_000);
    const first = await createRun(projectId.value, "codex", null, null, { request_key: requestKey });
    const second = await createRun(projectId.value, "codex", null, null, { request_key: requestKey });
    const same = first?.id && second?.id && first.id === second.id;
    status.value = same ? "retry-path:success" : "retry-path:failed";
    message.value = `first=${first?.id || "na"} second=${second?.id || "na"} request_key=${requestKey}`;
    if (!same) error.value = "idempotency failed: duplicate run id mismatch";
  } catch (err: any) {
    status.value = "retry-path:failed";
    error.value = err?.message || "retry path failed";
  } finally {
    busy.value = false;
  }
}
</script>
