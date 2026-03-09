<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-3xl font-semibold text-slate-900">Project Overview</h1>
        <p class="text-slate-600">Review project state and enter Mission Control when ready.</p>
      </div>
      <el-button type="primary" :disabled="!projectId" @click="goToRun">
        Enter Mission Control
      </el-button>
    </div>

  <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
    <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div class="text-xs uppercase tracking-wide text-slate-400">Project</div>
      <div class="mt-2 text-lg font-semibold text-slate-900">{{ projectName || "—" }}</div>
      <div class="text-xs text-slate-500 break-all">ID: {{ projectId || "—" }}</div>
      <div class="mt-1 text-xs text-slate-500">
        Stage: <span class="font-semibold">{{ projectStatus || "INTAKE" }}</span>
        <span v-if="allowedTransitions.length"> · Next: {{ allowedTransitions.join(", ") }}</span>
      </div>
    </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Stage</div>
        <div class="mt-2 flex items-center gap-2 text-lg font-semibold text-slate-900">
          <StageBadge :label="stage" />
          <span>{{ stage }}</span>
        </div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Runs</div>
        <div class="mt-2 text-lg font-semibold text-slate-900">{{ runSummary }}</div>
        <div class="text-xs text-slate-500">Latest: {{ latestRunText }}</div>
      </div>
    </div>

    <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Plan Freshness</div>
        <div class="mt-2 text-sm font-semibold" :class="planMeta?.plan_fresh ? 'text-emerald-600' : 'text-amber-600'">
          {{ planMeta?.plan_fresh ? 'Fresh' : 'Stale or missing' }}
        </div>
        <div class="text-xs text-slate-500 break-all">Plan SHA: {{ shortSha(planMeta?.plan_requirements_sha) }}</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Requirements</div>
        <div class="mt-2 text-sm font-semibold">Version: {{ planMeta?.requirements_version ?? '—' }}</div>
        <div class="text-xs text-slate-500 break-all">Req SHA: {{ shortSha(planMeta?.requirements_sha) }}</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Plan Metadata</div>
        <div class="mt-2 text-sm font-semibold">Plan ID: {{ planMeta?.plan_id || '—' }}</div>
        <div class="text-xs text-slate-500">Created: {{ planMeta?.plan_created_at || '—' }}</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-xs uppercase tracking-wide text-slate-400">Graph Health</div>
            <div class="mt-1 text-sm font-semibold" :class="healthOk ? 'text-emerald-600' : 'text-amber-600'">
              {{ healthOk ? 'Healthy' : 'Issues found' }}
            </div>
          </div>
          <el-button size="small" type="primary" plain @click="loadHealth">Refresh</el-button>
        </div>
        <ul class="mt-2 text-xs text-slate-600 space-y-1">
          <li>Orphan tasks: {{ health?.counts?.orphan_tasks ?? 0 }}</li>
          <li>Docs without tasks: {{ health?.counts?.docs_without_tasks ?? 0 }}</li>
          <li>Tasks without trace: {{ health?.counts?.tasks_without_trace ?? 0 }}</li>
          <li>Deprecated without supersede: {{ health?.counts?.deprecated_without_supersede ?? 0 }}</li>
          <li>Cycles detected: {{ health?.counts?.cycles ?? 0 }}</li>
          <li v-if="health && healthOk" class="text-emerald-600">• No major issues</li>
          <li v-if="healthError" class="text-rose-600">Error: {{ healthError }}</li>
        </ul>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-xs uppercase tracking-wide text-slate-400">Lifecycle Score</div>
            <div class="mt-1 text-sm font-semibold" :class="riskClass">
              {{ lifecycleScore?.health_index ?? '—' }} ({{ lifecycleScore?.grade || '—' }})
            </div>
          </div>
          <el-button size="small" type="primary" plain @click="() => { loadLifecycleScore(); loadLifecycleHistory(); }">Refresh</el-button>
        </div>
        <ul class="mt-2 text-xs text-slate-600 space-y-1">
          <li>Risk: {{ lifecycleScore?.risk_level || '—' }}</li>
          <li>Structural: {{ lifecycleScore?.structural_score ?? '—' }}</li>
          <li>Execution: {{ lifecycleScore?.execution_score ?? '—' }}</li>
          <li>Stability: {{ lifecycleScore?.stability_score ?? '—' }}</li>
          <li>Confidence: {{ lifecycleScore?.confidence_score ?? '—' }}</li>
          <li>Governance: {{ lifecycleScore?.governance_score ?? '—' }}</li>
          <li>Coverage: {{ lifecycleScore?.coverage_score ?? '—' }}</li>
          <li v-if="lifecycleScore?.warnings?.length">Warnings: {{ lifecycleScore?.warnings?.join(', ') }}</li>
          <li v-if="lifecycleError" class="text-rose-600">Error: {{ lifecycleError }}</li>
        </ul>
        <div v-if="lifecycleHistory?.length" class="mt-3 text-xs text-slate-600">
          <div class="font-semibold text-slate-700 mb-1">Recent Scores</div>
          <div class="space-y-1">
            <div v-for="(item, idx) in lifecycleHistory.slice(0,5)" :key="idx" class="flex justify-between">
              <span>{{ item.timestamp }}</span>
              <span>{{ item.score }} ({{ item.grade || '—' }})</span>
            </div>
          </div>
        </div>
        <div v-if="lifecycleHistoryError" class="mt-2 text-rose-600">{{ lifecycleHistoryError }}</div>
      </div>
    </div>

    <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm" v-if="planHistory.length">
      <div class="flex items-center justify-between">
        <div class="text-sm uppercase tracking-wide text-slate-400">Plan History</div>
        <span class="text-xs text-slate-500">Latest {{ Math.min(planHistory.length, 5) }} shown</span>
      </div>
      <el-table :data="planHistory.slice(-5).reverse()" size="small" class="mt-3">
        <el-table-column prop="version" label="Version" width="90" />
        <el-table-column prop="plan_id" label="Plan ID" />
        <el-table-column label="Req SHA" width="140">
          <template #default="{ row }">
            {{ shortSha(row.requirements_sha) }}
          </template>
        </el-table-column>
        <el-table-column prop="triggered_by" label="Triggered By" width="140" />
        <el-table-column prop="created_at" label="Created At" />
      </el-table>
    </div>

    <div class="grid gap-4 md:grid-cols-3">
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Architecture Refresh</div>
        <div class="mt-2 text-sm font-semibold" :class="architectureRefreshNeeded ? 'text-amber-600' : 'text-slate-700'">
          {{ architectureRefreshNeeded ? 'Needed' : 'Up to date' }}
        </div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Plan Refresh</div>
        <div class="mt-2 text-sm font-semibold" :class="planRefreshNeeded ? 'text-amber-600' : 'text-slate-700'">
          {{ planRefreshNeeded ? 'Needed' : 'Up to date' }}
        </div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Test Refresh</div>
        <div class="mt-2 text-sm font-semibold" :class="testRefreshNeeded ? 'text-amber-600' : 'text-slate-700'">
          {{ testRefreshNeeded ? 'Needed' : 'Up to date' }}
        </div>
      </div>
    </div>

    <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div class="text-sm uppercase tracking-wide text-slate-400">Actions</div>
      <div class="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        <el-button @click="goHome">Switch Project</el-button>
        <el-tooltip
          content="Enter Mission Control is available in RUN stage."
          placement="top"
          :disabled="projectStatus === 'RUN'"
        >
          <el-button :disabled="!projectId || projectStatus !== 'RUN'" @click="goToRun">
            Enter Mission Control
          </el-button>
        </el-tooltip>
        <el-button type="primary" plain :disabled="!projectId" @click="showImpactDialog = true">
          Preview Impact
        </el-button>
        <el-button type="success" plain :disabled="!projectId || !documents.length" @click="showRegenDialog = true">
          Regenerate Tasks
        </el-button>
        <el-button type="info" plain :disabled="!projectId" @click="openTasksDialog">
          View Tasks
        </el-button>
        <el-button type="warning" plain :disabled="!projectId" @click="showExplainDialog = true">
          Explain Task
        </el-button>
        <el-button type="default" plain :disabled="!projectId" @click="openActivityDialog">
          Activity Log
        </el-button>
        <div class="col-span-full grid grid-cols-3 gap-2">
          <el-button
            :disabled="!allowedTransitions.includes('PLAN') || stageUpdating"
            @click="advanceStage('PLAN')"
          >
            Move to PLAN
          </el-button>
          <el-button
            :disabled="!allowedTransitions.includes('RUN') || stageUpdating"
            @click="advanceStage('RUN')"
          >
            Move to RUN
          </el-button>
          <el-button
            :disabled="!allowedTransitions.includes('EVALUATE') || stageUpdating"
            @click="advanceStage('EVALUATE')"
          >
            Move to EVALUATE
          </el-button>
        </div>
      </div>
      <div v-if="stageMessage" class="mt-2 text-xs text-emerald-600">{{ stageMessage }}</div>
      <div v-if="stageError" class="mt-2 text-xs text-rose-600 whitespace-pre-line">{{ stageError }}</div>
    </div>

    <div class="grid gap-4 lg:grid-cols-3">
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm lg:col-span-2">
        <div class="flex items-center justify-between">
          <div class="text-xs uppercase tracking-wide text-slate-400">Runs</div>
          <div class="flex gap-2">
            <el-select v-model="selectedExecutor" size="small" style="width: 140px" placeholder="Executor">
              <el-option label="Dummy" value="dummy" />
              <el-option label="Codex" value="codex" />
            </el-select>
            <el-button size="small" :disabled="projectStatus !== 'RUN' || runs.some(r => r.status === 'RUNNING')" @click="startRun">
              Start Run
            </el-button>
            <el-button size="small" plain @click="loadRuns">Refresh</el-button>
          </div>
        </div>
        <div v-if="runError" class="text-xs text-rose-600 mt-2">{{ runError }}</div>
        <el-table :data="runs" size="small" class="mt-3" v-loading="runsLoading">
          <el-table-column prop="id" label="Run ID" width="230" />
          <el-table-column prop="status" label="Status" width="110" />
          <el-table-column prop="executor" label="Executor" width="100" />
          <el-table-column prop="started_at" label="Started" width="150" />
          <el-table-column prop="finished_at" label="Finished" width="150" />
          <el-table-column label="Actions" width="160">
            <template #default="{ row }">
              <el-button size="small" plain :disabled="!['RUNNING','QUEUED'].includes(row.status)" @click="setRunStatus(row.id, 'CANCELED')">
                Cancel
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Lifecycle Trend</div>
        <div class="mt-2 text-xs text-slate-500">Shows recent lifecycle scores</div>
        <div class="mt-3 space-y-1 text-xs text-slate-700 max-h-64 overflow-auto">
          <div v-if="!lifecycleHistory?.length" class="text-slate-500">No history yet.</div>
          <div v-for="(item, idx) in lifecycleHistory" :key="idx" class="flex justify-between">
            <span>{{ item.timestamp }}</span>
            <span>{{ item.score }} ({{ item.grade || '—' }})</span>
          </div>
        </div>
      </div>
    </div>

    <div class="grid gap-4 lg:grid-cols-3">
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm lg:col-span-2">
        <div class="flex items-center justify-between">
          <div class="text-xs uppercase tracking-wide text-slate-400">Work Items (latest run)</div>
          <el-button size="small" plain @click="loadWorkItems">Refresh</el-button>
        </div>
        <div v-if="workItemError" class="text-xs text-rose-600 mt-2">{{ workItemError }}</div>
        <el-table :data="workItems" size="small" class="mt-3" v-loading="workItemsLoading">
          <el-table-column prop="id" label="ID" width="230" />
          <el-table-column prop="type" label="Type" width="100" />
          <el-table-column prop="status" label="Status" width="100" />
          <el-table-column prop="executor" label="Exec" width="90" />
          <el-table-column prop="attempt" label="Attempt" width="80" />
          <el-table-column prop="priority" label="Priority" width="80" />
          <el-table-column prop="updated_at" label="Updated" />
        </el-table>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Run Events (latest)</div>
        <div class="mt-2 text-xs text-slate-500">Recent 10</div>
        <div class="mt-3 space-y-1 text-xs text-slate-700 max-h-64 overflow-auto">
          <div v-if="!runEvents.length" class="text-slate-500">No events yet.</div>
          <div v-for="(ev, idx) in runEvents.slice(-10).reverse()" :key="idx" class="flex justify-between">
            <span>{{ ev.ts }}</span>
            <span>{{ ev.event_type }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
      Tip: Mission Control becomes available when a run is active. You can start a run from the API or future run controls.
    </div>

    <span v-if="error" class="text-sm text-rose-600">{{ error }}</span>

    <el-dialog v-model="showImpactDialog" title="Preview Impact" width="520px">
      <div class="space-y-3">
        <el-select
          v-model="impactDocId"
          placeholder="Select document"
          filterable
          :loading="documentsLoading"
          style="width: 100%"
        >
          <el-option
            v-for="doc in documents"
            :key="doc.id"
            :label="doc.title || doc.id"
            :value="doc.id"
          />
        </el-select>
        <div v-if="!documents.length" class="text-xs text-amber-700">
          Add a document first before previewing impact.
        </div>
        <el-input v-model="proposedBody" type="textarea" :rows="4" placeholder="Proposed document body" />
        <el-button type="primary" :loading="impactLoading" @click="doPreviewImpact">Preview</el-button>
        <div v-if="impactResult" class="text-sm text-slate-700 space-y-1">
          <div>Similarity: {{ impactResult.similarity?.toFixed(2) }} ({{ impactResult.risk_tier }})</div>
          <div>Regeneration required: {{ impactResult.regeneration_required ? 'Yes' : 'No' }}</div>
          <div>Impacted tasks: {{ impactResult.impacted_tasks?.length || 0 }}</div>
          <div v-if="impactResult.warnings?.length" class="text-amber-700">
            Warnings: {{ impactResult.warnings.join(', ') }}
          </div>
        </div>
        <div v-if="impactError" class="text-sm text-rose-600">{{ impactError }}</div>
      </div>
    </el-dialog>

    <el-dialog v-model="showRegenDialog" title="Regenerate Tasks" width="480px">
      <div class="space-y-3">
        <el-select
          v-model="regenDocId"
          placeholder="Select document"
          filterable
          :loading="documentsLoading"
          style="width: 100%"
        >
          <el-option
            v-for="doc in documents"
            :key="doc.id"
            :label="doc.title || doc.id"
            :value="doc.id"
          />
        </el-select>
        <div v-if="!documents.length" class="text-xs text-amber-700">
          Add a document first before regenerating tasks.
        </div>
        <el-checkbox v-model="regenForce">Force (override existing tasks for this version)</el-checkbox>
        <el-button type="success" :disabled="!documents.length" :loading="regenLoading" @click="doRegenerate">
          Regenerate
        </el-button>
        <div v-if="regenMessage" class="text-sm text-emerald-700">{{ regenMessage }}</div>
        <div v-if="regenError" class="text-sm text-rose-600">{{ regenError }}</div>
      </div>
    </el-dialog>

    <el-dialog v-model="showTasksDialog" title="Tasks" width="640px">
      <el-table :data="tasks" size="small">
        <el-table-column prop="id" label="ID" width="240" />
        <el-table-column prop="title" label="Title" />
        <el-table-column prop="status" label="Status" width="120" />
        <el-table-column prop="generated_from_document_version" label="Doc Ver" width="90" />
      </el-table>
      <div v-if="tasksError" class="mt-2 text-sm text-rose-600">{{ tasksError }}</div>
    </el-dialog>

    <el-dialog v-model="showExplainDialog" title="Explain Task" width="640px">
      <div class="space-y-3">
        <el-input v-model="explainTaskId" placeholder="Task ID" />
        <el-button type="warning" :loading="explainLoading" @click="doExplain">Explain</el-button>
        <div v-if="explainResult" class="space-y-2 text-sm text-slate-700">
          <div><strong>Origin Docs:</strong> {{ explainResult.origin_documents?.length || 0 }}</div>
          <div><strong>Artifacts:</strong> {{ explainResult.artifacts?.length || 0 }}</div>
          <div><strong>Approvals:</strong> {{ explainResult.approvals?.length || 0 }}</div>
          <div><strong>Confidence:</strong> {{ explainResult.confidence_score ?? '—' }}</div>
        </div>
        <div v-if="explainError" class="text-sm text-rose-600">{{ explainError }}</div>
      </div>
    </el-dialog>

    <el-dialog v-model="activityDialog" title="Activity Log" width="720px">
      <el-table :data="activity" size="small">
        <el-table-column prop="created_at" label="When" width="170" />
        <el-table-column prop="action_type" label="Action" width="160" />
        <el-table-column prop="entity_type" label="Entity" width="120" />
        <el-table-column prop="entity_id" label="Entity ID" />
      </el-table>
      <div v-if="activityError" class="mt-2 text-sm text-rose-600">{{ activityError }}</div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import StageBadge from "../components/StageBadge.vue";
import { projectContext } from "../state/projectContext";
import { fetchProjectSummary, fetchPlanHistory } from "../api/requirements";
import { previewImpact, regenerateTasks, listTasks, explainTask, listActivity, fetchHealth, fetchLifecycleScore, fetchLifecycleScoreHistory, listDocuments, fetchProjectMeta, listRuns, createRun, updateRunStatus } from "../api/lifecycle";

const route = useRoute();
const router = useRouter();
const error = computed(() => (!projectContext.projectId ? "No project selected." : ""));

const projectId = computed(() => (route.params.projectId as string) || projectContext.projectId);
const projectName = computed(() => projectContext.projectName || "Project");
const stage = computed(() => projectContext.stage || "UNKNOWN");
const runSummary = computed(() => (projectContext.latestRunId ? "Has runs" : "No runs yet"));
const latestRunText = computed(() => projectContext.latestRunId || "None");
const architectureRefreshNeeded = computed(() => projectContext.architectureRefreshNeeded);
const planRefreshNeeded = computed(() => projectContext.planRefreshNeeded);
const testRefreshNeeded = computed(() => projectContext.testRefreshNeeded);
const planMeta = ref<any | null>(null);
const planHistory = ref<any[]>([]);
const health = ref<any | null>(null);
const healthError = ref("");
const healthOk = computed(
  () =>
    health.value &&
    !health.value.orphan_tasks &&
    !health.value.docs_without_tasks &&
    !health.value.tasks_without_trace &&
    !health.value.deprecated_without_supersede &&
    !health.value.graph_cycles_detected
);
const lifecycleScore = ref<any | null>(null);
const lifecycleError = ref("");
const lifecycleHistory = ref<any[]>([]);
const lifecycleHistoryError = ref("");
const activityDialog = ref(false);
const activity = ref<any[]>([]);
const activityError = ref("");
const showImpactDialog = ref(false);
const showRegenDialog = ref(false);
const showTasksDialog = ref(false);
const showExplainDialog = ref(false);
const impactDocId = ref("");
const proposedBody = ref("");
const impactResult = ref<any | null>(null);
const impactError = ref("");
const impactLoading = ref(false);
const regenDocId = ref("");
const regenForce = ref(false);
const regenMessage = ref("");
const regenError = ref("");
const regenLoading = ref(false);
const tasks = ref<any[]>([]);
const tasksError = ref("");
const explainTaskId = ref("");
const explainResult = ref<any | null>(null);
const explainError = ref("");
const explainLoading = ref(false);
const documents = ref<any[]>([]);
const documentsLoading = ref(false);
const projectStatus = ref<string | null>(null);
const allowedTransitions = ref<string[]>([]);
const stageUpdating = ref(false);
const stageMessage = ref("");
const stageError = ref("");
const runs = ref<any[]>([]);
const runsLoading = ref(false);
const runError = ref("");
const selectedExecutor = ref("dummy");
const workItems = ref<any[]>([]);
const workItemsLoading = ref(false);
const workItemError = ref("");
const runEvents = ref<any[]>([]);
const riskClass = computed(() => {
  const risk = lifecycleScore.value?.risk_level || "UNKNOWN";
  if (risk === "HIGH") return "text-rose-600";
  if (risk === "MEDIUM") return "text-amber-600";
  if (risk === "LOW") return "text-emerald-600";
  return "text-slate-500";
});

function goHome() {
  router.push("/");
}

function goToRun() {
  if (!projectId.value || projectStatus.value !== "RUN") {
    error.value = "Enter Mission Control is available only in RUN stage.";
    return;
  }
  router.push(`/projects/${projectId.value}/run`);
}

async function doPreviewImpact() {
  if (!projectId.value || !impactDocId.value) {
    impactError.value = "Project ID and Document ID required.";
    return;
  }
  impactError.value = "";
  impactLoading.value = true;
  try {
    impactResult.value = await previewImpact(projectId.value, impactDocId.value, proposedBody.value);
  } catch (err: any) {
    impactError.value = err?.message || "Preview failed";
  } finally {
    impactLoading.value = false;
  }
}

async function doRegenerate() {
  if (!projectId.value || !regenDocId.value) {
    regenError.value = "Add/select a document first.";
    return;
  }
  regenError.value = "";
  regenMessage.value = "";
  regenLoading.value = true;
  try {
    const res = await regenerateTasks(projectId.value, regenDocId.value, regenForce.value);
    regenMessage.value = `Generated ${res.tasks?.length || 0} tasks.`;
  } catch (err: any) {
    regenError.value = err?.message || "Regeneration failed";
  } finally {
    regenLoading.value = false;
  }
}

async function openTasksDialog() {
  showTasksDialog.value = true;
  tasksError.value = "";
  if (!projectId.value) return;
  try {
    tasks.value = await listTasks(projectId.value);
  } catch (err: any) {
    tasksError.value = err?.message || "Failed to load tasks";
  }
}

async function loadDocuments() {
  if (!projectId.value) return;
  documentsLoading.value = true;
  try {
    documents.value = await listDocuments(projectId.value);
  } catch (err: any) {
    regenError.value = err?.message || "Failed to load documents";
    impactError.value = err?.message || "Failed to load documents";
  } finally {
    documentsLoading.value = false;
  }
}

async function loadProjectMeta() {
  if (!projectId.value) return;
  try {
    const meta = await fetchProjectMeta(projectId.value);
    projectStatus.value = meta.status || null;
    allowedTransitions.value = meta.allowed_transitions || [];
  } catch {
    // non-blocking
  }
}

async function loadRuns() {
  if (!projectId.value) return;
  runsLoading.value = true;
  runError.value = "";
  try {
    runs.value = await listRuns(projectId.value);
    await loadWorkItems();
    await loadRunEvents();
  } catch (err: any) {
    runError.value = err?.message || "Failed to load runs";
  } finally {
    runsLoading.value = false;
  }
}

async function startRun() {
  if (!projectId.value) return;
  runError.value = "";
  try {
    await createRun(projectId.value, selectedExecutor.value);
    await loadRuns();
    await loadWorkItems();
    await loadRunEvents();
  } catch (err: any) {
    runError.value = err?.message || "Failed to create run";
  }
}

async function setRunStatus(runId: string, status: string) {
  runError.value = "";
  try {
    await updateRunStatus(runId, status);
    await loadRuns();
    await loadWorkItems();
    await loadRunEvents();
    await loadLifecycleScore();
    await loadLifecycleHistory();
  } catch (err: any) {
    runError.value = err?.message || "Failed to update run status";
  }
}

async function loadWorkItems() {
  if (!projectId.value || !runs.value.length) {
    workItems.value = [];
    return;
  }
  workItemsLoading.value = true;
  workItemError.value = "";
  const currentRunId = runs.value[0].id;
  try {
    workItems.value = await listWorkItems(projectId.value, currentRunId);
  } catch (err: any) {
    workItemError.value = err?.message || "Failed to load work items";
  } finally {
    workItemsLoading.value = false;
  }
}

async function loadRunEvents() {
  if (!runs.value.length) {
    runEvents.value = [];
    return;
  }
  const currentRunId = runs.value[0].id;
  try {
    runEvents.value = await listRunEvents(currentRunId);
  } catch (err) {
    // ignore
  }
}

async function advanceStage(target: string) {
  if (!projectId.value) return;
  stageMessage.value = "";
  stageError.value = "";
  stageUpdating.value = true;
  try {
    const updated = await updateProjectStage(projectId.value, target);
    projectStatus.value = updated.status;
    allowedTransitions.value = updated.allowed_transitions || [];
    stageMessage.value = `Stage advanced to ${updated.status}.`;
    // refresh dependent data
    await Promise.all([loadLifecycleScore(), loadLifecycleHistory(), loadHealth()]);
  } catch (err: any) {
    stageError.value = err?.message || "Failed to advance stage.";
  } finally {
    stageUpdating.value = false;
  }
}

async function loadHealth() {
  if (!projectId.value) return;
  try {
    health.value = await fetchHealth(projectId.value);
    healthError.value = "";
  } catch (err: any) {
    healthError.value = err?.message || "Health check failed";
  }
}

async function loadLifecycleScore() {
  if (!projectId.value) return;
  try {
    lifecycleScore.value = await fetchLifecycleScore(projectId.value);
    lifecycleError.value = "";
  } catch (err: any) {
    lifecycleError.value = err?.message || "Lifecycle score failed";
  }
}

async function loadLifecycleHistory() {
  if (!projectId.value) return;
  try {
    lifecycleHistory.value = await fetchLifecycleScoreHistory(projectId.value);
    lifecycleHistoryError.value = "";
  } catch (err: any) {
    lifecycleHistoryError.value = err?.message || "Lifecycle history failed";
  }
}

async function openActivityDialog() {
  activityDialog.value = true;
  activityError.value = "";
  if (!projectId.value) return;
  try {
    activity.value = await listActivity(projectId.value);
  } catch (err: any) {
    activityError.value = err?.message || "Failed to load activity";
  }
}

async function doExplain() {
  if (!projectId.value || !explainTaskId.value) {
    explainError.value = "Project ID and Task ID required.";
    return;
  }
  explainError.value = "";
  explainLoading.value = true;
  try {
    explainResult.value = await explainTask(projectId.value, explainTaskId.value);
  } catch (err: any) {
    explainError.value = err?.message || "Explain failed";
  } finally {
    explainLoading.value = false;
  }
}

function shortSha(val?: string | null) {
  if (!val) return "—";
  return val.slice(0, 8);
}

onMounted(async () => {
  if (!projectId.value) return;
  try {
    const data = await fetchProjectSummary(projectId.value);
    planMeta.value = {
      plan_id: data.plan_id,
      plan_fresh: data.plan_fresh,
      requirements_sha: data.requirements_sha,
      plan_requirements_sha: data.plan_requirements_sha,
      plan_created_at: data.plan_created_at,
      requirements_version: data.requirements_version,
    };
    const history = await fetchPlanHistory(projectId.value);
    planHistory.value = history.entries || [];
  } catch {
    /* ignore */
  }
  await loadHealth();
  await loadLifecycleScore();
  await loadLifecycleHistory();
  await loadDocuments();
  await loadProjectMeta();
  await loadRuns();
  await loadWorkItems();
  await loadRunEvents();
});
</script>
