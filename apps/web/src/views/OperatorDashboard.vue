<template>
  <div v-if="projectId" class="page-stack operator-dashboard-page">
    <section class="premium-hero operator-hero">
      <div class="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
        <div class="max-w-3xl">
          <div class="premium-hero__eyebrow">AI Engineering Operator</div>
          <h1 class="premium-hero__title">Assign work, watch execution, and review outcomes from one control center.</h1>
          <p class="premium-hero__copy">
            This dashboard turns the platform into an operator workbench: tasks on the left, active runs in flight, transparent execution narrative, and the repository map that keeps edits grounded.
          </p>
          <div class="mt-5 flex flex-wrap gap-2">
            <span class="topbar-chip">
              <AppIcon name="project" size="sm" />
              {{ project?.name || "Loading project…" }}
            </span>
            <span class="topbar-chip">
              <AppIcon name="status" size="sm" />
              {{ project?.current_stage || "UNKNOWN" }}
            </span>
            <span class="topbar-chip">
              <AppIcon name="runs" size="sm" />
              {{ selectedRun?.status || latestRun?.status || "IDLE" }}
            </span>
            <span class="topbar-chip">
              <AppIcon name="branch" size="sm" />
              {{ projectRepo?.repo_full_name || repoMap?.repo_full_name || "Repo not connected" }}
            </span>
          </div>
        </div>
        <div class="operator-hero__controls">
          <el-button :loading="loading" @click="loadDashboard">Refresh</el-button>
          <el-button plain :disabled="!projectId" @click="goToMissionControl">Execution View</el-button>
          <el-button plain :disabled="!projectId" @click="goToAutomationMap">Repository Map</el-button>
          <el-button plain :disabled="!selectedRunId" @click="goToRuns">Open Run Viewer</el-button>
          <el-button type="primary" :disabled="!projectId" @click="goToOverview">Project Overview</el-button>
        </div>
      </div>
    </section>

    <div v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
      {{ error }}
    </div>

    <section class="surface-grid md:grid-cols-2 xl:grid-cols-4">
      <MetricCard
        label="Task Board"
        :value="taskBoardCount"
        :detail="`${openTaskCount} open · ${completedTaskCount} completed`"
        tone="warning"
      >
        <template #icon><AppIcon name="requirements" size="lg" /></template>
      </MetricCard>
      <MetricCard
        label="Runs"
        :value="runs.length"
        :detail="`${activeRunCount} active · ${completedRunCount} completed`"
        :tone="activeRunCount ? 'warning' : 'neutral'"
      >
        <template #icon><AppIcon name="runs" size="lg" /></template>
      </MetricCard>
      <MetricCard
        label="Repository Map"
        :value="repoMap?.total_files ?? 0"
        :detail="`${repoMap?.directories?.length || 0} directories · ${repoMap?.top_features?.length || 0} focus areas`"
        tone="success"
      >
        <template #icon><AppIcon name="map" size="lg" /></template>
      </MetricCard>
      <MetricCard
        label="Workers"
        :value="workerSummary.active"
        :detail="`${workerSummary.idle} idle · ${workerSummary.stale} stale`"
        :tone="workerSummary.active ? 'success' : 'neutral'"
      >
        <template #icon><AppIcon name="mission" size="lg" /></template>
      </MetricCard>
    </section>

    <section class="operator-dashboard-grid">
      <div class="premium-card operator-panel p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Tasks</div>
            <div class="text-xs text-slate-500">
              Developers assign work here. The AI turns these into governed runs with reviewable outcomes.
            </div>
          </div>
          <el-tag effect="light" type="warning">{{ taskBoardCount }} live</el-tag>
        </div>
        <div class="mt-4 grid gap-3">
          <button
            v-for="task in visibleTasks"
            :key="task.key"
            type="button"
            class="operator-row-card"
            @click="openTaskTarget(task)"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="text-sm font-semibold text-slate-900">{{ task.title }}</span>
                  <el-tag size="small" effect="light" :type="task.tagType">{{ task.status }}</el-tag>
                  <el-tag size="small" effect="light" type="info">{{ task.kind }}</el-tag>
                </div>
                <div v-if="task.summary" class="mt-2 text-sm text-slate-600">{{ task.summary }}</div>
                <div class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                  <span v-if="task.metaA">{{ task.metaA }}</span>
                  <span v-if="task.metaB">{{ task.metaB }}</span>
                </div>
              </div>
              <span class="topbar-chip">{{ task.actionLabel }}</span>
            </div>
          </button>
          <div v-if="!visibleTasks.length" class="premium-empty">
            No tasks or intake signals yet. Create tasks from Project Overview to populate the board.
          </div>
        </div>
      </div>

      <div class="premium-card operator-panel p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Runs</div>
            <div class="text-xs text-slate-500">
              Watch the AI attempt each task, including runtime status, branch, and current delivery state.
            </div>
          </div>
          <el-tag effect="light" type="info">{{ runs.length }} total</el-tag>
        </div>
        <div class="mt-4 grid gap-3">
          <button
            v-for="run in visibleRuns"
            :key="run.id"
            type="button"
            class="operator-row-card"
            :class="{ 'is-selected': selectedRunId === run.id }"
            @click="selectRun(run.id)"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="font-mono text-sm text-slate-900">{{ shortenId(run.id) }}</span>
                  <el-tag size="small" effect="light" :type="runStatusTagType(run.status)">{{ run.status }}</el-tag>
                  <span class="text-xs text-slate-500">{{ run.executor || "executor unavailable" }}</span>
                </div>
                <div class="mt-2 text-sm text-slate-600">{{ run.summary?.goal_text || "No goal summary recorded." }}</div>
                <div class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                  <span>Branch {{ run.branch_name || "—" }}</span>
                  <span>Workspace {{ run.workspace_status || "PENDING" }}</span>
                  <span>{{ formatTimestamp(run.started_at) }}</span>
                </div>
              </div>
              <span class="topbar-chip">{{ run.summary?.artifact_count ?? 0 }} artifacts</span>
            </div>
          </button>
          <div v-if="!visibleRuns.length" class="premium-empty">
            No runs yet. Start a run from Project Overview or Mission Control.
          </div>
        </div>
      </div>
    </section>

    <section class="operator-dashboard-grid operator-dashboard-grid--narrative">
      <div class="premium-card operator-panel p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Execution View</div>
            <div class="text-xs text-slate-500">
              Transparent execution narrative showing what the AI looked at, changed, verified, and delivered.
            </div>
          </div>
          <div class="flex flex-wrap gap-2">
            <span class="topbar-chip">{{ selectedTimeline?.steps?.length || 0 }} steps</span>
            <span v-if="selectedRunMetrics.confidenceLabel" class="topbar-chip">
              Confidence {{ selectedRunMetrics.confidenceLabel }}
            </span>
          </div>
        </div>

        <div v-if="selectedRun" class="mt-4 operator-metric-strip">
          <div class="operator-inline-metric">
            <span class="operator-inline-metric__label">Files inspected</span>
            <span class="operator-inline-metric__value">{{ selectedRunMetrics.filesInspected }}</span>
          </div>
          <div class="operator-inline-metric">
            <span class="operator-inline-metric__label">Files modified</span>
            <span class="operator-inline-metric__value">{{ selectedRunMetrics.filesModified }}</span>
          </div>
          <div class="operator-inline-metric">
            <span class="operator-inline-metric__label">Tests / verifications</span>
            <span class="operator-inline-metric__value">{{ selectedRunMetrics.verificationSteps }}</span>
          </div>
          <div class="operator-inline-metric">
            <span class="operator-inline-metric__label">Execution time</span>
            <span class="operator-inline-metric__value">{{ selectedRunMetrics.elapsed }}</span>
          </div>
        </div>

        <div v-if="selectedTimeline?.steps?.length" class="mt-4 space-y-3">
          <div v-for="step in selectedTimeline.steps.slice(0, 7)" :key="step.id" class="operator-narrative-step">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <el-tag size="small" effect="light" :type="timelineStepTagType(step.status)">{{ step.status }}</el-tag>
                  <span class="text-sm font-semibold text-slate-900">{{ step.title }}</span>
                </div>
                <div v-if="step.message" class="mt-2 text-sm text-slate-600">{{ step.message }}</div>
                <div class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                  <span v-if="step.work_item_type">Work item {{ step.work_item_type }}</span>
                  <span v-if="step.artifact_type">Artifact {{ step.artifact_type }}</span>
                  <span>{{ formatTimestamp(step.ts) }}</span>
                </div>
                <div v-if="step.changed_files?.length" class="mt-3 flex flex-wrap gap-2">
                  <span v-for="file in step.changed_files" :key="`${step.id}-${file}`" class="topbar-chip">{{ file }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="premium-empty mt-4">
          Select a run to inspect its execution narrative.
        </div>

        <div class="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-xs uppercase tracking-wide text-slate-400">Diff Viewer</div>
              <div class="mt-1 text-xs text-slate-500">
                Review the latest patch before approving or routing to a pull request.
              </div>
            </div>
            <a
              v-if="selectedRunMetrics.pullRequestUrl"
              :href="selectedRunMetrics.pullRequestUrl"
              target="_blank"
              rel="noreferrer"
              class="topbar-chip"
            >
              PR Link
            </a>
          </div>
          <div v-if="selectedDiffFile" class="mt-4 space-y-3">
            <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span class="topbar-chip">{{ selectedDiffFile.path }}</span>
              <span>{{ selectedDiffFile.additions }} additions</span>
              <span>{{ selectedDiffFile.deletions }} deletions</span>
            </div>
            <pre class="operator-diff-preview">{{ selectedDiffFile.patch || "No patch content available." }}</pre>
          </div>
          <div v-else class="mt-4 text-sm text-slate-500">
            No patch artifact preview is available for the selected run yet.
          </div>
        </div>
      </div>

      <div class="space-y-4">
        <div class="premium-card operator-panel p-6">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-sm uppercase tracking-wide text-slate-400">Repository Map</div>
              <div class="text-xs text-slate-500">
                Keep the AI grounded in the architecture: subsystems, directories, top files, and mapped features.
              </div>
            </div>
            <el-tag effect="light" type="success">{{ repoMap?.source_type || "workspace" }}</el-tag>
          </div>
          <div v-if="repoMap" class="mt-4 space-y-4">
            <div>
              <div class="text-xs uppercase tracking-wide text-slate-400">Top Features</div>
              <div class="mt-3 flex flex-wrap gap-2">
                <span v-for="feature in repoMap.top_features.slice(0, 8)" :key="feature" class="topbar-chip">{{ feature }}</span>
                <span v-if="!repoMap.top_features.length" class="text-sm text-slate-500">No feature hints available yet.</span>
              </div>
            </div>
            <div>
              <div class="text-xs uppercase tracking-wide text-slate-400">Subsystems</div>
              <div class="mt-3 grid gap-2">
                <div v-for="directory in repoMap.directories.slice(0, 8)" :key="directory" class="operator-subsystem-row">
                  <span class="font-mono text-xs text-slate-700">{{ directory }}</span>
                  <span class="text-xs text-slate-400">active path</span>
                </div>
              </div>
            </div>
            <div>
              <div class="text-xs uppercase tracking-wide text-slate-400">High-signal files</div>
              <div class="mt-3 grid gap-3">
                <div v-for="file in repoMap.files.slice(0, 6)" :key="file.path" class="operator-file-card">
                  <div class="flex items-center justify-between gap-3">
                    <span class="font-mono text-xs text-slate-800">{{ file.path }}</span>
                    <span class="topbar-chip">{{ file.kind }}</span>
                  </div>
                  <div class="mt-2 text-sm text-slate-600">{{ file.summary }}</div>
                  <div v-if="file.symbols?.length" class="mt-3 flex flex-wrap gap-2">
                    <span v-for="symbol in file.symbols.slice(0, 4)" :key="`${file.path}-${symbol}`" class="topbar-chip">{{ symbol }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="premium-empty mt-4">
            Repo map unavailable. Connect a repo and run a repo-backed execution to populate architecture context.
          </div>
        </div>

        <div class="premium-card operator-panel p-6">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-sm uppercase tracking-wide text-slate-400">Preview Delivery</div>
              <div class="text-xs text-slate-500">
                Governed preview launch from the selected run workspace. Configure once per project, then launch verified previews on demand.
              </div>
            </div>
            <div class="flex gap-2">
              <el-tag effect="light" :type="previewProfile?.enabled ? 'success' : 'warning'">
                {{ previewProfile?.enabled ? "PROFILE READY" : "PROFILE NEEDED" }}
              </el-tag>
              <el-button plain size="small" @click="openPreviewProfileDialog">
                {{ previewProfile ? "Edit Profile" : "Configure" }}
              </el-button>
            </div>
          </div>
          <div class="mt-4 space-y-3 text-sm text-slate-600">
            <div><strong>Run:</strong> {{ selectedRun ? shortenId(selectedRun.id) : "—" }}</div>
            <div><strong>Status:</strong> {{ selectedRunPreview?.status || "NOT_CONFIGURED" }}</div>
            <div><strong>Mode:</strong> {{ selectedRunPreview?.mode || previewProfile?.mode || "local" }}</div>
            <div v-if="selectedRunPreview?.frontend?.url"><strong>Frontend:</strong> <a :href="selectedRunPreview.frontend.url" target="_blank" rel="noreferrer" class="underline">{{ selectedRunPreview.frontend.url }}</a></div>
            <div v-if="selectedRunPreview?.backend?.url"><strong>Backend:</strong> <a :href="selectedRunPreview.backend.url" target="_blank" rel="noreferrer" class="underline">{{ selectedRunPreview.backend.url }}</a></div>
            <div v-if="selectedRunPreview?.frontend?.log_path"><strong>Frontend log:</strong> <span class="font-mono text-xs">{{ selectedRunPreview.frontend.log_path }}</span></div>
            <div v-if="selectedRunPreview?.backend?.log_path"><strong>Backend log:</strong> <span class="font-mono text-xs">{{ selectedRunPreview.backend.log_path }}</span></div>
            <div v-if="selectedRunPreview?.expires_at"><strong>Expires:</strong> {{ formatTimestamp(selectedRunPreview.expires_at) }}</div>
            <div v-if="selectedRunPreview?.verification_note" class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              {{ selectedRunPreview.verification_note }}
            </div>
            <div v-if="previewLaunchError || previewProfileError" class="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              {{ previewLaunchError || previewProfileError }}
            </div>
            <div class="flex flex-wrap gap-2 pt-1">
              <el-button
                type="primary"
                size="small"
                :loading="previewLaunchLoading"
                :disabled="!selectedRun?.id || !previewProfile?.enabled || Boolean(selectedRunPreview?.requires_verification)"
                @click="startSelectedRunPreview"
              >
                {{ selectedRunPreview?.preview_url ? "Refresh Preview" : "Launch Preview" }}
              </el-button>
              <el-button
                plain
                size="small"
                type="danger"
                :loading="previewLaunchLoading"
                :disabled="!selectedRun?.id || !['STARTING', 'READY', 'FAILED', 'STOPPED'].includes(selectedRunPreview?.status || '')"
                @click="stopSelectedRunPreview"
              >
                Stop Preview
              </el-button>
              <el-button plain size="small" :disabled="!selectedRunPreview?.frontend?.url" @click="openExternal(selectedRunPreview?.frontend?.url)">
                Open Frontend
              </el-button>
              <el-button plain size="small" :disabled="!selectedRunPreview?.backend?.url" @click="openExternal(selectedRunPreview?.backend?.url)">
                Open Backend
              </el-button>
            </div>
          </div>
        </div>

        <div class="premium-card operator-panel p-6">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-sm uppercase tracking-wide text-slate-400">Memory + Workers</div>
              <div class="text-xs text-slate-500">
                Surface similar historical runs and the worker pool handling current automation.
              </div>
            </div>
          </div>
          <div class="mt-4 space-y-4">
            <div>
              <div class="text-xs uppercase tracking-wide text-slate-400">Similar Past Runs</div>
              <div v-if="similarRuns.length" class="mt-3 grid gap-3">
                <div v-for="match in similarRuns.slice(0, 3)" :key="match.run_id" class="operator-memory-card">
                  <div class="flex items-center justify-between gap-3">
                    <span class="font-mono text-xs text-slate-900">{{ shortenId(match.run_id) }}</span>
                    <el-tag size="small" effect="light" :type="runStatusTagType(match.status)">{{ match.status }}</el-tag>
                  </div>
                  <div class="mt-2 text-sm text-slate-600">{{ match.goal_text || "No goal summary" }}</div>
                  <div class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                    <span>Recoveries {{ match.recovery_count ?? 0 }}</span>
                    <span>Score {{ formatSimilarity(match.score) }}</span>
                  </div>
                </div>
              </div>
              <div v-else class="mt-3 text-sm text-slate-500">No similar runs surfaced yet.</div>
            </div>

            <div>
              <div class="text-xs uppercase tracking-wide text-slate-400">Workers</div>
              <div v-if="workers.length" class="mt-3 grid gap-3">
                <div v-for="worker in workers.slice(0, 4)" :key="worker.id" class="operator-worker-row">
                  <div>
                    <div class="text-sm font-semibold text-slate-900">{{ worker.name }}</div>
                    <div class="mt-1 text-xs text-slate-500">{{ worker.executors?.join(", ") || "No executors recorded" }}</div>
                  </div>
                  <div class="text-right">
                    <el-tag size="small" effect="light" :type="workerStatusTagType(worker)">{{ workerStatusLabel(worker) }}</el-tag>
                    <div class="mt-1 text-[11px] text-slate-400">{{ formatTimestamp(worker.last_heartbeat_at) }}</div>
                  </div>
                </div>
              </div>
              <div v-else class="mt-3 text-sm text-slate-500">No registered workers reported yet.</div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <el-dialog v-model="previewProfileDialogOpen" title="Preview Profile" width="720px">
      <div class="grid gap-4 md:grid-cols-2">
        <div class="space-y-2">
          <div class="text-xs uppercase tracking-wide text-slate-400">Roots</div>
          <el-input v-model="previewForm.frontend_root" placeholder="Frontend root (e.g. apps/web)" />
          <el-input v-model="previewForm.backend_root" placeholder="Backend root (e.g. apps/api)" />
        </div>
        <div class="space-y-2">
          <div class="text-xs uppercase tracking-wide text-slate-400">TTL + Health</div>
          <el-input-number v-model="previewForm.ttl_hours" :min="1" :max="168" />
          <el-input v-model="previewForm.frontend_healthcheck_path" placeholder="Frontend health path" />
          <el-input v-model="previewForm.backend_healthcheck_path" placeholder="Backend health path" />
        </div>
        <div class="space-y-2">
          <div class="text-xs uppercase tracking-wide text-slate-400">Build Commands</div>
          <el-input v-model="previewForm.frontend_build_command" placeholder="npm run build" />
          <el-input v-model="previewForm.backend_build_command" placeholder="pytest -q" />
        </div>
        <div class="space-y-2">
          <div class="text-xs uppercase tracking-wide text-slate-400">Start Commands</div>
          <el-input v-model="previewForm.frontend_start_command" placeholder="npm run dev -- --host $HOST --port $PORT" />
          <el-input v-model="previewForm.backend_start_command" placeholder="uvicorn app.main:app --host $HOST --port $PORT" />
        </div>
      </div>
      <div v-if="previewProfileError" class="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
        {{ previewProfileError }}
      </div>
      <template #footer>
        <div class="flex items-center justify-between gap-3">
          <el-switch v-model="previewForm.enabled" active-text="Enabled" inactive-text="Disabled" />
          <div class="flex gap-2">
            <el-button @click="previewProfileDialogOpen = false">Cancel</el-button>
            <el-button type="primary" :loading="previewProfileSaving" @click="savePreviewProfile">Save Profile</el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppIcon from "../components/AppIcon.vue";
import MetricCard from "../components/MetricCard.vue";
import {
  deleteRunPreview,
  fetchArtifactDiff,
  fetchMissionControlOverview,
  fetchProjectMeta,
  fetchProjectPreviewProfile,
  fetchProjectRepo,
  fetchRepoMap,
  fetchRunPreview,
  fetchRunTimeline,
  findSimilarRuns,
  hasRunMemorySearchContext,
  launchRunPreview,
  listRuns,
  listTasks,
  saveProjectPreviewProfile,
} from "../api/lifecycle";
import { updateProjectContext } from "../state/projectContext";

type MissionControlOverview = {
  work_intake?: any[];
  recent_runs?: any[];
  latest_change_impact?: any | null;
  previews_and_prs?: any | null;
  strategy_learning?: any[];
  system_insights?: any | null;
};

type RepoMapFile = {
  path: string;
  kind: string;
  summary: string;
  symbols?: string[];
  features?: string[];
};

type RepoMapResponse = {
  source_type: string;
  repo_root: string;
  repo_full_name?: string | null;
  branch_name?: string | null;
  total_files: number;
  directories: string[];
  top_features: string[];
  files: RepoMapFile[];
};

type RunTimelineResponse = {
  run: any;
  summary: {
    status: string;
    executor: string;
    branch_name?: string | null;
    workspace_status: string;
    elapsed_seconds?: number | null;
    recovery_count: number;
    artifact_count: number;
    changed_files: string[];
    primary_error?: string | null;
    pull_request_url?: string | null;
  };
  steps: Array<{
    id: string;
    kind: string;
    ts?: string | null;
    title: string;
    status: string;
    message?: string | null;
    work_item_type?: string | null;
    artifact_type?: string | null;
    changed_files?: string[];
  }>;
};

type ArtifactDiffFile = {
  path: string;
  additions: number;
  deletions: number;
  patch: string;
};

type ArtifactDiffResponse = {
  files: ArtifactDiffFile[];
  additions: number;
  deletions: number;
  file_count: number;
};

type AgentRecord = {
  id: string;
  name: string;
  kind: string;
  executors: string[];
  status: string;
  last_heartbeat_at?: string | null;
};

type PreviewProfileRecord = {
  enabled: boolean;
  mode?: string;
  frontend_root?: string | null;
  backend_root?: string | null;
  frontend_build_command?: string | null;
  backend_build_command?: string | null;
  frontend_start_command?: string | null;
  backend_start_command?: string | null;
  frontend_healthcheck_path?: string | null;
  backend_healthcheck_path?: string | null;
  ttl_hours?: number;
};

type RunPreviewRecord = {
  status: string;
  mode?: string;
  preview_url?: string | null;
  frontend?: { url?: string | null; status?: string | null; log_path?: string | null } | null;
  backend?: { url?: string | null; status?: string | null; log_path?: string | null } | null;
  expires_at?: string | null;
  requires_verification?: boolean;
  verification_note?: string | null;
  profile_configured?: boolean;
  repository_connected?: boolean;
};

const route = useRoute();
const router = useRouter();

const projectId = computed(() => String(route.params.projectId || ""));

const loading = ref(false);
const error = ref("");
const project = ref<any | null>(null);
const tasks = ref<any[]>([]);
const runs = ref<any[]>([]);
const overview = ref<MissionControlOverview | null>(null);
const repoMap = ref<RepoMapResponse | null>(null);
const projectRepo = ref<any | null>(null);
const previewProfile = ref<PreviewProfileRecord | null>(null);
const previewProfileDialogOpen = ref(false);
const previewProfileSaving = ref(false);
const previewProfileError = ref("");
const previewLaunchLoading = ref(false);
const previewLaunchError = ref("");
const selectedRunPreview = ref<RunPreviewRecord | null>(null);
const workers = ref<AgentRecord[]>([]);
const selectedRunId = ref("");
const selectedTimeline = ref<RunTimelineResponse | null>(null);
const selectedDiff = ref<ArtifactDiffResponse | null>(null);
const similarRuns = ref<any[]>([]);
const previewForm = ref<PreviewProfileRecord>({
  enabled: true,
  mode: "local",
  frontend_root: "",
  backend_root: "",
  frontend_build_command: "",
  backend_build_command: "",
  frontend_start_command: "",
  backend_start_command: "",
  frontend_healthcheck_path: "/",
  backend_healthcheck_path: "/",
  ttl_hours: 24,
});

const latestRun = computed(() => runs.value[0] || null);
const selectedRun = computed(() => runs.value.find((run) => run.id === selectedRunId.value) || latestRun.value || null);
const overviewRuns = computed(() => overview.value?.recent_runs || []);
const intakeItems = computed(() => overview.value?.work_intake || []);

const taskBoardCount = computed(() => tasks.value.length + intakeItems.value.length);
const openTaskCount = computed(
  () => tasks.value.filter((task) => !["DONE", "COMPLETED", "CANCELED"].includes(String(task.status || "").toUpperCase())).length + intakeItems.value.length
);
const completedTaskCount = computed(
  () => tasks.value.filter((task) => ["DONE", "COMPLETED"].includes(String(task.status || "").toUpperCase())).length
);
const activeRunCount = computed(() => runs.value.filter((run) => ["RUNNING", "QUEUED"].includes(String(run.status || "").toUpperCase())).length);
const completedRunCount = computed(() => runs.value.filter((run) => String(run.status || "").toUpperCase() === "COMPLETED").length);

const visibleTasks = computed(() => {
  const taskRows = tasks.value.slice(0, 4).map((task) => ({
    key: `task-${task.id}`,
    title: task.title || task.key || "Untitled task",
    summary: task.description || null,
    status: task.status || "OPEN",
    tagType: taskStatusTagType(task.status),
    kind: task.category || task.stage || "Task",
    metaA: task.assignee ? `Assignee ${task.assignee}` : task.stage ? `Stage ${task.stage}` : null,
    metaB: task.source ? `Source ${task.source}` : null,
    actionLabel: "Open",
    path: `/projects/${projectId.value}`,
  }));
  const intakeRows = intakeItems.value.slice(0, Math.max(0, 4 - taskRows.length)).map((item: any) => ({
    key: `intake-${item.id}`,
    title: item.title,
    summary: item.summary || null,
    status: item.risk_tier || "INTAKE",
    tagType: riskTagType(item.risk_tier),
    kind: item.kind || "Intake",
    metaA: item.predicted_modules?.length ? `Modules ${item.predicted_modules.slice(0, 2).join(", ")}` : null,
    metaB: item.predicted_files?.length ? `Files ${item.predicted_files.slice(0, 2).join(", ")}` : null,
    actionLabel: "Review",
    path: `/projects/${projectId.value}/run`,
  }));
  return [...taskRows, ...intakeRows];
});

const visibleRuns = computed(() => runs.value.slice(0, 5));

const selectedRunCard = computed(() => overviewRuns.value.find((run: any) => run.run_id === selectedRunId.value || run.run_id === selectedRun.value?.id) || null);
const selectedDiffFile = computed(() => selectedDiff.value?.files?.[0] || null);
const selectedRunMetrics = computed(() => {
  const timeline = selectedTimeline.value;
  const inspected = new Set<string>();
  const verificationSteps = timeline?.steps?.filter((step) => {
    const title = `${step.title} ${step.message || ""}`.toLowerCase();
    return title.includes("test") || title.includes("build") || title.includes("lint") || title.includes("verify");
  }).length || 0;
  for (const step of timeline?.steps || []) {
    for (const file of step.changed_files || []) {
      inspected.add(file);
    }
  }
  for (const file of timeline?.summary?.changed_files || []) {
    inspected.add(file);
  }
  const confidence = selectedRunCard.value?.confidence_score;
  return {
    filesInspected: inspected.size || 0,
    filesModified: timeline?.summary?.changed_files?.length || selectedDiff.value?.file_count || 0,
    verificationSteps,
    elapsed: formatElapsed(timeline?.summary?.elapsed_seconds),
    pullRequestUrl: timeline?.summary?.pull_request_url || selectedRunCard.value?.pull_request_url || null,
    confidenceLabel: typeof confidence === "number" ? `${Math.round(confidence * 100)}%` : "",
  };
});

const workerSummary = computed(() => {
  const now = Date.now();
  let active = 0;
  let idle = 0;
  let stale = 0;
  for (const worker of workers.value) {
    const hb = worker.last_heartbeat_at ? new Date(worker.last_heartbeat_at).getTime() : 0;
    if (!hb || Number.isNaN(hb) || now - hb > 60_000) {
      stale += 1;
      continue;
    }
    if ((worker.status || "").toUpperCase() === "ACTIVE") active += 1;
    else idle += 1;
  }
  return { active, idle, stale };
});

watch(projectId, () => {
  if (!projectId.value) return;
  void loadDashboard();
}, { immediate: true });

watch(selectedRunId, () => {
  if (!selectedRunId.value) return;
  void loadRunDetail(selectedRunId.value);
});

onMounted(() => {
  if (projectId.value) void loadDashboard();
});

async function loadDashboard() {
  if (!projectId.value) return;
  loading.value = true;
  error.value = "";
  try {
    const [projectResp, taskResp, runResp, overviewResp, repoMapResp, repoResp, profileResp] = await Promise.all([
      fetchProjectMeta(projectId.value),
      listTasks(projectId.value).catch(() => []),
      listRuns(projectId.value).catch(() => []),
      fetchMissionControlOverview(projectId.value).catch(() => null),
      fetchRepoMap(projectId.value),
      fetchProjectRepo(projectId.value),
      fetchProjectPreviewProfile(projectId.value),
    ]);

    project.value = projectResp;
    tasks.value = Array.isArray(taskResp) ? taskResp : [];
    runs.value = Array.isArray(runResp) ? runResp : [];
    overview.value = overviewResp;
    repoMap.value = repoMapResp || null;
    projectRepo.value = repoResp || null;
    previewProfile.value = profileResp || null;
    workers.value = [];
    previewProfileError.value = "";

    updateProjectContext({
      projectId: projectResp.id,
      projectName: projectResp.name,
      stage: projectResp.current_stage || "UNKNOWN",
      runStatus: runs.value[0]?.status || "IDLE",
      latestRunId: runs.value[0]?.id || "",
      activeAgents: workerSummary.value.active,
      hasActiveRun: ["RUNNING", "QUEUED"].includes(String(runs.value[0]?.status || "").toUpperCase()),
      updatedAt: new Date().toISOString(),
    });

    if (!selectedRunId.value && runs.value.length) {
      selectedRunId.value = runs.value[0].id;
    } else if (selectedRunId.value) {
      await loadRunDetail(selectedRunId.value);
    }
  } catch (err: any) {
    error.value = err?.message || "Failed to load operator dashboard.";
  } finally {
    loading.value = false;
  }
}

async function loadRunDetail(runId: string) {
  if (!projectId.value || !runId) return;
  try {
    const [timeline, preview] = await Promise.all([
      fetchRunTimeline(runId),
      fetchRunPreview(runId).catch(() => null),
    ]);
    selectedTimeline.value = timeline;
    selectedRunPreview.value = preview;
    previewLaunchError.value = "";
    const runCard = overviewRuns.value.find((run: any) => run.run_id === runId);
    if (runCard?.patch_artifact?.id) {
      selectedDiff.value = await fetchArtifactDiff(projectId.value, runCard.patch_artifact.id);
    } else {
      selectedDiff.value = null;
    }
    const memoryQuery = {
      goal: timeline?.summary?.goal_text || "",
      error: timeline?.summary?.primary_error || "",
      files: timeline?.summary?.changed_files || [],
    };
    if (hasRunMemorySearchContext(memoryQuery)) {
      similarRuns.value = await findSimilarRuns(projectId.value, {
        ...memoryQuery,
        limit: 3,
      }).catch(() => []);
    } else {
      similarRuns.value = [];
    }
  } catch (err: any) {
    selectedTimeline.value = null;
    selectedRunPreview.value = null;
    selectedDiff.value = null;
    similarRuns.value = [];
    error.value = err?.message || "Failed to load run detail.";
  }
}

function openPreviewProfileDialog() {
  const profile = previewProfile.value;
  previewForm.value = {
    enabled: profile?.enabled ?? true,
    mode: profile?.mode || "local",
    frontend_root: profile?.frontend_root || "",
    backend_root: profile?.backend_root || "",
    frontend_build_command: profile?.frontend_build_command || "",
    backend_build_command: profile?.backend_build_command || "",
    frontend_start_command: profile?.frontend_start_command || "",
    backend_start_command: profile?.backend_start_command || "",
    frontend_healthcheck_path: profile?.frontend_healthcheck_path || "/",
    backend_healthcheck_path: profile?.backend_healthcheck_path || "/",
    ttl_hours: profile?.ttl_hours || 24,
  };
  previewProfileError.value = "";
  previewProfileDialogOpen.value = true;
}

async function savePreviewProfile() {
  if (!projectId.value) return;
  previewProfileSaving.value = true;
  previewProfileError.value = "";
  try {
    previewProfile.value = await saveProjectPreviewProfile(projectId.value, {
      enabled: previewForm.value.enabled,
      mode: previewForm.value.mode || "local",
      frontend_root: normalizeBlank(previewForm.value.frontend_root),
      backend_root: normalizeBlank(previewForm.value.backend_root),
      frontend_build_command: normalizeBlank(previewForm.value.frontend_build_command),
      backend_build_command: normalizeBlank(previewForm.value.backend_build_command),
      frontend_start_command: normalizeBlank(previewForm.value.frontend_start_command),
      backend_start_command: normalizeBlank(previewForm.value.backend_start_command),
      frontend_healthcheck_path: normalizeBlank(previewForm.value.frontend_healthcheck_path) || "/",
      backend_healthcheck_path: normalizeBlank(previewForm.value.backend_healthcheck_path) || "/",
      ttl_hours: previewForm.value.ttl_hours || 24,
    });
    previewProfileDialogOpen.value = false;
  } catch (err: any) {
    previewProfileError.value = err?.message || "Failed to save preview profile.";
  } finally {
    previewProfileSaving.value = false;
  }
}

async function startSelectedRunPreview() {
  if (!selectedRun.value?.id) return;
  previewLaunchLoading.value = true;
  previewLaunchError.value = "";
  try {
    selectedRunPreview.value = await launchRunPreview(selectedRun.value.id, { reuse_if_healthy: true });
    overview.value = await fetchMissionControlOverview(projectId.value).catch(() => overview.value);
  } catch (err: any) {
    previewLaunchError.value = err?.message || "Failed to launch preview.";
  } finally {
    previewLaunchLoading.value = false;
  }
}

async function stopSelectedRunPreview() {
  if (!selectedRun.value?.id) return;
  previewLaunchLoading.value = true;
  previewLaunchError.value = "";
  try {
    selectedRunPreview.value = await deleteRunPreview(selectedRun.value.id);
    overview.value = await fetchMissionControlOverview(projectId.value).catch(() => overview.value);
  } catch (err: any) {
    previewLaunchError.value = err?.message || "Failed to stop preview.";
  } finally {
    previewLaunchLoading.value = false;
  }
}

function selectRun(runId: string) {
  selectedRunId.value = runId;
}

function openTaskTarget(task: { path: string }) {
  router.push(task.path);
}

function goToOverview() {
  router.push(`/projects/${projectId.value}`);
}

function goToMissionControl() {
  router.push(`/projects/${projectId.value}/run`);
}

function goToAutomationMap() {
  router.push(`/projects/${projectId.value}/map`);
}

function goToRuns() {
  router.push(`/projects/${projectId.value}/runs`);
}

function shortenId(value: string | undefined | null) {
  if (!value) return "—";
  return value.slice(0, 8);
}

function formatTimestamp(value: string | undefined | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatElapsed(value: number | undefined | null) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  if (value < 60) return `${Math.round(value)}s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}m ${seconds}s`;
}

function runStatusTagType(status?: string | null) {
  const normalized = String(status || "").toUpperCase();
  if (normalized === "COMPLETED" || normalized === "DONE") return "success";
  if (normalized === "RUNNING" || normalized === "QUEUED") return "warning";
  if (normalized === "FAILED" || normalized === "CANCELED") return "danger";
  return "info";
}

function taskStatusTagType(status?: string | null) {
  const normalized = String(status || "").toUpperCase();
  if (["DONE", "COMPLETED"].includes(normalized)) return "success";
  if (["RUNNING", "QUEUED", "OPEN"].includes(normalized)) return "warning";
  if (["FAILED", "BLOCKED", "CANCELED"].includes(normalized)) return "danger";
  return "info";
}

function riskTagType(risk?: string | null) {
  const normalized = String(risk || "").toUpperCase();
  if (normalized === "LOW") return "success";
  if (normalized === "MEDIUM") return "warning";
  if (normalized === "HIGH") return "danger";
  return "info";
}

function timelineStepTagType(status?: string | null) {
  return runStatusTagType(status);
}

function workerStatusLabel(worker: AgentRecord) {
  const hb = worker.last_heartbeat_at ? new Date(worker.last_heartbeat_at).getTime() : 0;
  if (!hb || Number.isNaN(hb) || Date.now() - hb > 60_000) return "STALE";
  return (worker.status || "IDLE").toUpperCase();
}

function workerStatusTagType(worker: AgentRecord) {
  const label = workerStatusLabel(worker);
  if (label === "ACTIVE") return "success";
  if (label === "STALE") return "danger";
  return "info";
}

function formatSimilarity(value: number | undefined | null) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

function normalizeBlank(value: string | null | undefined) {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function openExternal(url?: string | null) {
  if (!url) return;
  window.open(url, "_blank", "noopener,noreferrer");
}
</script>
