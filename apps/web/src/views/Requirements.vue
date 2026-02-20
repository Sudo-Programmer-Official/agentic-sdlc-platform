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
        <el-button type="primary" :loading="approving" :disabled="!graph" @click="approveGraph">
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
        <el-button :loading="ingesting" @click="ingestPrd">Submit PRD</el-button>
      </div>
      <el-input
        v-model="prdText"
        type="textarea"
        :rows="5"
        placeholder="Paste PRD markdown here..."
      />
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
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";

import { projectContext, updateProjectContext } from "../state/projectContext";
import { approveGraph, fetchGraph, fetchProjectSummary, ingestPrd, updateGraph } from "../api/requirements";

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

async function loadGraph() {
  if (!projectId.value) return;
  loading.value = true;
  error.value = "";
  try {
    const data = await fetchGraph(projectId.value);
    graph.value = data;
    frNodes.value = data.nodes.filter((n: any) => n.type === "FR");
    qrNodes.value = data.nodes.filter((n: any) => n.type === "QR");
    edges.value = data.edges;
  } catch (err: any) {
    error.value = err?.message || "Failed to load requirements graph.";
  } finally {
    loading.value = false;
  }
}

async function ingestPrd() {
  if (!projectId.value || !prdText.value.trim()) {
    error.value = "PRD text required.";
    return;
  }
  ingesting.value = true;
  error.value = "";
  try {
    graph.value = await ingestPrd(projectId.value, prdText.value, "typed", "markdown");
    frNodes.value = graph.value.nodes.filter((n: any) => n.type === "FR");
    qrNodes.value = graph.value.nodes.filter((n: any) => n.type === "QR");
    edges.value = graph.value.edges;
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
    graph.value = await updateGraph(projectId.value, payload);
    ElMessage.success("Requirements graph saved.");
    await loadSummary();
  } catch (err: any) {
    error.value = err?.message || "Failed to save graph.";
  } finally {
    saving.value = false;
  }
}

async function approveGraph() {
  if (!projectId.value) return;
  approving.value = true;
  error.value = "";
  try {
    const data = await approveGraph(projectId.value, "ui-user");
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

onMounted(async () => {
  await Promise.all([loadSummary(), loadGraph()]);
});
</script>
