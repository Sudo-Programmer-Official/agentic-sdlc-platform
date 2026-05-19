<template>
  <div class="space-y-6 project-overview-page">
    <div class="project-overview-hero rounded-2xl border border-slate-200 p-5 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-3xl font-semibold text-slate-900">Project Overview</h1>
        <p class="text-slate-600">Review project state and enter Mission Control when ready.</p>
      </div>
      <el-button type="primary" :disabled="!projectId || projectStatus !== 'RUN'" @click="goToRun">
        Enter Mission Control
      </el-button>
      </div>
    </div>

    <div class="rounded-2xl border-2 border-sky-300 bg-sky-50 p-4 shadow-sm">
      <div class="text-xs font-semibold uppercase tracking-[0.2em] text-sky-700">Live Execution Status</div>
      <div class="mt-2 grid gap-2 text-sm font-semibold text-slate-900 md:grid-cols-3">
        <div>Queue: {{ overviewStatusBanner.queue }}</div>
        <div>In Progress: {{ overviewStatusBanner.inProgress }} ({{ overviewStatusBanner.inProgressTaskName }})</div>
        <div>Completed: {{ overviewStatusBanner.completed }} / {{ overviewStatusBanner.total }}</div>
      </div>
    </div>

    <div class="project-overview-primary rounded-2xl border border-slate-200 p-5 shadow-sm">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div class="text-xs uppercase tracking-wide text-slate-400">Primary Action</div>
          <div class="mt-1 text-lg font-semibold text-slate-900">{{ journeyHeadline }}</div>
          <div class="text-sm text-slate-600">{{ journeyHint }}</div>
        </div>
        <div class="flex items-center gap-2">
          <el-tag effect="light" type="info">{{ stage }}</el-tag>
          <el-button type="primary" @click="runPrimaryJourneyAction">{{ journeyPrimaryActionLabel }}</el-button>
        </div>
      </div>
    </div>

    <div class="grid gap-4 lg:grid-cols-2">
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs uppercase tracking-wide text-slate-400">Governed Content Runtime</div>
        <div class="mt-2 text-sm text-slate-700">
          Hero title preview:
          <strong class="ml-1">
            <ContentSlot
              v-if="projectId"
              :project-id="projectId"
              content-key="landing.hero.title"
              fallback="From Prompt to Production. Governed."
              environment="PREVIEW"
              :refresh-ms="5000"
            />
          </strong>
        </div>
      </div>
      <ContentEditorPanel v-if="projectId" :project-id="projectId" />
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
        <div class="mt-2">
          <el-tag effect="light" :type="latestRepositoryStateTagType">{{ latestRepositoryStateLabel }}</el-tag>
        </div>
        <div class="mt-1 text-xs text-slate-500">{{ latestRepositoryStateDescription }}</div>
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
          Derivation confidence: {{ architectureSummary?.derivation_confidence || "LOW" }}
          · Derived from: {{ architectureSummary?.derived_from?.join(", ") || "—" }}
        </div>
        <div class="text-xs text-slate-500">
          Protected zones: {{ architectureSummary?.protected_zone_count ?? 0 }}
          · Validation recipes: {{ architectureSummary?.validation_recipe_count ?? 0 }}
        </div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-center justify-between gap-2">
          <div class="text-xs uppercase tracking-wide text-slate-400">Design Contract</div>
          <el-button size="small" plain :disabled="!projectId" @click="openDesignContractDialog">
            Manage
          </el-button>
        </div>
        <div class="mt-2 text-sm font-semibold text-slate-900">
          {{ designContractIdentityName }}
        </div>
        <div class="mt-1 text-xs text-slate-600">
          {{ designContractIdentityTone }} · {{ designContractIdentityPersonality }}
        </div>
        <div class="mt-2 text-xs text-slate-500">
          Tokens: {{ designContractTokenCount }} · Components: {{ designContractRegistryCount }}
        </div>
        <div class="text-xs text-slate-500">
          Typography: {{ designContractTypographyLabel }} · Layout: {{ designContractLayoutLabel }}
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
        <div class="mt-1 text-xs text-slate-700">
          Production readiness score: <span class="font-semibold">{{ productionReadinessScore }}/100</span>
        </div>
        <div class="mt-1 text-xs text-slate-600">
          {{ foundationReadiness?.recommended_next_step || "Evaluate repository and architecture prerequisites." }}
        </div>
        <div class="mt-2 text-xs text-slate-500">
          Missing: {{ foundationReadiness?.missing_prerequisites?.join(", ") || "none" }}
        </div>
        <div v-if="productionReadinessActions.length" class="mt-2 text-xs text-slate-600">
          Next actions: {{ productionReadinessActions.join(" · ") }}
        </div>
        <div v-if="foundationReadinessError" class="mt-2 text-xs text-rose-600">{{ foundationReadinessError }}</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <DeploymentTrustSurfaceCard v-if="deploymentReadinessContract" :contract="deploymentReadinessContract" />
        <template v-else>
          <div class="text-xs uppercase tracking-wide text-slate-400">Deployment Trust Surface</div>
          <div class="mt-2 text-sm font-semibold" :class="deploymentTrustTone">{{ deploymentTrustSummary.tier }}</div>
          <div class="mt-1 text-xs text-slate-700">
            Confidence: <span class="font-semibold">{{ deploymentTrustSummary.confidencePct }}%</span>
            · Rollback confidence: <span class="font-semibold">{{ deploymentTrustSummary.rollbackConfidencePct }}%</span>
          </div>
          <div class="mt-1 text-xs text-slate-600">{{ deploymentTrustSummary.evidence }}</div>
          <div v-if="deploymentTrustSummary.blockers.length" class="mt-2 text-xs text-slate-500">
            Blockers: {{ deploymentTrustSummary.blockers.join(" · ") }}
          </div>
        </template>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-center justify-between gap-2">
          <div class="text-xs uppercase tracking-wide text-slate-400">Environment Readiness</div>
          <el-button size="small" plain :disabled="!projectId" @click="goToEnvironmentCenter">Open</el-button>
        </div>
        <div class="mt-2 text-sm font-semibold text-slate-900">{{ projectEnvironmentReadiness.scorePct }}% overall</div>
        <div class="mt-2 grid gap-1 text-xs text-slate-600">
          <div v-for="env in projectEnvironmentReadiness.environments" :key="env.environment" class="flex items-center justify-between">
            <span>{{ env.environment }}</span>
            <span>{{ env.scorePct }}% · user blockers {{ env.userPending }}</span>
          </div>
        </div>
        <div class="mt-2 text-xs text-slate-500">
          Managed by platform: orchestration, retries, recovery. User-owned: credentials, domains, integrations, approvals.
        </div>
        <div v-if="projectEnvironmentReadiness.nextUserActions.length" class="mt-2 text-xs text-slate-600">
          Next: {{ projectEnvironmentReadiness.nextUserActions.map((item) => item.label).join(" · ") }}
        </div>
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

    <div class="rounded-xl border border-sky-200 bg-sky-50 p-5 shadow-sm project-overview-panel">
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

    <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm project-overview-panel">
      <div class="text-sm uppercase tracking-wide text-slate-400">Actions</div>
      <div class="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-3 project-actions-grid">
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
            <el-tooltip :content="startRunBlockedReason" placement="top" :disabled="!startRunBlockedReason">
              <span>
                <el-button
                  size="small"
                  :disabled="projectStatus !== 'RUN' || runs.some(r => r.status === 'RUNNING') || Boolean(startRunBlockedReason)"
                  @click="startRun"
                >
                  Start Run
                </el-button>
              </span>
            </el-tooltip>
            <el-button size="small" plain :disabled="!startRunBlockedReason" @click="openArchitectureDialog">
              Prepare Architecture
            </el-button>
            <el-button size="small" plain @click="loadRuns">Refresh</el-button>
          </div>
        </div>
        <div v-if="startRunBlockedReason" class="text-xs text-amber-700 mt-2">
          {{ startRunBlockedReason }}
        </div>
        <div v-if="overviewPolicyBlockHint" class="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {{ overviewPolicyBlockHint }}
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
              <el-button size="small" plain :loading="Boolean(runResumeLoading[row.id])" :disabled="row.status !== 'PAUSED'" @click="resumeRunById(row.id)">
                Resume
              </el-button>
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

    <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
      <div class="flex items-center justify-between gap-3">
        <div>
          <div class="text-sm uppercase tracking-wide text-slate-400">Requirement-Centric Operational Dashboard</div>
          <div class="text-xs text-slate-500">Bounded project understanding, regression clusters, recovery hotspots, and deployment risk signals.</div>
        </div>
        <el-button size="small" plain :loading="memoryDashboardLoading" @click="loadMemoryDashboard">Refresh</el-button>
      </div>
      <div v-if="memoryDashboardError" class="text-xs text-rose-600">{{ memoryDashboardError }}</div>
      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div class="rounded-lg border border-slate-200 p-4">
          <div class="text-xs uppercase tracking-wide text-slate-400">Summary Artifacts</div>
          <div class="mt-1 text-lg font-semibold text-slate-900">{{ memoryUnderstanding?.summary_artifact_count ?? 0 }}</div>
          <div class="text-xs text-slate-500">Compressed memory units retained for bounded retrieval.</div>
        </div>
        <div class="rounded-lg border border-slate-200 p-4">
          <div class="text-xs uppercase tracking-wide text-slate-400">Unstable Requirements</div>
          <div class="mt-1 text-lg font-semibold text-slate-900">{{ unstableRequirements.length }}</div>
          <div class="text-xs text-slate-500">Requirements with low stability or repeated retries.</div>
        </div>
        <div class="rounded-lg border border-slate-200 p-4">
          <div class="text-xs uppercase tracking-wide text-slate-400">Recovery Hotspots</div>
          <div class="mt-1 text-lg font-semibold text-slate-900">{{ recoveryHotspots.length }}</div>
          <div class="text-xs text-slate-500">Repeated recovery patterns in recent operational memory.</div>
        </div>
        <div class="rounded-lg border border-slate-200 p-4">
          <div class="text-xs uppercase tracking-wide text-slate-400">Deployment Risk</div>
          <div class="mt-1 text-lg font-semibold text-slate-900">{{ deploymentRiskSignals }}</div>
          <div class="text-xs text-slate-500">Derived from linked critical/recovery/deployment events.</div>
        </div>
      </div>
      <div class="grid gap-4 md:grid-cols-2">
        <div class="rounded-lg border border-slate-200 p-4">
          <div class="text-xs uppercase tracking-wide text-slate-400">Top Unstable Requirements</div>
          <ul v-if="unstableRequirements.length" class="mt-2 space-y-1 text-xs text-slate-600">
            <li v-for="card in unstableRequirements" :key="card.requirement_id">
              {{ card.requirement_id }} · stability {{ card.stability_score }} · retries {{ card.retry_count }}
            </li>
          </ul>
          <div v-else class="mt-2 text-xs text-slate-500">No unstable requirement cluster detected.</div>
        </div>
        <div class="rounded-lg border border-slate-200 p-4">
          <div class="text-xs uppercase tracking-wide text-slate-400">Recovery Hotspots</div>
          <ul v-if="recoveryHotspots.length" class="mt-2 space-y-1 text-xs text-slate-600">
            <li v-for="item in recoveryHotspots" :key="item.name">{{ item.name }} · {{ item.count }}</li>
          </ul>
          <div v-else class="mt-2 text-xs text-slate-500">No recovery hotspot pattern in current bounded window.</div>
        </div>
      </div>
      <div class="rounded-lg border border-slate-200 p-4">
        <div class="text-xs uppercase tracking-wide text-slate-400">Project Understanding Summary</div>
        <div class="mt-2 text-xs text-slate-600">
          {{ memoryUnderstanding?.top_risks?.join(" · ") || "No high-risk synthesis signal currently." }}
        </div>
        <div class="mt-2 text-xs text-slate-500">
          Stale architecture zones: {{ staleArchitectureZones }}
        </div>
        <div class="mt-2 text-xs text-slate-500">
          Latest synthesis artifacts: {{ memorySummaries.slice(0, 3).map((row) => `${row.summary_type}@v${row.version}`).join(", ") || "none" }}
        </div>
      </div>
    </div>

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
          <el-button
            v-if="canBootstrapEmptyRepo"
            type="warning"
            plain
            :loading="repoBootstrapLoading"
            @click="bootstrapEmptyRepo"
          >
            Initialize Empty Repo
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
                {{ modalArchitectureSummary.repo_layout_label || "Repository" }}
                <span class="text-slate-500">· {{ modalArchitectureSummary.status || "MISSING" }}</span>
              </div>
              <div class="mt-1 text-xs text-slate-600">
                {{ modalArchitectureSummary.summary || "No architecture profile saved yet." }}
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
            <div><strong>Packages:</strong> {{ modalArchitectureSummary.packages.join(", ") || "—" }}</div>
            <div><strong>Execution slice:</strong> {{ modalArchitectureSummary.execution_slice.join(", ") || "—" }}</div>
            <div><strong>Protected zones:</strong> {{ modalArchitectureSummary.protected_zones.join(", ") || "—" }}</div>
            <div><strong>Safe zones:</strong> {{ modalArchitectureSummary.safe_zones.join(", ") || "—" }}</div>
            <div><strong>Commands:</strong> {{ modalArchitectureSummary.commands.join(", ") || "—" }}</div>
            <div><strong>Validation recipes:</strong> {{ modalArchitectureSummary.validation_recipes.join(", ") || "—" }}</div>
            <div><strong>Confidence:</strong> {{ modalArchitectureSummary.derivation_confidence || "LOW" }}</div>
            <div><strong>Derived from:</strong> {{ modalArchitectureSummary.derived_from.join(", ") || "—" }}</div>
          </div>
          <div v-if="modalArchitectureSummary.assumptions_used.length" class="mt-3 text-xs text-slate-500">
            <strong>Assumptions:</strong> {{ modalArchitectureSummary.assumptions_used.join(" · ") }}
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

    <el-dialog v-model="showDesignContractDialog" title="Design Contract" width="760px">
      <div class="space-y-4">
        <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div class="text-sm font-semibold text-slate-900">Governed UI Profile</div>
          <div class="mt-1 text-xs text-slate-600">
            Define design identity, tokens, typography, component rules, and layout defaults used by runtime generation.
          </div>
          <div class="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
            <div><strong>Identity:</strong> {{ designContractIdentityName }}</div>
            <div><strong>Tone:</strong> {{ designContractIdentityTone }}</div>
            <div><strong>Personality:</strong> {{ designContractIdentityPersonality }}</div>
            <div><strong>Tokens:</strong> {{ designContractTokenCount }}</div>
          </div>
        </div>

        <div v-if="designContractLoading" class="text-sm text-slate-500">Loading design contract…</div>
        <template v-else>
          <div class="grid gap-2 md:grid-cols-[1fr_auto]">
            <el-select v-model="selectedDesignPreset" placeholder="Select experience preset">
              <el-option
                v-for="preset in designPresetOptions"
                :key="preset.value"
                :label="preset.label"
                :value="preset.value"
              />
            </el-select>
            <el-button type="primary" plain :disabled="!selectedDesignPreset" @click="applyDesignPreset">
              Apply Preset
            </el-button>
          </div>
          <div
            v-if="presetDiffRows.length"
            class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800"
          >
            <div class="font-semibold">Preset changes preview</div>
            <div class="mt-1">Applying this preset will update:</div>
            <ul class="mt-1 list-disc pl-5">
              <li v-for="row in presetDiffRows.slice(0, 10)" :key="row.path">
                <span class="font-mono">{{ row.path }}</span>:
                <span class="text-slate-700">{{ row.from }}</span>
                <span class="mx-1">→</span>
                <span class="text-slate-900">{{ row.to }}</span>
              </li>
            </ul>
            <div v-if="presetDiffRows.length > 10" class="mt-1">
              +{{ presetDiffRows.length - 10 }} more field changes
            </div>
          </div>
          <div class="text-xs text-slate-500">
            Presets set a governed baseline. You can still refine the JSON before saving.
          </div>
          <div class="rounded-xl border border-slate-200 bg-white p-3 space-y-3">
            <div class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Experience Blueprint</div>
            <el-select v-model="designContractForm.experience_blueprint" placeholder="Select blueprint">
              <el-option
                v-for="preset in designPresetOptions"
                :key="preset.value"
                :label="preset.label"
                :value="preset.value"
              />
            </el-select>
          </div>
          <div class="rounded-xl border border-slate-200 bg-white p-3 space-y-3">
            <div class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Visual Tone</div>
            <div class="grid gap-2 md:grid-cols-2">
              <el-input v-model="designContractForm.identity.tone" placeholder="Tone (e.g. technical_minimal_premium)" />
              <el-input v-model="designContractForm.identity.personality" placeholder="Personality (e.g. confident_operational_clean)" />
            </div>
            <el-input v-model="designContractForm.identity.name" placeholder="Brand / Product name" />
          </div>
          <div class="rounded-xl border border-slate-200 bg-white p-3 space-y-3">
            <div class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Layout Density</div>
            <div class="grid gap-2 md:grid-cols-3">
              <el-select v-model="designContractForm.typography.density">
                <el-option label="Compact" value="compact" />
                <el-option label="Comfortable" value="comfortable" />
                <el-option label="Spacious" value="spacious" />
              </el-select>
              <el-select v-model="designContractForm.layout.spacing">
                <el-option label="Compact" value="compact" />
                <el-option label="Airy" value="airy" />
                <el-option label="Structured" value="structured" />
              </el-select>
              <el-select v-model="designContractForm.layout.container_width">
                <el-option label="Narrow" value="narrow" />
                <el-option label="Wide" value="wide" />
                <el-option label="Full" value="full" />
              </el-select>
            </div>
          </div>
          <div class="rounded-xl border border-slate-200 bg-white p-3 space-y-3">
            <div class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Component Policy</div>
            <el-checkbox-group v-model="designContractForm.allowed_components">
              <el-checkbox v-for="component in componentPolicyOptions" :key="component" :label="component">
                {{ component }}
              </el-checkbox>
            </el-checkbox-group>
          </div>
          <div class="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-2">
            <div class="flex items-center justify-between">
              <div class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Advanced</div>
              <el-switch v-model="showDesignAdvancedEditor" />
            </div>
            <div class="text-xs text-slate-500">Enable raw JSON editing only when needed for advanced overrides.</div>
          </div>
          <template v-if="showDesignAdvancedEditor">
            <el-button size="small" plain @click="syncDesignEditorFromForm">Refresh JSON from guided fields</el-button>
          <el-input
            v-model="designContractEditorValue"
            type="textarea"
            :rows="18"
            placeholder='{"identity": {...}, "tokens": {...}, "typography": {...}, "components": {...}, "layout": {...}}'
            class="font-mono"
          />
            <el-button size="small" plain @click="applyDesignEditorToForm">Apply JSON to guided fields</el-button>
          </template>
        </template>

        <div v-if="designContractError" class="text-sm text-rose-600">{{ designContractError }}</div>
        <div class="flex justify-end gap-2">
          <el-button @click="showDesignContractDialog = false">Close</el-button>
          <el-button type="primary" :loading="designContractSaveLoading" @click="saveDesignContractDraft">
            Save Contract
          </el-button>
        </div>
      </div>
    </el-dialog>

    <el-dialog
      v-model="showTasksDialog"
      title="Tasks"
      :width="tasksDialogFullscreen ? '96vw' : '92vw'"
      :top="tasksDialogFullscreen ? '2vh' : '4vh'"
      :fullscreen="tasksDialogFullscreen"
      class="tasks-dialog"
      append-to-body
      destroy-on-close
    >
      <div class="mb-3 flex items-center justify-between gap-3">
        <div class="text-xs text-slate-500">
          Create tasks manually or from approved requirements. Use Run All to execute in deterministic order.
        </div>
        <div class="flex items-center gap-2">
          <el-button size="small" plain @click="openTasksPage">
            Open Full Page
          </el-button>
          <el-button size="small" plain @click="tasksDialogFullscreen = !tasksDialogFullscreen">
            {{ tasksDialogFullscreen ? "Exit Fullscreen" : "Fullscreen" }}
          </el-button>
          <el-button type="primary" size="small" plain @click="openCreateTaskDialog">
            Create Task
          </el-button>
          <el-button
            type="success"
            size="small"
            plain
            :disabled="!selectedRunnableTasks.length || runAllLoading"
            :loading="runSelectedLoading"
            @click="runSelectedTasksOrdered"
          >
            Run Selected (Ordered)
          </el-button>
          <el-button
            type="success"
            size="small"
            plain
            :disabled="!runnableTasks.length || runAllLoading"
            :loading="runAllLoading"
            @click="runAllTasksOrdered"
          >
            Run All (Ordered)
          </el-button>
        </div>
      </div>
      <div class="mb-3 flex flex-wrap gap-2 text-xs">
        <el-tag effect="light" type="info">Total {{ filteredTasks.length }} / {{ sortedTasks.length }}</el-tag>
        <el-tag effect="light" type="warning">Queued {{ taskStatusCountsGlobal.queued }}</el-tag>
        <el-tag effect="light" type="primary">In Progress {{ taskStatusCountsGlobal.inProgress }}</el-tag>
        <el-tag effect="light" type="success">Done {{ taskStatusCountsGlobal.done }}</el-tag>
        <el-tag effect="light" type="info">Visible Done {{ taskStatusCounts.done }}</el-tag>
        <el-tag effect="light" type="danger">Blocked/Failed {{ taskStatusCountsGlobal.failed }}</el-tag>
        <el-tag effect="light" type="info">Selected {{ selectedTaskIds.length }}</el-tag>
        <el-tag effect="light" type="success">Batch Runnable {{ selectedRunnableTasks.length }}</el-tag>
        <el-tag v-if="batchExecutionTotal > 0" effect="light" type="primary">Current Step {{ batchExecutionStepLabel }}</el-tag>
        <el-tag v-if="batchExecutionTotal > 0" effect="light" type="warning">Batch Remaining {{ batchExecutionRemaining }}</el-tag>
        <el-tag v-if="batchExecutionNextTitle" effect="light" type="info">Auto-picked next: {{ batchExecutionNextTitle }}</el-tag>
      </div>
      <div class="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <span class="text-slate-500">Attempt filter:</span>
        <el-tag
          v-for="option in attemptFilterOptions"
          :key="option.value"
          effect="light"
          :type="attemptFilter === option.value ? option.type : 'info'"
          class="cursor-pointer"
          @click="attemptFilter = option.value"
        >
          {{ option.label }}
        </el-tag>
        <el-switch
          v-model="showCompletedTasks"
          size="small"
          inline-prompt
          active-text="Show completed"
          inactive-text="Hide completed"
        />
        <span class="ml-3 text-slate-500">Execution mode:</span>
        <el-radio-group v-model="selectedExecutionMode" size="small">
          <el-radio-button label="smart">Smart</el-radio-button>
          <el-radio-button label="manual">My Order</el-radio-button>
        </el-radio-group>
        <el-tag v-if="shouldPollOverview()" effect="light" type="warning">
          Live polling active
        </el-tag>
      </div>
      <div v-if="runAllProgressLabel" class="mb-2 text-xs text-slate-500">{{ runAllProgressLabel }}</div>
      <el-table
        ref="tasksTableRef"
        :data="filteredTasks"
        size="small"
        max-height="65vh"
        row-key="id"
        :reserve-selection="true"
        @selection-change="onTaskSelectionChange"
        @select="onTaskSelectChange"
      >
        <el-table-column type="selection" width="46" :selectable="canSelectTaskForOrderedRun" />
        <el-table-column label="#" width="56">
          <template #default="scope">
            <span class="font-mono text-xs text-slate-500">{{ scope.$index + 1 }}</span>
          </template>
        </el-table-column>
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
        <el-table-column label="Lineage" min-width="220">
          <template #default="scope">
            <div class="text-xs text-slate-700">{{ taskLineageSourceLabel(scope.row) }}</div>
            <div class="font-mono text-xs text-slate-500">
              task {{ shortId(scope.row.id) }} · run {{ taskLinkedRunLabel(scope.row) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Attempt" width="120">
          <template #default="scope">
            <el-tag size="small" effect="light" :type="attemptTagType(scope.row)">
              {{ taskAttemptTypeLabel(scope.row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Status" width="140">
          <template #default="scope">
            <span>{{ taskEffectiveStatus(scope.row) }}</span>
            <div class="mt-1">
              <el-tag v-if="taskCompletionBadgeLabel(scope.row)" size="small" effect="light" :type="taskCompletionBadgeType(scope.row)">
                {{ taskCompletionBadgeLabel(scope.row) }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Branch" width="200">
          <template #default="scope">
            <div class="text-sm text-slate-800">{{ taskBranchLabel(scope.row) }}</div>
            <div class="text-xs text-slate-500">{{ taskBranchDetail(scope.row) }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="generated_from_document_version" label="Doc Ver" width="90" />
        <el-table-column label="Action" width="140">
          <template #default="scope">
            <div class="flex flex-col items-start gap-1">
              <el-button
                type="primary"
                size="small"
                text
                :disabled="runAllLoading || !canRunTask(scope.row)"
                :loading="taskRunLoadingId === scope.row.id"
                @click="runTask(scope.row)"
              >
                Run This Task
              </el-button>
              <el-button
                v-if="canForceRunTask(scope.row)"
                type="warning"
                size="small"
                text
                :disabled="runAllLoading"
                :loading="taskRunLoadingId === scope.row.id"
                @click="runTask(scope.row, true)"
              >
                Force Run
              </el-button>
            </div>
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
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";

import DeploymentTrustSurfaceCard from "../components/DeploymentTrustSurfaceCard.vue";
import StageBadge from "../components/StageBadge.vue";
import ContentSlot from "../components/ContentSlot.vue";
import ContentEditorPanel from "../components/ContentEditorPanel.vue";
import { buildDeploymentTrustSummary, clampPercent } from "../composables/deploymentTrust";
import { buildEnvironmentReadiness } from "../composables/environmentReadiness";
import { projectContext, updateProjectContext } from "../state/projectContext";
import { fetchProjectSummary, fetchPlanHistory, fetchRequirementSummary } from "../api/requirements";
import {
  createEmptyArchitectureProfileSummary,
  createEmptyFoundationReadiness,
  fetchProjectArchitectureProfile,
  bootstrapProjectArchitectureProfile,
  deriveProjectArchitectureProfile,
  saveProjectArchitectureProfile,
  fetchDesignContract,
  saveDesignContract,
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
  resumeRun,
  unblockRun,
  listWorkItems,
  listRunEvents,
  fetchProjectRepo,
  connectProjectRepo,
  preflightProjectRepo,
  bootstrapProjectRepo,
  fetchGitHubConnectInfo,
  listGitHubInstallationRepositories,
  fetchFoundationReadiness,
  listDeploymentConnectors,
  listImprovementRequests,
  listStackPresets,
  fetchProjectBlueprint,
  fetchLatestGenesisRun,
  createProjectBlueprint,
  explainProjectMemory,
  fetchProjectMemorySummaries,
  fetchProjectUnderstanding,
  getProjectEnvironmentChecklists,
  fetchProjectDeploymentReadiness,
  fetchTaskRerunPreflight,
  createTaskRerunNoopAttempt,
  getOrCreateActionRequestKey,
  getActiveTenantId,
} from "../api/lifecycle";

const route = useRoute();
const router = useRouter();
const error = ref("");

const projectId = computed(() => (route.params.projectId as string) || projectContext.projectId);
const projectName = computed(() => projectContext.projectName || "Project");
const stage = computed(() => projectContext.stage || "UNKNOWN");
const runStatusPriority: Record<string, number> = {
  RUNNING: 0,
  CLAIMED: 1,
  QUEUED: 2,
  PAUSED: 3,
  FAILED: 4,
  CANCELED: 5,
  DONE: 6,
  COMPLETED: 7,
};
function runTimestampScore(run: any) {
  return (
    Date.parse(String(run?.started_at || "")) ||
    Date.parse(String(run?.created_at || "")) ||
    Date.parse(String(run?.updated_at || "")) ||
    0
  );
}
function canonicalizeRuns(runList: any[]) {
  const rows = Array.isArray(runList) ? [...runList] : [];
  return rows.sort((a, b) => {
    const aStatus = String(a?.status || "").toUpperCase();
    const bStatus = String(b?.status || "").toUpperCase();
    const aPriority = runStatusPriority[aStatus] ?? 99;
    const bPriority = runStatusPriority[bStatus] ?? 99;
    if (aPriority !== bPriority) return aPriority - bPriority;
    const byTime = runTimestampScore(b) - runTimestampScore(a);
    if (byTime !== 0) return byTime;
    return String(b?.id || "").localeCompare(String(a?.id || ""));
  });
}
const runSummary = computed(() => {
  if (!runs.value.length) return "No runs yet";
  return `${runs.value.length} run${runs.value.length === 1 ? "" : "s"}`;
});
const latestRunRecord = computed(() => runs.value[0] || null);
const latestRunText = computed(() => latestRunRecord.value?.id || projectContext.latestRunId || "None");
const latestRepositoryState = computed(() => {
  const summary = latestRunRecord.value?.summary;
  if (!summary || typeof summary !== "object") return "ACTIVE_PRODUCT";
  const raw = String((summary as Record<string, any>).repository_state || "").trim().toUpperCase();
  if (raw === "GENESIS" || raw === "EARLY_BUILD" || raw === "ACTIVE_PRODUCT" || raw === "PRODUCTION_CRITICAL") {
    return raw;
  }
  return "ACTIVE_PRODUCT";
});
const latestRepositoryStateLabel = computed(() => {
  if (latestRepositoryState.value === "GENESIS") return "Genesis Mode";
  if (latestRepositoryState.value === "EARLY_BUILD") return "Early Build Mode";
  if (latestRepositoryState.value === "PRODUCTION_CRITICAL") return "Production Critical Mode";
  return "Active Product Mode";
});
const latestRepositoryStateDescription = computed(() => {
  if (latestRepositoryState.value === "GENESIS") {
    return "Broad scaffolding and bootstrap operations are allowed while foundation is being established.";
  }
  if (latestRepositoryState.value === "EARLY_BUILD") {
    return "Larger bounded mutations are allowed while architecture and deployment topology are still evolving.";
  }
  if (latestRepositoryState.value === "PRODUCTION_CRITICAL") {
    return "Strict governance and high-risk protections are enforced for protected production surfaces.";
  }
  return "Stricter governance, decomposition, validation, and deployment protections are enforced.";
});
const latestRepositoryStateTagType = computed(() => {
  if (latestRepositoryState.value === "GENESIS") return "success";
  if (latestRepositoryState.value === "EARLY_BUILD") return "warning";
  if (latestRepositoryState.value === "PRODUCTION_CRITICAL") return "danger";
  return "info";
});
const architectureRefreshNeeded = computed(() => projectContext.architectureRefreshNeeded);
const planRefreshNeeded = computed(() => projectContext.planRefreshNeeded);
const testRefreshNeeded = computed(() => projectContext.testRefreshNeeded);
const planMeta = ref<any | null>(null);
const latestDelivery = ref<any | null>(null);
const architectureSummary = ref<any>(createEmptyArchitectureProfileSummary());
const foundationReadiness = ref<any>(createEmptyFoundationReadiness());
const foundationReadinessError = ref("");
const deploymentProviderHints = ref<string[]>([]);
const deploymentReadinessContract = ref<any | null>(null);
const environmentChecklistSummary = ref<any | null>(null);
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
const designContract = ref<any | null>(null);
const showDesignContractDialog = ref(false);
const designContractLoading = ref(false);
const designContractSaveLoading = ref(false);
const designContractError = ref("");
const designContractEditorValue = ref("{}");
const showDesignAdvancedEditor = ref(false);
const selectedDesignPreset = ref("");
const componentPolicyOptions = [
  "HeroSection",
  "DashboardShell",
  "MetricCard",
  "Timeline",
  "PrimaryButton",
  "PolicyPanel",
  "AuditTimeline",
  "FeatureGrid",
  "CTASection",
  "PromptPanel",
  "AssistantThread",
  "InsightCard",
  "PricingSection",
  "DataTable",
];
const designContractForm = ref<any>({
  experience_blueprint: "premium_saas",
  identity: { name: "Product", tone: "technical_minimal_premium", personality: "confident_operational_clean" },
  tokens: {},
  token_registry: { colors: {}, spacing: {}, radius: {}, motion: {}, elevation: {} },
  allowed_components: [],
  typography: { heading_font: "Inter", body_font: "Inter", radius_scale: "soft", density: "comfortable" },
  components: { buttons: { style: "glass", radius: "xl", shadow: "soft" }, registry: [] },
  layout: { spacing: "airy", container_width: "wide", visual_weight: "balanced", hero_style: "immersive" },
});
const designPresetOptions = [
  { label: "Premium SaaS", value: "premium_saas" },
  { label: "Operational Dashboard", value: "operational_dashboard" },
  { label: "AI Native", value: "ai_native" },
  { label: "Modern Startup", value: "modern_startup" },
  { label: "Enterprise", value: "enterprise" },
];
const designPresetRegistry: Record<string, any> = {
  premium_saas: {
    experience_blueprint: "premium_saas",
    identity: { name: "Product", tone: "technical_minimal_premium", personality: "confident_operational_clean" },
    tokens: { primary: "#2563eb", surface: "#f8fafc", accent: "#7c3aed", success: "#22c55e", text_primary: "#0f172a" },
    token_registry: {
      colors: { primary: "#2563eb", surface: "#f8fafc", accent: "#7c3aed", success: "#22c55e", text_primary: "#0f172a" },
      spacing: { xs: "0.25rem", sm: "0.5rem", md: "1rem", lg: "1.5rem", xl: "2rem" },
      radius: { sm: "0.375rem", md: "0.5rem", lg: "0.75rem", xl: "1rem" },
      motion: { fast: "120ms", base: "200ms", slow: "320ms" },
      elevation: { sm: "shadow-sm", md: "shadow", lg: "shadow-lg" },
    },
    allowed_components: ["HeroSection", "PricingSection", "PrimaryButton"],
    typography: { heading_font: "Sora", body_font: "Inter", radius_scale: "soft", density: "comfortable" },
    components: { buttons: { style: "glass", radius: "xl", shadow: "soft" }, registry: ["HeroSection", "PricingSection", "PrimaryButton"] },
    layout: { spacing: "airy", container_width: "wide", visual_weight: "balanced", hero_style: "immersive" },
  },
  operational_dashboard: {
    experience_blueprint: "enterprise_operational",
    identity: { name: "Operations", tone: "dense_operational_structured", personality: "precise_fast_signal_heavy" },
    tokens: { primary: "#0ea5e9", surface: "#f1f5f9", accent: "#14b8a6", success: "#16a34a", text_primary: "#0f172a" },
    token_registry: {
      colors: { primary: "#0ea5e9", surface: "#f1f5f9", accent: "#14b8a6", success: "#16a34a", text_primary: "#0f172a" },
      spacing: { xs: "0.25rem", sm: "0.5rem", md: "0.875rem", lg: "1.25rem", xl: "1.75rem" },
      radius: { sm: "0.25rem", md: "0.375rem", lg: "0.5rem", xl: "0.75rem" },
      motion: { fast: "100ms", base: "180ms", slow: "280ms" },
      elevation: { sm: "shadow-sm", md: "shadow", lg: "shadow-md" },
    },
    allowed_components: ["DashboardShell", "MetricCard", "Timeline", "DataTable"],
    typography: { heading_font: "Manrope", body_font: "Inter", radius_scale: "medium", density: "compact" },
    components: { buttons: { style: "solid", radius: "lg", shadow: "none" }, registry: ["DashboardShell", "MetricCard", "Timeline", "DataTable"] },
    layout: { spacing: "compact", container_width: "wide", visual_weight: "information_dense", hero_style: "functional" },
  },
  ai_native: {
    experience_blueprint: "ai_native",
    identity: { name: "AI Product", tone: "modern_dynamic_assistive", personality: "adaptive_clear_experimental" },
    tokens: { primary: "#0f766e", surface: "#f8fafc", accent: "#2563eb", success: "#22c55e", text_primary: "#0f172a" },
    token_registry: {
      colors: { primary: "#0f766e", surface: "#f8fafc", accent: "#2563eb", success: "#22c55e", text_primary: "#0f172a" },
      spacing: { xs: "0.25rem", sm: "0.5rem", md: "1rem", lg: "1.5rem", xl: "2rem" },
      radius: { sm: "0.375rem", md: "0.5rem", lg: "0.75rem", xl: "1rem" },
      motion: { fast: "120ms", base: "200ms", slow: "300ms" },
      elevation: { sm: "shadow-sm", md: "shadow", lg: "shadow-lg" },
    },
    allowed_components: ["PromptPanel", "AssistantThread", "InsightCard"],
    typography: { heading_font: "Space Grotesk", body_font: "Inter", radius_scale: "soft", density: "comfortable" },
    components: { buttons: { style: "elevated", radius: "xl", shadow: "soft" }, registry: ["PromptPanel", "AssistantThread", "InsightCard"] },
    layout: { spacing: "airy", container_width: "wide", visual_weight: "balanced", hero_style: "immersive" },
  },
  modern_startup: {
    experience_blueprint: "startup_launch",
    identity: { name: "Startup", tone: "bold_consumer_fast", personality: "energetic_confident_simple" },
    tokens: { primary: "#ef4444", surface: "#fff7ed", accent: "#f59e0b", success: "#22c55e", text_primary: "#111827" },
    token_registry: {
      colors: { primary: "#ef4444", surface: "#fff7ed", accent: "#f59e0b", success: "#22c55e", text_primary: "#111827" },
      spacing: { xs: "0.25rem", sm: "0.5rem", md: "1rem", lg: "1.5rem", xl: "2rem" },
      radius: { sm: "0.5rem", md: "0.75rem", lg: "1rem", xl: "1.25rem" },
      motion: { fast: "120ms", base: "220ms", slow: "340ms" },
      elevation: { sm: "shadow", md: "shadow-md", lg: "shadow-lg" },
    },
    allowed_components: ["HeroSection", "FeatureGrid", "CTASection"],
    typography: { heading_font: "Sora", body_font: "Inter", radius_scale: "rounded", density: "comfortable" },
    components: { buttons: { style: "solid", radius: "xl", shadow: "medium" }, registry: ["HeroSection", "FeatureGrid", "CTASection"] },
    layout: { spacing: "airy", container_width: "wide", visual_weight: "hero_forward", hero_style: "immersive" },
  },
  enterprise: {
    experience_blueprint: "enterprise_operational",
    identity: { name: "Enterprise", tone: "governed_structured_stable", personality: "trustworthy_clear_ordered" },
    tokens: { primary: "#1d4ed8", surface: "#f8fafc", accent: "#475569", success: "#16a34a", text_primary: "#0f172a" },
    token_registry: {
      colors: { primary: "#1d4ed8", surface: "#f8fafc", accent: "#475569", success: "#16a34a", text_primary: "#0f172a" },
      spacing: { xs: "0.25rem", sm: "0.5rem", md: "1rem", lg: "1.25rem", xl: "1.75rem" },
      radius: { sm: "0.25rem", md: "0.375rem", lg: "0.5rem", xl: "0.75rem" },
      motion: { fast: "100ms", base: "180ms", slow: "260ms" },
      elevation: { sm: "shadow-sm", md: "shadow", lg: "shadow-md" },
    },
    allowed_components: ["DashboardShell", "PolicyPanel", "AuditTimeline"],
    typography: { heading_font: "Inter", body_font: "Inter", radius_scale: "medium", density: "comfortable" },
    components: { buttons: { style: "solid", radius: "lg", shadow: "none" }, registry: ["DashboardShell", "PolicyPanel", "AuditTimeline"] },
    layout: { spacing: "structured", container_width: "wide", visual_weight: "balanced", hero_style: "functional" },
  },
};
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

const designContractIdentityName = computed(
  () => String(designContract.value?.identity?.name || "Product").trim() || "Product"
);
const designContractIdentityTone = computed(
  () => String(designContract.value?.identity?.tone || "technical_minimal_premium").trim() || "technical_minimal_premium"
);
const designContractIdentityPersonality = computed(
  () => String(designContract.value?.identity?.personality || "confident_operational_clean").trim() || "confident_operational_clean"
);
const designContractTokenCount = computed(() => {
  const tokens = designContract.value?.token_registry?.colors || designContract.value?.tokens;
  return tokens && typeof tokens === "object" ? Object.keys(tokens).length : 0;
});
const designContractRegistryCount = computed(() => {
  const registry = designContract.value?.allowed_components || designContract.value?.components?.registry;
  return Array.isArray(registry) ? registry.length : 0;
});
const designContractTypographyLabel = computed(() => {
  const heading = String(designContract.value?.typography?.heading_font || "Inter");
  const body = String(designContract.value?.typography?.body_font || "Inter");
  return `${heading}/${body}`;
});
const designContractLayoutLabel = computed(() => {
  const spacing = String(designContract.value?.layout?.spacing || "airy");
  const width = String(designContract.value?.layout?.container_width || "wide");
  return `${spacing}, ${width}`;
});
const presetDiffRows = computed(() => {
  const key = String(selectedDesignPreset.value || "").trim();
  const preset = designPresetRegistry[key];
  if (!preset) return [] as Array<{ path: string; from: string; to: string }>;

  let current: any = {};
  try {
    current = JSON.parse(designContractEditorValue.value || "{}");
  } catch {
    current = designContract.value || {};
  }
  const rows: Array<{ path: string; from: string; to: string }> = [];
  collectDesignDiffRows(current, preset, "", rows);
  return rows;
});
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
const runAllLoading = ref(false);
const runAllProgressLabel = ref("");
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
const repoBootstrapLoading = ref(false);
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
const runSelectedLoading = ref(false);
const selectedTaskIds = ref<string[]>([]);
const tasksDialogFullscreen = ref(false);
const runUnblockLoading = ref<Record<string, boolean>>({});
const runResumeLoading = ref<Record<string, boolean>>({});
const attemptFilter = ref<"all" | "initial" | "retry" | "noop">("all");
const showCompletedTasks = ref(true);
const selectedExecutionMode = ref<"smart" | "manual">("smart");
const selectedTaskOrder = ref<string[]>([]);
const tasksTableRef = ref<any>(null);
const taskSelectionSyncing = ref(false);
const batchExecutionTotal = ref(0);
const batchExecutionStarted = ref(0);
const batchExecutionNextTitle = ref("");
let overviewPollHandle: ReturnType<typeof setTimeout> | null = null;
let overviewPollInFlight = false;
const selectedExecutor = ref("codex");
const executorSelectionDirty = ref(false);
const workItems = ref<any[]>([]);
const workItemsLoading = ref(false);
const workItemError = ref("");
const runEvents = ref<any[]>([]);
const memoryDashboardLoading = ref(false);
const memoryDashboardError = ref("");
const memoryUnderstanding = ref<any | null>(null);
const memorySummaries = ref<any[]>([]);
const memoryExplain = ref<any | null>(null);
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
const overviewStatusBanner = computed(() => {
  const rows = taskSnapshot.value || [];
  const statusOf = (row: any) => String(row?.status || "").toUpperCase();
  const inProgressStatuses = new Set(["RUNNING", "IN_PROGRESS", "CLAIMED"]);
  const queueStatuses = new Set(["PENDING", "QUEUED"]);
  const doneStatuses = new Set(["DONE", "COMPLETED", "CLOSED"]);
  const inProgressTask = rows.find((row) => inProgressStatuses.has(statusOf(row)));
  const inProgressTaskName = String(
    inProgressTask?.title || inProgressTask?.task_title || inProgressTask?.name || inProgressTask?.id || "None"
  );
  return {
    queue: rows.filter((row) => queueStatuses.has(statusOf(row))).length,
    inProgress: rows.filter((row) => inProgressStatuses.has(statusOf(row))).length,
    completed: rows.filter((row) => doneStatuses.has(statusOf(row))).length,
    total: rows.length,
    inProgressTaskName,
  };
});
const overviewPolicyBlockHint = computed(() => {
  const latestFailedItem = [...workItems.value]
    .reverse()
    .find((item: any) => String(item?.status || "").toUpperCase() === "FAILED");
  const itemResult = latestFailedItem?.result && typeof latestFailedItem.result === "object" ? latestFailedItem.result : {};
  const itemStopReason = String(itemResult?.stop_reason || "").toLowerCase();
  const itemApprovalRequired = itemResult?.approval_required;
  if (itemStopReason === "human_review_required" && itemApprovalRequired === false) {
    return "Runtime policy blocked a step internally (human_review_required). This is not waiting for manual approval; inspect failed work item details before rerun.";
  }

  const latestFailedEvent = [...runEvents.value]
    .reverse()
    .find((event: any) => String(event?.event_type || "").toUpperCase() === "WORK_ITEM_FAILED");
  const payload = latestFailedEvent?.payload && typeof latestFailedEvent.payload === "object" ? latestFailedEvent.payload : {};
  const stopReason = String(payload?.stop_reason || payload?.message || payload?.error || "").toLowerCase();
  const approvalRequired = payload?.approval_required;
  if (stopReason.includes("human_review_required") && approvalRequired === false) {
    return "Runtime policy blocked a step internally (human_review_required). This is not waiting for manual approval; inspect failed work item details before rerun.";
  }

  return "";
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
const statusPriority: Record<string, number> = {
  RUNNING: 0,
  CLAIMED: 1,
  PENDING: 2,
  QUEUED: 3,
  FAILED: 4,
  BLOCKED: 5,
  CANCELED: 6,
  DONE: 7,
  COMPLETED: 8,
  CLOSED: 9,
};
const sortedTasks = computed(() => {
  const rows = Array.isArray(tasks.value) ? [...tasks.value] : [];
  return rows.sort((a, b) => {
    const aStatus = taskEffectiveStatus(a);
    const bStatus = taskEffectiveStatus(b);
    const aPriority = statusPriority[aStatus] ?? 99;
    const bPriority = statusPriority[bStatus] ?? 99;
    if (aPriority !== bPriority) return aPriority - bPriority;
    const aVersion = Number(a?.generated_from_document_version || 0);
    const bVersion = Number(b?.generated_from_document_version || 0);
    if (aVersion !== bVersion) return bVersion - aVersion;
    const aCreated = Date.parse(String(a?.created_at || "")) || 0;
    const bCreated = Date.parse(String(b?.created_at || "")) || 0;
    if (aCreated !== bCreated) return aCreated - bCreated;
    return String(a?.id || "").localeCompare(String(b?.id || ""));
  });
});
const attemptFilterOptions = [
  { value: "all" as const, label: "All", type: "info" as const },
  { value: "initial" as const, label: "Initial", type: "success" as const },
  { value: "retry" as const, label: "Retry", type: "warning" as const },
  { value: "noop" as const, label: "No-op", type: "primary" as const },
];
const filteredTasks = computed(() => {
  const mode = attemptFilter.value;
  const completionFiltered = sortedTasks.value.filter((task) => {
    if (showCompletedTasks.value) return true;
    return !["DONE", "COMPLETED", "CLOSED"].includes(taskEffectiveStatus(task));
  });
  if (mode === "all") return completionFiltered;
  return completionFiltered.filter((task) => {
    const label = taskAttemptTypeLabel(task).toUpperCase();
    if (mode === "initial") return label === "INITIAL";
    if (mode === "retry") return label !== "INITIAL" && label !== "NO_OP";
    if (mode === "noop") return label === "NO_OP";
    return true;
  });
});
const filteredTaskIdSignature = computed(() => {
  const ids = filteredTasks.value
    .map((task) => String(task?.id || ""))
    .filter((value) => !!value)
    .sort();
  return ids.join("|");
});
const runnableTasks = computed(() => filteredTasks.value.filter((task) => canRunTask(task)));
const selectedRunnableTasks = computed(() => {
  const byId = new Map(filteredTasks.value.map((task) => [String(task?.id || ""), task]));
  const orderedSelected = selectedTaskOrder.value
    .map((id) => byId.get(String(id)))
    .filter((task): task is any => !!task && canRunTask(task));
  if (orderedSelected.length) return orderedSelected;
  const selected = new Set(selectedTaskIds.value);
  return filteredTasks.value.filter((task) => selected.has(String(task?.id || "")) && canRunTask(task));
});
const taskStatusCounts = computed(() => {
  const rows = filteredTasks.value;
  const statusOf = (row: any) => taskEffectiveStatus(row);
  const count = (statuses: string[]) => rows.filter((row) => statuses.includes(statusOf(row))).length;
  return {
    queued: count(["PENDING", "QUEUED"]),
    inProgress: count(["RUNNING", "IN_PROGRESS", "CLAIMED"]),
    done: count(["DONE", "COMPLETED", "CLOSED"]),
    failed: count(["FAILED", "BLOCKED", "CANCELED"]),
  };
});
const taskStatusCountsGlobal = computed(() => {
  const rows = sortedTasks.value;
  const statusOf = (row: any) => taskEffectiveStatus(row);
  const count = (statuses: string[]) => rows.filter((row) => statuses.includes(statusOf(row))).length;
  return {
    queued: count(["PENDING", "QUEUED"]),
    inProgress: count(["RUNNING", "IN_PROGRESS", "CLAIMED"]),
    done: count(["DONE", "COMPLETED", "CLOSED"]),
    failed: count(["FAILED", "BLOCKED", "CANCELED"]),
  };
});
const batchExecutionRemaining = computed(() => Math.max(0, batchExecutionTotal.value - batchExecutionStarted.value));
const batchExecutionStepLabel = computed(() => `${Math.min(batchExecutionStarted.value + 1, Math.max(batchExecutionTotal.value, 1))}/${batchExecutionTotal.value}`);
const requirementsNeedingReview = computed(
  () => requirementSummaryCards.value.filter((card) => String(card?.status || "").toUpperCase() === "NEEDS_REVIEW").length
);
const requirementsSpendCentsFromSummary = computed(() =>
  requirementSummaryCards.value.reduce((sum, card) => sum + Number(card?.ai_spend_cents || 0), 0)
);
const requirementsTokensFromSummary = computed(() =>
  requirementSummaryCards.value.reduce((sum, card) => sum + Number(card?.ai_total_tokens || 0), 0)
);
const requirementsSpendCentsFromRuns = computed(() =>
  (Array.isArray(runs.value) ? runs.value : []).reduce((sum, run) => {
    const cents = Number(run?.summary?.execution_contract?.budget?.used_cost_cents || 0);
    return sum + (Number.isFinite(cents) ? cents : 0);
  }, 0)
);
const requirementsTokensFromRuns = computed(() =>
  (Array.isArray(runs.value) ? runs.value : []).reduce((sum, run) => {
    const tokens = Number(run?.summary?.execution_contract?.budget?.used_tokens || 0);
    return sum + (Number.isFinite(tokens) ? tokens : 0);
  }, 0)
);

watch([filteredTaskIdSignature, showCompletedTasks], () => {
  void restoreTaskSelection();
});
const totalRequirementAiSpendCents = computed(() =>
  Math.max(requirementsSpendCentsFromSummary.value, requirementsSpendCentsFromRuns.value)
);
const totalRequirementAiSpendUsd = computed(() => (totalRequirementAiSpendCents.value / 100).toFixed(4));
const totalRequirementAiTokens = computed(() =>
  Math.max(requirementsTokensFromSummary.value, requirementsTokensFromRuns.value)
);
const topCostlyRequirements = computed(() =>
  [...requirementSummaryCards.value]
    .sort((a, b) => Number(b?.ai_spend_cents || 0) - Number(a?.ai_spend_cents || 0))
    .filter((card) => Number(card?.ai_spend_cents || 0) > 0)
    .slice(0, 5)
);
const unstableRequirements = computed(() =>
  [...requirementSummaryCards.value]
    .filter((card) => Number(card?.stability_score || 100) < 70 || Number(card?.retry_count || 0) >= 2)
    .sort((a, b) => Number(a?.stability_score || 100) - Number(b?.stability_score || 100))
    .slice(0, 6)
);
const recoveryHotspots = computed(() => {
  const rows = Array.isArray(memoryExplain.value?.linked_events) ? memoryExplain.value.linked_events : [];
  const counts = new Map<string, number>();
  for (const row of rows) {
    if (String(row?.domain || "") !== "recovery") continue;
    const key = String(row?.event_type || "RECOVERY");
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 5);
});
const deploymentRiskSignals = computed(() => {
  const rows = Array.isArray(memoryExplain.value?.linked_events) ? memoryExplain.value.linked_events : [];
  const deploymentEvents = rows.filter((row: any) => String(row?.domain || "") === "deployment").length;
  const criticalEvents = rows.filter((row: any) => String(row?.severity || "") === "critical").length;
  if (criticalEvents >= 3) return "High risk";
  if (criticalEvents > 0 || deploymentEvents > 0) return "Elevated";
  return "Stable";
});
const staleArchitectureZones = computed(() => {
  const payload = memoryUnderstanding.value?.latest_summaries?.weekly || {};
  const domains = payload?.domains || {};
  if (Number(domains?.architecture || 0) === 0) return "No recent architecture updates";
  return "Recent architecture activity present";
});
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
const productionReadinessScore = computed(() => {
  const status = String(foundationReadiness.value?.status || "MISSING").toUpperCase();
  const missing = Array.isArray(foundationReadiness.value?.missing_prerequisites)
    ? foundationReadiness.value.missing_prerequisites.length
    : 0;
  let score = 35;
  if (status === "READY") score = 86;
  else if (status === "PARTIAL") score = 62;
  if (projectRepo.value?.repo_url || projectRepo.value?.repo_full_name) score += 6;
  if (String(architectureSummary.value?.status || "").toUpperCase() === "ACTIVE") score += 6;
  score -= missing * 8;
  return Math.max(0, Math.min(100, Math.round(score)));
});
const productionReadinessActions = computed(() => {
  const missing: string[] = Array.isArray(foundationReadiness.value?.missing_prerequisites)
    ? foundationReadiness.value.missing_prerequisites.map((item: any) => String(item))
    : [];
  if (!missing.length) return [];
  const actions: string[] = [];
  for (const item of missing) {
    const normalized = item.toLowerCase();
    if (normalized.includes("repo")) actions.push("Connect repository and set default branch");
    else if (normalized.includes("arch")) actions.push("Create architecture contract and derive safe paths");
    else if (normalized.includes("requirement")) actions.push("Approve requirements and regenerate task lineage");
    else if (normalized.includes("preview")) actions.push("Configure preview profile and verify healthchecks");
    else actions.push(`Resolve ${item.replaceAll("_", " ").toLowerCase()}`);
  }
  return Array.from(new Set(actions)).slice(0, 4);
});
const deploymentTrustSummary = computed(() => {
  const risk = deploymentRiskSignals.value;
  const instability = unstableRequirements.value.length;
  const hotspotCount = recoveryHotspots.value.reduce((acc, row) => acc + Number(row.count || 0), 0);
  let confidencePct = 90;
  if (risk === "Elevated") confidencePct -= 18;
  if (risk === "High risk") confidencePct -= 34;
  confidencePct -= Math.min(25, instability * 3);
  confidencePct -= Math.min(20, hotspotCount * 2);
  confidencePct = clampPercent(Math.max(15, Math.min(98, Math.round(confidencePct))));
  const blockers: string[] = [
    risk !== "Stable" ? `Deployment risk: ${risk}` : "",
    instability > 0 ? `${instability} unstable requirement signals` : "",
    hotspotCount > 0 ? `${hotspotCount} recovery hotspot events` : "",
  ];
  return buildDeploymentTrustSummary({
    confidencePct: risk === "High risk" ? Math.min(confidencePct, 55) : confidencePct,
    blockerSignals: blockers,
    evidence: `${deploymentRiskSignals.value} deployment risk · ${unstableRequirements.value.length} unstable requirements · ${recoveryHotspots.value.length} hotspot types`,
  });
});
const deploymentTrustTone = computed(() => {
  if (deploymentTrustSummary.value.tone === "danger") return "text-rose-600";
  if (deploymentTrustSummary.value.tone === "warning") return "text-amber-600";
  return "text-emerald-600";
});
const projectEnvironmentReadiness = computed(() => {
  if (environmentChecklistSummary.value) {
    const summary = environmentChecklistSummary.value;
    const nextUserActions = Array.isArray(summary.items)
      ? summary.items.filter((item: any) => item?.owner === "user" && String(item?.status || "").toLowerCase() !== "done").slice(0, 6)
      : [];
    const environments = Array.isArray(summary.environments)
      ? summary.environments.map((env: any) => ({
          environment: String(env?.environment || ""),
          scorePct: Number(env?.score_pct || 0),
          userPending: Number(env?.user_pending || 0),
        }))
      : [];
    return {
      scorePct: Number(summary.score_pct || 0),
      environments,
      nextUserActions: nextUserActions.map((item: any) => ({ label: String(item?.label || item?.item_key || "User action required") })),
    };
  }
  const missing = Array.isArray(foundationReadiness.value?.missing_prerequisites)
    ? foundationReadiness.value.missing_prerequisites.map((item: any) => String(item))
    : [];
  return buildEnvironmentReadiness({
    hasRepo: Boolean(projectRepo.value?.repo_url || projectRepo.value?.repo_full_name),
    hasDeploymentConnector: deploymentProviderHints.value.length > 0,
    deploymentProviders: deploymentProviderHints.value,
    foundationMissing: missing,
    previewReady: runs.value.some((run) => String(run?.status || "").toUpperCase() === "COMPLETED"),
  });
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
const architectureRunReady = computed(() => Boolean(architectureSummary.value?.profile_exists && architectureSummary.value?.derived_ready));
const modalArchitectureSummary = computed(() => {
  let parsed: any = {};
  try {
    parsed = JSON.parse(architectureEditorValue.value || "{}");
  } catch {
    parsed = architectureProfile.value?.profile_json || {};
  }
  if (!parsed || typeof parsed !== "object") parsed = {};
  const repoLayout = parsed.repo_layout && typeof parsed.repo_layout === "object" ? parsed.repo_layout : {};
  const packagesRaw = Array.isArray(repoLayout.packages) ? repoLayout.packages : [];
  const packages = packagesRaw
    .map((item: any) => (item && typeof item.name === "string" ? item.name : ""))
    .filter((item: string) => Boolean(item));
  const safeZones = Array.isArray(parsed.safe_refactor_zones) ? parsed.safe_refactor_zones.filter((x: any) => typeof x === "string") : [];
  const protectedZones = Array.isArray(parsed.do_not_touch_zones)
    ? parsed.do_not_touch_zones
        .map((item: any) => (typeof item === "string" ? item : typeof item?.path === "string" ? item.path : ""))
        .filter((item: string) => Boolean(item))
    : [];
  const commandsObj = parsed.commands && typeof parsed.commands === "object" ? parsed.commands : {};
  const commands = Object.keys(commandsObj);
  const validationRaw = Array.isArray(parsed.validation_recipes) ? parsed.validation_recipes : [];
  const validationRecipes = validationRaw
    .map((item: any) => (item && typeof item.name === "string" ? item.name : ""))
    .filter((item: string) => Boolean(item));
  const derivedFrom: string[] = [];
  if (parsed.blueprint_key) derivedFrom.push("blueprint");
  if (packages.length || commands.length || validationRecipes.length) derivedFrom.push("repo_intelligence");
  if (Array.isArray(parsed.deployment_surfaces) && parsed.deployment_surfaces.length) derivedFrom.push("deployment_topology");
  let confidence = "LOW";
  if (derivedFrom.length >= 3) confidence = "HIGH";
  else if (derivedFrom.length === 2) confidence = "MEDIUM";
  const assumptions = Array.isArray(architectureSummary.value?.assumptions_used) ? architectureSummary.value.assumptions_used : [];
  return {
    repo_layout_label: String(repoLayout.label || (repoLayout.monorepo ? "Monorepo" : "Repository")),
    status: String(architectureProfile.value?.status || architectureSummary.value?.status || "MISSING"),
    summary: String(architectureSummaryText.value || architectureSummary.value?.summary || ""),
    packages,
    execution_slice: packages.slice(0, 3),
    protected_zones: protectedZones,
    safe_zones: safeZones,
    commands,
    validation_recipes: validationRecipes,
    derivation_confidence: confidence,
    derived_from: derivedFrom,
    assumptions_used: assumptions,
  };
});
const startRunBlockedReason = computed(() => {
  if (!checklistRepo.value) return "Connect a repository before starting runs.";
  if (!checklistRequirements.value) return "Approve requirements before starting runs.";
  if (!checklistTasks.value) return "Generate at least one task before starting runs.";
  if (!architectureRunReady.value) {
    return "Architecture profile must be derived first (Architecture Contract -> Manage -> Bootstrap -> Derive).";
  }
  return "";
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

function taskLineageSourceLabel(task: any) {
  return String(task?.source_surface || task?.source_type || task?.source || "project_overview");
}

function taskAttemptTypeLabel(task: any) {
  const provenance = task?.provenance && typeof task.provenance === "object" ? task.provenance : {};
  const explicit = String(provenance?.attempt_type || "").trim().toUpperCase();
  if (explicit) return explicit;
  if (task?.rerun_of_task_id || provenance?.rerun_of_task_id || provenance?.parent_task_id) return "RETRY";
  return "INITIAL";
}

function attemptTagType(task: any) {
  const label = taskAttemptTypeLabel(task);
  if (label === "NO_OP") return "info";
  if (label === "RETRY" || label === "RECOVERY" || label === "DRIFT_REPAIR" || label === "VALIDATION_REPLAY") return "warning";
  if (label === "DECOMPOSED") return "primary";
  return "success";
}

function normalizedTaskTitle(task: any) {
  return String(task?.title || "").trim().toLowerCase();
}

function taskId(task: any) {
  return String(task?.id || "");
}

function inferTaskDependencyIds(task: any, allTasks: any[]) {
  const id = taskId(task);
  const title = normalizedTaskTitle(task);
  const provenance = task?.provenance && typeof task.provenance === "object" ? task.provenance : {};
  const allById = new Map(allTasks.map((row) => [taskId(row), row]));
  const allByTitle = new Map(allTasks.map((row) => [normalizedTaskTitle(row), row]));
  const deps = new Set<string>();

  const collectIds = (value: any) => {
    if (Array.isArray(value)) {
      for (const item of value) {
        const candidate = String(item || "").trim();
        if (!candidate) continue;
        if (allById.has(candidate)) deps.add(candidate);
      }
    } else if (typeof value === "string") {
      const candidate = value.trim();
      if (candidate && allById.has(candidate)) deps.add(candidate);
    }
  };
  const collectTitles = (value: any) => {
    if (Array.isArray(value)) {
      for (const item of value) {
        const key = String(item || "").trim().toLowerCase();
        if (!key) continue;
        const row = allByTitle.get(key);
        if (row) deps.add(taskId(row));
      }
    } else if (typeof value === "string") {
      const key = value.trim().toLowerCase();
      if (!key) return;
      const row = allByTitle.get(key);
      if (row) deps.add(taskId(row));
    }
  };

  collectIds(provenance?.depends_on_task_ids);
  collectIds(provenance?.depends_on);
  collectIds(provenance?.prerequisite_task_ids);
  collectTitles(provenance?.depends_on_titles);
  collectTitles(provenance?.prerequisite_titles);

  // Foundation fallback graph for predictable bootstrap ordering.
  if (String(task?.source || "") === "genesis" || String(task?.source_type || "").includes("genesis")) {
    const monorepo = allByTitle.get("initialize monorepo");
    if (
      monorepo &&
      title !== "initialize monorepo" &&
      (
        title.startsWith("initialize frontend")
        || title.startsWith("initialize backend")
        || title.startsWith("initialize contracts")
        || title.startsWith("initialize requirements")
        || title.startsWith("initialize ci")
        || title.startsWith("initialize deployment profile")
        || title.startsWith("initialize telemetry")
        || title.startsWith("validate foundation")
      )
    ) {
      deps.add(taskId(monorepo));
    }
    if (title.startsWith("validate foundation")) {
      const prereqTitles = [
        "initialize frontend",
        "initialize backend",
        "initialize contracts",
        "initialize requirements",
        "initialize ci",
        "initialize deployment profile",
        "initialize telemetry",
      ];
      for (const key of prereqTitles) {
        const row = allByTitle.get(key);
        if (row) deps.add(taskId(row));
      }
    }
  }

  deps.delete(id);
  return deps;
}

function planSelectedTasksByDependencies(selectedTasks: any[], allTasks: any[]) {
  const selectedById = new Map(selectedTasks.map((row) => [taskId(row), row]));
  const depsById = new Map<string, Set<string>>();
  const missingById = new Map<string, string[]>();

  for (const task of selectedTasks) {
    const id = taskId(task);
    const inferred = inferTaskDependencyIds(task, allTasks);
    depsById.set(id, inferred);
    const missing = [...inferred].filter((depId) => !selectedById.has(depId));
    if (missing.length) missingById.set(id, missing);
  }

  const indegree = new Map<string, number>();
  const outgoing = new Map<string, string[]>();
  for (const task of selectedTasks) {
    const id = taskId(task);
    indegree.set(id, 0);
    outgoing.set(id, []);
  }
  for (const [taskNodeId, deps] of depsById.entries()) {
    for (const depId of deps) {
      if (!selectedById.has(depId)) continue;
      indegree.set(taskNodeId, (indegree.get(taskNodeId) || 0) + 1);
      outgoing.set(depId, [...(outgoing.get(depId) || []), taskNodeId]);
    }
  }

  const stageRank: Record<string, number> = { PLAN: 0, RUN: 1, EVALUATE: 2 };
  const queue = [...selectedTasks]
    .filter((row) => (indegree.get(taskId(row)) || 0) === 0)
    .sort((a, b) => {
      const aPriority = taskExecutionPriority(a);
      const bPriority = taskExecutionPriority(b);
      if (aPriority !== bPriority) return aPriority - bPriority;
      const aStage = stageRank[String(a?.stage || "").toUpperCase()] ?? 9;
      const bStage = stageRank[String(b?.stage || "").toUpperCase()] ?? 9;
      if (aStage !== bStage) return aStage - bStage;
      const aCreated = Date.parse(String(a?.created_at || "")) || 0;
      const bCreated = Date.parse(String(b?.created_at || "")) || 0;
      return aCreated - bCreated;
    });
  const ordered: any[] = [];
  while (queue.length) {
    const row = queue.shift();
    if (!row) break;
    const id = taskId(row);
    ordered.push(row);
    const children = outgoing.get(id) || [];
    for (const childId of children) {
      const nextIn = (indegree.get(childId) || 0) - 1;
      indegree.set(childId, nextIn);
      if (nextIn === 0) {
        const child = selectedById.get(childId);
        if (child) {
          queue.push(child);
          queue.sort((a, b) => {
            const aPriority = taskExecutionPriority(a);
            const bPriority = taskExecutionPriority(b);
            if (aPriority !== bPriority) return aPriority - bPriority;
            const aStage = stageRank[String(a?.stage || "").toUpperCase()] ?? 9;
            const bStage = stageRank[String(b?.stage || "").toUpperCase()] ?? 9;
            if (aStage !== bStage) return aStage - bStage;
            const aCreated = Date.parse(String(a?.created_at || "")) || 0;
            const bCreated = Date.parse(String(b?.created_at || "")) || 0;
            return aCreated - bCreated;
          });
        }
      }
    }
  }

  const unresolvedCycle = ordered.length !== selectedTasks.length;
  return { ordered, missingById, unresolvedCycle };
}

function taskExecutionPriority(task: any): number {
  const title = String(task?.title || "").trim().toLowerCase();
  if (title.startsWith("initialize monorepo")) return 0;
  if (title.includes("deterministic monorepo baseline")) return 1;
  if (title.startsWith("initialize frontend")) return 2;
  if (title.startsWith("initialize backend")) return 3;
  if (title.startsWith("initialize contracts")) return 4;
  if (title.startsWith("initialize requirements")) return 5;
  if (title.startsWith("initialize ci")) return 6;
  if (title.startsWith("initialize deployment profile")) return 7;
  if (title.startsWith("initialize telemetry")) return 8;
  if (title.startsWith("validate foundation")) return 9;
  if (title.includes("foundation readiness")) return 10;
  if (title.includes("lineage in mission control")) return 11;
  return 100;
}

function planSmartSelectedTasks(selectedTasks: any[], allTasks: any[]) {
  const allById = new Map(allTasks.map((row) => [taskId(row), row]));
  const selectedById = new Map(selectedTasks.map((row) => [taskId(row), row]));
  const autoIncluded: any[] = [];

  let expanded = true;
  while (expanded) {
    expanded = false;
    for (const task of [...selectedById.values()]) {
      const deps = inferTaskDependencyIds(task, allTasks);
      for (const depId of deps) {
        if (selectedById.has(depId)) continue;
        const depTask = allById.get(depId);
        if (!depTask) continue;
        if (!canRunTask(depTask)) continue;
        selectedById.set(depId, depTask);
        autoIncluded.push(depTask);
        expanded = true;
      }
    }
  }

  const expandedSelection = [...selectedById.values()];
  const plan = planSelectedTasksByDependencies(expandedSelection, allTasks);
  return { ...plan, autoIncluded };
}

function taskLinkedRunLabel(task: any) {
  return shortId(
    task?.latest_run_id ||
    task?.run_id ||
    task?.linked_run_id ||
    task?.last_run_id ||
    task?.summary?.run_id ||
    ""
  );
}

function shortId(value?: string | null) {
  if (!value) return "—";
  return String(value).slice(0, 8);
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

function goToEnvironmentCenter() {
  if (!projectId.value) return;
  router.push(`/projects/${projectId.value}/environments`);
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
  if (startRunBlockedReason.value) {
    runError.value = startRunBlockedReason.value;
    showArchitectureDialog.value = true;
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

async function openTasksPage() {
  if (!projectId.value) return;
  await router.push(`/projects/${projectId.value}/tasks`);
}

async function loadTasks() {
  tasksError.value = "";
  if (!projectId.value) return;
  try {
    tasks.value = await listTasks(projectId.value, { latest_per_title: true, include_deleted: false });
    taskSnapshot.value = await listTasks(projectId.value, { latest_per_title: true, include_deleted: false });
    await restoreTaskSelection();
  } catch (err: any) {
    tasksError.value = err?.message || "Failed to load tasks";
  }
}

async function restoreTaskSelection() {
  await nextTick();
  const table = tasksTableRef.value;
  if (!table) return;
  const idSet = new Set(selectedTaskIds.value.map((id) => String(id)));
  taskSelectionSyncing.value = true;
  try {
    table.clearSelection?.();
    for (const task of filteredTasks.value) {
      const id = String(task?.id || "");
      if (idSet.has(id)) {
        table.toggleRowSelection?.(task, true);
      }
    }
  } finally {
    taskSelectionSyncing.value = false;
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

async function loadMemoryDashboard() {
  if (!projectId.value) return;
  memoryDashboardLoading.value = true;
  memoryDashboardError.value = "";
  try {
    const [understanding, summaries, explain] = await Promise.all([
      fetchProjectUnderstanding(projectId.value),
      fetchProjectMemorySummaries(projectId.value, { limit: 20 }),
      explainProjectMemory(projectId.value, { limit: 40 }),
    ]);
    memoryUnderstanding.value = understanding || null;
    memorySummaries.value = Array.isArray(summaries?.items) ? summaries.items : [];
    memoryExplain.value = explain || null;
  } catch (err: any) {
    memoryDashboardError.value = err?.message || "Failed to load operational memory dashboard.";
  } finally {
    memoryDashboardLoading.value = false;
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

async function runTask(task: any, force = false) {
  if (!projectId.value || !task?.id) return;
  if (!force && !canRunTask(task)) {
    ElMessage.warning("Task is not runnable in its current status.");
    return;
  }
  if (force && hasRunningRun.value) {
    ElMessage.warning("Another run is active. Wait for it to finish before force-running.");
    return;
  }
  taskRunLoadingId.value = task.id;
  tasksError.value = "";
  runError.value = "";
  try {
    if (force) {
      try {
        const preflight = await fetchTaskRerunPreflight(projectId.value, String(task.id));
        const classification = String(preflight?.classification || "").toLowerCase();
        if (classification === "already_satisfied") {
          await createTaskRerunNoopAttempt(projectId.value, String(task.id));
          await loadTasks();
          ElMessage.info("Created NO_OP attempt: repository already satisfies this task intent.");
          return;
        }
      } catch (preflightErr: any) {
        const detail = String(preflightErr?.message || preflightErr || "").toLowerCase();
        // Preflight is an optimization. If it fails, continue with the force rerun path.
        if (detail.includes("404") || detail.includes("not found")) {
          ElMessage.warning("Rerun preflight endpoint unavailable; continuing with force run.");
        } else {
          ElMessage.warning("Rerun preflight failed; continuing with force run.");
        }
      }
    }
    const actionKey = force ? "force_task" : "task";
    const requestKey = getOrCreateActionRequestKey("start_run", `project_overview:${actionKey}:${projectId.value}:${task.id}`);
    const createdRun = await createRun(projectId.value, selectedExecutor.value, task.id, null, {
      request_key: requestKey,
      force_rerun: force,
    });
    if (createdRun?.id) {
      runs.value = canonicalizeRuns([createdRun, ...runs.value.filter((run) => run?.id !== createdRun.id)]);
      updateProjectContext({
        latestRunId: createdRun.id,
        runStatus: createdRun.status || "QUEUED",
        hasActiveRun: true,
        updatedAt: new Date().toISOString(),
      });
      ElMessage.success(`${force ? "Force run" : "Run"} queued for task: ${task.title} (${String(createdRun.id).slice(0, 8)})`);
    } else {
      ElMessage.success(`${force ? "Force run" : "Run"} queued for task: ${task.title}`);
    }
    await loadTasks();
    await loadRuns();
  } catch (err: any) {
    const message = err?.message || "Failed to create run for task";
    tasksError.value = message;
    runError.value = message;
  } finally {
    taskRunLoadingId.value = "";
  }
}

function canRunTask(task: any) {
  const status = taskEffectiveStatus(task);
  return ["PENDING", "QUEUED", "FAILED", "BLOCKED", "CANCELED"].includes(status);
}

function canForceRunTask(task: any) {
  const status = taskEffectiveStatus(task);
  return ["DONE", "COMPLETED", "CLOSED"].includes(status);
}

function taskEffectiveStatus(task: any) {
  const taskStatus = String(task?.status || "").toUpperCase();
  const linkedRunStatus = String(
    task?.latest_run_status ||
      (task?.run_id ? runs.value.find((row: any) => row?.id === task.run_id)?.status : "") ||
      ""
  ).toUpperCase();
  if (linkedRunStatus === "RUNNING" || linkedRunStatus === "CLAIMED" || linkedRunStatus === "QUEUED") {
    return linkedRunStatus;
  }
  if (linkedRunStatus === "FAILED" || linkedRunStatus === "CANCELED") {
    return linkedRunStatus;
  }
  if (linkedRunStatus === "COMPLETED") {
    return "DONE";
  }
  return taskStatus || "PENDING";
}

function taskCompletionBadgeLabel(task: any) {
  const linkedRunId = task?.run_id || task?.latest_run_id;
  if (!linkedRunId) return "";
  const linkedRun = runs.value.find((row: any) => row?.id === linkedRunId);
  const quality = String(linkedRun?.summary?.terminal_quality || "").trim().toUpperCase();
  if (quality) return quality;
  const status = String(linkedRun?.status || task?.latest_run_status || "").trim().toUpperCase();
  if (status === "COMPLETED") return "COMPLETED";
  if (status === "FAILED") return "FAILED";
  return "";
}

function taskCompletionBadgeType(task: any): "success" | "warning" | "danger" | "info" {
  const badge = taskCompletionBadgeLabel(task);
  if (badge === "COMPLETED_CLEAN" || badge === "COMPLETED" || badge === "COMPLETED_WITH_RECOVERY") return "success";
  if (badge === "DEGRADED_COMPLETION") return "warning";
  if (badge === "FAILED") return "danger";
  return "info";
}

async function runAllTasksOrdered() {
  if (!projectId.value || runAllLoading.value) return;
  const queue = runnableTasks.value;
  if (!queue.length) {
    ElMessage.info("No runnable tasks found.");
    return;
  }
  runAllLoading.value = true;
  batchExecutionTotal.value = queue.length;
  batchExecutionStarted.value = 0;
  batchExecutionNextTitle.value = queue[0]?.title || queue[0]?.id || "";
  runAllProgressLabel.value = `Starting 0/${queue.length} tasks…`;
  tasksError.value = "";
  runError.value = "";
  let started = 0;
  try {
    for (const task of queue) {
      batchExecutionNextTitle.value = task?.title || task?.id || "";
      runAllProgressLabel.value = `Starting ${started + 1}/${queue.length}: ${task.title || task.id}`;
      const requestKey = getOrCreateActionRequestKey("start_run", `project_overview:run_all:${projectId.value}:${task.id}`);
      await createRun(projectId.value, selectedExecutor.value, task.id, null, { request_key: requestKey });
      started += 1;
      batchExecutionStarted.value = started;
    }
    await Promise.all([loadTasks(), loadRuns()]);
    ElMessage.success(`Queued ${started} task run${started === 1 ? "" : "s"} in order.`);
  } catch (err: any) {
    const message = err?.message || "Failed while queueing all tasks";
    tasksError.value = message;
    runError.value = message;
    ElMessage.error(`Queued ${started}/${queue.length}. ${message}`);
  } finally {
    runAllLoading.value = false;
    runAllProgressLabel.value = "";
    batchExecutionTotal.value = 0;
    batchExecutionStarted.value = 0;
    batchExecutionNextTitle.value = "";
  }
}

function canSelectTaskForOrderedRun(row: any) {
  return canRunTask(row);
}

function onTaskSelectionChange(rows: any[]) {
  if (taskSelectionSyncing.value) return;
  const currentIds = rows
    .map((row) => String(row?.id || ""))
    .filter((value) => !!value);
  selectedTaskIds.value = currentIds;
  const selectedSet = new Set(currentIds);
  selectedTaskOrder.value = selectedTaskOrder.value.filter((id) => selectedSet.has(id));
  for (const id of currentIds) {
    if (!selectedTaskOrder.value.includes(id)) selectedTaskOrder.value.push(id);
  }
}

function onTaskSelectChange(selection: any[], row: any) {
  if (taskSelectionSyncing.value) return;
  const id = String(row?.id || "");
  if (!id) return;
  const selectedSet = new Set(selection.map((item) => String(item?.id || "")));
  if (selectedSet.has(id)) {
    selectedTaskOrder.value = selectedTaskOrder.value.filter((value) => value !== id);
    selectedTaskOrder.value.push(id);
  } else {
    selectedTaskOrder.value = selectedTaskOrder.value.filter((value) => value !== id);
  }
}

function manualSelectionDependencyWarnings(queue: any[], allTasks: any[]) {
  const selectedIds = new Set(queue.map((task) => taskId(task)));
  const positions = new Map(queue.map((task, index) => [taskId(task), index]));
  const warnings: string[] = [];
  for (const task of queue) {
    const title = String(task?.title || task?.id || "task");
    const deps = [...inferTaskDependencyIds(task, allTasks)];
    for (const depId of deps) {
      const dep = allTasks.find((row) => taskId(row) === depId);
      const depTitle = String(dep?.title || depId);
      if (!dep) continue;
      if (selectedIds.has(depId)) {
        if ((positions.get(depId) ?? -1) > (positions.get(taskId(task)) ?? -1)) {
          warnings.push(`${title} depends on ${depTitle}, but ${depTitle} is selected later.`);
        }
        continue;
      }
      if (canRunTask(dep)) {
        warnings.push(`${title} depends on ${depTitle}, which is not in your manual selection.`);
      }
    }
  }
  return [...new Set(warnings)];
}

function hasActiveRuns(rows: any[]) {
  // PAUSED runs should not block ordered dispatch; they are resumable/idle states.
  // Only truly active execution states should gate the next task launch.
  return rows.some((run) => ["RUNNING", "QUEUED", "CLAIMED"].includes(String(run?.status || "").toUpperCase()));
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForRunTerminal(runId: string, timeoutMs = 30 * 60 * 1000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const latestRuns = await listRuns(projectId.value);
    runs.value = canonicalizeRuns(Array.isArray(latestRuns) ? latestRuns : []);
    const target = runs.value.find((run: any) => String(run?.id || "") === String(runId));
    const status = String(target?.status || "").toUpperCase();
    if (["COMPLETED", "FAILED", "CANCELED"].includes(status)) return status;
    await sleep(3000);
  }
  throw new Error("Timed out waiting for run completion.");
}

async function waitUntilNoActiveRuns(timeoutMs = 30 * 60 * 1000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const latestRuns = await listRuns(projectId.value);
    runs.value = canonicalizeRuns(Array.isArray(latestRuns) ? latestRuns : []);
    if (!hasActiveRuns(runs.value)) return;
    await sleep(3000);
  }
  throw new Error("Timed out waiting for active run to finish.");
}

async function runSelectedTasksOrdered() {
  if (!projectId.value || runAllLoading.value || runSelectedLoading.value) return;
  const queue = selectedRunnableTasks.value;
  if (!queue.length) {
    ElMessage.info("Select at least one runnable task.");
    return;
  }
  let executionQueue: any[] = [];
  if (selectedExecutionMode.value === "smart") {
    const plan = planSmartSelectedTasks(queue, sortedTasks.value);
    if (plan.unresolvedCycle) {
      tasksError.value = "Selected tasks contain a dependency cycle or ambiguous dependency metadata.";
      ElMessage.error(tasksError.value);
      return;
    }
    const unresolvedMissing = [...plan.missingById.entries()].filter(([_, depIds]) =>
      depIds.some((depId) => {
        const depTask = sortedTasks.value.find((row) => taskId(row) === depId);
        return Boolean(depTask) && canRunTask(depTask);
      })
    );
    if (unresolvedMissing.length) {
      const first = unresolvedMissing[0];
      const task = queue.find((row) => taskId(row) === first[0]);
      const missingTitles = first[1]
        .map((depId) => sortedTasks.value.find((row) => taskId(row) === depId))
        .filter(Boolean)
        .map((row: any) => row.title || depId);
      tasksError.value = `Missing prerequisite selection for "${task?.title || first[0]}": ${missingTitles.join(", ")}`;
      ElMessage.error(tasksError.value);
      return;
    }
    executionQueue = plan.ordered;
    if (plan.autoIncluded.length) {
      ElMessage.info(
        `Smart ordering included ${plan.autoIncluded.length} prerequisite task${plan.autoIncluded.length === 1 ? "" : "s"} automatically.`
      );
    }
  } else {
    executionQueue = queue;
    const warnings = manualSelectionDependencyWarnings(executionQueue, sortedTasks.value);
    if (warnings.length) {
      const preview = warnings.slice(0, 3).join("\n• ");
      try {
        await ElMessageBox.confirm(
          `Dependency warnings detected:\n• ${preview}${warnings.length > 3 ? `\n• ...and ${warnings.length - 3} more` : ""}\n\nRun anyway in your selected order?`,
          "Manual Order Warning",
          {
            confirmButtonText: "Run Anyway",
            cancelButtonText: "Use Smart Order",
            type: "warning",
          }
        );
      } catch {
        selectedExecutionMode.value = "smart";
        ElMessage.info("Switched to Smart mode. Run Selected again to apply intelligent ordering.");
        return;
      }
    }
  }
  runSelectedLoading.value = true;
  batchExecutionTotal.value = executionQueue.length;
  batchExecutionStarted.value = 0;
  batchExecutionNextTitle.value = executionQueue[0]?.title || executionQueue[0]?.id || "";
  runAllProgressLabel.value = `Starting 0/${executionQueue.length} selected tasks…`;
  tasksError.value = "";
  runError.value = "";
  let started = 0;
  try {
    for (const task of executionQueue) {
      batchExecutionNextTitle.value = task?.title || task?.id || "";
      runAllProgressLabel.value = `Waiting to start ${started + 1}/${executionQueue.length}: ${task.title || task.id}`;
      await waitUntilNoActiveRuns();
      runAllProgressLabel.value = `Starting ${started + 1}/${executionQueue.length}: ${task.title || task.id}`;
      const requestKey = getOrCreateActionRequestKey("start_run", `project_overview:run_selected:${projectId.value}:${task.id}`);
      const createdRun = await createRun(projectId.value, selectedExecutor.value, task.id, null, { request_key: requestKey });
      started += 1;
      batchExecutionStarted.value = started;
      const runId = String(createdRun?.id || "");
      if (runId) {
        const finalStatus = await waitForRunTerminal(runId);
        if (finalStatus !== "COMPLETED") {
          throw new Error(`Task ${task.title || task.id} ended with run status ${finalStatus}.`);
        }
      }
      await loadTasks();
    }
    await Promise.all([loadTasks(), loadRuns()]);
    ElMessage.success(`Completed ordered execution for ${started} selected task run${started === 1 ? "" : "s"}.`);
  } catch (err: any) {
    const message = err?.message || "Failed while running selected tasks in order";
    tasksError.value = message;
    runError.value = message;
    ElMessage.error(`Completed ${started}/${executionQueue.length}. ${message}`);
  } finally {
    runSelectedLoading.value = false;
    runAllProgressLabel.value = "";
    batchExecutionTotal.value = 0;
    batchExecutionStarted.value = 0;
    batchExecutionNextTitle.value = "";
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

async function loadDeploymentProviderHints() {
  try {
    const connectors = await listDeploymentConnectors();
    const providers = Array.isArray(connectors)
      ? connectors.map((row: any) => String(row?.provider || "").toLowerCase()).filter(Boolean)
      : [];
    deploymentProviderHints.value = Array.from(new Set(providers));
  } catch {
    deploymentProviderHints.value = [];
  }
}

async function loadDeploymentReadinessContract() {
  if (!projectId.value) return;
  try {
    deploymentReadinessContract.value = await fetchProjectDeploymentReadiness(projectId.value, "PRODUCTION");
  } catch {
    deploymentReadinessContract.value = null;
  }
}

async function loadEnvironmentChecklistSummary() {
  if (!projectId.value) return;
  try {
    environmentChecklistSummary.value = await getProjectEnvironmentChecklists(projectId.value, false);
  } catch {
    environmentChecklistSummary.value = null;
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
    await loadProjectSummary();
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
    if (result?.ok) {
      await loadProjectSummary();
    }
    repoMessage.value = result.ok ? "Repository clone preflight passed." : "";
    repoError.value = result.ok ? "" : result.error || "Repository clone preflight failed.";
  } catch (err: any) {
    repoError.value = err?.message || "Repository clone preflight failed.";
  } finally {
    repoPreflightLoading.value = false;
  }
}

function isHeadMissingCloneError(message: string | null | undefined) {
  const text = String(message || "").toLowerCase();
  return text.includes("ambiguous argument 'head'") || text.includes("unknown revision or path not in the working tree");
}

const canBootstrapEmptyRepo = computed(() => {
  if (repoPreflightLoading.value || repoBootstrapLoading.value) return false;
  if (repoPreflightResult.value?.ok) return false;
  const errorText = String(repoPreflightResult.value?.error || repoError.value || "");
  return isHeadMissingCloneError(errorText);
});

async function bootstrapEmptyRepo() {
  if (!projectId.value) return;
  if (!repoForm.value.repo_url.trim()) {
    repoError.value = "Repository URL is required.";
    return;
  }
  repoBootstrapLoading.value = true;
  repoError.value = "";
  repoMessage.value = "";
  try {
    repoForm.value.repo_url = normalizeRepoUrlForStrategy(
      repoForm.value.repo_url,
      repoForm.value.auth_strategy,
      repoForm.value.repo_full_name
    );
    const result = await bootstrapProjectRepo(projectId.value, {
      provider: "github",
      repo_url: repoForm.value.repo_url.trim(),
      repo_full_name: repoForm.value.repo_full_name.trim() || null,
      default_branch: repoForm.value.default_branch.trim() || "main",
      installation_id: repoForm.value.installation_id.trim()
        ? Number.parseInt(repoForm.value.installation_id.trim(), 10)
        : null,
      auth_strategy: repoForm.value.auth_strategy,
      readme_title: projectName.value || "Project Bootstrap",
      commit_message: "chore(repo): bootstrap repository",
    });
    if (!result?.ok) {
      repoError.value = result?.error || result?.message || "Repository bootstrap failed.";
      return;
    }
    repoMessage.value = result?.created
      ? "Empty repository initialized. Re-running clone preflight."
      : "Repository already initialized. Re-running clone preflight.";
    await runRepoPreflight();
  } catch (err: any) {
    repoError.value = err?.message || "Repository bootstrap failed.";
  } finally {
    repoBootstrapLoading.value = false;
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

async function loadDesignContract() {
  if (!projectId.value) return;
  designContractError.value = "";
  try {
    const payload = await fetchDesignContract(projectId.value);
    designContract.value = payload || null;
    designContractForm.value = {
      experience_blueprint: payload?.experience_blueprint || "premium_saas",
      identity: payload?.identity || {},
      tokens: payload?.tokens || {},
      token_registry: payload?.token_registry || {},
      allowed_components: Array.isArray(payload?.allowed_components) ? payload.allowed_components : [],
      typography: payload?.typography || {},
      components: payload?.components || {},
      layout: payload?.layout || {},
    };
    syncDesignEditorFromForm();
  } catch (err: any) {
    designContract.value = null;
    designContractForm.value = {
      experience_blueprint: "premium_saas",
      identity: { name: "Product", tone: "technical_minimal_premium", personality: "confident_operational_clean" },
      tokens: {},
      token_registry: { colors: {}, spacing: {}, radius: {}, motion: {}, elevation: {} },
      allowed_components: [],
      typography: { heading_font: "Inter", body_font: "Inter", radius_scale: "soft", density: "comfortable" },
      components: { buttons: { style: "glass", radius: "xl", shadow: "soft" }, registry: [] },
      layout: { spacing: "airy", container_width: "wide", visual_weight: "balanced", hero_style: "immersive" },
    };
    designContractEditorValue.value = JSON.stringify({}, null, 2);
    designContractError.value = err?.message || "Failed to load design contract.";
  }
}

async function openDesignContractDialog() {
  if (!projectId.value) return;
  showDesignContractDialog.value = true;
  designContractLoading.value = true;
  designContractError.value = "";
  try {
    await loadDesignContract();
  } finally {
    designContractLoading.value = false;
  }
}

async function saveDesignContractDraft() {
  if (!projectId.value) return;
  designContractSaveLoading.value = true;
  designContractError.value = "";
  try {
    const payload = showDesignAdvancedEditor.value
      ? JSON.parse(designContractEditorValue.value || "{}")
      : { ...designContractForm.value };
    const saved = await saveDesignContract(projectId.value, {
      experience_blueprint: payload?.design_contract?.experience_blueprint || payload?.experience_blueprint || undefined,
      identity: payload?.design_contract?.identity || payload?.identity || undefined,
      tokens: payload?.design_contract?.tokens || payload?.tokens || {},
      token_registry: payload?.design_contract?.token_registry || payload?.token_registry || undefined,
      allowed_components: payload?.design_contract?.allowed_components || payload?.allowed_components || [],
      typography: payload?.design_contract?.typography || payload?.typography || undefined,
      components: payload?.design_contract?.components || payload?.components || {},
      layout: payload?.design_contract?.layout || payload?.layout || undefined,
      updated_by: "ui-user",
    });
    const normalized = saved?.contract_json?.design_contract || payload?.design_contract || payload || {};
    designContract.value = normalized;
    designContractForm.value = {
      experience_blueprint: normalized?.experience_blueprint || "premium_saas",
      identity: normalized?.identity || {},
      tokens: normalized?.tokens || {},
      token_registry: normalized?.token_registry || {},
      allowed_components: Array.isArray(normalized?.allowed_components) ? normalized.allowed_components : [],
      typography: normalized?.typography || {},
      components: normalized?.components || {},
      layout: normalized?.layout || {},
    };
    designContractEditorValue.value = JSON.stringify(normalized, null, 2);
    ElMessage.success("Design contract saved.");
  } catch (err: any) {
    designContractError.value = err?.message || "Failed to save design contract.";
  } finally {
    designContractSaveLoading.value = false;
  }
}

function applyDesignPreset() {
  const key = String(selectedDesignPreset.value || "").trim();
  if (!key) return;
  const preset = designPresetRegistry[key];
  if (!preset) return;
  designContract.value = { ...preset };
  designContractForm.value = JSON.parse(JSON.stringify(preset));
  syncDesignEditorFromForm();
  ElMessage.success(`Applied ${designPresetOptions.find((item) => item.value === key)?.label || "preset"} preset.`);
}

function syncDesignEditorFromForm() {
  designContractEditorValue.value = JSON.stringify(designContractForm.value || {}, null, 2);
}

function applyDesignEditorToForm() {
  try {
    const parsed = JSON.parse(designContractEditorValue.value || "{}");
    designContractForm.value = {
      experience_blueprint: parsed?.experience_blueprint || "premium_saas",
      identity: parsed?.identity || {},
      tokens: parsed?.tokens || {},
      token_registry: parsed?.token_registry || {},
      allowed_components: Array.isArray(parsed?.allowed_components) ? parsed.allowed_components : [],
      typography: parsed?.typography || {},
      components: parsed?.components || {},
      layout: parsed?.layout || {},
    };
    ElMessage.success("Applied JSON to guided fields.");
  } catch (err: any) {
    designContractError.value = err?.message || "Invalid design contract JSON.";
  }
}

function collectDesignDiffRows(
  source: any,
  target: any,
  basePath: string,
  rows: Array<{ path: string; from: string; to: string }>
) {
  const sourceObj = source && typeof source === "object" ? source : {};
  const targetObj = target && typeof target === "object" ? target : {};
  const keys = Array.from(new Set([...Object.keys(sourceObj), ...Object.keys(targetObj)])).sort();

  for (const key of keys) {
    const path = basePath ? `${basePath}.${key}` : key;
    const left = sourceObj[key];
    const right = targetObj[key];
    const leftIsObj = left && typeof left === "object" && !Array.isArray(left);
    const rightIsObj = right && typeof right === "object" && !Array.isArray(right);

    if (leftIsObj || rightIsObj) {
      collectDesignDiffRows(left, right, path, rows);
      continue;
    }
    const leftText = formatDesignDiffValue(left);
    const rightText = formatDesignDiffValue(right);
    if (leftText !== rightText) {
      rows.push({ path, from: leftText, to: rightText });
    }
  }
}

function formatDesignDiffValue(value: any) {
  if (value === undefined) return "∅";
  if (value === null) return "null";
  if (Array.isArray(value)) return JSON.stringify(value);
  if (typeof value === "object") return JSON.stringify(value);
  const text = String(value);
  return text.length > 70 ? `${text.slice(0, 67)}...` : text;
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
    runs.value = canonicalizeRuns(await listRuns(projectId.value));
    updateProjectContext({
      latestRunId: latestRunRecord.value?.id || "",
      runStatus: latestRunRecord.value?.status || "IDLE",
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
  if (startRunBlockedReason.value) {
    runError.value = startRunBlockedReason.value;
    ElMessage.warning(startRunBlockedReason.value);
    return;
  }
  runError.value = "";
  try {
    const requestKey = getOrCreateActionRequestKey("start_run", `project_overview:start:${projectId.value}`);
    const createdRun = await createRun(projectId.value, selectedExecutor.value, null, null, { request_key: requestKey });
    if (createdRun?.id) {
      runs.value = canonicalizeRuns([createdRun, ...runs.value.filter((run) => run?.id !== createdRun.id)]);
      updateProjectContext({
        latestRunId: createdRun.id,
        runStatus: createdRun.status || "QUEUED",
        hasActiveRun: true,
        updatedAt: new Date().toISOString(),
      });
      ElMessage.success(`Run queued: ${String(createdRun.id).slice(0, 8)}`);
    }
    await loadRuns();
    await loadWorkItems();
    await loadRunEvents();
  } catch (err: any) {
    runError.value = err?.message || "Failed to create run";
    if (String(runError.value).toLowerCase().includes("architecture profile must be derived")) {
      ElMessage.warning("Run blocked: complete Bootstrap and Derive in Architecture Contract.");
      showArchitectureDialog.value = true;
    }
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

async function resumeRunById(runId: string) {
  runError.value = "";
  runResumeLoading.value = { ...runResumeLoading.value, [runId]: true };
  try {
    await resumeRun(runId, { start_now: true });
    ElMessage.success("Run resumed.");
    await loadRuns();
    await loadWorkItems();
    await loadRunEvents();
  } catch (err: any) {
    runError.value = err?.message || "Failed to resume run";
  } finally {
    runResumeLoading.value = { ...runResumeLoading.value, [runId]: false };
  }
}

async function loadWorkItems() {
  if (!projectId.value || !latestRunRecord.value?.id) {
    workItems.value = [];
    return;
  }
  workItemsLoading.value = true;
  workItemError.value = "";
  const currentRunId = latestRunRecord.value.id;
  try {
    workItems.value = await listWorkItems(projectId.value, currentRunId);
  } catch (err: any) {
    workItemError.value = err?.message || "Failed to load work items";
  } finally {
    workItemsLoading.value = false;
  }
}

async function loadRunEvents() {
  if (!latestRunRecord.value?.id) {
    runEvents.value = [];
    return;
  }
  const currentRunId = latestRunRecord.value.id;
  try {
    runEvents.value = await listRunEvents(currentRunId);
  } catch (err) {
    // ignore
  }
}

function shouldPollOverview() {
  const status = String(latestRunRecord.value?.status || "").toUpperCase();
  return status === "RUNNING" || status === "QUEUED" || status === "CLAIMED";
}

function stopOverviewPolling() {
  if (overviewPollHandle) {
    clearTimeout(overviewPollHandle);
    overviewPollHandle = null;
  }
}

async function pollOverviewOnce() {
  if (!projectId.value || overviewPollInFlight) return;
  overviewPollInFlight = true;
  try {
    await loadRuns();
  } finally {
    overviewPollInFlight = false;
    syncOverviewPolling();
  }
}

function syncOverviewPolling() {
  stopOverviewPolling();
  if (!shouldPollOverview()) return;
  const hidden = typeof document !== "undefined" && document.hidden;
  const delayMs = hidden ? 5000 : 2000;
  overviewPollHandle = setTimeout(() => {
    void pollOverviewOnce();
  }, delayMs);
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
  window.addEventListener("agentic:tenant-changed", handleTenantChanged as EventListener);
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
  await loadMemoryDashboard();
    await loadFoundationReadiness();
    await loadGenesisState();
  await loadProjectMeta();
  await loadRuns();
  await loadDesignContract();
  await loadProjectRepo();
  await loadDeploymentProviderHints();
  await loadDeploymentReadinessContract();
  await loadEnvironmentChecklistSummary();
  await loadGitHubConnectInfo();
  await loadWorkItems();
  await loadRunEvents();
  await hydrateGitHubInstallFromRoute();
  if (String(route.name || "") === "project-tasks") {
    tasksDialogFullscreen.value = true;
    await openTasksDialog();
  }
  syncOverviewPolling();
});

onBeforeUnmount(() => {
  stopOverviewPolling();
  window.removeEventListener("agentic:tenant-changed", handleTenantChanged as EventListener);
});

function resetOverviewStateForTenantSwitch() {
  error.value = "";
  runs.value = [];
  workItems.value = [];
  runEvents.value = [];
  documents.value = [];
  tasks.value = [];
  taskSnapshot.value = [];
  improvementRequests.value = [];
  requirementSummaryCards.value = [];
  planHistory.value = [];
  latestDelivery.value = null;
  projectRepo.value = null;
  stopOverviewPolling();
}

function handleTenantChanged() {
  resetOverviewStateForTenantSwitch();
  if (!getActiveTenantId()) {
    void router.replace({
      path: "/",
      query: { tenantRequired: "1", requestedProject: projectId.value || undefined },
    });
    return;
  }
  if (projectId.value) {
    void router.replace({ path: `/projects/${projectId.value}` });
  }
}

watch(
  () => [route.query.installation_id, route.query.setup_action],
  () => {
    void hydrateGitHubInstallFromRoute();
  }
);

watch(
  () => latestRunRecord.value?.status,
  () => {
    syncOverviewPolling();
  }
);
</script>

<style scoped>
.project-overview-hero,
.project-overview-panel,
.project-overview-primary {
  border-radius: 22px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: linear-gradient(160deg, rgba(255, 255, 255, 0.88), rgba(248, 250, 252, 0.78));
  box-shadow:
    0 16px 34px rgba(15, 23, 42, 0.09),
    inset 0 1px 0 rgba(255, 255, 255, 0.5);
}

.project-overview-primary {
  position: sticky;
  top: 0.75rem;
  z-index: 6;
}

.project-actions-grid {
  max-height: 18rem;
  overflow-y: auto;
  padding-right: 0.25rem;
  scrollbar-width: thin;
}

.project-actions-grid::-webkit-scrollbar {
  width: 10px;
}

.project-actions-grid::-webkit-scrollbar-thumb {
  border-radius: 9999px;
  background: linear-gradient(180deg, rgba(100, 116, 139, 0.35), rgba(148, 163, 184, 0.5));
}

:deep(.tasks-dialog .el-dialog__body) {
  max-height: calc(100vh - 140px);
  overflow-y: auto;
  padding-top: 0.5rem;
}

@media (max-width: 1024px) {
  .project-overview-primary {
    position: static;
  }

  .project-actions-grid {
    max-height: 15rem;
  }
}
</style>
