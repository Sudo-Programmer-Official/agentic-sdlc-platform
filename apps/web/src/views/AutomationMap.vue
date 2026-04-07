<template>
  <div class="space-y-6">
    <section class="premium-hero">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="max-w-3xl space-y-3">
          <div class="topbar-chip">
            <AppIcon name="map" size="sm" />
            Live SDLC Map
          </div>
          <div>
            <h1 class="text-3xl font-semibold" style="color: var(--text-strong);">Automation Map</h1>
            <p class="mt-2 text-sm leading-6" style="color: var(--text-muted);">
              Visualize what entered the system, what the platform planned, what executed, what changed, and what is ready for delivery.
            </p>
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <el-select
            v-model="selectedRunId"
            class="min-w-[260px]"
            placeholder="Focus run"
            clearable
            filterable
            @change="handleRunSelection"
          >
            <el-option
              v-for="run in runs"
              :key="run.id"
              :label="runOptionLabel(run)"
              :value="run.id"
            />
          </el-select>
          <button type="button" class="utility-button" @click="loadPage" :disabled="loading">
            <AppIcon name="spark" />
            {{ loading ? "Refreshing…" : "Refresh" }}
          </button>
        </div>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <MetricCard
        label="Inputs"
        :value="documents.length + intakeItems.length"
        :helper="`${documents.length} docs · ${intakeItems.length} intake signals`"
        tone="neutral"
      />
      <MetricCard
        label="Planned"
        :value="tasks.length"
        :helper="`${requirementNodeCount} requirement nodes · ${strategyInsights.length} strategies`"
        tone="warning"
      />
      <MetricCard
        label="Execution"
        :value="runs.length"
        :helper="`${activeRunCount} active · ${failedRunCount} failed/canceled`"
        tone="success"
      />
      <MetricCard
        label="Delivery"
        :value="deliveryHeadline"
        :helper="deliveryDetail"
        :tone="deliveryTone"
      />
    </section>

    <section class="premium-card">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Filters & Legend</div>
          <div class="mt-1 text-sm" style="color: var(--text-muted);">
            Switch between broad system view and focused delivery slices without leaving the map.
          </div>
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="filter in filterOptions"
            :key="filter.id"
            type="button"
            class="topbar-chip"
            :style="selectedFilter === filter.id ? activeFilterStyle : undefined"
            @click="selectedFilter = filter.id"
          >
            {{ filter.label }}
          </button>
        </div>
      </div>

      <div class="mt-4 flex flex-wrap gap-2 text-xs">
        <span class="topbar-chip automation-map__legend">
          <span class="automation-map__legend-swatch automation-map__legend-swatch--input" />
          Inputs
        </span>
        <span class="topbar-chip automation-map__legend">
          <span class="automation-map__legend-swatch automation-map__legend-swatch--plan" />
          Planning
        </span>
        <span class="topbar-chip automation-map__legend">
          <span class="automation-map__legend-swatch automation-map__legend-swatch--execute" />
          Execution
        </span>
        <span class="topbar-chip automation-map__legend">
          <span class="automation-map__legend-swatch automation-map__legend-swatch--artifact" />
          Artifacts
        </span>
        <span class="topbar-chip automation-map__legend">
          <span class="automation-map__legend-swatch automation-map__legend-swatch--deliver" />
          Delivery
        </span>
      </div>
    </section>

    <section class="automation-map">
      <div class="automation-map__canvas">
        <div class="automation-map__flow">
          <div class="automation-map__flow-step" v-for="lane in lanes" :key="lane.id">
            <div class="automation-map__flow-dot" :class="`is-${lane.id}`" />
            <span>{{ lane.label }}</span>
          </div>
        </div>

        <div v-if="error" class="rounded-2xl border px-4 py-3 text-sm" style="border-color: rgba(239, 68, 68, 0.2); background: rgba(239, 68, 68, 0.08); color: var(--danger);">
          {{ error }}
        </div>

        <div class="automation-map__lanes">
          <section
            v-for="lane in visibleLanes"
            :key="lane.id"
            class="automation-map__lane"
          >
            <div class="automation-map__lane-head">
              <div>
                <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">{{ lane.label }}</div>
                <div class="mt-1 text-sm" style="color: var(--text-muted);">{{ lane.description }}</div>
              </div>
              <div class="topbar-chip">{{ lane.nodes.length }}</div>
            </div>

            <div v-if="lane.nodes.length" class="automation-map__lane-body">
              <button
                v-for="node in lane.nodes"
                :key="node.key"
                type="button"
                class="automation-node"
                :class="{
                  'is-selected': selectedNode?.key === node.key,
                  'is-active': node.pulse,
                }"
                :style="nodeStyle(node)"
                @click="selectNode(node)"
              >
                <div class="automation-node__header">
                  <div class="flex items-center gap-2">
                    <AppIcon :name="node.icon" size="sm" />
                    <span class="automation-node__kind">{{ node.kindLabel }}</span>
                  </div>
                  <div v-if="node.status" class="status-ring" :style="statusPillStyle(node.status)">
                    <span class="soft-dot" :class="{ 'pulse-dot': node.pulse }" />
                    {{ node.status }}
                  </div>
                </div>
                <div class="automation-node__title">{{ node.title }}</div>
                <div v-if="node.subtitle" class="automation-node__subtitle">{{ node.subtitle }}</div>
                <div v-if="node.tags.length" class="automation-node__tags">
                  <span v-for="tag in node.tags" :key="`${node.key}-${tag}`" class="topbar-chip">{{ tag }}</span>
                </div>
                <div v-if="node.summary" class="automation-node__summary">{{ node.summary }}</div>
              </button>
            </div>

            <div v-else class="premium-empty mt-4">
              No nodes match this filter in {{ lane.label.toLowerCase() }}.
            </div>
          </section>
        </div>
      </div>

      <aside class="automation-map__inspector">
        <div class="premium-card sticky top-6">
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Inspector</div>
              <div class="mt-1 text-sm" style="color: var(--text-muted);">
                Click any node to inspect its lineage, delivery status, and next action.
              </div>
            </div>
            <button
              v-if="selectedNode"
              type="button"
              class="utility-button"
              @click="clearSelection"
            >
              Clear
            </button>
          </div>

          <div v-if="selectedNode" class="mt-5 space-y-4">
            <div class="rounded-2xl border p-4" :style="nodeStyle(selectedNode)">
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-2">
                  <AppIcon :name="selectedNode.icon" />
                  <div>
                    <div class="text-sm font-semibold" style="color: var(--text-strong);">{{ selectedNode.title }}</div>
                    <div class="text-xs" style="color: var(--text-soft);">{{ selectedNode.kindLabel }}</div>
                  </div>
                </div>
                <div v-if="selectedNode.status" class="status-ring" :style="statusPillStyle(selectedNode.status)">
                  <span class="soft-dot" :class="{ 'pulse-dot': selectedNode.pulse }" />
                  {{ selectedNode.status }}
                </div>
              </div>
              <div v-if="selectedNode.subtitle" class="mt-3 text-sm" style="color: var(--text-muted);">
                {{ selectedNode.subtitle }}
              </div>
              <div v-if="selectedNode.summary" class="mt-3 text-sm leading-6" style="color: var(--text-muted);">
                {{ selectedNode.summary }}
              </div>
              <div v-if="selectedNode.tags.length" class="mt-3 flex flex-wrap gap-2">
                <span v-for="tag in selectedNode.tags" :key="`${selectedNode.key}-inspector-${tag}`" class="topbar-chip">{{ tag }}</span>
              </div>
            </div>

            <div class="rounded-2xl border p-4" style="border-color: var(--border-soft); background: var(--surface-soft);">
              <div class="text-xs uppercase tracking-[0.2em]" style="color: var(--text-soft);">Node Detail</div>
              <div class="mt-3 space-y-2 text-sm" style="color: var(--text-muted);">
                <div v-for="fact in selectedNodeFacts" :key="fact.label" class="flex items-start justify-between gap-4">
                  <span style="color: var(--text-soft);">{{ fact.label }}</span>
                  <span class="text-right break-all" style="color: var(--text-strong);">{{ fact.value }}</span>
                </div>
              </div>
            </div>

            <div
              v-if="inspectorLoading"
              class="premium-empty"
            >
              Loading node detail…
            </div>

            <div
              v-else-if="inspectorError"
              class="rounded-2xl border px-4 py-3 text-sm"
              style="border-color: rgba(245, 158, 11, 0.2); background: rgba(245, 158, 11, 0.08); color: var(--warning);"
            >
              {{ inspectorError }}
            </div>

            <div
              v-if="inspectorArtifactExplain"
              class="rounded-2xl border p-4"
              style="border-color: var(--border-soft); background: var(--surface-soft);"
            >
              <div class="text-xs uppercase tracking-[0.2em]" style="color: var(--text-soft);">Artifact Explain</div>
              <div class="mt-3 space-y-2 text-sm" style="color: var(--text-muted);">
                <div><strong style="color: var(--text-strong);">Origin docs:</strong> {{ inspectorArtifactExplain.origin_documents?.length || 0 }}</div>
                <div><strong style="color: var(--text-strong);">Artifacts:</strong> {{ inspectorArtifactExplain.artifacts?.length || 0 }}</div>
                <div><strong style="color: var(--text-strong);">Approvals:</strong> {{ inspectorArtifactExplain.approvals?.length || 0 }}</div>
                <div><strong style="color: var(--text-strong);">Confidence:</strong> {{ formatConfidence(inspectorArtifactExplain.confidence_score) }}</div>
              </div>
            </div>

            <div
              v-if="inspectorArtifactDiff"
              class="rounded-2xl border p-4"
              style="border-color: var(--border-soft); background: var(--surface-soft);"
            >
              <div class="flex items-center justify-between gap-3">
                <div class="text-xs uppercase tracking-[0.2em]" style="color: var(--text-soft);">Patch Preview</div>
                <div class="topbar-chip">+{{ inspectorArtifactDiff.additions || 0 }} / -{{ inspectorArtifactDiff.deletions || 0 }}</div>
              </div>
              <pre class="automation-map__diff">{{ inspectorArtifactDiff.patch_text || inspectorArtifactDiff.patch || "No diff preview available." }}</pre>
            </div>

            <div
              v-if="inspectorTimeline"
              class="rounded-2xl border p-4"
              style="border-color: var(--border-soft); background: var(--surface-soft);"
            >
              <div class="text-xs uppercase tracking-[0.2em]" style="color: var(--text-soft);">Replay Snapshot</div>
              <div class="mt-3 space-y-3">
                <div
                  v-for="step in inspectorTimeline.steps.slice(0, 6)"
                  :key="step.id"
                  class="rounded-xl border p-3"
                  style="border-color: rgba(255,255,255,0.06); background: var(--surface);"
                >
                  <div class="flex items-center justify-between gap-3">
                    <div class="text-sm font-medium" style="color: var(--text-strong);">{{ step.title }}</div>
                    <div class="status-ring" :style="statusPillStyle(step.status)">{{ step.status }}</div>
                  </div>
                  <div v-if="step.message" class="mt-2 text-xs" style="color: var(--text-muted);">{{ step.message }}</div>
                </div>
              </div>
            </div>

            <div class="flex flex-wrap gap-2">
              <button
                v-for="action in inspectorActions"
                :key="action.label"
                type="button"
                class="utility-button"
                @click="action.onClick"
              >
                <AppIcon :name="action.icon" size="sm" />
                {{ action.label }}
              </button>
            </div>
          </div>

          <div v-else class="premium-empty mt-5">
            Select a document, task, run, artifact, or delivery node to inspect the system graph.
          </div>
        </div>
      </aside>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppIcon from "../components/AppIcon.vue";
import MetricCard from "../components/MetricCard.vue";
import {
  explainArtifact,
  fetchArtifactDiff,
  fetchMissionControlOverview,
  fetchProjectMeta,
  fetchProjectRepo,
  fetchRunTimeline,
  listArtifacts,
  listDocuments,
  listRuns,
  listTasks,
} from "../api/lifecycle";
import { fetchGraph } from "../api/requirements";
import { updateProjectContext } from "../state/projectContext";

type FilterId = "all" | "current-run" | "current-stage" | "artifacts" | "failures" | "pr-path";
type LaneId = "input" | "plan" | "execute" | "artifact" | "deliver";

type AutomationNode = {
  key: string;
  lane: LaneId;
  kind: string;
  kindLabel: string;
  icon: string;
  title: string;
  subtitle?: string;
  summary?: string;
  status?: string | null;
  tags: string[];
  pulse?: boolean;
  raw: any;
};

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const error = ref("");
const project = ref<any | null>(null);
const projectRepo = ref<any | null>(null);
const requirementsGraph = ref<any | null>(null);
const documents = ref<any[]>([]);
const tasks = ref<any[]>([]);
const runs = ref<any[]>([]);
const artifacts = ref<any[]>([]);
const missionOverview = ref<any | null>(null);
const selectedRunId = ref("");
const selectedFilter = ref<FilterId>("all");
const selectedNodeKey = ref("");
const inspectorLoading = ref(false);
const inspectorError = ref("");
const inspectorTimeline = ref<any | null>(null);
const inspectorArtifactExplain = ref<any | null>(null);
const inspectorArtifactDiff = ref<any | null>(null);

const projectId = computed(() => String(route.params.projectId || ""));

const filterOptions: Array<{ id: FilterId; label: string }> = [
  { id: "all", label: "All" },
  { id: "current-run", label: "This Run" },
  { id: "current-stage", label: "This Stage" },
  { id: "artifacts", label: "Artifacts" },
  { id: "failures", label: "Failures" },
  { id: "pr-path", label: "PR Path" },
];

const lanes = computed(() => [
  {
    id: "input" as LaneId,
    label: "Input",
    description: "Documents and intake signals entering the system.",
    nodes: filteredInputNodes.value,
  },
  {
    id: "plan" as LaneId,
    label: "Plan",
    description: "Tasks, requirements, and strategy signals generated from input.",
    nodes: filteredPlanNodes.value,
  },
  {
    id: "execute" as LaneId,
    label: "Execute",
    description: "Runs and replay steps showing active or completed automation.",
    nodes: filteredExecutionNodes.value,
  },
  {
    id: "artifact" as LaneId,
    label: "Artifacts",
    description: "Patches, test logs, and other outputs emitted by execution.",
    nodes: filteredArtifactNodes.value,
  },
  {
    id: "deliver" as LaneId,
    label: "Deliver",
    description: "Approvals, previews, and PR nodes that close the delivery loop.",
    nodes: filteredDeliveryNodes.value,
  },
]);

const visibleLanes = computed(() => lanes.value.filter((lane) => lane.nodes.length || selectedFilter.value === "all"));

const intakeItems = computed(() => missionOverview.value?.work_intake || []);
const strategyInsights = computed(() => missionOverview.value?.strategy_learning || []);
const previewsAndPrs = computed(() => missionOverview.value?.previews_and_prs || null);

const requirementNodeCount = computed(() => {
  const nodes = Array.isArray(requirementsGraph.value?.nodes) ? requirementsGraph.value.nodes : [];
  return nodes.length;
});
const activeRunCount = computed(() => runs.value.filter((run) => ["QUEUED", "RUNNING", "PAUSED"].includes(run.status)).length);
const failedRunCount = computed(() => runs.value.filter((run) => ["FAILED", "CANCELED"].includes(run.status)).length);
const deliveryHeadline = computed(() => {
  if (previewsAndPrs.value?.pull_request_url) return "PR Created";
  if (previewsAndPrs.value?.approval_status) return previewsAndPrs.value.approval_status;
  if (previewsAndPrs.value?.repository_connected) return "Repo Linked";
  return "Not Ready";
});
const deliveryDetail = computed(() => {
  if (previewsAndPrs.value?.pull_request_url) return "Delivery path has reached pull request creation.";
  if (previewsAndPrs.value?.preview_url) return "Preview environment is available for inspection.";
  if (previewsAndPrs.value?.repository_connected) return "Repository connected. Awaiting governed delivery.";
  return "Connect a repository to close the loop.";
});
const deliveryTone = computed<"neutral" | "success" | "warning" | "danger">(() => {
  if (previewsAndPrs.value?.pull_request_url) return "success";
  if (previewsAndPrs.value?.approval_status === "REJECTED") return "danger";
  if (previewsAndPrs.value?.repository_connected) return "warning";
  return "neutral";
});

const selectedRun = computed(() => runs.value.find((run) => run.id === selectedRunId.value) || runs.value[0] || null);
const visibleRunsForFilter = computed(() => {
  if (selectedFilter.value === "current-run" && selectedRunId.value) {
    return runs.value.filter((run) => run.id === selectedRunId.value);
  }
  if (selectedFilter.value === "failures") {
    return runs.value.filter((run) => ["FAILED", "CANCELED"].includes(run.status)).slice(0, 4);
  }
  return runs.value.slice(0, 4);
});
const visibleArtifactsForFilter = computed(() => {
  if (selectedFilter.value === "current-run" && selectedRunId.value) {
    return artifacts.value.filter((artifact) => String(artifact.run_id || "") === selectedRunId.value).slice(0, 6);
  }
  if (selectedFilter.value === "pr-path") {
    return artifacts.value.filter((artifact) => /patch|diff|test/i.test(String(artifact.type || ""))).slice(0, 6);
  }
  if (selectedFilter.value === "failures") {
    return artifacts.value.filter((artifact) => /error|log|fail/i.test(String(artifact.type || ""))).slice(0, 6);
  }
  return artifacts.value.slice(0, 6);
});
const selectedRunTimelineSteps = computed(() =>
  inspectorTimeline.value?.run?.id === selectedRunId.value ? inspectorTimeline.value.steps || [] : []
);

const baseInputNodes = computed<AutomationNode[]>(() => {
  const docNodes = documents.value.slice(0, 5).map((doc) => ({
    key: `document:${doc.id}`,
    lane: "input" as LaneId,
    kind: "document",
    kindLabel: "Document",
    icon: "requirements",
    title: doc.title || doc.type?.toUpperCase() || shortId(doc.id),
    subtitle: `${(doc.type || "document").toUpperCase()} · ${formatTimestamp(doc.created_at)}`,
    summary: doc.source ? `Source ${doc.source}` : undefined,
    status: "READY",
    tags: compactTags([doc.type, doc.version ? `v${doc.version}` : null]),
    raw: doc,
  }));

  const intakeNodes = intakeItems.value.slice(0, 4).map((item: any) => ({
    key: `intake:${item.id}`,
    lane: "input" as LaneId,
    kind: "intake",
    kindLabel: "Intake Signal",
    icon: "spark",
    title: item.title,
    subtitle: `${item.kind} · ${item.risk_tier}`,
    summary: item.summary || item.predicted_modules?.join(", ") || "",
    status: item.risk_tier || "LOW",
    tags: compactTags([...(item.predicted_files || []).slice(0, 2), item.related_task_count ? `${item.related_task_count} tasks` : null]),
    raw: item,
  }));

  return [...docNodes, ...intakeNodes];
});

const basePlanNodes = computed<AutomationNode[]>(() => {
  const taskNodes = tasks.value.slice(0, 6).map((task) => ({
    key: `task:${task.id}`,
    lane: "plan" as LaneId,
    kind: "task",
    kindLabel: "Task",
    icon: "project",
    title: task.title || shortId(task.id),
    subtitle: `${task.stage || "PLAN"} · ${task.status || "PENDING"}`,
    summary: task.description || "",
    status: task.status || "PENDING",
    tags: compactTags([task.category, task.generated_from_document_version ? `doc v${task.generated_from_document_version}` : null]),
    raw: task,
  }));

  const strategyNodes = strategyInsights.value.slice(0, 3).map((strategy: any) => ({
    key: `strategy:${strategy.strategy_type}`,
    lane: "plan" as LaneId,
    kind: "strategy",
    kindLabel: "Strategy",
    icon: "spark",
    title: strategy.label,
    subtitle: `${Math.round((strategy.success_rate || 0) * 100)}% success`,
    summary: strategy.average_elapsed_seconds ? `Avg ${formatElapsed(strategy.average_elapsed_seconds)}` : "Observed from prior runs",
    status: "LEARNING",
    tags: compactTags([`${strategy.uses} uses`]),
    raw: strategy,
  }));

  return [...taskNodes, ...strategyNodes];
});

const baseExecutionNodes = computed<AutomationNode[]>(() => {
  const runNodes = visibleRunsForFilter.value.map((run) => ({
    key: `run:${run.id}`,
    lane: "execute" as LaneId,
    kind: "run",
    kindLabel: "Run",
    icon: "runs",
    title: shortId(run.id),
    subtitle: `${run.executor || "executor"} · ${run.branch_name || "no-branch"}`,
    summary: run.summary?.goal_text || `Started ${formatTimestamp(run.started_at)}`,
    status: run.status,
    tags: compactTags([run.workspace_status, run.finished_at ? "completed" : null]),
    pulse: run.status === "RUNNING",
    raw: run,
  }));

  const stepNodes =
    selectedRunTimelineSteps.value.slice(0, 6).map((step: any) => ({
      key: `step:${step.id}`,
      lane: "execute" as LaneId,
      kind: "step",
      kindLabel: "Replay Step",
      icon: step.status === "FAILED" ? "warning" : "timeline",
      title: step.title,
      subtitle: `${step.kind || "step"} · ${formatTimestamp(step.ts)}`,
      summary: step.message || "",
      status: step.status,
      tags: compactTags([step.work_item_type, step.artifact_type]),
      pulse: step.status === "RUNNING",
      raw: step,
    })) || [];

  return [...runNodes, ...stepNodes];
});

const baseArtifactNodes = computed<AutomationNode[]>(() => {
  return visibleArtifactsForFilter.value.map((artifact) => ({
    key: `artifact:${artifact.id}`,
    lane: "artifact" as LaneId,
    kind: "artifact",
    kindLabel: "Artifact",
    icon: "artifact",
    title: basenameFromUri(artifact.uri) || artifact.type || shortId(artifact.id),
    subtitle: `${artifact.type || "artifact"} · ${formatTimestamp(artifact.created_at)}`,
    summary: artifact.uri,
    status: "READY",
    tags: compactTags([artifact.run_id ? shortId(artifact.run_id) : null]),
    raw: artifact,
  }));
});

const baseDeliveryNodes = computed<AutomationNode[]>(() => {
  const nodes: AutomationNode[] = [];
  if (projectRepo.value) {
    nodes.push({
      key: `repo:${projectRepo.value.id || projectRepo.value.repo_url}`,
      lane: "deliver",
      kind: "repository",
      kindLabel: "Repository",
      icon: "branch",
      title: projectRepo.value.repo_full_name || projectRepo.value.repo_url,
      subtitle: `${projectRepo.value.provider || "provider"} · ${projectRepo.value.default_branch || "main"}`,
      summary: "Connected repository target for workspace-backed execution.",
      status: "CONNECTED",
      tags: compactTags([projectRepo.value.default_branch]),
      raw: projectRepo.value,
    });
  }
  if (previewsAndPrs.value?.patch_artifact) {
    nodes.push({
      key: `approval:${previewsAndPrs.value.patch_artifact.id}`,
      lane: "deliver",
      kind: "approval",
      kindLabel: "Approval Gate",
      icon: "approvals",
      title: previewsAndPrs.value.approval_status || "Awaiting decision",
      subtitle: "Patch approval state",
      summary: "Governed checkpoint before PR creation.",
      status: previewsAndPrs.value.approval_status || "PENDING",
      tags: compactTags([`+${previewsAndPrs.value.additions || 0} / -${previewsAndPrs.value.deletions || 0}`]),
      raw: previewsAndPrs.value,
    });
  }
  if (previewsAndPrs.value?.preview_url || previewsAndPrs.value?.preview_status) {
    nodes.push({
      key: "preview:current",
      lane: "deliver",
      kind: "preview",
      kindLabel: "Preview",
      icon: "play",
      title: previewsAndPrs.value.preview_status || "Preview",
      subtitle: previewsAndPrs.value.preview_url || "No preview URL",
      summary: "Preview deployment readiness associated with the latest patch flow.",
      status: previewsAndPrs.value.preview_status || "NOT_CONFIGURED",
      tags: compactTags([previewsAndPrs.value.branch_name, previewsAndPrs.value.repository_connected ? "repo-linked" : null]),
      raw: previewsAndPrs.value,
    });
  }
  if (previewsAndPrs.value?.pull_request_url) {
    nodes.push({
      key: "pr:current",
      lane: "deliver",
      kind: "pull-request",
      kindLabel: "Pull Request",
      icon: "branch",
      title: pullRequestLabel(previewsAndPrs.value.pull_request_url),
      subtitle: previewsAndPrs.value.pull_request_url,
      summary: "Latest governed delivery output.",
      status: "OPEN",
      tags: compactTags([previewsAndPrs.value.branch_name, previewsAndPrs.value.provider]),
      raw: previewsAndPrs.value,
    });
  }
  return nodes;
});

const filteredInputNodes = computed(() => applyNodeFilter(baseInputNodes.value, "input"));
const filteredPlanNodes = computed(() => applyNodeFilter(basePlanNodes.value, "plan"));
const filteredExecutionNodes = computed(() => applyNodeFilter(baseExecutionNodes.value, "execute"));
const filteredArtifactNodes = computed(() => applyNodeFilter(baseArtifactNodes.value, "artifact"));
const filteredDeliveryNodes = computed(() => applyNodeFilter(baseDeliveryNodes.value, "deliver"));

const allNodes = computed(() => [
  ...filteredInputNodes.value,
  ...filteredPlanNodes.value,
  ...filteredExecutionNodes.value,
  ...filteredArtifactNodes.value,
  ...filteredDeliveryNodes.value,
]);

const selectedNode = computed(() => allNodes.value.find((node) => node.key === selectedNodeKey.value) || null);

const selectedNodeFacts = computed(() => {
  if (!selectedNode.value) return [];
  const raw = selectedNode.value.raw || {};
  switch (selectedNode.value.kind) {
    case "document":
      return [
        { label: "Type", value: String(raw.type || "document").toUpperCase() },
        { label: "Source", value: raw.source || "—" },
        { label: "Version", value: raw.version != null ? String(raw.version) : "—" },
        { label: "Created", value: formatTimestamp(raw.created_at) },
      ];
    case "intake":
      return [
        { label: "Risk", value: raw.risk_tier || "LOW" },
        { label: "Confidence", value: formatConfidence(raw.confidence_score) },
        { label: "Predicted files", value: (raw.predicted_files || []).join(", ") || "—" },
        { label: "Related tasks", value: String(raw.related_task_count || 0) },
      ];
    case "task":
      return [
        { label: "Stage", value: raw.stage || "PLAN" },
        { label: "Status", value: raw.status || "PENDING" },
        { label: "Category", value: raw.category || "—" },
        { label: "Document version", value: raw.generated_from_document_version != null ? String(raw.generated_from_document_version) : "—" },
      ];
    case "strategy":
      return [
        { label: "Uses", value: String(raw.uses || 0) },
        { label: "Success rate", value: `${Math.round((raw.success_rate || 0) * 100)}%` },
        { label: "Average elapsed", value: formatElapsed(raw.average_elapsed_seconds) },
      ];
    case "run":
      return [
        { label: "Executor", value: raw.executor || "—" },
        { label: "Workspace", value: raw.workspace_status || "PENDING" },
        { label: "Branch", value: raw.branch_name || "—" },
        { label: "Started", value: formatTimestamp(raw.started_at) },
      ];
    case "step":
      return [
        { label: "Kind", value: raw.kind || "step" },
        { label: "Work item", value: raw.work_item_type || "—" },
        { label: "Artifact", value: raw.artifact_type || "—" },
        { label: "Timestamp", value: formatTimestamp(raw.ts) },
      ];
    case "artifact":
      return [
        { label: "Type", value: raw.type || "artifact" },
        { label: "Run", value: raw.run_id ? shortId(raw.run_id) : "—" },
        { label: "URI", value: raw.uri || "—" },
        { label: "Created", value: formatTimestamp(raw.created_at) },
      ];
    case "repository":
      return [
        { label: "Provider", value: raw.provider || "—" },
        { label: "Repository", value: raw.repo_full_name || raw.repo_url || "—" },
        { label: "Default branch", value: raw.default_branch || "main" },
      ];
    case "approval":
      return [
        { label: "Status", value: raw.approval_status || "PENDING" },
        { label: "Patch size", value: `+${raw.additions || 0} / -${raw.deletions || 0}` },
        { label: "Files", value: String(raw.file_count || 0) },
      ];
    case "preview":
      return [
        { label: "Preview status", value: raw.preview_status || "NOT_CONFIGURED" },
        { label: "Branch", value: raw.branch_name || "—" },
        { label: "URL", value: raw.preview_url || "—" },
      ];
    case "pull-request":
      return [
        { label: "PR URL", value: raw.pull_request_url || "—" },
        { label: "Provider", value: raw.provider || "—" },
        { label: "Branch", value: raw.branch_name || "—" },
      ];
    default:
      return [];
  }
});

const inspectorActions = computed(() => {
  if (!selectedNode.value) return [];
  const actions: Array<{ label: string; icon: string; onClick: () => void }> = [];
  if (selectedNode.value.kind === "run" && selectedNode.value.raw?.id) {
    actions.push({
      label: "Open Replay",
      icon: "timeline",
      onClick: () => router.push(`/projects/${projectId.value}/runs/${selectedNode.value!.raw.id}/debug`),
    });
    actions.push({
      label: "Mission Control",
      icon: "mission",
      onClick: () => router.push(`/projects/${projectId.value}/run`),
    });
  }
  if (selectedNode.value.kind === "artifact") {
    actions.push({
      label: "Mission Control",
      icon: "mission",
      onClick: () => router.push(`/projects/${projectId.value}/run`),
    });
  }
  if (selectedNode.value.kind === "document" || selectedNode.value.kind === "task" || selectedNode.value.kind === "strategy") {
    actions.push({
      label: "Requirements",
      icon: "requirements",
      onClick: () => router.push(`/projects/${projectId.value}/requirements`),
    });
  }
  if (selectedNode.value.kind === "approval") {
    actions.push({
      label: "Open Approvals",
      icon: "approvals",
      onClick: () => router.push(`/projects/${projectId.value}/approvals`),
    });
  }
  if ((selectedNode.value.kind === "preview" || selectedNode.value.kind === "pull-request") && selectedNode.value.raw) {
    const url = selectedNode.value.kind === "preview" ? selectedNode.value.raw.preview_url : selectedNode.value.raw.pull_request_url;
    if (url) {
      actions.push({
        label: "Open Link",
        icon: "branch",
        onClick: () => window.open(url, "_blank", "noreferrer"),
      });
    }
  }
  return actions;
});

const activeFilterStyle = { background: "rgba(91, 156, 255, 0.16)", color: "var(--accent)", borderColor: "rgba(91, 156, 255, 0.35)" };

watch(
  projectId,
  () => {
    void loadPage();
  },
  { immediate: true }
);

watch(
  selectedRunId,
  async () => {
    if (!selectedRunId.value) {
      inspectorTimeline.value = null;
      return;
    }
    await preloadRunTimeline(selectedRunId.value);
  }
);

watch(
  allNodes,
  (nodes) => {
    if (!nodes.length) {
      selectedNodeKey.value = "";
      return;
    }
    if (!nodes.find((node) => node.key === selectedNodeKey.value)) {
      selectedNodeKey.value = nodes[0].key;
    }
  },
  { immediate: true }
);

watch(
  selectedNode,
  async (node) => {
    inspectorError.value = "";
    inspectorArtifactExplain.value = null;
    inspectorArtifactDiff.value = null;
    if (!node) return;
    inspectorLoading.value = true;
    try {
      if (node.kind === "artifact" && node.raw?.id) {
        const [explainResult, diffResult] = await Promise.allSettled([
          explainArtifact(projectId.value, node.raw.id),
          fetchArtifactDiff(projectId.value, node.raw.id),
        ]);
        if (explainResult.status === "fulfilled") inspectorArtifactExplain.value = explainResult.value;
        if (diffResult.status === "fulfilled") inspectorArtifactDiff.value = diffResult.value;
      } else if (node.kind === "run" && node.raw?.id) {
        await preloadRunTimeline(node.raw.id);
      }
    } catch (err: any) {
      inspectorError.value = err?.message || "Failed to load node detail.";
    } finally {
      inspectorLoading.value = false;
    }
  },
  { immediate: true }
);

async function loadPage() {
  if (!projectId.value) return;
  loading.value = true;
  error.value = "";
  try {
    const results = await Promise.allSettled([
      fetchProjectMeta(projectId.value),
      fetchProjectRepo(projectId.value),
      fetchGraph(projectId.value),
      listDocuments(projectId.value),
      listTasks(projectId.value),
      listRuns(projectId.value),
      listArtifacts(projectId.value),
      fetchMissionControlOverview(projectId.value),
    ]);

    project.value = settledValue(results[0], null);
    projectRepo.value = settledValue(results[1], null);
    requirementsGraph.value = settledValue(results[2], null);
    documents.value = settledValue(results[3], []);
    tasks.value = settledValue(results[4], []);
    runs.value = sortRuns(settledValue(results[5], []));
    artifacts.value = sortArtifacts(settledValue(results[6], []));
    missionOverview.value = settledValue(results[7], null);

    selectedRunId.value = selectedRunId.value || runs.value[0]?.id || "";
    updateProjectContext({
      projectId: projectId.value,
      projectName: project.value?.name || "Project",
      stage: project.value?.status || project.value?.stage || "UNKNOWN",
      latestRunId: runs.value[0]?.id || "",
      runStatus: runs.value[0]?.status || "IDLE",
      hasActiveRun: ["QUEUED", "RUNNING", "PAUSED"].includes(runs.value[0]?.status || ""),
      updatedAt: new Date().toISOString(),
    });

    if (selectedRunId.value) {
      await preloadRunTimeline(selectedRunId.value);
    }
  } catch (err: any) {
    error.value = err?.message || "Failed to load automation map.";
  } finally {
    loading.value = false;
  }
}

async function preloadRunTimeline(runId: string) {
  if (!runId) return;
  try {
    inspectorTimeline.value = await fetchRunTimeline(runId);
  } catch {
    if (inspectorTimeline.value?.run?.id === runId) {
      inspectorTimeline.value = null;
    }
  }
}

function settledValue<T>(result: PromiseSettledResult<any>, fallback: T): T {
  if (result.status === "fulfilled") return result.value as T;
  return fallback;
}

function sortRuns(rows: any[]) {
  if (!Array.isArray(rows)) return [];
  return [...rows].sort((a, b) => new Date(b.started_at || 0).getTime() - new Date(a.started_at || 0).getTime());
}

function sortArtifacts(rows: any[]) {
  if (!Array.isArray(rows)) return [];
  return [...rows].sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime());
}

function handleRunSelection() {
  if (selectedFilter.value === "all") {
    selectedFilter.value = "current-run";
  }
}

function selectNode(node: AutomationNode) {
  selectedNodeKey.value = node.key;
}

function clearSelection() {
  selectedNodeKey.value = "";
}

function applyNodeFilter(nodes: AutomationNode[], lane: LaneId) {
  switch (selectedFilter.value) {
    case "current-run":
      return nodes.filter((node) => filterByCurrentRun(node, lane));
    case "current-stage":
      return nodes.filter((node) => filterByCurrentStage(node, lane));
    case "artifacts":
      return nodes.filter((node) => lane === "execute" || lane === "artifact" || lane === "deliver");
    case "failures":
      return nodes.filter((node) => filterFailures(node, lane));
    case "pr-path":
      return nodes.filter((node) => filterPrPath(node, lane));
    default:
      return nodes;
  }
}

function filterByCurrentRun(node: AutomationNode, lane: LaneId) {
  if (!selectedRunId.value) return lane === "input" || lane === "plan";
  if (lane === "execute") {
    return node.kind === "run" ? node.raw?.id === selectedRunId.value : true;
  }
  if (lane === "artifact") {
    return node.raw?.run_id === selectedRunId.value;
  }
  if (lane === "deliver") {
    const deliveryRunId = missionOverview.value?.latest_change_impact?.run_id;
    return !deliveryRunId || String(deliveryRunId) === selectedRunId.value;
  }
  return true;
}

function filterByCurrentStage(node: AutomationNode, lane: LaneId) {
  const stage = String(project.value?.status || project.value?.stage || "").toUpperCase();
  if (lane === "plan") {
    return node.kind === "task" ? String(node.raw?.stage || "").toUpperCase() === stage || stage === "PLAN" : true;
  }
  if (lane === "execute") {
    return stage === "RUN" || node.kind === "run";
  }
  if (lane === "deliver") {
    return stage === "EVALUATE" || stage === "DEPLOY" || node.kind === "repository";
  }
  return true;
}

function filterFailures(node: AutomationNode, lane: LaneId) {
  if (lane === "execute") return ["FAILED", "CANCELED"].includes(String(node.status || "").toUpperCase()) || node.kind === "step";
  if (lane === "artifact") return /error|log|fail/i.test(String(node.raw?.type || "")) || /error|fail/i.test(String(node.summary || ""));
  if (lane === "deliver") return ["REJECTED", "PENDING"].includes(String(node.status || "").toUpperCase());
  if (lane === "input") return String(node.status || "").toUpperCase() === "HIGH";
  return false;
}

function filterPrPath(node: AutomationNode, lane: LaneId) {
  if (lane === "deliver") return true;
  if (lane === "artifact") return /patch|diff|test/i.test(String(node.raw?.type || ""));
  if (lane === "execute") return node.kind === "run";
  if (lane === "plan") return node.kind === "task" || node.kind === "strategy";
  return lane === "input";
}

function runOptionLabel(run: any) {
  return `${shortId(run.id)} · ${run.status} · ${run.executor || "executor"}`;
}

function nodeStyle(node: AutomationNode) {
  const tone = toneForNode(node);
  const selected = selectedNode.value?.key === node.key;
  return {
    borderColor: selected ? tone.border : tone.borderSoft,
    background: selected ? tone.selectedBackground : tone.background,
    boxShadow: selected ? tone.selectedShadow : tone.shadow,
  };
}

function toneForNode(node: AutomationNode) {
  switch (node.lane) {
    case "input":
      return tonePalette("rgba(91, 156, 255, 0.30)", "rgba(91, 156, 255, 0.14)");
    case "plan":
      return tonePalette("rgba(168, 85, 247, 0.30)", "rgba(168, 85, 247, 0.14)");
    case "execute":
      return tonePalette("rgba(56, 189, 248, 0.30)", "rgba(56, 189, 248, 0.14)");
    case "artifact":
      return tonePalette("rgba(34, 197, 94, 0.30)", "rgba(34, 197, 94, 0.14)");
    case "deliver":
      return tonePalette("rgba(236, 72, 153, 0.30)", "rgba(236, 72, 153, 0.14)");
  }
}

function tonePalette(border: string, background: string) {
  return {
    border,
    borderSoft: "var(--border-soft)",
    background: "var(--surface-soft)",
    selectedBackground: `linear-gradient(180deg, ${background}, rgba(255,255,255,0.02))`,
    shadow: "0 12px 30px rgba(0, 0, 0, 0.14)",
    selectedShadow: "0 18px 36px rgba(0, 0, 0, 0.22)",
  };
}

function statusPillStyle(status?: string | null) {
  const normalized = String(status || "").toUpperCase();
  if (["COMPLETED", "APPROVED", "OPEN", "CONNECTED", "READY", "PREVIEW_READY"].includes(normalized)) {
    return { background: "rgba(34, 197, 94, 0.12)", color: "var(--success)" };
  }
  if (["FAILED", "REJECTED", "CANCELED", "BLOCKED"].includes(normalized)) {
    return { background: "rgba(239, 68, 68, 0.12)", color: "var(--danger)" };
  }
  if (["RUNNING", "QUEUED", "PENDING", "LOW", "MEDIUM", "HIGH", "LEARNING"].includes(normalized)) {
    return { background: "rgba(245, 158, 11, 0.12)", color: "var(--warning)" };
  }
  return { background: "var(--surface)", color: "var(--text-muted)" };
}

function formatTimestamp(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString();
}

function formatElapsed(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  if (value < 60) return `${Math.round(value)}s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}m ${seconds}s`;
}

function formatConfidence(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

function basenameFromUri(uri?: string | null) {
  if (!uri) return "";
  const parts = String(uri).split("/");
  return parts[parts.length - 1] || uri;
}

function pullRequestLabel(url?: string | null) {
  if (!url) return "Pull Request";
  const match = String(url).match(/\/pull\/(\d+)/);
  return match ? `PR #${match[1]}` : "Pull Request";
}

function shortId(value?: string | null) {
  if (!value) return "—";
  return String(value).slice(0, 8);
}

function compactTags(values: Array<string | null | undefined>) {
  return values
    .filter((value): value is string => Boolean(value && String(value).trim()))
    .slice(0, 3);
}
</script>

<style scoped>
.automation-map {
  display: grid;
  gap: 1rem;
  grid-template-columns: minmax(0, 1.55fr) minmax(320px, 0.75fr);
}

.automation-map__canvas {
  border: 1px solid var(--border-soft);
  border-radius: 28px;
  background:
    radial-gradient(circle at top left, rgba(91, 156, 255, 0.08), transparent 26%),
    linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01)),
    var(--surface-1);
  box-shadow: var(--shadow-elevated);
  padding: 1.25rem;
}

.automation-map__flow {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  margin-bottom: 1.25rem;
}

.automation-map__flow-step {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  color: var(--text-soft);
  font-size: 0.72rem;
  letter-spacing: 0.22em;
  text-transform: uppercase;
}

.automation-map__flow-dot {
  width: 0.8rem;
  height: 0.8rem;
  border-radius: 999px;
  box-shadow: 0 0 0 4px rgba(255,255,255,0.03);
}

.automation-map__flow-dot.is-input { background: #5b9cff; }
.automation-map__flow-dot.is-plan { background: #a855f7; }
.automation-map__flow-dot.is-execute { background: #38bdf8; }
.automation-map__flow-dot.is-artifact { background: #22c55e; }
.automation-map__flow-dot.is-deliver { background: #ec4899; }

.automation-map__lanes {
  display: grid;
  gap: 1rem;
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.automation-map__lane {
  min-width: 0;
  border: 1px solid var(--border-soft);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.02);
  padding: 0.95rem;
}

.automation-map__lane-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
}

.automation-map__lane-body {
  margin-top: 1rem;
  display: grid;
  gap: 0.85rem;
}

.automation-node {
  width: 100%;
  text-align: left;
  border: 1px solid var(--border-soft);
  border-radius: 20px;
  padding: 0.95rem;
  transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease;
}

.automation-node:hover {
  transform: translateY(-1px);
}

.automation-node.is-selected {
  transform: translateY(-1px);
}

.automation-node.is-active {
  animation: automation-node-pulse 1.8s ease-in-out infinite;
}

.automation-node__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.automation-node__kind {
  font-size: 0.72rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--text-soft);
}

.automation-node__title {
  margin-top: 0.8rem;
  font-size: 0.98rem;
  font-weight: 600;
  color: var(--text-strong);
  word-break: break-word;
}

.automation-node__subtitle {
  margin-top: 0.35rem;
  font-size: 0.82rem;
  color: var(--text-muted);
  word-break: break-word;
}

.automation-node__summary {
  margin-top: 0.7rem;
  font-size: 0.8rem;
  color: var(--text-soft);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.automation-node__tags {
  margin-top: 0.75rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.automation-map__legend {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}

.automation-map__legend-swatch {
  width: 0.7rem;
  height: 0.7rem;
  border-radius: 999px;
}

.automation-map__legend-swatch--input { background: #5b9cff; }
.automation-map__legend-swatch--plan { background: #a855f7; }
.automation-map__legend-swatch--execute { background: #38bdf8; }
.automation-map__legend-swatch--artifact { background: #22c55e; }
.automation-map__legend-swatch--deliver { background: #ec4899; }

.automation-map__inspector {
  min-width: 0;
}

.automation-map__diff {
  margin-top: 0.9rem;
  max-height: 18rem;
  overflow: auto;
  border-radius: 16px;
  background: rgba(6, 10, 18, 0.7);
  padding: 0.9rem;
  color: #d7e4ff;
  font-size: 0.73rem;
  line-height: 1.55;
  white-space: pre-wrap;
}

@keyframes automation-node-pulse {
  0%, 100% {
    box-shadow: 0 12px 30px rgba(245, 158, 11, 0.08);
  }
  50% {
    box-shadow: 0 18px 38px rgba(245, 158, 11, 0.18);
  }
}

@media (max-width: 1400px) {
  .automation-map {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 1200px) {
  .automation-map__flow,
  .automation-map__lanes {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .automation-map__flow,
  .automation-map__lanes {
    grid-template-columns: 1fr;
  }
}
</style>
