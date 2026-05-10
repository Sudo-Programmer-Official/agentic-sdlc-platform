<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-3xl font-semibold text-slate-900">Project Overview</h1>
        <p class="text-slate-600">Review project state and enter Mission Control when ready.</p>
      </div>
      <el-button type="primary" :disabled="!projectId || projectStatus !== 'RUN'" @click="goToRun">
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
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-center justify-between gap-2">
          <div class="text-xs uppercase tracking-wide text-slate-400">Repository</div>
          <el-button size="small" plain :disabled="!projectId" @click="openConnectRepoDialog">
            {{ projectRepo ? "Reconnect" : "Connect" }}
          </el-button>
        </div>
        <div class="mt-2 text-sm font-semibold text-slate-900">
          {{ projectRepo?.repo_full_name || projectRepo?.repo_url || "No repository connected" }}
        </div>
        <div class="text-xs text-slate-500">Provider: {{ projectRepo?.provider || "—" }}</div>
        <div class="text-xs text-slate-500">Default branch: {{ projectRepo?.default_branch || "—" }}</div>
        <div v-if="repoError" class="mt-2 text-xs text-rose-600">{{ repoError }}</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-center justify-between gap-2">
          <div class="text-xs uppercase tracking-wide text-slate-400">Architecture Contract</div>
          <el-button size="small" plain :disabled="!projectId" @click="openArchitectureDialog">
            Manage
          </el-button>
        </div>
        <div class="mt-2 text-sm font-semibold" :class="architectureStatusTone">
          {{ architectureSummary?.status || "MISSING" }}
        </div>
        <div class="mt-1 text-xs text-slate-600">
          {{ architectureSummary?.summary || "No architecture profile saved yet." }}
        </div>
        <div class="mt-2 text-xs text-slate-500">
          Layout: {{ architectureSummary?.repo_layout_label || "Repository" }}
          · Packages: {{ architectureSummary?.package_count ?? 0 }}
        </div>
        <div class="text-xs text-slate-500">
          Protected zones: {{ architectureSummary?.protected_zone_count ?? 0 }}
          · Validation recipes: {{ architectureSummary?.validation_recipe_count ?? 0 }}
        </div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-center justify-between gap-2">
          <div class="text-xs uppercase tracking-wide text-slate-400">Foundation Readiness</div>
          <el-button size="small" plain :disabled="!projectId" @click="loadFoundationReadiness">
            Refresh
          </el-button>
        </div>
        <div class="mt-2 text-sm font-semibold" :class="foundationReadinessTone">
          {{ foundationReadiness?.status || "MISSING" }}
          <span class="text-slate-500">· {{ foundationReadiness?.mode || "new_bootstrap" }}</span>
        </div>
        <div class="mt-1 text-xs text-slate-600">
          {{ foundationReadiness?.recommended_next_step || "Evaluate repository and architecture prerequisites." }}
        </div>
        <div class="mt-2 text-xs text-slate-500">
          Missing: {{ foundationReadiness?.missing_prerequisites?.join(", ") || "none" }}
        </div>
        <div v-if="foundationReadinessError" class="mt-2 text-xs text-rose-600">{{ foundationReadinessError }}</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-center justify-between gap-2">
          <div class="text-xs uppercase tracking-wide text-slate-400">Project Blueprint</div>
          <el-button size="small" plain :disabled="!projectId" @click="openGenesisDialog">
            {{ projectBlueprint?.id ? "Recreate" : "Create" }}
          </el-button>
        </div>
        <div class="mt-2 text-sm font-semibold text-slate-900">
          {{ projectBlueprint?.blueprint_key || "No blueprint yet" }}
        </div>
        <div class="text-xs text-slate-500">
          Preset: {{ projectBlueprint?.stack_preset_key || "—" }} · Readiness gate:
          {{ projectBlueprint?.readiness_enforced ? "On" : "Off" }}
        </div>
        <div class="text-xs text-slate-500">
          Genesis: {{ latestGenesisRun?.status || "Not run" }}
        </div>
        <div v-if="genesisError" class="mt-2 text-xs text-rose-600">{{ genesisError }}</div>
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
        <div class="mt-2 text-sm font-semibold">
          Status: {{ planMeta?.requirements_status || '—' }} · Version: {{ planMeta?.requirements_version ?? '—' }}
        </div>
        <div class="text-xs text-slate-500 break-all">Req SHA: {{ shortSha(planMeta?.requirements_sha) }}</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Plan Metadata</div>
        <div class="mt-2 text-sm font-semibold">Plan ID: {{ planMeta?.plan_id || '—' }}</div>
        <div class="text-xs text-slate-500">Created: {{ planMeta?.plan_created_at || '—' }}</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Task Lifecycle</div>
        <div class="mt-2 text-sm font-semibold text-slate-900">
          Open {{ taskLifecycle.open }} · In Progress {{ taskLifecycle.inProgress }} · Closed {{ taskLifecycle.closed }}
        </div>
        <div class="text-xs text-slate-500">
          Needs rerun: {{ taskLifecycle.needsRerun }} · Total tracked: {{ taskLifecycle.total }}
        </div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Improvement Requests</div>
        <div class="mt-2 text-sm font-semibold text-slate-900">
          Queued {{ improvementLifecycle.queued }} · Running {{ improvementLifecycle.running }}
        </div>
        <div class="text-xs text-slate-500">
          Completed {{ improvementLifecycle.completed }} · Failed {{ improvementLifecycle.failed }} · Total {{ improvementLifecycle.total }}
        </div>
        <div v-if="improvementRequestsError" class="mt-2 text-xs text-rose-600">{{ improvementRequestsError }}</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Requirements Needing Review</div>
        <div class="mt-2 text-sm font-semibold text-slate-900">{{ requirementsNeedingReview }}</div>
        <div class="text-xs text-slate-500">
          Count of requirements flagged by lineage status as pending review.
        </div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Requirement AI Spend</div>
        <div class="mt-2 text-sm font-semibold text-slate-900">${{ totalRequirementAiSpendUsd }}</div>
        <div class="text-xs text-slate-500">Total tracked tokens: {{ totalRequirementAiTokens.toLocaleString() }}</div>
        <div class="mt-2 text-xs text-slate-600" v-if="topCostlyRequirements.length">
          Top 5 costly requirements
        </div>
        <ul v-if="topCostlyRequirements.length" class="mt-1 space-y-1 text-xs text-slate-600">
          <li v-for="card in topCostlyRequirements" :key="card.requirement_id" class="flex justify-between gap-2">
            <span class="truncate" :title="card.title || card.requirement_id">{{ card.requirement_id }}</span>
            <span class="font-medium text-slate-800">${{ (((card.ai_spend_cents || 0) as number) / 100).toFixed(4) }}</span>
          </li>
        </ul>
        <div v-else class="mt-2 text-xs text-slate-500">No requirement spend data yet.</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Latest Delivery</div>
        <div class="mt-2 text-sm font-semibold" :class="latestDeliveryTone">
          {{ latestDeliveryStatus }}
        </div>
        <div class="text-xs text-slate-500">
          Branch: {{ latestDelivery?.delivery_branch_name || latestDelivery?.branch_name || '—' }}
        </div>
        <div class="text-xs text-slate-500">Commit: {{ shortSha(latestDelivery?.delivery_commit_sha) }}</div>
        <div class="text-xs text-slate-500">
          Files changed: {{ latestDelivery?.files_changed?.length ?? 0 }} · Artifacts: {{ latestDelivery?.artifact_count ?? 0 }}
        </div>
        <div v-if="latestDelivery?.pull_request_url" class="mt-2 text-xs">
          <a
            :href="latestDelivery.pull_request_url"
            target="_blank"
            rel="noreferrer"
            class="font-medium text-sky-600 hover:text-sky-700"
          >
            Open PR{{ latestDelivery.pull_request_number ? ` #${latestDelivery.pull_request_number}` : "" }}
          </a>
        </div>
        <div v-else-if="latestDelivery?.primary_error" class="mt-2 text-xs text-rose-600">
          {{ latestDelivery.primary_error }}
        </div>
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

    <div class="rounded-xl border border-sky-200 bg-sky-50 p-5 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div class="text-xs uppercase tracking-wide text-sky-700">Journey Guide</div>
          <div class="mt-1 text-sm font-semibold text-sky-900">
            {{ journeyHeadline }}
          </div>
          <div class="text-xs text-sky-700">
            {{ journeyHint }}
          </div>
        </div>
        <div class="flex flex-wrap gap-2">
          <el-button size="small" type="primary" @click="runPrimaryJourneyAction">
            {{ journeyPrimaryActionLabel }}
          </el-button>
          <el-button size="small" plain :disabled="!projectId" @click="goToRequirements">
            Requirements
          </el-button>
        </div>
      </div>
      <div class="mt-3 grid gap-2 text-xs md:grid-cols-2 xl:grid-cols-4">
        <div class="rounded-lg border border-sky-100 bg-white px-3 py-2">
          <span class="font-semibold text-sky-900">{{ checklistRepo ? "Done" : "Pending" }}</span>
          · Repository connected
        </div>
        <div class="rounded-lg border border-sky-100 bg-white px-3 py-2">
          <span class="font-semibold text-sky-900">{{ checklistRequirements ? "Done" : "Pending" }}</span>
          · Requirements ready
        </div>
        <div class="rounded-lg border border-sky-100 bg-white px-3 py-2">
          <span class="font-semibold text-sky-900">{{ checklistTasks ? "Done" : "Pending" }}</span>
          · Tasks available
        </div>
        <div class="rounded-lg border border-sky-100 bg-white px-3 py-2">
          <span class="font-semibold text-sky-900">{{ checklistRuns ? "Done" : "Pending" }}</span>
          · Execution observed
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
        <el-button type="primary" plain :disabled="!projectId" @click="openCreateDocumentDialog">
          Create Document
        </el-button>
        <el-button type="primary" plain :disabled="!projectId" @click="openConnectRepoDialog">
          Connect Repo
        </el-button>
        <el-button type="primary" plain :disabled="!projectId" @click="openArchitectureDialog">
          Architecture Contract
        </el-button>
        <el-button type="primary" plain :disabled="!projectId" @click="openGenesisDialog">
          Create Project Blueprint
        </el-button>
        <el-button type="success" plain :disabled="!projectId || !documents.length" @click="showRegenDialog = true">
          Regenerate Tasks
        </el-button>
        <el-button type="primary" plain :disabled="!projectId" @click="openCreateTaskDialog">
          Create Task
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
          <el-tooltip :content="stageBlockReason('PLAN')" placement="top" :disabled="!stageBlockReason('PLAN')">
            <span>
              <el-button
                :disabled="isStageBlocked('PLAN') || stageUpdating"
                @click="advanceStage('PLAN')"
              >
                Move to PLAN
              </el-button>
            </span>
          </el-tooltip>
          <el-tooltip :content="stageBlockReason('RUN')" placement="top" :disabled="!stageBlockReason('RUN')">
            <span>
              <el-button
                :disabled="isStageBlocked('RUN') || stageUpdating"
                @click="advanceStage('RUN')"
              >
                Move to RUN
              </el-button>
            </span>
          </el-tooltip>
          <el-tooltip :content="stageBlockReason('EVALUATE')" placement="top" :disabled="!stageBlockReason('EVALUATE')">
            <span>
              <el-button
                :disabled="isStageBlocked('EVALUATE') || stageUpdating"
                @click="advanceStage('EVALUATE')"
              >
                Move to EVALUATE
              </el-button>
            </span>
          </el-tooltip>
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
            <el-select
              v-model="selectedExecutor"
              size="small"
              style="width: 140px"
              placeholder="Executor"
              @change="markExecutorSelection"
            >
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
          <el-table-column label="Actions" width="280">
            <template #default="{ row }">
              <el-button size="small" plain :loading="Boolean(runUnblockLoading[row.id])" :disabled="!['RUNNING','QUEUED'].includes(row.status)" @click="unblockRunById(row.id)">
                Unblock
              </el-button>
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
          Approve a requirements graph or add a document first before regenerating tasks.
        </div>
        <el-checkbox v-model="regenForce">Force (override existing tasks for this version)</el-checkbox>
        <el-button type="success" :disabled="!documents.length" :loading="regenLoading" @click="doRegenerate">
          Regenerate
        </el-button>
        <div v-if="regenMessage" class="text-sm text-emerald-700">{{ regenMessage }}</div>
        <div v-if="regenError" class="text-sm text-rose-600">{{ regenError }}</div>
      </div>
    </el-dialog>

    <el-dialog v-model="showCreateDocumentDialog" title="Create Document" width="640px">
      <div class="space-y-3">
        <el-select
          v-model="newDocument.type"
          placeholder="Document type"
          filterable
          allow-create
          default-first-option
          style="width: 100%"
        >
          <el-option label="PRD" value="prd" />
          <el-option label="Design" value="design" />
          <el-option label="Spec" value="spec" />
          <el-option label="Notes" value="notes" />
          <el-option label="Test Plan" value="test-plan" />
        </el-select>
        <el-input v-model="newDocument.title" placeholder="Document title" />
        <el-input
          v-model="newDocument.body"
          type="textarea"
          :rows="8"
          placeholder="Paste or write the document content"
        />
        <el-input v-model="newDocument.created_by" placeholder="Created by (optional)" />
        <el-button type="primary" :loading="createDocumentLoading" @click="submitCreateDocument">
          Create Document
        </el-button>
        <div v-if="createDocumentError" class="text-sm text-rose-600">{{ createDocumentError }}</div>
      </div>
    </el-dialog>

    <el-dialog v-model="showConnectRepoDialog" title="Connect Repository" width="620px">
      <div class="space-y-3">
        <div
          v-if="githubConnectInfo?.enabled"
          class="rounded-2xl border border-sky-200 bg-sky-50 p-4"
        >
          <div class="text-sm font-semibold text-sky-900">Connect with GitHub</div>
          <div class="mt-1 text-xs text-sky-700">
            Install or authorize the GitHub App, then pick a repository instead of typing repo details manually.
          </div>
          <div class="mt-3 flex flex-wrap gap-2">
            <el-button type="primary" plain @click="startGitHubAppInstall">Continue with GitHub</el-button>
            <el-button
              v-if="repoForm.installation_id"
              :loading="githubInstallLoading"
              @click="loadGitHubInstallationRepositories"
            >
              Refresh Repositories
            </el-button>
          </div>
          <div v-if="githubConnectInfo.allowed_org" class="mt-2 text-xs text-sky-700">
            Allowed org: {{ githubConnectInfo.allowed_org }}
          </div>
          <div v-if="githubInstallMessage" class="mt-3 text-sm text-emerald-700">{{ githubInstallMessage }}</div>
          <div v-if="githubInstallError" class="mt-3 text-sm text-rose-600">{{ githubInstallError }}</div>
        </div>

        <el-select
          v-if="githubInstallationRepos.length"
          v-model="selectedGitHubRepo"
          filterable
          placeholder="Choose a repository from this GitHub installation"
          style="width: 100%"
          @change="applySelectedGitHubRepository"
        >
          <el-option
            v-for="repo in githubInstallationRepos"
            :key="repo.id"
            :label="repo.full_name"
            :value="repo.full_name"
          >
            <div class="flex items-center justify-between gap-3">
              <span>{{ repo.full_name }}</span>
              <span class="text-xs text-slate-400">{{ repo.default_branch || "main" }}</span>
            </div>
          </el-option>
        </el-select>

        <div
          v-if="repoForm.installation_id && !githubInstallLoading && !githubInstallationRepos.length && githubConnectInfo?.enabled"
          class="text-xs text-slate-500"
        >
          No repositories loaded yet for installation {{ repoForm.installation_id }}. Use refresh after GitHub authorization completes.
        </div>

        <div v-if="githubConnectInfo?.enabled" class="pt-1 text-xs uppercase tracking-wide text-slate-400">
          Manual fallback
        </div>
        <el-input v-model="repoForm.repo_url" placeholder="Repository URL or local path" />
        <div class="grid gap-3 md:grid-cols-2">
          <el-input v-model="repoForm.repo_full_name" placeholder="owner/repo (optional for GitHub API)" />
          <el-input v-model="repoForm.default_branch" placeholder="Default branch" />
        </div>
        <el-input v-model="repoForm.installation_id" placeholder="GitHub installation ID (optional)" />
        <el-segmented
          v-model="repoForm.auth_strategy"
          :options="repoAuthStrategyOptions"
          class="w-full"
        />
        <div class="text-xs text-slate-500">
          The selected strategy is saved with this project and used by the worker for every repo-backed run.
        </div>
        <div
          v-if="repoPreflightResult"
          :class="repoPreflightResult.ok ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-rose-200 bg-rose-50 text-rose-700'"
          class="rounded-xl border px-3 py-2 text-xs"
        >
          <div class="font-semibold">
            {{ repoPreflightResult.ok ? "Clone preflight passed" : "Clone preflight failed" }}
          </div>
          <div class="mt-1">
            {{ repoPreflightResult.auth_strategy }} · {{ repoPreflightResult.auth_mode || "unknown" }} ·
            {{ repoPreflightResult.transport_url || repoForm.repo_url }}
          </div>
          <div v-if="repoPreflightResult.error" class="mt-1">{{ repoPreflightResult.error }}</div>
        </div>
        <div class="flex flex-wrap gap-2">
          <el-button :loading="repoPreflightLoading" @click="runRepoPreflight">
            Test Clone
          </el-button>
          <el-button type="primary" :loading="repoLoading" @click="submitConnectRepo">
            Save Repository
          </el-button>
        </div>
        <div v-if="repoMessage" class="text-sm text-emerald-700">{{ repoMessage }}</div>
        <div v-if="repoError" class="text-sm text-rose-600">{{ repoError }}</div>
      </div>
    </el-dialog>

    <el-dialog v-model="showGenesisDialog" title="Create Project Blueprint" width="560px">
      <div class="space-y-3">
        <el-select v-model="genesisForm.stack_preset_key" placeholder="Stack preset" style="width: 100%">
          <el-option v-for="preset in stackPresets" :key="preset.key" :label="preset.label" :value="preset.key" />
        </el-select>
        <el-input v-model="genesisForm.deployment_profile" placeholder="Deployment profile (e.g. local_preview)" />
        <el-checkbox v-model="genesisForm.readiness_enforced">Enforce readiness gate before feature runs</el-checkbox>
        <el-button type="primary" :loading="genesisLoading" :disabled="!projectId" @click="submitGenesisBlueprint">
          Create Blueprint
        </el-button>
        <div v-if="genesisError" class="text-sm text-rose-600">{{ genesisError }}</div>
      </div>
    </el-dialog>

    <el-dialog v-model="showArchitectureDialog" title="Architecture Contract" width="760px">
      <div class="space-y-4">
        <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div class="text-sm font-semibold text-slate-900">
                {{ architectureSummary?.repo_layout_label || "Repository" }}
                <span class="text-slate-500">· {{ architectureSummary?.status || "MISSING" }}</span>
              </div>
              <div class="mt-1 text-xs text-slate-600">
                {{ architectureSummary?.summary || "No architecture profile saved yet." }}
              </div>
            </div>
            <div class="flex flex-wrap gap-2">
              <el-button
                size="small"
                :loading="architectureBootstrapLoading"
                :disabled="!projectId"
                @click="bootstrapArchitectureProfile(true)"
              >
                Bootstrap
              </el-button>
              <el-button
                size="small"
                plain
                :loading="architectureDeriveLoading"
                :disabled="!projectId"
                @click="deriveArchitectureProfile(true)"
              >
                Derive
              </el-button>
            </div>
          </div>
          <div class="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
            <div><strong>Packages:</strong> {{ architectureSummary?.packages?.join(", ") || "—" }}</div>
            <div><strong>Execution slice:</strong> {{ architectureSummary?.execution_slice?.join(", ") || "—" }}</div>
            <div><strong>Protected zones:</strong> {{ architectureSummary?.protected_zones?.join(", ") || "—" }}</div>
            <div><strong>Safe zones:</strong> {{ architectureSummary?.safe_zones?.join(", ") || "—" }}</div>
            <div><strong>Commands:</strong> {{ architectureSummary?.commands?.join(", ") || "—" }}</div>
            <div><strong>Validation recipes:</strong> {{ architectureSummary?.validation_recipes?.join(", ") || "—" }}</div>
          </div>
          <div v-if="architectureSummary?.assumptions_used?.length" class="mt-3 text-xs text-slate-500">
            <strong>Assumptions:</strong> {{ architectureSummary.assumptions_used.join(" · ") }}
          </div>
        </div>

        <div v-if="architectureLoading" class="text-sm text-slate-500">Loading architecture profile…</div>
        <template v-else>
          <el-input
            v-model="architectureSummaryText"
            placeholder="Architecture summary"
            type="textarea"
            :rows="3"
          />
          <el-input
            v-model="architectureEditorValue"
            type="textarea"
            :rows="18"
            placeholder='{"repo_layout": {...}}'
            class="font-mono"
          />
        </template>

        <div v-if="architectureError" class="text-sm text-rose-600">{{ architectureError }}</div>

        <div class="flex justify-end gap-2">
          <el-button @click="showArchitectureDialog = false">Close</el-button>
          <el-button type="primary" :loading="architectureSaveLoading" @click="saveArchitectureProfileDraft">
            Save Contract
          </el-button>
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="showTasksDialog" title="Tasks" width="640px">
      <div class="mb-3 flex items-center justify-between gap-3">
        <div class="text-xs text-slate-500">
          Create a task manually, or approve requirements/create a document and use Regenerate Tasks.
        </div>
        <el-button type="primary" size="small" plain @click="openCreateTaskDialog">
          Create Task
        </el-button>
      </div>
      <el-table :data="tasks" size="small">
        <el-table-column prop="id" label="ID" width="240" />
        <el-table-column label="Title" min-width="260">
          <template #default="scope">
            <div class="text-sm font-medium text-slate-900">{{ scope.row.title }}</div>
            <div class="text-xs text-slate-500">
              {{ taskLineageLabel(scope.row) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Source" width="170">
          <template #default="scope">
            <div class="text-sm text-slate-800">{{ scope.row.source_type || scope.row.source || "manual" }}</div>
            <div class="text-xs text-slate-500">{{ scope.row.architecture_slice || "—" }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="Status" width="120" />
        <el-table-column label="Branch" width="200">
          <template #default="scope">
            <div class="text-sm text-slate-800">{{ taskBranchLabel(scope.row) }}</div>
            <div class="text-xs text-slate-500">{{ taskBranchDetail(scope.row) }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="generated_from_document_version" label="Doc Ver" width="90" />
        <el-table-column label="Action" width="140">
          <template #default="scope">
            <el-button
              type="primary"
              size="small"
              text
              :loading="taskRunLoadingId === scope.row.id"
              @click="runTask(scope.row)"
            >
              Run This Task
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="tasksError" class="mt-2 text-sm text-rose-600">{{ tasksError }}</div>
    </el-dialog>

    <el-dialog v-model="showCreateTaskDialog" title="Create Task" width="640px">
      <div class="space-y-3">
        <el-input v-model="newTask.title" placeholder="Task title" />
        <el-input v-model="newTask.description" type="textarea" :rows="3" placeholder="Description (optional)" />
        <div class="grid gap-3 md:grid-cols-2">
          <el-select v-model="newTask.stage" placeholder="Stage">
            <el-option label="PLAN" value="PLAN" />
            <el-option label="RUN" value="RUN" />
            <el-option label="EVALUATE" value="EVALUATE" />
          </el-select>
          <el-select v-model="newTask.status" placeholder="Status">
            <el-option label="PENDING" value="PENDING" />
            <el-option label="RUNNING" value="RUNNING" />
            <el-option label="DONE" value="DONE" />
            <el-option label="FAILED" value="FAILED" />
            <el-option label="CANCELED" value="CANCELED" />
          </el-select>
        </div>
        <div class="grid gap-3 md:grid-cols-2">
          <el-select v-model="newTask.category" placeholder="Category">
            <el-option label="Functional" value="func" />
            <el-option label="Quality" value="quality" />
            <el-option label="Ops" value="ops" />
          </el-select>
          <el-input v-model="newTask.assignee" placeholder="Assignee (optional)" />
        </div>
        <div class="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Branch strategy</div>
          <el-select v-model="newTask.branch_strategy" placeholder="Select branch strategy" style="width: 100%">
            <el-option label="Auto-generate isolated run branch" value="auto" />
            <el-option label="Create new branch from base" value="new" />
            <el-option label="Reuse existing branch" value="existing" />
          </el-select>
          <div v-if="newTask.branch_strategy === 'auto'" class="text-xs text-slate-500">
            System will create an isolated run branch automatically for this task.
          </div>
          <template v-else-if="newTask.branch_strategy === 'new'">
            <div class="grid gap-3 md:grid-cols-2">
              <el-input v-model="newTask.base_branch" placeholder="Base branch" />
              <el-input v-model="newTask.branch_name" placeholder="New branch name" />
            </div>
            <div class="text-xs text-slate-500">Suggested branch: {{ suggestedTaskBranchName }}</div>
          </template>
          <template v-else>
            <el-input v-model="newTask.branch_name" placeholder="Target branch" />
            <div class="text-xs text-slate-500">
              Reuse a branch for follow-on work. Avoid overlapping active runs on the same branch.
            </div>
          </template>
        </div>
        <el-select
          v-model="newTask.document_id"
          placeholder="Link document (optional)"
          clearable
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
        <el-input v-model="newTask.created_by" placeholder="Created by (optional)" />
        <el-button type="primary" :loading="createTaskLoading" @click="submitCreateTask">
          Create Task
        </el-button>
        <div v-if="createTaskError" class="text-sm text-rose-600">{{ createTaskError }}</div>
      </div>
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
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";

import StageBadge from "../components/StageBadge.vue";
import { projectContext, updateProjectContext } from "../state/projectContext";
import { fetchProjectSummary, fetchPlanHistory, fetchRequirementSummary } from "../api/requirements";
import {
  createEmptyArchitectureProfileSummary,
  createEmptyFoundationReadiness,
  fetchProjectArchitectureProfile,
  bootstrapProjectArchitectureProfile,
  deriveProjectArchitectureProfile,
  saveProjectArchitectureProfile,
  previewImpact,
  regenerateTasks,
  listTasks,
  createTask,
  createDocument,
  explainTask,
  listActivity,
  fetchHealth,
  fetchLifecycleScore,
  fetchLifecycleScoreHistory,
  listDocuments,
  fetchProjectMeta,
  updateProjectStage,
  listRuns,
  createRun,
  updateRunStatus,
  unblockRun,
  listWorkItems,
  listRunEvents,
  fetchProjectRepo,
  connectProjectRepo,
  preflightProjectRepo,
  fetchGitHubConnectInfo,
  listGitHubInstallationRepositories,
  fetchFoundationReadiness,
  listImprovementRequests,
  listStackPresets,
  fetchProjectBlueprint,
  fetchLatestGenesisRun,
  createProjectBlueprint,
} from "../api/lifecycle";

const route = useRoute();
const router = useRouter();
const error = ref("");

const projectId = computed(() => (route.params.projectId as string) || projectContext.projectId);
const projectName = computed(() => projectContext.projectName || "Project");
const stage = computed(() => projectContext.stage || "UNKNOWN");
const runSummary = computed(() => {
  if (!runs.value.length) return "No runs yet";
  return `${runs.value.length} run${runs.value.length === 1 ? "" : "s"}`;
});
const latestRunText = computed(() => runs.value[0]?.id || projectContext.latestRunId || "None");
const architectureRefreshNeeded = computed(() => projectContext.architectureRefreshNeeded);
const planRefreshNeeded = computed(() => projectContext.planRefreshNeeded);
const testRefreshNeeded = computed(() => projectContext.testRefreshNeeded);
const planMeta = ref<any | null>(null);
const latestDelivery = ref<any | null>(null);
const architectureSummary = ref<any>(createEmptyArchitectureProfileSummary());
const foundationReadiness = ref<any>(createEmptyFoundationReadiness());
const foundationReadinessError = ref("");
const projectBlueprint = ref<any | null>(null);
const latestGenesisRun = ref<any | null>(null);
const stackPresets = ref<any[]>([]);
const showGenesisDialog = ref(false);
const genesisLoading = ref(false);
const genesisError = ref("");
const genesisForm = ref({
  blueprint_key: "fullstack_monorepo",
  stack_preset_key: "vue_fastapi",
  deployment_profile: "local_preview",
  readiness_enforced: true,
});
const architectureProfile = ref<any | null>(null);
const showArchitectureDialog = ref(false);
const architectureLoading = ref(false);
const architectureBootstrapLoading = ref(false);
const architectureDeriveLoading = ref(false);
const architectureSaveLoading = ref(false);
const architectureError = ref("");
const architectureEditorValue = ref("{}");
const architectureSummaryText = ref("");
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
const showCreateDocumentDialog = ref(false);
const showRegenDialog = ref(false);
const showTasksDialog = ref(false);
const showCreateTaskDialog = ref(false);
const showExplainDialog = ref(false);
const showConnectRepoDialog = ref(false);
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
const createDocumentLoading = ref(false);
const createDocumentError = ref("");
const newDocument = ref({
  type: "prd",
  title: "",
  body: "",
  created_by: "ui-user",
});
const tasks = ref<any[]>([]);
const taskSnapshot = ref<any[]>([]);
const improvementRequests = ref<any[]>([]);
const improvementRequestsError = ref("");
const requirementSummaryCards = ref<any[]>([]);
const tasksError = ref("");
const taskRunLoadingId = ref("");
const createTaskLoading = ref(false);
const createTaskError = ref("");
const newTask = ref({
  title: "",
  description: "",
  category: "func",
  stage: "PLAN",
  status: "PENDING",
  assignee: "",
  document_id: "",
  created_by: "ui-user",
  branch_strategy: "auto",
  base_branch: "main",
  branch_name: "",
});
const explainTaskId = ref("");
const explainResult = ref<any | null>(null);
const explainError = ref("");
const explainLoading = ref(false);
const documents = ref<any[]>([]);
const documentsLoading = ref(false);
const projectRepo = ref<any | null>(null);
const repoLoading = ref(false);
const repoError = ref("");
const repoMessage = ref("");
const repoForm = ref({
  repo_url: "",
  repo_full_name: "",
  default_branch: "main",
  installation_id: "",
  auth_strategy: "public_https",
});
const repoAuthStrategyOptions = [
  { label: "Public HTTPS", value: "public_https" },
  { label: "GitHub App", value: "github_app" },
  { label: "SSH", value: "ssh" },
  { label: "Runtime Default", value: "runtime_default" },
];
const repoPreflightLoading = ref(false);
const repoPreflightResult = ref<any | null>(null);
const githubConnectInfo = ref<any | null>(null);
const githubConnectLoading = ref(false);
const githubInstallLoading = ref(false);
const githubInstallationRepos = ref<any[]>([]);
const githubInstallError = ref("");
const githubInstallMessage = ref("");
const selectedGitHubRepo = ref("");
const handledGitHubInstallation = ref("");
const projectStatus = ref<string | null>(null);
const allowedTransitions = ref<string[]>([]);
const stageUpdating = ref(false);
const stageMessage = ref("");
const stageError = ref("");
const runs = ref<any[]>([]);
const runsLoading = ref(false);
const runError = ref("");
const runUnblockLoading = ref<Record<string, boolean>>({});
const selectedExecutor = ref("codex");
const executorSelectionDirty = ref(false);
const workItems = ref<any[]>([]);
const workItemsLoading = ref(false);
const workItemError = ref("");
const runEvents = ref<any[]>([]);
const hasCompletedRun = computed(() => runs.value.some((run) => run.status === "COMPLETED"));
const hasRunningRun = computed(() => runs.value.some((run) => ["RUNNING", "QUEUED"].includes(run.status)));
const taskDefaultBaseBranch = computed(() => projectRepo.value?.default_branch || "main");
const suggestedTaskBranchName = computed(() => suggestTaskBranchName(newTask.value.title));
const taskLifecycle = computed(() => {
  const rows = taskSnapshot.value || [];
  const statusOf = (row: any) => String(row?.status || "").toUpperCase();
  const has = (row: any, statuses: string[]) => statuses.includes(statusOf(row));
  return {
    total: rows.length,
    open: rows.filter((r) => has(r, ["PENDING", "QUEUED"])).length,
    inProgress: rows.filter((r) => has(r, ["RUNNING", "IN_PROGRESS"])).length,
    closed: rows.filter((r) => has(r, ["DONE", "COMPLETED", "CLOSED"])).length,
    needsRerun: rows.filter((r) => has(r, ["FAILED", "CANCELED", "BLOCKED"])).length,
  };
});
const improvementLifecycle = computed(() => {
  const rows = improvementRequests.value || [];
  const statusOf = (row: any) => String(row?.status || "").toUpperCase();
  const count = (statuses: string[]) => rows.filter((r) => statuses.includes(statusOf(r))).length;
  return {
    total: rows.length,
    queued: count(["QUEUED"]),
    running: count(["RUNNING"]),
    completed: count(["COMPLETED", "DONE"]),
    failed: count(["FAILED", "CANCELED"]),
  };
});
const requirementsNeedingReview = computed(
  () => requirementSummaryCards.value.filter((card) => String(card?.status || "").toUpperCase() === "NEEDS_REVIEW").length
);
const totalRequirementAiSpendCents = computed(() =>
  requirementSummaryCards.value.reduce((sum, card) => sum + Number(card?.ai_spend_cents || 0), 0)
);
const totalRequirementAiSpendUsd = computed(() => (totalRequirementAiSpendCents.value / 100).toFixed(4));
const totalRequirementAiTokens = computed(() =>
  requirementSummaryCards.value.reduce((sum, card) => sum + Number(card?.ai_total_tokens || 0), 0)
);
const topCostlyRequirements = computed(() =>
  [...requirementSummaryCards.value]
    .sort((a, b) => Number(b?.ai_spend_cents || 0) - Number(a?.ai_spend_cents || 0))
    .filter((card) => Number(card?.ai_spend_cents || 0) > 0)
    .slice(0, 5)
);
const riskClass = computed(() => {
  const risk = lifecycleScore.value?.risk_level || "UNKNOWN";
  if (risk === "HIGH") return "text-rose-600";
  if (risk === "MEDIUM") return "text-amber-600";
  if (risk === "LOW") return "text-emerald-600";
  return "text-slate-500";
});
const latestDeliveryStatus = computed(() => {
  if (!latestDelivery.value) return "No delivery yet";
  if (latestDelivery.value.pull_request_url) {
    return latestDelivery.value.pull_request_number
      ? `PR #${latestDelivery.value.pull_request_number} ready`
      : "Pull request ready";
  }
  if (latestDelivery.value.delivery_pushed) return "Branch pushed";
  if (latestDelivery.value.status === "COMPLETED") return "Completed locally";
  return latestDelivery.value.status || "Unknown";
});
const latestDeliveryTone = computed(() => {
  if (!latestDelivery.value) return "text-slate-500";
  if (latestDelivery.value.status === "FAILED" || latestDelivery.value.primary_error) return "text-rose-600";
  if (latestDelivery.value.pull_request_url || latestDelivery.value.delivery_pushed) return "text-emerald-600";
  return "text-slate-700";
});
const architectureStatusTone = computed(() => {
  const status = String(architectureSummary.value?.status || "MISSING").toUpperCase();
  if (status === "ACTIVE" || status === "READY") return "text-emerald-600";
  if (status === "MISSING") return "text-amber-600";
  return "text-slate-700";
});
const foundationReadinessTone = computed(() => {
  const status = String(foundationReadiness.value?.status || "MISSING").toUpperCase();
  if (status === "READY") return "text-emerald-600";
  if (status === "PARTIAL") return "text-amber-600";
  return "text-rose-600";
});
const checklistRepo = computed(() => Boolean(projectRepo.value?.repo_url || projectRepo.value?.repo_full_name));
const checklistRequirements = computed(() => {
  const status = String(planMeta.value?.requirements_status || "").toUpperCase();
  return ["APPROVED", "READY", "ACTIVE"].includes(status) || requirementSummaryCards.value.length > 0;
});
const checklistTasks = computed(() => taskLifecycle.value.total > 0);
const checklistRuns = computed(() => runs.value.length > 0);
const journeyHeadline = computed(() => {
  if (!checklistRepo.value) return "Connect a repository to unlock governed runtime execution.";
  if (!checklistRequirements.value) return "Prepare requirements so lineage and planning stay connected.";
  if (!checklistTasks.value) return "Generate or create tasks to make execution actionable.";
  if (!checklistRuns.value) return "Start the first run to validate runtime confidence.";
  if (projectStatus.value !== "RUN") return "Move to RUN stage to operate from Mission Control.";
  return "Use Mission Control to monitor live execution and delivery outcomes.";
});
const journeyHint = computed(() => {
  if (!checklistRepo.value) return "Without repo context, run previews and delivery tracking remain limited.";
  if (!checklistRequirements.value) return "Requirement status drives task generation and run lineage quality.";
  if (!checklistTasks.value) return "Tasks are the bridge between requirements and runs.";
  if (!checklistRuns.value) return "A first run establishes baseline telemetry, timeline, and artifact visibility.";
  return "You can continue iterating tasks, replaying runs, and tracking requirement health.";
});
const journeyPrimaryActionLabel = computed(() => {
  if (!checklistRepo.value) return "Connect Repository";
  if (!checklistRequirements.value) return "Open Requirements";
  if (!checklistTasks.value) return "Create Task";
  if (!checklistRuns.value) return "Start Run";
  return projectStatus.value === "RUN" ? "Enter Mission Control" : "Move to RUN";
});

function syncArchitectureEditor(profile: any | null) {
  architectureProfile.value = profile;
  architectureSummaryText.value = profile?.summary || architectureSummary.value?.summary || "";
  architectureEditorValue.value = JSON.stringify(profile?.profile_json || {}, null, 2);
}

function goHome() {
  router.push("/");
}

function suggestTaskBranchName(title: string) {
  const slug = title
    .toLowerCase()
    .replace(/['"]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return slug ? `task/${slug}` : "task/new-work";
}

function taskBranchLabel(task: any) {
  const strategy = (task?.branch_strategy || "auto").toLowerCase();
  if (strategy === "new") return "New branch";
  if (strategy === "existing") return "Existing branch";
  return "Auto run branch";
}

function taskBranchDetail(task: any) {
  const strategy = (task?.branch_strategy || "auto").toLowerCase();
  if (strategy === "new") {
    return `${task?.branch_name || "task/new-work"} from ${task?.base_branch || taskDefaultBaseBranch.value}`;
  }
  if (strategy === "existing") {
    return task?.branch_name || "Branch required";
  }
  return "System-generated isolated branch";
}

function taskLineageLabel(task: any) {
  const reqs = Array.isArray(task?.derived_from_requirement_ids) ? task.derived_from_requirement_ids : [];
  const parts = [];
  if (task?.rerun_of_task_id) parts.push(`Rerun of ${String(task.rerun_of_task_id).slice(0, 8)}`);
  if (reqs.length) parts.push(`Derived from ${reqs.join(", ")}`);
  if (task?.capability_id) parts.push(`Capability ${task.capability_id}`);
  if (task?.impact_zone?.length) parts.push(`Impact ${task.impact_zone.join(", ")}`);
  return parts.join(" · ") || "Manual or unlinked task";
}

function markExecutorSelection() {
  executorSelectionDirty.value = true;
}

function goToRun() {
  if (!projectId.value || projectStatus.value !== "RUN") {
    error.value = "Enter Mission Control is available only in RUN stage.";
    return;
  }
  error.value = "";
  router.push(`/projects/${projectId.value}/run`);
}

function goToRequirements() {
  if (!projectId.value) return;
  router.push(`/projects/${projectId.value}/requirements`);
}

function runPrimaryJourneyAction() {
  if (!checklistRepo.value) {
    openConnectRepoDialog();
    return;
  }
  if (!checklistRequirements.value) {
    goToRequirements();
    return;
  }
  if (!checklistTasks.value) {
    openCreateTaskDialog();
    return;
  }
  if (!checklistRuns.value) {
    void startRun();
    return;
  }
  if (projectStatus.value !== "RUN") {
    void advanceStage("RUN");
    return;
  }
  goToRun();
}

function stageBlockReason(target: string) {
  if (!allowedTransitions.value.includes(target)) return "";
  if (target === "PLAN" && !documents.value.length) {
    return "Add at least one document before moving to PLAN.";
  }
  if (target === "RUN" && !tasks.value.length) {
    return "Create or generate tasks before moving to RUN.";
  }
  if (target === "EVALUATE" && !hasCompletedRun.value) {
    return "Complete at least one run before moving to EVALUATE.";
  }
  if (target === "EVALUATE" && hasRunningRun.value) {
    return "Wait for the active run to finish before moving to EVALUATE.";
  }
  return "";
}

function isStageBlocked(target: string) {
  if (!allowedTransitions.value.includes(target)) return true;
  return Boolean(stageBlockReason(target));
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
    await loadTasks();
  } catch (err: any) {
    regenError.value = err?.message || "Regeneration failed";
  } finally {
    regenLoading.value = false;
  }
}

function resetCreateDocumentForm() {
  newDocument.value = {
    type: "prd",
    title: "",
    body: "",
    created_by: "ui-user",
  };
  createDocumentError.value = "";
}

function openCreateDocumentDialog() {
  resetCreateDocumentForm();
  showCreateDocumentDialog.value = true;
}

async function submitCreateDocument() {
  if (!projectId.value) return;
  if (!newDocument.value.type.trim() || !newDocument.value.title.trim() || !newDocument.value.body.trim()) {
    createDocumentError.value = "Document type, title, and body are required.";
    return;
  }
  createDocumentLoading.value = true;
  createDocumentError.value = "";
  try {
    const created = await createDocument(projectId.value, {
      type: newDocument.value.type.trim(),
      title: newDocument.value.title.trim(),
      body: newDocument.value.body.trim(),
      created_by: newDocument.value.created_by.trim() || null,
      source: "manual",
    });
    showCreateDocumentDialog.value = false;
    await loadDocuments();
    regenDocId.value = created.id;
    impactDocId.value = created.id;
    ElMessage.success("Document created. You can now regenerate tasks.");
  } catch (err: any) {
    createDocumentError.value = err?.message || "Failed to create document";
  } finally {
    createDocumentLoading.value = false;
  }
}

async function openTasksDialog() {
  showTasksDialog.value = true;
  await loadTasks();
}

async function loadTasks() {
  tasksError.value = "";
  if (!projectId.value) return;
  try {
    tasks.value = await listTasks(projectId.value, { active_only: true, latest_per_title: true });
    taskSnapshot.value = await listTasks(projectId.value, { latest_per_title: true, include_deleted: false });
  } catch (err: any) {
    tasksError.value = err?.message || "Failed to load tasks";
  }
}

async function loadImprovementRequests() {
  improvementRequestsError.value = "";
  if (!projectId.value) return;
  try {
    improvementRequests.value = await listImprovementRequests(projectId.value, 100);
  } catch (err: any) {
    improvementRequests.value = [];
    improvementRequestsError.value = err?.message || "Failed to load improvement requests";
  }
}

async function loadRequirementSummaryCards() {
  if (!projectId.value) return;
  try {
    const payload = await fetchRequirementSummary(projectId.value, 200, 0);
    requirementSummaryCards.value = Array.isArray(payload?.items) ? payload.items : [];
  } catch {
    requirementSummaryCards.value = [];
  }
}

async function loadFoundationReadiness() {
  foundationReadinessError.value = "";
  if (!projectId.value) return;
  try {
    foundationReadiness.value = await fetchFoundationReadiness(projectId.value);
  } catch (err: any) {
    foundationReadinessError.value = err?.message || "Foundation readiness failed";
  }
}

async function loadGenesisState() {
  genesisError.value = "";
  if (!projectId.value) return;
  try {
    const [presets, blueprint, latestRun] = await Promise.all([
      listStackPresets(projectId.value),
      fetchProjectBlueprint(projectId.value),
      fetchLatestGenesisRun(projectId.value),
    ]);
    stackPresets.value = Array.isArray(presets) ? presets : [];
    projectBlueprint.value = blueprint || null;
    latestGenesisRun.value = latestRun || null;
    if (stackPresets.value.length && !stackPresets.value.some((row) => row.key === genesisForm.value.stack_preset_key)) {
      genesisForm.value.stack_preset_key = stackPresets.value[0].key;
    }
  } catch (err: any) {
    genesisError.value = err?.message || "Failed to load genesis state";
  }
}

async function openGenesisDialog() {
  await loadGenesisState();
  showGenesisDialog.value = true;
}

async function submitGenesisBlueprint() {
  if (!projectId.value) return;
  genesisLoading.value = true;
  genesisError.value = "";
  try {
    const payload = await createProjectBlueprint(projectId.value, {
      blueprint_key: genesisForm.value.blueprint_key,
      stack_preset_key: genesisForm.value.stack_preset_key,
      deployment_profile: genesisForm.value.deployment_profile,
      readiness_enforced: genesisForm.value.readiness_enforced,
    });
    projectBlueprint.value = payload?.blueprint || null;
    latestGenesisRun.value = payload?.genesis_run || null;
    showGenesisDialog.value = false;
    await Promise.all([loadTasks(), loadFoundationReadiness()]);
    ElMessage.success("Project blueprint created");
  } catch (err: any) {
    genesisError.value = err?.message || "Failed to create blueprint";
  } finally {
    genesisLoading.value = false;
  }
}

async function runTask(task: any) {
  if (!projectId.value) return;
  taskRunLoadingId.value = task.id;
  tasksError.value = "";
  runError.value = "";
  try {
    await createRun(projectId.value, selectedExecutor.value, task.id);
    await loadTasks();
    await loadRuns();
    ElMessage.success(`Run queued for task: ${task.title}`);
  } catch (err: any) {
    const message = err?.message || "Failed to create run for task";
    tasksError.value = message;
    runError.value = message;
  } finally {
    taskRunLoadingId.value = "";
  }
}

function openConnectRepoDialog() {
  repoMessage.value = "";
  repoError.value = "";
  repoPreflightResult.value = null;
  githubInstallError.value = "";
  githubInstallMessage.value = "";
  repoForm.value = {
    repo_url: projectRepo.value?.repo_url || "",
    repo_full_name: projectRepo.value?.repo_full_name || "",
    default_branch: projectRepo.value?.default_branch || "main",
    installation_id:
      projectRepo.value?.installation_id !== null && projectRepo.value?.installation_id !== undefined
        ? String(projectRepo.value.installation_id)
        : "",
    auth_strategy: projectRepo.value?.auth_strategy || "public_https",
  };
  selectedGitHubRepo.value = projectRepo.value?.repo_full_name || "";
  void loadGitHubConnectInfo();
  if (repoForm.value.installation_id.trim()) {
    void loadGitHubInstallationRepositories();
  } else {
    githubInstallationRepos.value = [];
  }
  showConnectRepoDialog.value = true;
}

async function loadGitHubConnectInfo() {
  githubConnectLoading.value = true;
  try {
    githubConnectInfo.value = await fetchGitHubConnectInfo();
  } catch {
    githubConnectInfo.value = null;
  } finally {
    githubConnectLoading.value = false;
  }
}

async function loadGitHubInstallationRepositories() {
  const installationId = Number.parseInt(repoForm.value.installation_id.trim(), 10);
  if (!Number.isFinite(installationId) || installationId <= 0) {
    githubInstallationRepos.value = [];
    githubInstallError.value = "GitHub installation ID is required before repositories can be loaded.";
    return;
  }

  githubInstallLoading.value = true;
  githubInstallError.value = "";
  try {
    const repos = await listGitHubInstallationRepositories(installationId);
    githubInstallationRepos.value = Array.isArray(repos) ? repos : [];
    if (!githubInstallationRepos.value.length) {
      githubInstallMessage.value = "No repositories were returned for this installation yet.";
      return;
    }
    const configuredFullName = String(repoForm.value.repo_full_name || "").trim();
    const preferredRepo = githubInstallationRepos.value.find((repo) => repo.full_name === configuredFullName);
    if (preferredRepo) {
      selectedGitHubRepo.value = preferredRepo.full_name;
      applySelectedGitHubRepository(preferredRepo.full_name);
      githubInstallMessage.value = "GitHub repositories loaded. Review the selected repo URL before saving.";
      return;
    }

    if (!configuredFullName) {
      const defaultRepo = githubInstallationRepos.value[0];
      if (defaultRepo) {
        selectedGitHubRepo.value = defaultRepo.full_name;
        applySelectedGitHubRepository(defaultRepo.full_name);
      }
      githubInstallMessage.value = "GitHub repositories loaded. Review the selected repo URL before saving.";
      return;
    }

    // Keep the currently configured repository when it is outside this installation scope.
    selectedGitHubRepo.value = configuredFullName;
    githubInstallMessage.value =
      "GitHub repositories loaded. Current project repo is not in this installation list; preserving configured value.";
  } catch (err: any) {
    githubInstallationRepos.value = [];
    githubInstallError.value = err?.message || "Failed to load repositories for this GitHub installation.";
  } finally {
    githubInstallLoading.value = false;
  }
}

function applySelectedGitHubRepository(fullName: string) {
  const selectedRepo = githubInstallationRepos.value.find((repo) => repo.full_name === fullName);
  if (!selectedRepo) return;
  selectedGitHubRepo.value = selectedRepo.full_name;
  repoForm.value.repo_full_name = selectedRepo.full_name || "";
  repoForm.value.repo_url = normalizeRepoUrlForStrategy(
    repoForm.value.repo_url,
    repoForm.value.auth_strategy,
    selectedRepo.full_name || repoForm.value.repo_full_name
  );
  repoForm.value.default_branch = selectedRepo.default_branch || repoForm.value.default_branch || "main";
  const strategy = String(repoForm.value.auth_strategy || "public_https").toLowerCase();
  githubInstallMessage.value =
    strategy === "ssh"
      ? "Repository selected from GitHub and normalized for SSH runtime access."
      : "Repository selected from GitHub and normalized for HTTPS runtime access.";
}

function normalizeRepoUrlForStrategy(repoUrl: string, strategy: string, repoFullName?: string | null) {
  const normalizedStrategy = String(strategy || "public_https").toLowerCase();
  const cleaned = String(repoUrl || "").trim();
  const fullName = String(repoFullName || repoForm.value.repo_full_name || "").trim();
  if (!cleaned) return cleaned;

  const sshMatch = cleaned.match(/^git@github\.com:(.+?)(?:\.git)?$/i);
  const httpsMatch = cleaned.match(/^https?:\/\/github\.com\/(.+?)(?:\.git)?$/i);
  const path = (fullName || sshMatch?.[1] || httpsMatch?.[1] || "").replace(/\.git$/i, "");
  if (!path || !/^[^/]+\/[^/]+$/.test(path)) return cleaned;

  if (normalizedStrategy === "ssh") {
    return `git@github.com:${path}.git`;
  }
  return `https://github.com/${path}.git`;
}

function startGitHubAppInstall() {
  if (!githubConnectInfo.value?.install_url) {
    githubInstallError.value = "GitHub App install flow is not configured yet.";
    return;
  }
  const installUrl = new URL(githubConnectInfo.value.install_url);
  installUrl.searchParams.set(
    "state",
    window.btoa(
      JSON.stringify({
        projectId: projectId.value,
        returnPath: route.fullPath,
      })
    )
  );
  window.location.assign(installUrl.toString());
}

async function hydrateGitHubInstallFromRoute() {
  const rawInstallationId = Array.isArray(route.query.installation_id)
    ? route.query.installation_id[0]
    : route.query.installation_id;
  const installationId = Number.parseInt(String(rawInstallationId || ""), 10);
  if (!Number.isFinite(installationId) || installationId <= 0) return;
  if (handledGitHubInstallation.value === String(installationId)) return;

  handledGitHubInstallation.value = String(installationId);
  openConnectRepoDialog();
  repoForm.value.installation_id = String(installationId);
  githubInstallMessage.value =
    String(route.query.setup_action || "").toLowerCase() === "install"
      ? "GitHub authorization completed. Pick a repository from the connected installation."
      : "GitHub installation detected. Pick a repository to finish connecting this project.";
  await loadGitHubInstallationRepositories();

  const nextQuery = { ...route.query } as Record<string, any>;
  delete nextQuery.installation_id;
  delete nextQuery.setup_action;
  await router.replace({ query: nextQuery });
}

async function loadProjectRepo() {
  repoError.value = "";
  if (!projectId.value) return;
  try {
    projectRepo.value = await fetchProjectRepo(projectId.value);
    if (!executorSelectionDirty.value) {
      selectedExecutor.value = "codex";
    }
  } catch (err: any) {
    projectRepo.value = null;
    if (!executorSelectionDirty.value) {
      selectedExecutor.value = "codex";
    }
    if (err?.message && !String(err.message).includes("Project repository not connected")) {
      repoError.value = err.message;
    }
  }
}

async function submitConnectRepo() {
  if (!projectId.value) return;
  if (!repoForm.value.repo_url.trim()) {
    repoError.value = "Repository URL is required.";
    return;
  }
  repoLoading.value = true;
  repoError.value = "";
  repoMessage.value = "";
  try {
    repoForm.value.repo_url = normalizeRepoUrlForStrategy(
      repoForm.value.repo_url,
      repoForm.value.auth_strategy,
      repoForm.value.repo_full_name
    );
    projectRepo.value = await connectProjectRepo(projectId.value, {
      provider: "github",
      repo_url: repoForm.value.repo_url.trim(),
      repo_full_name: repoForm.value.repo_full_name.trim() || null,
      default_branch: repoForm.value.default_branch.trim() || "main",
      installation_id: repoForm.value.installation_id.trim()
        ? Number.parseInt(repoForm.value.installation_id.trim(), 10)
        : null,
      auth_strategy: repoForm.value.auth_strategy,
      created_by: "ui-user",
    });
    if (!executorSelectionDirty.value) {
      selectedExecutor.value = "codex";
    }
    await loadFoundationReadiness();
    showConnectRepoDialog.value = false;
    repoMessage.value = "Repository connected.";
  } catch (err: any) {
    repoError.value = err?.message || "Failed to connect repository";
  } finally {
    repoLoading.value = false;
  }
}

async function runRepoPreflight() {
  if (!projectId.value) return;
  if (!repoForm.value.repo_url.trim()) {
    repoError.value = "Repository URL is required.";
    return;
  }
  repoPreflightLoading.value = true;
  repoError.value = "";
  repoMessage.value = "";
  repoPreflightResult.value = null;
  try {
    repoForm.value.repo_url = normalizeRepoUrlForStrategy(
      repoForm.value.repo_url,
      repoForm.value.auth_strategy,
      repoForm.value.repo_full_name
    );
    const result = await preflightProjectRepo(projectId.value, {
      provider: "github",
      repo_url: repoForm.value.repo_url.trim(),
      repo_full_name: repoForm.value.repo_full_name.trim() || null,
      default_branch: repoForm.value.default_branch.trim() || "main",
      installation_id: repoForm.value.installation_id.trim()
        ? Number.parseInt(repoForm.value.installation_id.trim(), 10)
        : null,
      auth_strategy: repoForm.value.auth_strategy,
      clone: true,
    });
    repoPreflightResult.value = result;
    repoMessage.value = result.ok ? "Repository clone preflight passed." : "";
    repoError.value = result.ok ? "" : result.error || "Repository clone preflight failed.";
  } catch (err: any) {
    repoError.value = err?.message || "Repository clone preflight failed.";
  } finally {
    repoPreflightLoading.value = false;
  }
}

watch(
  () => repoForm.value.auth_strategy,
  () => {
    repoForm.value.repo_url = normalizeRepoUrlForStrategy(
      repoForm.value.repo_url,
      repoForm.value.auth_strategy,
      repoForm.value.repo_full_name
    );
  }
);

function resetCreateTaskForm() {
  newTask.value = {
    title: "",
    description: "",
    category: "func",
    stage: projectStatus.value || projectContext.stage || "PLAN",
    status: "PENDING",
    assignee: "",
    document_id: "",
    created_by: "ui-user",
    branch_strategy: "auto",
    base_branch: taskDefaultBaseBranch.value,
    branch_name: "",
  };
  createTaskError.value = "";
}

function openCreateTaskDialog() {
  resetCreateTaskForm();
  showCreateTaskDialog.value = true;
}

async function submitCreateTask() {
  if (!projectId.value) return;
  if (!newTask.value.title.trim()) {
    createTaskError.value = "Task title is required.";
    return;
  }
  if (["new", "existing"].includes(newTask.value.branch_strategy) && !newTask.value.branch_name.trim()) {
    createTaskError.value = "Branch name is required for new or existing branch strategies.";
    return;
  }
  createTaskLoading.value = true;
  createTaskError.value = "";
  try {
    await createTask(projectId.value, {
      title: newTask.value.title.trim(),
      description: newTask.value.description.trim() || null,
      category: newTask.value.category,
      stage: newTask.value.stage,
      status: newTask.value.status,
      assignee: newTask.value.assignee.trim() || null,
      document_id: newTask.value.document_id || null,
      created_by: newTask.value.created_by.trim() || null,
      branch_strategy: newTask.value.branch_strategy,
      base_branch:
        newTask.value.branch_strategy === "new"
          ? newTask.value.base_branch.trim() || taskDefaultBaseBranch.value
          : null,
      branch_name:
        newTask.value.branch_strategy === "auto" ? null : newTask.value.branch_name.trim() || null,
      source: "manual",
    });
    showCreateTaskDialog.value = false;
    await loadTasks();
    if (showTasksDialog.value) {
      showTasksDialog.value = true;
    }
    ElMessage.success("Task created.");
  } catch (err: any) {
    createTaskError.value = err?.message || "Failed to create task";
  } finally {
    createTaskLoading.value = false;
  }
}

watch(
  () => newTask.value.branch_strategy,
  (strategy, previousStrategy) => {
    if (strategy === "new" && previousStrategy !== "new") {
      newTask.value.base_branch = newTask.value.base_branch.trim() || taskDefaultBaseBranch.value;
      newTask.value.branch_name = newTask.value.branch_name.trim() || suggestedTaskBranchName.value;
      return;
    }
    if (strategy === "existing") {
      newTask.value.base_branch = taskDefaultBaseBranch.value;
      if (previousStrategy === "auto") {
        newTask.value.branch_name = "";
      }
      return;
    }
    newTask.value.base_branch = taskDefaultBaseBranch.value;
    newTask.value.branch_name = "";
  }
);

watch(
  () => newTask.value.title,
  (title, previousTitle) => {
    if (newTask.value.branch_strategy !== "new") return;
    const currentBranch = newTask.value.branch_name.trim();
    const previousSuggestion = suggestTaskBranchName(previousTitle || "");
    if (!currentBranch || currentBranch === previousSuggestion) {
      newTask.value.branch_name = suggestTaskBranchName(title);
    }
  }
);

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
    updateProjectContext({
      projectId: meta.id || projectId.value,
      projectName: meta.name || projectContext.projectName,
      stage: meta.status || projectContext.stage,
      updatedAt: new Date().toISOString(),
    });
  } catch {
    // non-blocking
  }
}

async function loadProjectSummary() {
  if (!projectId.value) return;
  try {
    const data = await fetchProjectSummary(projectId.value);
    planMeta.value = {
      plan_id: data.plan_id,
      plan_fresh: data.plan_fresh,
      requirements_status: data.requirements_status,
      requirements_sha: data.requirements_sha,
      plan_requirements_sha: data.plan_requirements_sha,
      plan_created_at: data.plan_created_at,
      requirements_version: data.requirements_version,
    };
    latestDelivery.value = data.latest_run || null;
    architectureSummary.value = data.architecture_profile || createEmptyArchitectureProfileSummary();
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
      hasActiveRun: Boolean(data.latest_run?.run_id),
    });
  } catch {
    /* ignore */
  }
}

async function openArchitectureDialog() {
  if (!projectId.value) return;
  showArchitectureDialog.value = true;
  architectureLoading.value = true;
  architectureError.value = "";
  try {
    const profile = await fetchProjectArchitectureProfile(projectId.value);
    syncArchitectureEditor(profile);
  } catch (err: any) {
    architectureProfile.value = null;
    architectureSummaryText.value = architectureSummary.value?.summary || "";
    architectureEditorValue.value = JSON.stringify({}, null, 2);
    architectureError.value = err?.message || "No saved architecture profile yet.";
  } finally {
    architectureLoading.value = false;
  }
}

async function bootstrapArchitectureProfile(refreshRepoMap = false) {
  if (!projectId.value) return;
  architectureBootstrapLoading.value = true;
  architectureError.value = "";
  try {
    const profile = await bootstrapProjectArchitectureProfile(projectId.value, {
      refresh_repo_map: refreshRepoMap,
      created_by: "ui-user",
    });
    syncArchitectureEditor(profile);
    await loadProjectSummary();
    await loadFoundationReadiness();
    ElMessage.success("Architecture profile bootstrapped.");
  } catch (err: any) {
    architectureError.value = err?.message || "Failed to bootstrap architecture profile";
  } finally {
    architectureBootstrapLoading.value = false;
  }
}

async function deriveArchitectureProfile(refreshRepoMap = false) {
  if (!projectId.value) return;
  architectureDeriveLoading.value = true;
  architectureError.value = "";
  try {
    const profile = await deriveProjectArchitectureProfile(projectId.value, {
      refresh_repo_map: refreshRepoMap,
      bootstrap_if_missing: true,
      updated_by: "ui-user",
    });
    syncArchitectureEditor(profile);
    await loadProjectSummary();
    await loadFoundationReadiness();
    ElMessage.success("Architecture profile derived.");
  } catch (err: any) {
    architectureError.value = err?.message || "Failed to derive architecture profile";
  } finally {
    architectureDeriveLoading.value = false;
  }
}

async function saveArchitectureProfileDraft() {
  if (!projectId.value) return;
  architectureSaveLoading.value = true;
  architectureError.value = "";
  try {
    const profileJson = JSON.parse(architectureEditorValue.value || "{}");
    const profile = await saveProjectArchitectureProfile(projectId.value, {
      status: architectureProfile.value?.status || "ACTIVE",
      source: architectureProfile.value?.source || "MANUAL",
      summary: architectureSummaryText.value.trim() || null,
      profile_json: profileJson,
      created_by: architectureProfile.value?.created_by || "ui-user",
      updated_by: "ui-user",
    });
    syncArchitectureEditor(profile);
    await loadProjectSummary();
    await loadFoundationReadiness();
    ElMessage.success("Architecture profile saved.");
  } catch (err: any) {
    architectureError.value = err?.message || "Failed to save architecture profile";
  } finally {
    architectureSaveLoading.value = false;
  }
}

async function loadRuns() {
  if (!projectId.value) return;
  runsLoading.value = true;
  runError.value = "";
  try {
    runs.value = await listRuns(projectId.value);
    updateProjectContext({
      latestRunId: runs.value[0]?.id || "",
      runStatus: runs.value[0]?.status || "IDLE",
      hasActiveRun: Boolean(runs.value.length),
      updatedAt: new Date().toISOString(),
    });
    await loadProjectSummary();
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

async function unblockRunById(runId: string) {
  runError.value = "";
  runUnblockLoading.value = { ...runUnblockLoading.value, [runId]: true };
  try {
    const result = await unblockRun(runId);
    const detail = result?.detail || "Unblock requested.";
    ElMessage.success(detail);
    await loadRuns();
    await loadWorkItems();
    await loadRunEvents();
  } catch (err: any) {
    runError.value = err?.message || "Failed to unblock run";
  } finally {
    runUnblockLoading.value = { ...runUnblockLoading.value, [runId]: false };
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
    updateProjectContext({
      stage: updated.status,
      updatedAt: new Date().toISOString(),
    });
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
  error.value = "";
  await loadProjectSummary();
  try {
    const history = await fetchPlanHistory(projectId.value);
    planHistory.value = history.entries || [];
  } catch {
    /* ignore */
  }
  await loadHealth();
  await loadLifecycleScore();
  await loadLifecycleHistory();
  await loadDocuments();
  await loadTasks();
  await loadImprovementRequests();
  await loadRequirementSummaryCards();
    await loadFoundationReadiness();
    await loadGenesisState();
  await loadProjectMeta();
  await loadRuns();
  await loadProjectRepo();
  await loadGitHubConnectInfo();
  await loadWorkItems();
  await loadRunEvents();
  await hydrateGitHubInstallFromRoute();
});

watch(
  () => [route.query.installation_id, route.query.setup_action],
  () => {
    void hydrateGitHubInstallFromRoute();
  }
);
</script>
