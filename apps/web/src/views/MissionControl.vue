<template>
  <div v-if="hasRun" class="space-y-6">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">Mission Control</h1>
      <p class="text-slate-600">
        Watch the active runtime, inspect agent steps, and follow execution as it happens.
      </p>
    </div>

    <el-alert
      v-if="lifecycleWarnings.length"
      type="warning"
      show-icon
      :closable="false"
      title="Runtime warnings"
      :description="lifecycleWarnings.join(' · ')"
      class="shadow-sm"
    />

    <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div class="text-sm uppercase tracking-wide text-slate-400">Runtime Controls</div>
          <div class="text-xs text-slate-500">
            Refresh the latest run, cancel it if needed, or jump back to the project overview.
          </div>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <el-button :loading="loading" @click="loadAll">Refresh</el-button>
          <el-button plain :disabled="!forkEnabled" @click="openForkDialog">
            Fork Run
          </el-button>
          <el-button plain :disabled="!compareEnabled" @click="openCompareDialog">
            Compare Runs
          </el-button>
          <el-button type="danger" plain :disabled="!cancelEnabled" @click="cancelLatestRun">
            Cancel Run
          </el-button>
          <el-button @click="goToOverview">Project Overview</el-button>
        </div>
      </div>
      <div class="mt-4 flex flex-wrap items-center gap-3 text-xs text-slate-500">
        <div class="rounded-lg bg-slate-50 px-3 py-2">
          Project ID
          <span class="ml-2 font-mono text-slate-900">{{ projectId || "—" }}</span>
        </div>
        <div class="rounded-lg bg-slate-50 px-3 py-2">
          Latest Run
          <span class="ml-2 font-mono text-slate-900">{{ latestRun?.id || "—" }}</span>
        </div>
        <div class="rounded-lg bg-slate-50 px-3 py-2">
          Workspace
          <span class="ml-2">
            <el-tag :type="workspaceStatusTagType(latestRun?.workspace_status)" effect="light" size="small">
              {{ latestRun?.workspace_status || "PENDING" }}
            </el-tag>
          </span>
          <div class="mt-1 font-mono text-[11px] text-slate-500">
            {{ latestRun?.branch_name || "—" }}
          </div>
          <div class="font-mono text-[11px] text-slate-400">
            {{ shortenPath(latestRun?.repo_path) }}
          </div>
        </div>
        <div v-if="error" class="rounded-lg bg-rose-50 px-3 py-2 text-rose-600">
          {{ error }}
        </div>
      </div>
    </div>

    <div v-if="project" class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Project Stage</div>
        <div class="mt-2 flex items-center gap-2 text-lg font-semibold text-slate-900">
          <StageBadge :label="currentStage" />
          <span>{{ currentStage }}</span>
        </div>
        <div class="mt-1 text-xs text-slate-500">Project: {{ project.name }}</div>
      </div>

      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Lifecycle Health</div>
        <div class="mt-2 flex items-center gap-2">
          <span class="text-2xl font-semibold text-slate-900">
            {{ lifecycleScore?.health_index ?? "—" }}
          </span>
          <el-tag v-if="lifecycleScore?.grade" effect="light" type="success">
            {{ lifecycleScore.grade }}
          </el-tag>
        </div>
        <div class="mt-1 text-xs text-slate-500">
          Risk: {{ lifecycleScore?.risk_level || "UNKNOWN" }}
        </div>
      </div>

      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Latest Run</div>
        <div class="mt-2 flex items-center gap-2">
          <el-tag :type="runStatusTagType(latestRun?.status)" effect="light">
            {{ latestRun?.status || "IDLE" }}
          </el-tag>
          <span class="text-sm text-slate-500">{{ latestRun?.executor || "—" }}</span>
        </div>
        <div class="mt-1 text-xs text-slate-500">
          Started: {{ formatTimestamp(latestRun?.started_at) }}
        </div>
      </div>

      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Work Items</div>
        <div class="mt-2 text-lg font-semibold text-slate-900">
          {{ runtimeCounts.running }} running
        </div>
        <div class="mt-1 text-xs text-slate-500">
          {{ runtimeCounts.queued }} queued · {{ runtimeCounts.done }} done · {{ runtimeCounts.failed }} failed
        </div>
      </div>
    </div>

    <div v-if="project" class="grid gap-4 lg:grid-cols-2">
      <AgentPanel :agents="agentRows" />

      <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div class="text-sm uppercase tracking-wide text-slate-400">Project Signals</div>
        <div class="mt-4 grid gap-3 sm:grid-cols-2">
          <div class="rounded-lg bg-slate-50 p-4">
            <div class="text-xs uppercase text-slate-400">Run Completion</div>
            <div class="mt-1 text-xl font-semibold text-slate-900">
              {{ lifecycleScore?.execution?.completed_runs ?? 0 }}/{{ lifecycleScore?.execution?.total_runs ?? 0 }}
            </div>
          </div>
          <div class="rounded-lg bg-slate-50 p-4">
            <div class="text-xs uppercase text-slate-400">Trace Coverage</div>
            <div class="mt-1 text-xl font-semibold text-slate-900">
              {{ coveragePercent }}
            </div>
          </div>
          <div class="rounded-lg bg-slate-50 p-4">
            <div class="text-xs uppercase text-slate-400">Graph Cycles</div>
            <div class="mt-1 text-xl font-semibold text-slate-900">
              {{ health?.counts?.cycles ?? 0 }}
            </div>
          </div>
          <div class="rounded-lg bg-slate-50 p-4">
            <div class="text-xs uppercase text-slate-400">Orphan Tasks</div>
            <div class="mt-1 text-xl font-semibold text-slate-900">
              {{ health?.counts?.orphan_tasks ?? 0 }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <ExecutionTimeline
      :logs="timelineLogs"
      :tasks="displayWorkItems"
      :current-stage="currentStage"
      :run-status="latestRun?.status || 'IDLE'"
      :run-id="latestRun?.id"
    />

    <div class="grid gap-4 xl:grid-cols-[2fr,1fr]">
      <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Agent Tasks</div>
            <div class="text-xs text-slate-500">Work items for the latest run.</div>
          </div>
          <el-tag :type="runStatusTagType(latestRun?.status)" effect="light">
            {{ latestRun?.status || "IDLE" }}
          </el-tag>
        </div>
        <el-table
          v-if="displayWorkItems.length"
          :data="displayWorkItems"
          class="mt-4"
          style="width: 100%"
        >
          <el-table-column prop="title" label="Step" min-width="220" />
          <el-table-column prop="agent" label="Agent" min-width="140" />
          <el-table-column prop="executor" label="Executor" min-width="120" />
          <el-table-column label="Status" width="130">
            <template #default="{ row }">
              <el-tag :type="workItemStatusTagType(row.rawStatus)" effect="light">
                {{ row.rawStatus }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Started" min-width="180">
            <template #default="{ row }">
              {{ formatTimestamp(row.started_at) }}
            </template>
          </el-table-column>
          <el-table-column label="Finished" min-width="180">
            <template #default="{ row }">
              {{ formatTimestamp(row.finished_at) }}
            </template>
          </el-table-column>
        </el-table>
        <div v-else class="mt-4 text-sm text-slate-500">No work items yet.</div>
      </div>

      <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Artifacts</div>
            <div class="text-xs text-slate-500">Artifacts captured by the latest run with explainable lineage.</div>
          </div>
          <el-tag effect="light" type="info">
            {{ latestArtifacts.length }} item{{ latestArtifacts.length === 1 ? "" : "s" }}
          </el-tag>
        </div>
        <el-table
          v-if="latestArtifacts.length"
          :data="latestArtifacts"
          class="mt-4"
          size="small"
          style="width: 100%"
        >
          <el-table-column prop="type" label="Type" min-width="120" />
          <el-table-column label="Artifact" min-width="220">
            <template #default="{ row }">
              <div class="font-mono text-xs text-slate-700">{{ shortenUri(row.uri) }}</div>
            </template>
          </el-table-column>
          <el-table-column label="Work Item" min-width="160">
            <template #default="{ row }">
              {{ artifactWorkItemLabel(row.work_item_id) }}
            </template>
          </el-table-column>
          <el-table-column label="Actions" width="100">
            <template #default="{ row }">
              <div class="flex flex-col items-start gap-1">
                <el-button link type="primary" @click="openArtifactExplain(row)">Explain</el-button>
                <el-button
                  v-if="row.type === 'git_diff'"
                  link
                  type="success"
                  @click="openCreatePrDialog(row)"
                >
                  Create PR
                </el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
        <div v-else class="mt-4 text-sm text-slate-500">No artifacts captured for this run yet.</div>
        <div v-if="artifactError" class="mt-3 text-sm text-rose-600">{{ artifactError }}</div>
      </div>
    </div>

    <el-dialog v-model="artifactDialogOpen" title="Explain Artifact" width="720px">
      <div v-if="artifactExplainLoading" class="text-sm text-slate-500">Loading artifact context...</div>
      <div v-else-if="artifactExplainResult" class="space-y-3 text-sm text-slate-700">
        <div><strong>Artifact:</strong> {{ artifactExplainResult.artifact.type }} · {{ artifactExplainResult.artifact.uri }}</div>
        <div><strong>Origin docs:</strong> {{ artifactExplainResult.origin_documents?.length || 0 }}</div>
        <div><strong>Task:</strong> {{ artifactExplainResult.task?.title || "—" }}</div>
        <div><strong>Run:</strong> {{ artifactExplainResult.run?.id || "—" }}</div>
        <div><strong>Work item:</strong> {{ artifactExplainResult.work_item?.key || artifactExplainResult.work_item?.type || "—" }}</div>
        <div><strong>Confidence:</strong> {{ artifactExplainResult.confidence_score ?? "—" }}</div>
        <div><strong>Why this exists:</strong> {{ artifactIntentText(artifactExplainResult) }}</div>
      </div>
      <div v-if="artifactExplainError" class="mt-2 text-sm text-rose-600">{{ artifactExplainError }}</div>
    </el-dialog>

    <el-dialog v-model="forkDialogOpen" title="Fork Run" width="560px">
      <div class="space-y-4">
        <div class="text-sm text-slate-600">
          Clone the latest run DAG, workspace settings, and execution metadata into a new run.
        </div>
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="space-y-1 text-sm text-slate-700">
            <span class="block font-medium text-slate-800">Executor</span>
            <select
              v-model="forkExecutor"
              class="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              <option v-for="option in forkExecutorOptions" :key="option" :value="option">
                {{ option }}
              </option>
            </select>
          </label>
          <label class="space-y-1 text-sm text-slate-700">
            <span class="block font-medium text-slate-800">Branch Name</span>
            <input
              v-model="forkBranchName"
              type="text"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              placeholder="run/my-fork"
            />
          </label>
        </div>
        <label class="space-y-1 text-sm text-slate-700">
          <span class="block font-medium text-slate-800">Fork Notes</span>
          <textarea
            v-model="forkNotes"
            rows="3"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="Why this fork exists, policy overrides, or operator notes"
          />
        </label>
        <label class="flex items-center gap-2 text-sm text-slate-700">
          <input v-model="forkStartNow" type="checkbox" class="rounded border-slate-300" />
          Start the forked run immediately
        </label>
        <div class="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
          Source run
          <span class="ml-2 font-mono text-slate-800">{{ latestRun?.id || "—" }}</span>
        </div>
        <div v-if="forkError" class="text-sm text-rose-600">{{ forkError }}</div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <el-button :disabled="forkLoading" @click="forkDialogOpen = false">Cancel</el-button>
          <el-button type="primary" :loading="forkLoading" :disabled="!forkEnabled" @click="submitForkRun">
            Fork Run
          </el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="compareDialogOpen" title="Compare Runs" width="880px">
      <div class="space-y-4">
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="space-y-1 text-sm text-slate-700">
            <span class="block font-medium text-slate-800">Run A</span>
            <select
              v-model="compareRunAId"
              class="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              <option v-for="option in compareRunOptions" :key="option.id" :value="option.id">
                {{ option.label }}
              </option>
            </select>
          </label>
          <label class="space-y-1 text-sm text-slate-700">
            <span class="block font-medium text-slate-800">Run B</span>
            <select
              v-model="compareRunBId"
              class="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              <option v-for="option in compareRunOptions" :key="option.id" :value="option.id">
                {{ option.label }}
              </option>
            </select>
          </label>
        </div>

        <div v-if="compareResult" class="grid gap-4 md:grid-cols-2">
          <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div class="flex items-center justify-between">
              <div class="text-sm font-semibold text-slate-900">Run A</div>
              <el-tag :type="runStatusTagType(compareResult.run_a.status)" effect="light">
                {{ compareResult.run_a.status }}
              </el-tag>
            </div>
            <div class="mt-3 space-y-1 text-sm text-slate-700">
              <div><strong>ID:</strong> <span class="font-mono">{{ compareResult.run_a.id }}</span></div>
              <div><strong>Executor:</strong> {{ compareResult.run_a.executor }}</div>
              <div><strong>Branch:</strong> {{ compareResult.run_a.branch_name || "—" }}</div>
              <div><strong>Elapsed:</strong> {{ formatElapsed(compareResult.run_a.elapsed_seconds) }}</div>
              <div><strong>Recoveries:</strong> {{ compareResult.run_a.recovery_count }}</div>
              <div><strong>Approval:</strong> {{ compareResult.run_a.approval_status || "—" }}</div>
              <div>
                <strong>PR:</strong>
                <a
                  v-if="compareResult.run_a.pull_request_url"
                  :href="compareResult.run_a.pull_request_url"
                  target="_blank"
                  rel="noreferrer"
                  class="underline"
                >
                  {{ compareResult.run_a.pull_request_url }}
                </a>
                <span v-else>—</span>
              </div>
            </div>
            <div class="mt-3 text-xs uppercase tracking-wide text-slate-400">Files Changed</div>
            <div class="mt-1 text-sm text-slate-600">
              {{ compareResult.run_a.files_changed.length ? compareResult.run_a.files_changed.join(", ") : "No diff files recorded." }}
            </div>
            <div class="mt-3 text-xs uppercase tracking-wide text-slate-400">Artifacts</div>
            <ul class="mt-1 space-y-1 text-sm text-slate-600">
              <li v-for="artifact in compareResult.run_a.artifacts" :key="artifact.id">
                {{ artifact.type }} · {{ shortenUri(artifact.uri) }}
              </li>
            </ul>
          </div>

          <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div class="flex items-center justify-between">
              <div class="text-sm font-semibold text-slate-900">Run B</div>
              <el-tag :type="runStatusTagType(compareResult.run_b.status)" effect="light">
                {{ compareResult.run_b.status }}
              </el-tag>
            </div>
            <div class="mt-3 space-y-1 text-sm text-slate-700">
              <div><strong>ID:</strong> <span class="font-mono">{{ compareResult.run_b.id }}</span></div>
              <div><strong>Executor:</strong> {{ compareResult.run_b.executor }}</div>
              <div><strong>Branch:</strong> {{ compareResult.run_b.branch_name || "—" }}</div>
              <div><strong>Elapsed:</strong> {{ formatElapsed(compareResult.run_b.elapsed_seconds) }}</div>
              <div><strong>Recoveries:</strong> {{ compareResult.run_b.recovery_count }}</div>
              <div><strong>Approval:</strong> {{ compareResult.run_b.approval_status || "—" }}</div>
              <div>
                <strong>PR:</strong>
                <a
                  v-if="compareResult.run_b.pull_request_url"
                  :href="compareResult.run_b.pull_request_url"
                  target="_blank"
                  rel="noreferrer"
                  class="underline"
                >
                  {{ compareResult.run_b.pull_request_url }}
                </a>
                <span v-else>—</span>
              </div>
            </div>
            <div class="mt-3 text-xs uppercase tracking-wide text-slate-400">Files Changed</div>
            <div class="mt-1 text-sm text-slate-600">
              {{ compareResult.run_b.files_changed.length ? compareResult.run_b.files_changed.join(", ") : "No diff files recorded." }}
            </div>
            <div class="mt-3 text-xs uppercase tracking-wide text-slate-400">Artifacts</div>
            <ul class="mt-1 space-y-1 text-sm text-slate-600">
              <li v-for="artifact in compareResult.run_b.artifacts" :key="artifact.id">
                {{ artifact.type }} · {{ shortenUri(artifact.uri) }}
              </li>
            </ul>
          </div>
        </div>

        <div v-if="compareResult" class="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700">
          <div class="text-xs uppercase tracking-wide text-slate-400">Comparison Summary</div>
          <div class="mt-2 space-y-1">
            <div><strong>Faster run:</strong> {{ comparisonSummaryLabel(compareResult.summary.faster_run_id) }}</div>
            <div><strong>More recoveries:</strong> {{ comparisonSummaryLabel(compareResult.summary.more_recoveries_run_id) }}</div>
            <div><strong>PR-ready run:</strong> {{ comparisonSummaryLabel(compareResult.summary.pull_request_run_id) }}</div>
            <div><strong>Artifact types only in Run A:</strong> {{ compareResult.summary.artifact_types_only_in_a.join(", ") || "—" }}</div>
            <div><strong>Artifact types only in Run B:</strong> {{ compareResult.summary.artifact_types_only_in_b.join(", ") || "—" }}</div>
            <div><strong>Files only in Run A:</strong> {{ compareResult.summary.files_only_in_a.join(", ") || "—" }}</div>
            <div><strong>Files only in Run B:</strong> {{ compareResult.summary.files_only_in_b.join(", ") || "—" }}</div>
          </div>
        </div>

        <div v-if="compareError" class="text-sm text-rose-600">{{ compareError }}</div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <el-button :disabled="compareLoading" @click="compareDialogOpen = false">Close</el-button>
          <el-button
            type="primary"
            :loading="compareLoading"
            :disabled="!compareEnabled || !compareRunAId || !compareRunBId || compareRunAId === compareRunBId"
            @click="submitRunComparison"
          >
            Compare
          </el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="createPrDialogOpen" title="Create Pull Request" width="620px">
      <div class="space-y-4">
        <div class="text-sm text-slate-600">
          Create a GitHub pull request from the selected patch artifact and the latest run workspace.
        </div>
        <div class="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
          Patch artifact
          <span class="ml-2 font-mono text-slate-800">{{ selectedPrArtifact?.uri || "—" }}</span>
        </div>
        <label class="space-y-1 text-sm text-slate-700">
          <span class="block font-medium text-slate-800">PR Title</span>
          <input
            v-model="createPrTitle"
            type="text"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="Automated fix from Agentic SDLC"
          />
        </label>
        <label class="space-y-1 text-sm text-slate-700">
          <span class="block font-medium text-slate-800">Branch Name</span>
          <input
            v-model="createPrBranch"
            type="text"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="run/fix-branch"
          />
        </label>
        <label class="space-y-1 text-sm text-slate-700">
          <span class="block font-medium text-slate-800">PR Body</span>
          <textarea
            v-model="createPrBody"
            rows="4"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="Context for reviewers"
          />
        </label>
        <div v-if="createPrResult?.pull_request_url" class="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          Pull request created:
          <a
            :href="createPrResult.pull_request_url"
            target="_blank"
            rel="noreferrer"
            class="ml-1 underline"
          >
            {{ createPrResult.pull_request_url }}
          </a>
        </div>
        <div v-if="createPrError" class="text-sm text-rose-600">{{ createPrError }}</div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <el-button :disabled="createPrLoading" @click="createPrDialogOpen = false">Cancel</el-button>
          <el-button type="primary" :loading="createPrLoading" :disabled="!selectedPrArtifact" @click="submitCreatePr">
            Create PR
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>

  <div v-else class="rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-800">
    Mission Control needs at least one run. Returning to project overview...
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AgentPanel from "../components/AgentPanel.vue";
import ExecutionTimeline from "../components/ExecutionTimeline.vue";
import StageBadge from "../components/StageBadge.vue";
import {
  compareRuns,
  createRunPullRequest,
  explainArtifact,
  fetchHealth,
  fetchLifecycleScore,
  fetchProjectMeta,
  forkRun,
  listArtifacts,
  listRunEvents,
  listRuns,
  listWorkItems,
  updateRunStatus,
} from "../api/lifecycle";
import { updateProjectContext } from "../state/projectContext";

const route = useRoute();
const router = useRouter();

const WORK_ITEM_LABELS: Record<string, string> = {
  PLAN_DAG: "Planner Agent",
  CODE_BACKEND: "Backend Builder",
  CODE_FRONTEND: "Frontend Builder",
  WRITE_TESTS: "Test Writer",
  REVIEW_DIFF: "Diff Reviewer",
  RUN_TESTS: "Test Runner",
  REVIEW_INTEGRATION: "Integration Reviewer",
};

const project = ref<any | null>(null);
const health = ref<any | null>(null);
const lifecycleScore = ref<any | null>(null);
const runs = ref<any[]>([]);
const workItems = ref<any[]>([]);
const runEvents = ref<any[]>([]);
const artifacts = ref<any[]>([]);
const loading = ref(false);
const error = ref("");
const artifactError = ref("");
const artifactDialogOpen = ref(false);
const artifactExplainLoading = ref(false);
const artifactExplainError = ref("");
const artifactExplainResult = ref<any | null>(null);
const createPrDialogOpen = ref(false);
const createPrLoading = ref(false);
const createPrError = ref("");
const createPrResult = ref<any | null>(null);
const selectedPrArtifact = ref<any | null>(null);
const createPrTitle = ref("");
const createPrBody = ref("");
const createPrBranch = ref("");
const forkDialogOpen = ref(false);
const forkLoading = ref(false);
const forkError = ref("");
const forkExecutor = ref("dummy");
const forkBranchName = ref("");
const forkNotes = ref("");
const forkStartNow = ref(true);
const compareDialogOpen = ref(false);
const compareLoading = ref(false);
const compareError = ref("");
const compareResult = ref<any | null>(null);
const compareRunAId = ref("");
const compareRunBId = ref("");

const projectId = computed(() => (route.params.projectId as string) || "");
const latestRun = computed(() => runs.value[0] || null);
const hasRun = computed(() => Boolean(latestRun.value?.id));
const forkEnabled = computed(() => Boolean(latestRun.value?.id));
const compareEnabled = computed(() => runs.value.length >= 2);
const currentStage = computed(() => project.value?.status || "UNKNOWN");
const lifecycleWarnings = computed<string[]>(() => lifecycleScore.value?.warnings || []);
const cancelEnabled = computed(() => ["QUEUED", "RUNNING"].includes(latestRun.value?.status || ""));
const forkExecutorOptions = computed(() => {
  const options = new Set(["dummy", "codex", "test"]);
  if (latestRun.value?.executor) options.add(String(latestRun.value.executor));
  return Array.from(options);
});
const compareRunOptions = computed(() =>
  runs.value.map((run) => ({
    id: run.id,
    label: runOptionLabel(run),
  }))
);
const coveragePercent = computed(() => {
  const ratio = lifecycleScore.value?.coverage?.coverage_ratio;
  return typeof ratio === "number" ? `${Math.round(ratio * 100)}%` : "—";
});

let pollHandle: ReturnType<typeof setInterval> | null = null;
let pollInFlight = false;

const displayWorkItems = computed(() =>
  workItems.value.map((wi) => {
    const payload = wi.payload || {};
    return {
      task_id: wi.id,
      title: payload.title || WORK_ITEM_LABELS[wi.type] || humanizeToken(wi.key || wi.type || "work_item"),
      agent: payload.agent || WORK_ITEM_LABELS[wi.type] || humanizeToken(wi.type || wi.executor || "agent"),
      executor: wi.executor,
      status: normalizeTimelineStatus(wi.status),
      rawStatus: wi.status,
      depends_on: Array.isArray(payload.depends_on) ? payload.depends_on : [],
      depends_on_count: wi.depends_on_count || 0,
      outputs: Array.isArray(payload.outputs) ? payload.outputs : [],
      parallel_group: payload.parallel_group || null,
      started_at: wi.started_at,
      finished_at: wi.finished_at,
      last_error: wi.last_error,
    };
  })
);

const displayWorkItemMap = computed(
  () => new Map(displayWorkItems.value.map((item) => [item.task_id, item]))
);

const timelineLogs = computed(() =>
  runEvents.value.map((event) => {
    const taskId = event.work_item_id || event.task_id || event.payload?.work_item_id || null;
    const workItem = taskId ? displayWorkItemMap.value.get(taskId) : null;
    return {
      timestamp: event.ts,
      run_id: event.run_id,
      stage: currentStage.value,
      message: event.message || mapEventMessage(event.event_type, workItem?.title),
      details: { ...(event.payload || {}), task_id: taskId },
      tool: event.actor_type || "runtime",
    };
  })
);

const agentRows = computed(() =>
  displayWorkItems.value.map((item) => ({
    name: item.title,
    status: panelStatusFor(item.rawStatus),
    taskCount: 1,
  }))
);

const agentSnapshot = computed(() => {
  let active = 0;
  let idle = 0;
  let blocked = 0;
  agentRows.value.forEach((row) => {
    if (row.status === "Running") active += 1;
    else if (row.status === "Blocked") blocked += 1;
    else idle += 1;
  });
  return { active, idle, blocked };
});

const runtimeCounts = computed(() => {
  const counts = {
    queued: 0,
    running: 0,
    done: 0,
    failed: 0,
    canceled: 0,
  };
  workItems.value.forEach((wi) => {
    if (wi.status === "QUEUED") counts.queued += 1;
    else if (wi.status === "CLAIMED" || wi.status === "RUNNING") counts.running += 1;
    else if (wi.status === "DONE") counts.done += 1;
    else if (wi.status === "FAILED") counts.failed += 1;
    else if (wi.status === "CANCELED") counts.canceled += 1;
  });
  return counts;
});

const latestArtifacts = computed(() => {
  if (!latestRun.value?.id) return [];
  return artifacts.value.filter((artifact) => artifact.run_id === latestRun.value.id);
});

watch(
  projectId,
  () => {
    resetState();
    if (projectId.value) {
      primeContext();
      void loadAll();
    } else {
      error.value = "No project selected.";
    }
  },
  { immediate: true }
);

watch(hasRun, (present) => {
  if (!present && !loading.value && projectId.value) {
    router.replace(`/projects/${projectId.value}`);
  }
});

onBeforeUnmount(() => {
  stopPolling();
});

function resetState() {
  stopPolling();
  project.value = null;
  health.value = null;
  lifecycleScore.value = null;
  runs.value = [];
  workItems.value = [];
  runEvents.value = [];
  artifacts.value = [];
  error.value = "";
  artifactError.value = "";
  artifactDialogOpen.value = false;
  artifactExplainLoading.value = false;
  artifactExplainError.value = "";
  artifactExplainResult.value = null;
  createPrDialogOpen.value = false;
  createPrLoading.value = false;
  createPrError.value = "";
  createPrResult.value = null;
  selectedPrArtifact.value = null;
  createPrTitle.value = "";
  createPrBody.value = "";
  createPrBranch.value = "";
  forkDialogOpen.value = false;
  forkLoading.value = false;
  forkError.value = "";
  forkExecutor.value = "dummy";
  forkBranchName.value = "";
  forkNotes.value = "";
  forkStartNow.value = true;
  compareDialogOpen.value = false;
  compareLoading.value = false;
  compareError.value = "";
  compareResult.value = null;
  compareRunAId.value = "";
  compareRunBId.value = "";
}

function primeContext() {
  updateProjectContext({
    projectId: projectId.value,
    projectName: "Loading project...",
    stage: "UNKNOWN",
    runStatus: "IDLE",
    latestRunId: "",
    activeAgents: 0,
    hasActiveRun: false,
    architectureRefreshNeeded: false,
    planRefreshNeeded: false,
    testRefreshNeeded: false,
    updatedAt: new Date().toISOString(),
  });
}

function syncContext() {
  updateProjectContext({
    projectId: projectId.value,
    projectName: project.value?.name || "Project",
    stage: currentStage.value,
    runStatus: latestRun.value?.status || "IDLE",
    latestRunId: latestRun.value?.id || "",
    activeAgents: agentSnapshot.value.active,
    hasActiveRun: Boolean(latestRun.value?.id),
    architectureRefreshNeeded: false,
    planRefreshNeeded: false,
    testRefreshNeeded: false,
    updatedAt: new Date().toISOString(),
  });
}

async function loadAll() {
  if (!projectId.value.trim()) {
    error.value = "Project ID is required.";
    return;
  }
  error.value = "";
  loading.value = true;
  try {
    const [projectMeta, projectHealth, score, runList] = await Promise.all([
      fetchProjectMeta(projectId.value),
      fetchHealth(projectId.value),
      fetchLifecycleScore(projectId.value),
      listRuns(projectId.value),
    ]);
    project.value = projectMeta;
    health.value = projectHealth;
    lifecycleScore.value = score;
    runs.value = runList;
    await loadRunRuntime();
    syncContext();
    syncPolling();
  } catch (err: any) {
    error.value = err?.message || "Failed to load Mission Control data.";
  } finally {
    loading.value = false;
  }
}

async function loadRunRuntime() {
  if (!latestRun.value?.id) {
    workItems.value = [];
    runEvents.value = [];
    artifacts.value = [];
    return;
  }
  artifactError.value = "";
  const [items, events, projectArtifacts] = await Promise.all([
    listWorkItems(projectId.value, latestRun.value.id),
    listRunEvents(latestRun.value.id),
    listArtifacts(projectId.value),
  ]);
  workItems.value = items;
  runEvents.value = events;
  artifacts.value = Array.isArray(projectArtifacts) ? projectArtifacts : [];
}

async function refreshRuntime() {
  if (!projectId.value.trim() || pollInFlight) return;
  pollInFlight = true;
  try {
    runs.value = await listRuns(projectId.value);
    await loadRunRuntime();
    if (!["QUEUED", "RUNNING"].includes(latestRun.value?.status || "")) {
      const [projectHealth, score] = await Promise.all([
        fetchHealth(projectId.value),
        fetchLifecycleScore(projectId.value),
      ]);
      health.value = projectHealth;
      lifecycleScore.value = score;
    }
    syncContext();
    syncPolling();
  } catch (err: any) {
    error.value = err?.message || "Failed to refresh runtime data.";
    stopPolling();
  } finally {
    pollInFlight = false;
  }
}

function syncPolling() {
  const shouldPoll = ["QUEUED", "RUNNING"].includes(latestRun.value?.status || "");
  if (shouldPoll && pollHandle === null) {
    pollHandle = setInterval(() => {
      void refreshRuntime();
    }, 3000);
  } else if (!shouldPoll && pollHandle !== null) {
    stopPolling();
  }
}

function stopPolling() {
  if (pollHandle !== null) {
    clearInterval(pollHandle);
    pollHandle = null;
  }
}

async function cancelLatestRun() {
  if (!latestRun.value?.id || !cancelEnabled.value) return;
  error.value = "";
  try {
    await updateRunStatus(latestRun.value.id, "CANCELED");
    await loadAll();
  } catch (err: any) {
    error.value = err?.message || "Failed to cancel run.";
  }
}

function openForkDialog() {
  if (!latestRun.value?.id) return;
  forkDialogOpen.value = true;
  forkError.value = "";
  forkExecutor.value = latestRun.value.executor || "dummy";
  forkBranchName.value = latestRun.value.branch_name ? `${latestRun.value.branch_name}-fork` : "";
  forkNotes.value = "";
  forkStartNow.value = true;
}

async function submitForkRun() {
  if (!latestRun.value?.id) return;
  forkLoading.value = true;
  forkError.value = "";
  try {
    await forkRun(latestRun.value.id, {
      executor: forkExecutor.value || undefined,
      branch_name: forkBranchName.value.trim() || undefined,
      start_now: forkStartNow.value,
      summary_overrides: forkNotes.value.trim()
        ? {
            fork_notes: forkNotes.value.trim(),
          }
        : {},
    });
    forkDialogOpen.value = false;
    await loadAll();
  } catch (err: any) {
    forkError.value = err?.message || "Failed to fork run.";
  } finally {
    forkLoading.value = false;
  }
}

function comparisonDefaults() {
  const newest = runs.value[0];
  if (!newest) return { runA: "", runB: "" };
  const forkSource = newest.summary?.forked_from_run_id;
  if (forkSource && runs.value.some((run) => run.id === forkSource)) {
    return { runA: forkSource, runB: newest.id };
  }
  const forkedFromNewest = runs.value.find((run) => run.summary?.forked_from_run_id === newest.id);
  if (forkedFromNewest) {
    return { runA: newest.id, runB: forkedFromNewest.id };
  }
  return { runA: newest.id, runB: runs.value[1]?.id || "" };
}

function openCompareDialog() {
  if (!compareEnabled.value) return;
  const defaults = comparisonDefaults();
  compareDialogOpen.value = true;
  compareError.value = "";
  compareResult.value = null;
  compareRunAId.value = defaults.runA;
  compareRunBId.value = defaults.runB;
  if (compareRunAId.value && compareRunBId.value && compareRunAId.value !== compareRunBId.value) {
    void submitRunComparison();
  }
}

async function submitRunComparison() {
  if (!compareRunAId.value || !compareRunBId.value) return;
  compareLoading.value = true;
  compareError.value = "";
  try {
    compareResult.value = await compareRuns(compareRunAId.value, compareRunBId.value);
  } catch (err: any) {
    compareError.value = err?.message || "Failed to compare runs.";
  } finally {
    compareLoading.value = false;
  }
}

function goToOverview() {
  router.push(`/projects/${projectId.value}`);
}

async function openArtifactExplain(artifact: any) {
  artifactDialogOpen.value = true;
  artifactExplainLoading.value = true;
  artifactExplainError.value = "";
  artifactExplainResult.value = null;
  try {
    artifactExplainResult.value = await explainArtifact(projectId.value, artifact.id);
  } catch (err: any) {
    artifactExplainError.value = err?.message || "Failed to explain artifact.";
  } finally {
    artifactExplainLoading.value = false;
  }
}

function openCreatePrDialog(artifact: any) {
  selectedPrArtifact.value = artifact;
  createPrDialogOpen.value = true;
  createPrError.value = "";
  createPrResult.value = null;
  createPrTitle.value = `Agentic SDLC run ${latestRun.value?.id || ""}`;
  createPrBody.value = `Automated patch generated from run ${latestRun.value?.id || "unknown"}.`;
  createPrBranch.value = latestRun.value?.branch_name || "";
}

async function submitCreatePr() {
  if (!latestRun.value?.id || !selectedPrArtifact.value?.id) return;
  createPrLoading.value = true;
  createPrError.value = "";
  try {
    createPrResult.value = await createRunPullRequest(latestRun.value.id, {
      artifact_id: selectedPrArtifact.value.id,
      title: createPrTitle.value.trim() || undefined,
      body: createPrBody.value.trim() || undefined,
      branch_name: createPrBranch.value.trim() || undefined,
    });
    await loadAll();
  } catch (err: any) {
    createPrError.value = err?.message || "Failed to create pull request.";
  } finally {
    createPrLoading.value = false;
  }
}

function formatTimestamp(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString();
}

function runStatusTagType(status?: string | null) {
  if (status === "RUNNING") return "warning";
  if (status === "COMPLETED") return "success";
  if (status === "FAILED" || status === "CANCELED") return "danger";
  if (status === "QUEUED") return "info";
  return "default";
}

function workspaceStatusTagType(status?: string | null) {
  if (status === "SEEDED") return "success";
  if (status === "READY") return "info";
  if (status === "ERROR") return "danger";
  return "warning";
}

function workItemStatusTagType(status?: string | null) {
  if (status === "RUNNING" || status === "CLAIMED") return "warning";
  if (status === "DONE") return "success";
  if (status === "FAILED" || status === "CANCELED") return "danger";
  if (status === "QUEUED") return "info";
  return "default";
}

function panelStatusFor(status?: string | null) {
  if (status === "RUNNING" || status === "CLAIMED") return "Running";
  if (status === "DONE") return "Completed";
  if (status === "FAILED" || status === "CANCELED") return "Blocked";
  return "Waiting";
}

function normalizeTimelineStatus(status?: string | null) {
  if (status === "QUEUED") return "PENDING";
  if (status === "CLAIMED" || status === "RUNNING") return "RUNNING";
  if (status === "DONE") return "DONE";
  if (status === "FAILED") return "FAILED";
  if (status === "CANCELED") return "CANCELED";
  return status || "PENDING";
}

function mapEventMessage(eventType: string, title?: string) {
  const itemTitle = title || "Work item";
  if (eventType === "RUN_CREATED") return "Run created";
  if (eventType === "RUN_RUNNING") return "Run started";
  if (eventType === "RUN_COMPLETED") return "Run completed";
  if (eventType === "RUN_FAILED") return "Run failed";
  if (eventType === "RUN_CANCELED") return "Run canceled";
  if (eventType === "RUN_FORKED") return "Run forked";
  if (eventType === "WORK_DAG_CREATED") return "Work DAG created";
  if (eventType === "WORK_ITEM_CREATED") return `Task ${itemTitle} created`;
  if (eventType === "WORK_ITEM_CLAIMED") return `Task ${itemTitle} claimed`;
  if (eventType === "WORK_ITEM_STARTED") return `Task ${itemTitle} started`;
  if (eventType === "WORK_ITEM_DONE") return `Task ${itemTitle} completed`;
  if (eventType === "WORK_ITEM_FAILED") return `Task ${itemTitle} failed`;
  if (eventType === "WORK_ITEM_LEASE_EXPIRED") return `Task ${itemTitle} lease expired`;
  if (eventType === "WORK_ITEM_RETRIED") return `Task ${itemTitle} retried`;
  if (eventType === "LIFECYCLE_SCORED") return "Lifecycle score updated";
  return humanizeToken(eventType);
}

function humanizeToken(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function runOptionLabel(run: any) {
  return `${String(run.id).slice(0, 8)} · ${run.status} · ${run.executor}`;
}

function comparisonSummaryLabel(runId?: string | null) {
  if (!runId) return "—";
  if (runId === compareResult.value?.run_a?.id) return "Run A";
  if (runId === compareResult.value?.run_b?.id) return "Run B";
  return runId;
}

function formatElapsed(seconds?: number | null) {
  if (typeof seconds !== "number") return "—";
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}m ${remainder}s`;
}

function shortenUri(uri?: string | null) {
  if (!uri) return "—";
  if (uri.length <= 52) return uri;
  return `...${uri.slice(-49)}`;
}

function shortenPath(path?: string | null) {
  if (!path) return "—";
  if (path.length <= 56) return path;
  return `...${path.slice(-53)}`;
}

function artifactWorkItemLabel(workItemId?: string | null) {
  if (!workItemId) return "—";
  const item = displayWorkItems.value.find((entry) => entry.task_id === workItemId);
  return item?.title || workItemId;
}

function artifactIntentText(explainResult: any) {
  const semantics = explainResult?.context?.root?.meta?.semantics || {};
  const summary = explainResult?.context?.root?.meta?.summary;
  return semantics.intent || summary || "Artifact recorded with lineage context.";
}
</script>
