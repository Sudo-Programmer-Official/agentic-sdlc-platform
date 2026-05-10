<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-3xl font-semibold text-slate-900">Requirements</h1>
        <p class="text-slate-600">Ingest PRD, edit FR/QR, manage approval and propagation flags.</p>
      </div>
      <div class="flex items-center gap-2">
        <el-tag :type="statusTag" effect="light">{{ graph?.status || "DRAFT" }}</el-tag>
        <span v-if="graph?.version" class="text-xs text-slate-500">v{{ graph.version }}</span>
        <el-button type="primary" :loading="approving" :disabled="!graph" @click="submitApproveGraph">
          Approve Graph
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="flags"
      type="warning"
      show-icon
      :closable="false"
      title="Propagation needed"
      description="Architecture / plan / tests may need refresh based on latest requirement changes."
      v-show="flags.architecture || flags.plan || flags.tests"
    />

    <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
      <div class="flex items-center justify-between gap-3">
        <div>
          <div class="text-sm uppercase tracking-wide text-slate-400">PRD Ingestion</div>
          <div class="text-xs text-slate-500">Paste PRD markdown to extract starter FR/QR.</div>
        </div>
        <el-button :loading="ingesting" @click="submitPrd">Submit PRD</el-button>
      </div>
      <el-input
        v-model="prdText"
        type="textarea"
        :rows="5"
        placeholder="Paste PRD markdown here..."
      />
    </div>

    <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-3">
      <div class="flex items-center justify-between">
        <div>
          <div class="text-sm uppercase tracking-wide text-slate-400">Requirement Tracking</div>
          <div class="text-xs text-slate-500">Progress cards linked to tasks, runs, and improvements.</div>
        </div>
        <div class="flex items-center gap-2">
          <el-button size="small" plain :loading="summaryLoading" @click="loadRequirementSummary">Refresh</el-button>
          <el-button size="small" plain :disabled="!projectId" @click="exportSummaryCsv">Export CSV</el-button>
        </div>
      </div>
      <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <div v-for="card in requirementCards" :key="card.requirement_id" class="rounded-lg border border-slate-200 p-4">
          <div class="flex items-center justify-between gap-2">
            <div class="text-sm font-semibold text-slate-900">{{ card.requirement_id }}</div>
            <el-tag size="small" effect="light" :type="riskTagType(card.risk_level)">{{ card.risk_level }}</el-tag>
          </div>
          <div class="mt-1 text-xs text-slate-500">{{ card.title }}</div>
          <div class="mt-2 text-xs text-slate-600">
            Status: <span class="font-semibold">{{ card.status }}</span> · Health: {{ card.health_score }}
          </div>
          <div class="mt-1 text-xs text-slate-600">
            Stability: {{ card.stability_score }} · Retries: {{ card.retry_count }} · Unresolved: {{ card.unresolved_count }}
          </div>
          <div class="mt-1 text-xs text-slate-600">
            AI spend: ${{ ((card.ai_spend_cents || 0) / 100).toFixed(4) }} · Tokens: {{ card.ai_total_tokens || 0 }}
          </div>
          <div class="mt-2 text-xs text-slate-600">
            Tasks {{ card.task_counts.open }}/{{ card.task_counts.total }} open · {{ card.task_counts.completed }} done · {{ card.task_counts.failed }} failed
          </div>
          <div class="mt-1 text-xs text-slate-600">
            Runs {{ card.run_counts.running }} running · {{ card.run_counts.completed }} completed · {{ card.run_counts.failed }} failed
          </div>
          <div class="mt-1 text-xs text-slate-600">
            Improvements {{ card.improvement_counts.open }} open · {{ card.improvement_counts.resolved }} resolved
          </div>
          <div class="mt-1 text-xs text-slate-500">Last activity: {{ card.last_activity_at || "—" }}</div>
          <div v-if="card.recurring_failure_patterns?.length" class="mt-1 text-xs text-rose-600">
            Repeated failures: {{ card.recurring_failure_patterns.join(" · ") }}
          </div>
          <div v-if="card.most_impacted_modules?.length" class="mt-1 text-xs text-slate-500">
            Impacted modules: {{ card.most_impacted_modules.join(", ") }}
          </div>
          <el-button class="mt-3" size="small" type="primary" plain @click="openTimeline(card.requirement_id)">
            View Timeline
          </el-button>
        </div>
      </div>
      <div v-if="!requirementCards.length" class="text-xs text-slate-500">
        No requirement cards yet. Ingest PRD or add FR/QR to initialize tracking.
      </div>
      <div v-if="summaryError" class="text-xs text-rose-600">{{ summaryError }}</div>
    </div>

    <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-3">
      <div class="flex items-center justify-between">
        <div>
          <div class="text-sm uppercase tracking-wide text-slate-400">Requirement Evolution</div>
          <div class="text-xs text-slate-500">Latest requirement sources and edits over time.</div>
        </div>
        <el-button size="small" plain :loading="historyLoading" @click="loadRequirementHistory">Refresh</el-button>
      </div>
      <el-table :data="requirementHistory" border size="small" max-height="280">
        <el-table-column prop="created_at" label="Created" width="190" />
        <el-table-column prop="type" label="Type" width="120" />
        <el-table-column prop="title" label="Title" />
        <el-table-column prop="created_by" label="By" width="140" />
      </el-table>
      <div v-if="!requirementHistory.length" class="text-xs text-slate-500">
        No requirement history yet. Submit PRD or create requirement documents to start timeline tracking.
      </div>
      <div v-if="historyError" class="text-xs text-rose-600">{{ historyError }}</div>
    </div>

    <div
      v-if="graph && !frNodes.length && !qrNodes.length && !edges.length"
      class="rounded-xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-700"
    >
      No requirements graph exists yet. Paste a PRD above or add FR/QR nodes manually to start the graph.
    </div>

    <div v-if="graph" class="grid gap-4 lg:grid-cols-2">
      <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-3">
        <div class="flex items-center justify-between">
          <div class="text-sm uppercase tracking-wide text-slate-400">Functional Requirements</div>
          <el-button link type="primary" @click="addFr">Add FR</el-button>
        </div>
        <div v-for="(node, idx) in frNodes" :key="node.id" class="space-y-2 rounded-lg border border-slate-100 p-3">
          <div class="flex items-center justify-between text-xs text-slate-500 gap-2">
            <el-input
              v-model="frNodes[idx].id"
              size="small"
              @blur="syncEdgeIds(node.originalId || node.id, frNodes[idx].id)"
            />
            <el-tag size="small" type="success">FR</el-tag>
            <el-button link type="danger" size="small" @click="removeFr(idx)">Delete</el-button>
          </div>
          <el-input v-model="frNodes[idx].text" type="textarea" :rows="2" />
        </div>
      </div>

      <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-3">
        <div class="flex items-center justify-between">
          <div class="text-sm uppercase tracking-wide text-slate-400">Quality Requirements</div>
          <el-button link type="primary" @click="addQr">Add QR</el-button>
        </div>
        <div v-for="(node, idx) in qrNodes" :key="node.id" class="space-y-2 rounded-lg border border-slate-100 p-3">
          <div class="flex items-center justify-between text-xs text-slate-500 gap-2">
            <el-input
              v-model="qrNodes[idx].id"
              size="small"
              @blur="syncEdgeIds(node.originalId || node.id, qrNodes[idx].id)"
            />
            <el-tag size="small" type="warning">QR</el-tag>
            <el-button link type="danger" size="small" @click="removeQr(idx)">Delete</el-button>
          </div>
          <el-input v-model="qrNodes[idx].text" type="textarea" :rows="2" />
          <el-select v-model="qrNodes[idx].quality_type" placeholder="Quality type" clearable>
            <el-option v-for="opt in qualityOptions" :key="opt" :label="opt" :value="opt" />
          </el-select>
        </div>
      </div>
    </div>

    <div v-if="graph" class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-3">
      <div class="flex items-center justify-between">
        <div class="text-sm uppercase tracking-wide text-slate-400">Edges</div>
        <el-button link type="primary" @click="addEdge">Add Edge</el-button>
      </div>
      <el-table :data="edges" border size="small">
        <el-table-column label="From" prop="from_id" width="160">
          <template #default="scope">
            <el-select v-model="edges[scope.$index].from_id" filterable>
              <el-option v-for="node in frNodes" :key="node.id" :value="node.id" :label="node.id" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="To" prop="to_id" width="160">
          <template #default="scope">
            <el-select v-model="edges[scope.$index].to_id" filterable>
              <el-option v-for="node in qrNodes" :key="node.id" :value="node.id" :label="node.id" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="Relation" prop="relation" width="140">
          <template #default="scope">
            <el-select v-model="edges[scope.$index].relation">
              <el-option label="constrains" value="constrains" />
              <el-option label="impacts" value="impacts" />
              <el-option label="requires" value="requires" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="Weight" prop="weight" width="120">
          <template #default="scope">
            <el-input-number v-model="edges[scope.$index].weight" :min="0" :max="1" :step="0.1" />
          </template>
        </el-table-column>
        <el-table-column label="Rationale">
          <template #default="scope">
            <el-input v-model="edges[scope.$index].rationale" placeholder="Optional" />
          </template>
        </el-table-column>
        <el-table-column width="80" align="center">
          <template #default="scope">
            <el-button link type="danger" @click="removeEdge(scope.$index)">Remove</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="flex gap-3">
      <el-button type="primary" :loading="saving" :disabled="!graph" @click="saveGraph">Save Draft</el-button>
      <el-button @click="loadGraph" :loading="loading">Refresh</el-button>
      <el-button disabled>Run AI Improve (coming soon)</el-button>
    </div>

    <div v-if="error" class="text-sm text-rose-600">{{ error }}</div>

    <el-drawer v-model="timelineOpen" title="Requirement Timeline" size="45%">
      <div class="space-y-3">
        <div class="text-xs text-slate-500">Requirement: {{ selectedRequirementId || "—" }}</div>
        <el-table :data="timelineItems" border size="small" max-height="560">
          <el-table-column prop="created_at" label="When" width="190" />
          <el-table-column prop="type" label="Type" width="170" />
          <el-table-column prop="status" label="Status" width="130" />
          <el-table-column prop="title" label="Title" />
        </el-table>
        <div v-if="timelineError" class="text-xs text-rose-600">{{ timelineError }}</div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";

import { projectContext, updateProjectContext } from "../state/projectContext";
import {
  approveGraph as approveRequirementsGraph,
  fetchGraph,
  fetchRequirementSummary,
  fetchRequirementTimeline,
  requirementSummaryExportUrl,
  fetchProjectSummary,
  ingestPrd as ingestProjectPrd,
  updateGraph,
} from "../api/requirements";
import { listDocuments } from "../api/lifecycle";

const route = useRoute();
const projectId = computed(() => route.params.projectId as string);

const loading = ref(false);
const saving = ref(false);
const approving = ref(false);
const ingesting = ref(false);
const error = ref("");

const prdText = ref("");
const graph = ref<any | null>(null);
const frNodes = ref<any[]>([]);
const qrNodes = ref<any[]>([]);
const edges = ref<any[]>([]);
const requirementHistory = ref<any[]>([]);
const historyLoading = ref(false);
const historyError = ref("");
const requirementCards = ref<any[]>([]);
const summaryLoading = ref(false);
const summaryError = ref("");
const timelineOpen = ref(false);
const selectedRequirementId = ref("");
const timelineItems = ref<any[]>([]);
const timelineError = ref("");

const statusTag = computed(() => {
  if (graph.value?.status === "APPROVED") return "success";
  if (graph.value?.status === "STALE") return "warning";
  return "info";
});

const flags = computed(() => ({
  architecture: projectContext.architectureRefreshNeeded,
  plan: projectContext.planRefreshNeeded,
  tests: projectContext.testRefreshNeeded
}));

const qualityOptions = [
  "performance",
  "security",
  "reliability",
  "usability",
  "scalability",
  "maintainability",
  "availability",
  "privacy",
  "compliance",
  "cost"
];

function applyGraph(data: any) {
  const safeGraph = data && typeof data === "object" ? data : null;
  const nodes = Array.isArray(safeGraph?.nodes) ? safeGraph.nodes : [];
  const graphEdges = Array.isArray(safeGraph?.edges) ? safeGraph.edges : [];

  graph.value = safeGraph;
  frNodes.value = nodes.filter((n: any) => n?.type === "FR");
  qrNodes.value = nodes.filter((n: any) => n?.type === "QR");
  edges.value = graphEdges;
}

async function loadGraph() {
  if (!projectId.value) return;
  loading.value = true;
  error.value = "";
  try {
    const data = await fetchGraph(projectId.value);
    applyGraph(data);
  } catch (err: any) {
    graph.value = null;
    frNodes.value = [];
    qrNodes.value = [];
    edges.value = [];
    error.value = err?.message || "Failed to load requirements graph.";
  } finally {
    loading.value = false;
  }
}

async function submitPrd() {
  if (!projectId.value || !prdText.value.trim()) {
    error.value = "PRD text required.";
    return;
  }
  ingesting.value = true;
  error.value = "";
  try {
    const data = await ingestProjectPrd(projectId.value, prdText.value, "typed", "markdown");
    applyGraph(data);
    ElMessage.success("PRD ingested and graph created.");
    await loadSummary();
  } catch (err: any) {
    error.value = err?.message || "Failed to ingest PRD.";
  } finally {
    ingesting.value = false;
  }
}

async function saveGraph() {
  if (!projectId.value) return;
  saving.value = true;
  error.value = "";
  try {
    const payload = { nodes: [...frNodes.value, ...qrNodes.value], edges: edges.value };
    const data = await updateGraph(projectId.value, payload);
    applyGraph(data);
    ElMessage.success("Requirements graph saved.");
    await loadSummary();
  } catch (err: any) {
    error.value = err?.message || "Failed to save graph.";
  } finally {
    saving.value = false;
  }
}

async function submitApproveGraph() {
  if (!projectId.value) return;
  approving.value = true;
  error.value = "";
  try {
    const data = await approveRequirementsGraph(projectId.value, "ui-user");
    graph.value = { ...graph.value, status: data.status, version: data.version };
    ElMessage.success(`Graph approved (sha ${data.sha256.slice(0, 8)}…)`);
    await loadSummary();
  } catch (err: any) {
    error.value = err?.message || "Failed to approve graph.";
  } finally {
    approving.value = false;
  }
}

function addFr() {
  const next = frNodes.value.length + 1;
  frNodes.value.push({
    id: `FR-${String(next).padStart(3, "0")}`,
    originalId: `FR-${String(next).padStart(3, "0")}`,
    type: "FR",
    text: "",
    confidence: 0.7,
    source: "HUMAN_EDITED",
    tags: []
  });
}

function addQr() {
  const next = qrNodes.value.length + 1;
  qrNodes.value.push({
    id: `QR-${String(next).padStart(3, "0")}`,
    originalId: `QR-${String(next).padStart(3, "0")}`,
    type: "QR",
    text: "",
    confidence: 0.7,
    source: "HUMAN_EDITED",
    quality_type: null,
    tags: []
  });
}

function addEdge() {
  const next = edges.value.length + 1;
  edges.value.push({
    id: `EDGE-${String(next).padStart(3, "0")}`,
    from_id: frNodes.value[0]?.id || "FR-001",
    to_id: qrNodes.value[0]?.id || "QR-001",
    relation: "constrains",
    weight: 0.5,
    rationale: ""
  });
}

function removeEdge(idx: number) {
  edges.value.splice(idx, 1);
}

function removeFr(idx: number) {
  const removed = frNodes.value.splice(idx, 1)[0];
  edges.value = edges.value.filter((e) => e.from_id !== removed.id);
}

function removeQr(idx: number) {
  const removed = qrNodes.value.splice(idx, 1)[0];
  edges.value = edges.value.filter((e) => e.to_id !== removed.id);
}

function syncEdgeIds(oldId: string, newId: string) {
  if (!oldId || !newId || oldId === newId) return;
  edges.value = edges.value.map((edge) => {
    if (edge.from_id === oldId) return { ...edge, from_id: newId };
    if (edge.to_id === oldId) return { ...edge, to_id: newId };
    return edge;
  });
}

async function loadSummary() {
  if (!projectId.value) return;
  try {
    const data = await fetchProjectSummary(projectId.value);
    updateProjectContext({
      projectId: data.project_id,
      projectName: data.name,
      stage: data.current_stage,
      latestRunId: data.latest_run?.run_id || "",
      runStatus: data.latest_run?.status || "IDLE",
      architectureRefreshNeeded: data.architecture_refresh_needed ?? false,
      planRefreshNeeded: data.plan_refresh_needed ?? false,
      testRefreshNeeded: data.test_refresh_needed ?? false,
      updatedAt: new Date().toISOString(),
      hasActiveRun: Boolean(data.latest_run?.run_id)
    });
  } catch {
    /* ignore */
  }
}

async function loadRequirementHistory() {
  if (!projectId.value) return;
  historyLoading.value = true;
  historyError.value = "";
  try {
    const docs = await listDocuments(projectId.value);
    const filtered = (Array.isArray(docs) ? docs : []).filter((doc: any) =>
      ["prd", "requirements", "requirements_graph", "spec"].includes(String(doc?.type || "").toLowerCase())
    );
    requirementHistory.value = filtered
      .sort((a: any, b: any) => String(b?.created_at || "").localeCompare(String(a?.created_at || "")))
      .slice(0, 50);
  } catch (err: any) {
    requirementHistory.value = [];
    historyError.value = err?.message || "Failed to load requirement history.";
  } finally {
    historyLoading.value = false;
  }
}

async function loadRequirementSummary() {
  if (!projectId.value) return;
  summaryLoading.value = true;
  summaryError.value = "";
  try {
    const payload = await fetchRequirementSummary(projectId.value, 100, 0);
    requirementCards.value = Array.isArray(payload?.items) ? payload.items : [];
  } catch (err: any) {
    requirementCards.value = [];
    summaryError.value = err?.message || "Failed to load requirement summary.";
  } finally {
    summaryLoading.value = false;
  }
}

function riskTagType(risk: string) {
  if (risk === "HIGH") return "danger";
  if (risk === "MEDIUM") return "warning";
  return "success";
}

async function openTimeline(requirementId: string) {
  if (!projectId.value || !requirementId) return;
  selectedRequirementId.value = requirementId;
  timelineOpen.value = true;
  timelineError.value = "";
  timelineItems.value = [];
  try {
    const payload = await fetchRequirementTimeline(projectId.value, requirementId, 200, 0);
    timelineItems.value = Array.isArray(payload?.items) ? payload.items : [];
  } catch (err: any) {
    timelineItems.value = [];
    timelineError.value = err?.message || "Failed to load requirement timeline.";
  }
}

function exportSummaryCsv() {
  if (!projectId.value) return;
  window.open(requirementSummaryExportUrl(projectId.value, "csv"), "_blank");
}

onMounted(async () => {
  await Promise.all([loadSummary(), loadGraph(), loadRequirementHistory(), loadRequirementSummary()]);
});
</script>
