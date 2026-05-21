<template>
  <div v-if="projectId" :class="['page-stack mission-control-page', `density-${densityMode}`]">
    <section v-if="project && primaryActionCard" class="grid gap-4">
      <div class="premium-card mission-panel mission-primary-top p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div class="text-xs uppercase tracking-wide text-slate-400">Primary Action</div>
            <div class="mt-1 text-base font-semibold text-slate-900">{{ primaryActionCard.title }}</div>
            <div class="mt-1 text-sm text-slate-600">{{ primaryActionCard.description }}</div>
          </div>
          <div class="flex items-center gap-2">
            <el-tag :type="primaryActionCard.tone" effect="light">{{ primaryActionCard.badge }}</el-tag>
            <el-button plain @click="scrollToWorkIntake">
              Open Work Intake
            </el-button>
            <el-button
              v-if="previewsAndPrs?.active_preview_url || previewsAndPrs?.preview_url"
              plain
              @click="openExternal(previewsAndPrs.active_preview_url || previewsAndPrs.preview_url)"
            >
              Open Preview
            </el-button>
            <el-button :type="primaryActionCard.buttonType" @click="handlePrimaryAction">
              {{ primaryActionCard.buttonLabel }}
            </el-button>
          </div>
        </div>
      </div>
    </section>

    <section class="premium-hero mission-hero">
      <div class="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
        <div class="max-w-3xl">
          <div class="premium-hero__eyebrow">Mission Control</div>
          <h1 class="premium-hero__title">Keep the automation loop visible, governed, and moving.</h1>
          <p class="premium-hero__copy">
            Watch the active runtime, inspect healing decisions, trace artifacts into pull requests, and keep the delivery system readable while it operates.
          </p>
          <div class="mt-5 flex flex-wrap gap-2">
            <span class="topbar-chip">
              <AppIcon name="project" size="sm" />
              {{ project?.name || "Loading project…" }}
            </span>
            <span class="topbar-chip">
              <AppIcon name="status" size="sm" />
              {{ currentStage }}
            </span>
            <span class="topbar-chip">
              <AppIcon name="runs" size="sm" />
              {{ latestRun?.status || "IDLE" }}
            </span>
            <span class="topbar-chip">
              <AppIcon name="branch" size="sm" />
              {{ previewsAndPrs?.repo_full_name || latestRun?.branch_name || "Repo not connected" }}
            </span>
          </div>
        </div>
        <div class="mission-hero__controls mission-subcard p-3">
          <div class="mission-hero__controls-label">Run Actions</div>
          <div class="mission-run-picker">
            <span class="mission-run-picker__label">Focus run</span>
            <el-select
              v-model="pinnedRunId"
              size="small"
              placeholder="Auto (current)"
              class="mission-run-picker__select"
              @change="onPinnedRunChange"
            >
              <el-option label="Auto (current)" value="" />
              <el-option
                v-for="option in runSelectorOptions"
                :key="option.id"
                :label="option.label"
                :value="option.id"
              />
            </el-select>
          </div>
          <div class="mission-density-toggle">
            <button
              type="button"
              class="topbar-chip"
              :style="densityMode === 'compact' ? activeFilterStyle : undefined"
              @click="densityMode = 'compact'"
            >
              Compact
            </button>
            <button
              type="button"
              class="topbar-chip"
              :style="densityMode === 'comfortable' ? activeFilterStyle : undefined"
              @click="densityMode = 'comfortable'"
            >
              Comfortable
            </button>
          </div>
          <div class="mission-hero__controls-grid">
          <el-button :loading="loading" @click="loadAll">Refresh</el-button>
          <el-button plain :disabled="!forkEnabled" @click="openForkDialog">
            Fork Run
          </el-button>
          <el-button plain :disabled="!forkEnabled" @click="openReplayDialog()">
            Replay Run
          </el-button>
          <el-tooltip v-if="resumeBlockedHint && !operatorConfirmationPaused" :content="resumeBlockedHint" placement="top">
            <span class="inline-flex">
              <el-button plain :disabled="!resumeActionEnabled" :loading="resumeLoading" @click="resumeLatestRun">
                {{ resumeActionLabel }}
              </el-button>
            </span>
          </el-tooltip>
          <el-button v-else plain :disabled="!resumeActionEnabled" :loading="resumeLoading" @click="resumeLatestRun">
            {{ resumeActionLabel }}
          </el-button>
          <el-button
            v-if="budgetPaused"
            type="warning"
            plain
            :disabled="!latestRun?.id || budgetExtendLoading"
            :loading="budgetExtendLoading"
            @click="openBudgetDialog"
          >
            Increase Budget & Continue
          </el-button>
          <el-button plain :disabled="!manualPushRequired" :loading="retryPushLoading" @click="retryLatestRunPush">
            Retry Push
          </el-button>
          <el-button plain :disabled="!forkEnabled" @click="openStrategyDialog">
            Strategy Lab
          </el-button>
          <el-button plain :disabled="!forkEnabled" @click="openImproveDialog()">
            Report Issue / Improve
          </el-button>
          <el-button plain :disabled="!compareEnabled" @click="openCompareDialog">
            Compare Runs
          </el-button>
          <el-button type="danger" plain :disabled="!cancelEnabled" @click="cancelLatestRun">
            Cancel Run
          </el-button>
          <el-button
            type="danger"
            plain
            :disabled="!latestRun?.id || discardLoading"
            :loading="discardLoading"
            @click="discardLatestRunWorkspace"
          >
            Discard Run
          </el-button>
          <el-button @click="goToOverview">Project Overview</el-button>
        </div>
        <div v-if="resumeBlockedHint" class="mt-2 text-xs text-amber-700">
          Resume unavailable: {{ resumeBlockedHint }}
        </div>
        <div v-if="internalPolicyBlockHint" class="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {{ internalPolicyBlockHint }}
        </div>
        </div>
      </div>
      <div class="mission-hero__rail">
        <div class="mission-chip-panel">
          <div class="mission-chip-panel__label">Project ID</div>
          <div class="mission-chip-panel__value font-mono">{{ projectId || "—" }}</div>
        </div>
        <div class="mission-chip-panel">
          <div class="mission-chip-panel__label">Focused Run</div>
          <div class="mission-chip-panel__value font-mono">{{ latestRun?.id || "—" }}</div>
          <div class="mission-chip-panel__meta">{{ latestRun?.executor || "No executor" }}</div>
        </div>
        <div class="mission-chip-panel">
          <div class="mission-chip-panel__label">Terminal Quality</div>
          <div class="mission-chip-panel__value">
            <el-tag effect="light" :type="runStatusTagType(latestTerminalQuality)">
              {{ latestTerminalQualityLabel }}
            </el-tag>
          </div>
          <div class="mission-chip-panel__meta">
            Critical failed {{ latestTerminalCounts.critical_failed || 0 }} · Optional failed {{ latestTerminalCounts.optional_failed || 0 }}
          </div>
        </div>
        <div class="mission-chip-panel">
          <div class="mission-chip-panel__label">Workspace</div>
          <div class="mission-chip-panel__value">{{ latestRun?.workspace_status || "PENDING" }}</div>
          <div class="mission-chip-panel__meta font-mono">{{ shortenPath(latestRun?.repo_path) }}</div>
        </div>
        <div class="mission-chip-panel">
          <div class="mission-chip-panel__label">Automation Pulse</div>
          <div class="mission-chip-panel__value">{{ agentSnapshot.active }} active agents</div>
          <div class="mission-chip-panel__meta">
            {{ runtimeCounts.queued }} queued · {{ runtimeCounts.blocked }} blocked · {{ runtimeCounts.warnings }} warnings · {{ runtimeCounts.done }} done
          </div>
        </div>
        <div v-if="linkedRequirementId" class="mission-chip-panel">
          <div class="mission-chip-panel__label">Linked Requirement</div>
          <div class="mission-chip-panel__value font-mono">{{ linkedRequirementId }}</div>
          <div class="mission-chip-panel__meta">
            Health {{ linkedRequirementHealth ?? "—" }} · Retries {{ linkedRequirementRetries }} · Unresolved {{ linkedRequirementUnresolved }}
          </div>
        </div>
      </div>
    </section>

    <section class="premium-card mission-panel p-4" style="border: 2px solid rgba(14, 165, 233, 0.5); background: rgba(14, 165, 233, 0.08);">
      <div class="text-xs font-semibold uppercase tracking-[0.2em] text-sky-700">Live Execution Status</div>
      <div class="mt-2 grid gap-2 text-sm font-semibold text-slate-900 md:grid-cols-3">
        <div>Queue: {{ missionStatusBanner.queue }}</div>
        <div>In Progress: {{ missionStatusBanner.inProgress }} ({{ missionStatusBanner.inProgressTaskName }})</div>
        <div>Completed: {{ missionStatusBanner.completed }} / {{ missionStatusBanner.total }}</div>
      </div>
    </section>

    <el-alert
      v-if="lifecycleWarnings.length"
      type="warning"
      show-icon
      :closable="false"
      title="Runtime warnings"
      :description="lifecycleWarnings.join(' · ')"
      class="shadow-sm"
    />

    <el-alert
      v-if="!hasRun"
      type="info"
      show-icon
      :closable="false"
      title="No runs yet"
      description="Mission Control is ready. Start a run from Work Intake or Project Overview to begin execution."
      class="shadow-sm"
    />

    <el-alert
      v-if="overviewError"
      type="warning"
      show-icon
      :closable="false"
      title="Mission Control overview is partially unavailable"
      :description="overviewError"
      class="shadow-sm"
    />
    <section v-if="stalledRuns.length" class="premium-card mission-panel p-4">
      <div class="text-xs font-semibold uppercase tracking-[0.2em] text-amber-700">Stalled Run Detector</div>
      <div class="mt-2 space-y-2">
        <div v-for="item in stalledRuns" :key="item.run_id" class="mission-subcard p-3 text-sm">
          <div class="font-semibold text-slate-900">
            Run {{ shortRunId(item.run_id) }} · {{ item.status }}
          </div>
          <div class="text-xs text-slate-600">
            Last event: {{ formatTimestamp(item.last_event_at) }} · stale {{ item.stale_seconds }}s
          </div>
          <div class="text-xs text-amber-700">{{ item.suggested_action }}</div>
        </div>
      </div>
    </section>

    <el-alert
      v-if="improveSuccessMessage"
      type="success"
      show-icon
      closable
      title="Improvement run created"
      :description="improveSuccessMessage"
      @close="improveSuccessMessage = ''"
      class="shadow-sm"
    />

    <el-alert
      v-if="manualPushRequired"
      type="warning"
      show-icon
      :closable="false"
      title="Remote push needs manual follow-up"
      :description="manualPushHint"
      class="shadow-sm"
    />
    <el-alert
      v-if="budgetPaused"
      type="warning"
      show-icon
      :closable="false"
      title="Run paused for budget approval"
      :description="budgetWarningHint"
      class="shadow-sm"
    />
    <el-alert
      v-if="operatorConfirmationPaused"
      type="warning"
      show-icon
      :closable="false"
      title="Run paused for operator confirmation"
      :description="operatorConfirmationHint"
      class="shadow-sm"
    />
    <div v-if="operatorConfirmationPaused" class="mission-inline-actions">
      <el-button
        size="small"
        type="warning"
        plain
        :disabled="!latestRun?.id || resumeLoading"
        :loading="resumeLoading"
        @click="resumeLatestRun"
      >
        Confirm & Resume
      </el-button>
      <el-button size="small" plain @click="openApprovalsView">
        Open Approvals
      </el-button>
      <el-button size="small" plain @click="openTimelinePage(latestRun?.id || '')">
        Go to Exact Run
      </el-button>
    </div>
    <div v-if="manualPushRequired" class="mission-inline-actions">
      <el-select v-model="retryPushStrategy" size="small" class="mission-inline-select">
        <el-option label="Runtime Default" value="runtime_default" />
        <el-option label="GitHub App" value="github_app" />
        <el-option label="SSH" value="ssh" />
        <el-option label="Public HTTPS" value="public_https" />
      </el-select>
      <el-button size="small" plain @click="copyManualPushCommands">Copy Commands</el-button>
    </div>
    <pre v-if="manualPushRequired" class="mission-inline-code">{{ manualPushCommands }}</pre>

    <div v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
      {{ error }}
    </div>
    <section v-if="importedReferences.length" class="premium-card mission-panel p-5">
      <div class="text-sm uppercase tracking-wide text-slate-400">Imported References</div>
      <div class="mt-2 text-xs text-slate-500">Governed external knowledge linked into runtime context.</div>
      <div class="mt-3 space-y-2">
        <div v-for="ref in importedReferences" :key="ref.id" class="mission-subcard p-3 text-sm">
          <div class="font-medium text-slate-900">{{ ref.label || ref.type }}</div>
          <a :href="ref.uri" target="_blank" rel="noreferrer" class="break-all text-sky-700 underline">{{ ref.uri }}</a>
          <div class="mt-1 text-xs text-slate-500">
            {{ ref.domain || "unknown domain" }} · imported {{ formatTimestamp(ref.imported_at || ref.created_at) }}
          </div>
          <div class="mt-1 text-xs text-slate-500">
            trust {{ ref.trust_score ?? "—" }} · freshness {{ ref.freshness_score ?? "—" }} · used {{ ref.used_in_execution_count || 0 }}x
          </div>
          <div class="mt-1 text-xs text-slate-500">
            req {{ ref.linked_requirement_id || "—" }} · run {{ shortRunId(ref.linked_run_id) }} · work item {{ shortRunId(ref.linked_work_item_id) }}
          </div>
        </div>
      </div>
    </section>

    <section v-if="project" class="surface-grid md:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="Project Stage" :value="currentStage" :detail="`Project: ${project.name}`">
        <template #icon>
          <AppIcon name="status" size="lg" />
        </template>
        <template #footer>
          <StageBadge :label="currentStage" />
        </template>
      </MetricCard>

      <MetricCard
        label="Lifecycle Health"
        :value="lifecycleScore?.health_index ?? '—'"
        :detail="`Risk: ${lifecycleScore?.risk_level || 'UNKNOWN'}`"
        :tone="healthTone"
      >
        <template #icon>
          <AppIcon name="spark" size="lg" />
        </template>
        <template #footer>
          <el-tag v-if="lifecycleScore?.grade" effect="light" :type="healthTagType">
            {{ lifecycleScore.grade }}
          </el-tag>
        </template>
      </MetricCard>

      <MetricCard
        label="Latest Run"
        :value="latestRun?.status || 'IDLE'"
        :detail="`Started: ${formatTimestamp(latestRun?.started_at)}`"
        :tone="runStatusTone"
      >
        <template #icon>
          <AppIcon name="runs" size="lg" />
        </template>
        <template #footer>
          <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <el-tag :type="runStatusTagType(latestRun?.status)" effect="light">
              {{ latestRun?.status || "IDLE" }}
            </el-tag>
            <span>{{ latestRun?.executor || "—" }}</span>
          </div>
        </template>
      </MetricCard>

      <MetricCard
        label="Work Items"
        :value="`${runtimeCounts.running} running`"
        :detail="`${runtimeCounts.queued} queued · ${runtimeCounts.done} done · ${runtimeCounts.blocked} blocked · ${runtimeCounts.warnings} warnings`"
        :tone="runtimeCounts.blocked ? 'danger' : runtimeCounts.warnings || runtimeCounts.running ? 'warning' : 'neutral'"
      >
        <template #icon>
          <AppIcon name="mission" size="lg" />
        </template>
        <template #footer>
          <div class="text-xs text-slate-500">
            ETA: {{ runEtaLabel }}
          </div>
        </template>
      </MetricCard>
    </section>

    <section v-if="project && hasRun" class="grid gap-4 xl:grid-cols-[1.2fr,1fr,0.95fr]">
      <div class="premium-card mission-panel p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Run Plan</div>
            <div class="text-xs text-slate-500">Structured plan snapshot for the latest run.</div>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <el-tag v-if="runNarrative?.plan?.risk_level" :type="impactRiskTagType(runNarrative.plan.risk_level)" effect="light">
              {{ runNarrative.plan.risk_level }}
            </el-tag>
            <el-tag effect="light" type="info">
              {{ planStepCounts.done }}/{{ planStepCounts.total || 0 }} done
            </el-tag>
          </div>
        </div>
        <div v-if="runNarrativeLoading" class="mt-4 text-sm text-slate-500">Building plan snapshot…</div>
        <div v-else-if="runNarrativeError" class="mt-4 text-sm text-rose-600">{{ runNarrativeError }}</div>
          <div v-else-if="runNarrative" class="mt-4 space-y-4 mission-content-scroll">
            <div class="mission-subcard p-4">
              <div class="text-xs uppercase tracking-wide text-slate-400">Goal</div>
            <div class="mt-2 text-sm font-medium text-slate-900">
              {{ runNarrative.plan.goal || runNarrative.summary.goal_text || "No run goal recorded." }}
            </div>
            <div v-if="runNarrative.plan.rationale" class="mt-2 text-sm text-slate-600">
              {{ runNarrative.plan.rationale }}
            </div>
              <div class="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
                <div><strong>Expected files:</strong> {{ runNarrative.plan.expected_files?.join(", ") || "—" }}</div>
                <div><strong>Commands:</strong> {{ runNarrative.plan.expected_commands?.join(", ") || "—" }}</div>
                <div><strong>Validation:</strong> {{ runNarrative.plan.validation_steps?.join(", ") || "—" }}</div>
                <div><strong>Confidence:</strong> {{ formatConfidence(runNarrative.plan.confidence_score) }}</div>
              </div>
            </div>

            <div class="mission-subcard p-4">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div class="text-xs uppercase tracking-wide text-slate-400">Task Decomposition</div>
                  <div class="mt-1 text-sm font-medium text-slate-900">
                    {{ runNarrative.task_decomposition.template_label || "Bounded Change" }}
                  </div>
                  <div v-if="runNarrative.task_decomposition.description" class="mt-1 text-sm text-slate-600">
                    {{ runNarrative.task_decomposition.description }}
                  </div>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <el-tag size="small" effect="light" :type="impactRiskTagType(runNarrative.task_decomposition.risk_level)">
                    {{ runNarrative.task_decomposition.risk_level }}
                  </el-tag>
                  <el-tag size="small" effect="light" type="info">
                    {{ taskDecompositionCounts.done }}/{{ taskDecompositionCounts.total || 0 }} done
                  </el-tag>
                </div>
              </div>
              <div class="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
                <div><strong>Goal:</strong> {{ runNarrative.task_decomposition.goal || "—" }}</div>
                <div><strong>Retry model:</strong> subtask-level only</div>
                <div><strong>Subtask budget:</strong> {{ runNarrative.task_decomposition.subtasks?.length || 0 }}/{{ runNarrative.task_decomposition.max_subtasks }}</div>
                <div><strong>Per-task file cap:</strong> {{ runNarrative.task_decomposition.max_files_per_task }}</div>
              </div>
              <div class="mt-3 space-y-2">
                <div
                  v-for="subtask in runNarrative.task_decomposition.subtasks"
                  :key="subtask.id"
                  class="rounded-xl border border-slate-200/70 bg-slate-50/80 p-3 text-sm"
                >
                  <div class="flex flex-wrap items-center justify-between gap-2">
                    <div class="font-medium text-slate-900">{{ subtask.title }}</div>
                    <el-tag size="small" effect="light" :type="narrativeStatusTagType(subtask.status, subtask.blocking)">
                      {{ subtask.status }}
                    </el-tag>
                    <el-tag v-if="subtask.blocking === false" size="small" effect="light" type="warning">Optional</el-tag>
                  </div>
                  <div v-if="subtask.description" class="mt-1 text-slate-600">{{ subtask.description }}</div>
                  <div class="mt-2 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
                    <div><strong>Retry scope:</strong> {{ subtask.retry_scope }}</div>
                    <div><strong>Work items:</strong> {{ subtask.work_item_types?.join(", ") || "—" }}</div>
                    <div><strong>Depends on:</strong> {{ subtask.depends_on?.join(", ") || "—" }}</div>
                    <div><strong>Expected files:</strong> {{ subtask.expected_files?.join(", ") || "—" }}</div>
                  </div>
                </div>
              </div>
              <div class="mt-4 flex flex-wrap items-center gap-2">
                <el-button
                  v-if="runNarrative.task_decomposition.requires_confirmation"
                  size="small"
                  type="warning"
                  plain
                  @click="requestRunConfirmation"
                >
                  Task Tree Requires Approval
                </el-button>
                <el-tag v-else effect="light" type="success">Bounded template</el-tag>
              </div>
            </div>

            <div class="mission-subcard p-4">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div class="text-xs uppercase tracking-wide text-slate-400">Patch Plan</div>
                  <div class="mt-1 text-sm font-medium text-slate-900">
                    {{ runNarrative.patch_plan.subsystem || "Scoped patch envelope" }}
                  </div>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <el-tag size="small" effect="light" :type="impactRiskTagType(runNarrative.patch_plan.risk_level)">
                    {{ runNarrative.patch_plan.risk_level }}
                  </el-tag>
                  <el-tag size="small" effect="light" type="info">
                    {{ runNarrative.patch_plan.total_scope_files || 0 }} files in scope
                  </el-tag>
                </div>
              </div>
              <div class="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
                <div><strong>Primary files:</strong> {{ runNarrative.patch_plan.primary_files?.join(", ") || "—" }}</div>
                <div><strong>Dependent files:</strong> {{ runNarrative.patch_plan.dependent_files?.join(", ") || "—" }}</div>
                <div><strong>Related tests:</strong> {{ runNarrative.patch_plan.related_tests?.join(", ") || "—" }}</div>
                <div><strong>Scope depth:</strong> {{ runNarrative.patch_plan.scope_depth || 1 }}</div>
              </div>
              <div class="mt-3 text-xs text-slate-500">
                <strong>Planned patch steps:</strong> {{ runNarrative.patch_plan.steps?.join(" · ") || "—" }}
              </div>
            </div>

            <div class="mission-subcard p-4">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div class="text-xs uppercase tracking-wide text-slate-400">Verification Summary</div>
                  <div class="mt-1 text-sm font-medium text-slate-900">
                    {{ runNarrative.verification.suggested_next_action || "Verification summary unavailable." }}
                  </div>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <el-tag size="small" effect="light" :type="verificationStatusTagType(runNarrative.verification.status)">
                    {{ runNarrative.verification.status }}
                  </el-tag>
                  <el-tag size="small" effect="light" :type="impactRiskTagType(runNarrative.verification.risk_level)">
                    {{ runNarrative.verification.risk_level }}
                  </el-tag>
                </div>
              </div>
              <div class="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
                <div><strong>Verified files:</strong> {{ runNarrative.verification.verified_files?.join(", ") || "—" }}</div>
                <div><strong>Actual files:</strong> {{ runNarrative.verification.actual_files?.join(", ") || "—" }}</div>
                <div><strong>Nearest tests:</strong> {{ runNarrative.verification.nearest_tests?.join(", ") || "—" }}</div>
                <div><strong>File budget:</strong> {{ runNarrative.verification.file_count }}/{{ runNarrative.verification.max_files }}</div>
                <div><strong>Depth budget:</strong> {{ runNarrative.verification.scope_depth }}/{{ runNarrative.verification.max_dependency_depth }}</div>
                <div><strong>Scope match:</strong> {{ verificationScopeLabel(runNarrative.verification.scope_match) }}</div>
                <div><strong>Extra files:</strong> {{ runNarrative.verification.extra_files?.join(", ") || "—" }}</div>
                <div><strong>Missing planned files:</strong> {{ runNarrative.verification.missing_files?.join(", ") || "—" }}</div>
              </div>
              <div v-if="runNarrative.verification.findings?.length" class="mt-3 space-y-2">
                <div
                  v-for="finding in runNarrative.verification.findings"
                  :key="finding.code"
                  class="rounded-xl border border-slate-200/70 bg-slate-50/80 p-3 text-sm"
                >
                  <div class="flex flex-wrap items-center justify-between gap-2">
                    <div class="font-medium text-slate-900">{{ finding.title }}</div>
                    <el-tag size="small" effect="light" :type="verificationFindingTagType(finding.severity)">
                      {{ humanizeToken(finding.severity) }}
                    </el-tag>
                  </div>
                  <div class="mt-1 text-slate-600">{{ finding.detail }}</div>
                  <div v-if="finding.files?.length" class="mt-2 text-xs text-slate-500">
                    {{ finding.files.join(", ") }}
                  </div>
                </div>
              </div>
              <div class="mt-4 flex flex-wrap items-center gap-2">
                <el-button
                  v-if="runNarrative.verification.requires_confirmation"
                  size="small"
                  type="warning"
                  plain
                  @click="requestRunConfirmation"
                >
                  Require Confirmation
                </el-button>
                <el-tag v-else effect="light" type="success">Proceed</el-tag>
              </div>
            </div>

          <div>
            <div class="text-xs uppercase tracking-wide text-slate-400">Planned Steps</div>
            <div class="mt-3 space-y-2">
              <div
                v-for="step in runNarrative.plan.steps"
                :key="step.id"
                class="mission-subcard flex flex-wrap items-start justify-between gap-3 p-3"
              >
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-2">
                    <div class="text-sm font-semibold text-slate-900">{{ step.title }}</div>
                    <el-tag size="small" effect="light" :type="narrativeStatusTagType(step.status, step.blocking)">
                      {{ step.status }}
                    </el-tag>
                    <el-tag v-if="step.blocking === false" size="small" effect="light" type="warning">Optional</el-tag>
                    <el-tag size="small" effect="light" type="info">
                      {{ humanizeToken(step.phase) }}
                    </el-tag>
                  </div>
                  <div v-if="step.rationale" class="mt-2 text-sm text-slate-600">{{ step.rationale }}</div>
                  <div class="mt-2 text-xs text-slate-500">
                    {{ step.success_criteria?.join(" · ") || "No success criteria recorded." }}
                  </div>
                </div>
                <div class="min-w-[12rem] text-right text-xs text-slate-500">
                  <div><strong>Files:</strong> {{ step.expected_files?.join(", ") || "—" }}</div>
                  <div class="mt-1"><strong>Ops:</strong> {{ step.expected_commands?.join(", ") || "—" }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="premium-card mission-panel p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Reflections</div>
            <div class="text-xs text-slate-500">What happened, whether it matched plan, and what changed next.</div>
          </div>
          <div class="flex items-center gap-2">
            <el-tag effect="light" type="info">{{ reflectionsDisplay.length }} shown</el-tag>
            <el-button
              v-if="recentNarrativeReflections.length > reflectionsCollapsedCount"
              plain
              size="small"
              @click="reflectionsExpanded = !reflectionsExpanded"
            >
              {{ reflectionsExpanded ? "Collapse" : "View all" }}
            </el-button>
          </div>
        </div>
        <div v-if="runNarrativeLoading" class="mt-4 text-sm text-slate-500">Summarizing latest run decisions…</div>
        <div v-else-if="runNarrativeError" class="mt-4 text-sm text-rose-600">{{ runNarrativeError }}</div>
        <div v-else-if="reflectionsDisplay.length" class="mt-4 mission-content-scroll">
          <div class="space-y-3">
            <div
              v-for="reflection in reflectionsDisplay"
              :key="reflection.id"
              class="mission-subcard p-4"
            >
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div class="text-sm font-semibold text-slate-900">{{ reflection.title }}</div>
              <div class="flex flex-wrap items-center gap-2">
                <el-tag size="small" effect="light" :type="narrativeStatusTagType(reflection.status, reflection.blocking)">
                  {{ reflection.status }}
                </el-tag>
                <el-tag v-if="reflection.blocking === false" size="small" effect="light" type="warning">Optional</el-tag>
                <el-tag
                  v-if="reflection.matched_plan !== null"
                  size="small"
                  effect="light"
                  :type="reflection.matched_plan ? 'success' : 'warning'"
                >
                  {{ reflection.matched_plan ? "Matched plan" : "Diverged" }}
                </el-tag>
              </div>
            </div>
            <div class="mt-2 text-sm text-slate-600">{{ reflection.happened }}</div>
            <div v-if="reflection.changed_next" class="mt-2 text-xs text-slate-500">
              <strong>What changed next:</strong> {{ reflection.changed_next }}
            </div>
            <div class="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
              <span>{{ formatTimestamp(reflection.ts) }}</span>
              <span v-if="reflection.files_touched?.length">Files: {{ reflection.files_touched.join(", ") }}</span>
            </div>
          </div>
          </div>
        </div>
        <div v-else class="mt-4 text-sm text-slate-500">No reflection records are available yet.</div>
      </div>

      <div class="premium-card mission-panel p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Working Context</div>
            <div class="text-xs text-slate-500">Compacted run state for the operator and review surfaces.</div>
          </div>
          <el-tag
            v-if="runNarrative?.working_context?.risk_level"
            :type="impactRiskTagType(runNarrative.working_context.risk_level)"
            effect="light"
          >
            {{ runNarrative.working_context.risk_level }}
          </el-tag>
        </div>
        <div v-if="runNarrativeLoading" class="mt-4 text-sm text-slate-500">Compacting current run state…</div>
        <div v-else-if="runNarrativeError" class="mt-4 text-sm text-rose-600">{{ runNarrativeError }}</div>
        <div v-else-if="runNarrative" class="mt-4 space-y-4 mission-content-scroll">
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Current Step</div>
              <div class="mt-1 font-semibold text-slate-900">
                {{ runNarrative.working_context.current_step || "—" }}
              </div>
            </div>
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Next Best Step</div>
              <div class="mt-1 font-semibold text-slate-900">
                {{ runNarrative.working_context.next_best_step || "—" }}
              </div>
            </div>
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Validation</div>
              <div class="mt-1 font-semibold text-slate-900">
                {{ runNarrative.working_context.validation_state || "—" }}
              </div>
            </div>
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Review State</div>
              <div class="mt-1 font-semibold text-slate-900">
                {{ runNarrative.working_context.review_state || "—" }}
              </div>
            </div>
          </div>
          <div class="text-sm text-slate-600">
            <strong>Files touched:</strong>
            {{ runNarrative.working_context.files_touched?.join(", ") || "—" }}
          </div>
          <div v-if="architectureProfile" class="mission-subcard p-3 text-sm">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div class="text-xs uppercase tracking-wide text-slate-400">Architecture Contract</div>
                <div class="mt-1 font-semibold text-slate-900">
                  {{ architectureProfile.repo_layout_label || "Repository" }}
                  <span class="text-slate-500">· {{ architectureProfile.status || "MISSING" }}</span>
                </div>
              </div>
              <el-tag
                size="small"
                effect="light"
                :type="architectureProfile.protected_zones_touched?.length ? 'danger' : 'success'"
              >
                {{ architectureProfile.protected_zones_touched?.length ? "Protected zone touched" : "Bounded slice" }}
              </el-tag>
            </div>
            <div class="mt-2 text-slate-600">
              {{ architectureProfile.summary || "No architecture contract summary recorded." }}
            </div>
            <div class="mt-2 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
              <div><strong>Execution slice:</strong> {{ architectureProfile.execution_slice?.join(", ") || "—" }}</div>
              <div><strong>Validation recipes:</strong> {{ architectureProfile.validation_recipes?.join(", ") || "—" }}</div>
              <div><strong>Protected zones:</strong> {{ architectureProfile.protected_zones?.join(", ") || "—" }}</div>
              <div><strong>Safe zones:</strong> {{ architectureProfile.safe_zones?.join(", ") || "—" }}</div>
            </div>
            <div v-if="architectureProfile.assumptions_used?.length" class="mt-2 text-xs text-slate-500">
              <strong>Assumptions:</strong> {{ architectureProfile.assumptions_used.join(" · ") }}
            </div>
            <div class="mt-3 flex flex-wrap items-center gap-2">
              <el-button
                size="small"
                type="primary"
                plain
                :loading="architectureDriftFixLoading"
                @click="fixArchitectureDriftAndOpenPr"
              >
                Fix Drift + Open PR
              </el-button>
              <span v-if="architectureDriftFixResult?.pr_url" class="text-xs text-slate-500">
                PR:
                <a :href="architectureDriftFixResult.pr_url" target="_blank" rel="noopener noreferrer" class="text-sky-700 hover:underline">
                  {{ architectureDriftFixResult.pr_url }}
                </a>
              </span>
            </div>
            <div v-if="architectureDriftFixError" class="mt-2 text-xs text-rose-600">
              {{ architectureDriftFixError }}
            </div>
          </div>
          <div v-if="projectContract" class="mission-subcard p-3 text-sm">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div class="text-xs uppercase tracking-wide text-slate-400">Project Contract</div>
                <div class="mt-1 font-semibold text-slate-900">
                  {{ projectContract.status || "MISSING" }}
                  <span class="text-slate-500">· v{{ projectContract.version ?? "—" }}</span>
                </div>
              </div>
              <el-tag
                size="small"
                effect="light"
                :type="projectContractEnforcementMode === 'strict' ? 'danger' : projectContractEnforcementMode === 'warn' ? 'warning' : 'info'"
              >
                {{
                  projectContractEnforcementMode === "strict"
                    ? "STRICT enforcement active"
                    : projectContractEnforcementMode === "warn"
                    ? "ENABLED (WARN)"
                    : "Enforcement OFF"
                }}
              </el-tag>
            </div>
            <div class="mt-2 text-slate-600">
              {{ projectContract.summary || "No project contract summary recorded." }}
            </div>
            <div class="mt-3 flex flex-wrap items-center gap-2">
              <el-button
                size="small"
                plain
                :loading="projectContractBootstrapLoading"
                :disabled="projectContractActionInFlight"
                @click="bootstrapProjectContractFromMissionControl"
              >
                {{ projectContractProfileExists ? "Re-sync Contract" : "Initialize Contract" }}
              </el-button>
              <el-button
                size="small"
                type="success"
                plain
                :loading="projectContractEnforcementLoading"
                :disabled="projectContractActionInFlight"
                @click="enableProjectContractEnforcement"
              >
                Enable Enforcement (WARN)
              </el-button>
              <el-button
                size="small"
                type="danger"
                plain
                :loading="projectContractStrictLoading"
                :disabled="projectContractActionInFlight || projectContractEnforcementMode === 'strict'"
                @click="upgradeProjectContractEnforcementToStrict"
              >
                Upgrade to Strict
              </el-button>
            </div>
            <div v-if="projectContractActionError" class="mt-2 text-xs text-rose-600">
              {{ projectContractActionError }}
            </div>
            <div class="mt-2 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
              <div><strong>Brand tokens:</strong> {{ projectContract.brand_token_count || 0 }}</div>
              <div><strong>Components:</strong> {{ projectContract.component_count || 0 }}</div>
              <div><strong>Active rules:</strong> {{ projectContract.active_rules?.join(", ") || "—" }}</div>
              <div><strong>Blocked patterns:</strong> {{ projectContract.blocked_patterns?.join(", ") || "—" }}</div>
            </div>
            <div v-if="projectContract.allowed_css_var_prefixes?.length" class="mt-2 text-xs text-slate-500">
              <strong>CSS var prefixes:</strong> {{ projectContract.allowed_css_var_prefixes.join(", ") }}
            </div>
            <div v-if="projectContract.assumptions_used?.length" class="mt-2 text-xs text-slate-500">
              <strong>Assumptions:</strong> {{ projectContract.assumptions_used.join(" · ") }}
            </div>
          </div>
          <div v-if="latestExecutionContract" class="mission-subcard p-3 text-sm">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div class="text-xs uppercase tracking-wide text-slate-400">Execution Contract</div>
                <div class="mt-1 font-semibold text-slate-900">
                  {{ humanizeToken(latestExecutionContract.lifecycle_state) }}
                  <span class="text-slate-500">· {{ humanizeToken(latestExecutionContract.scope_mode) }}</span>
                </div>
              </div>
              <div class="flex flex-wrap items-center gap-2">
                <el-tag size="small" effect="light" :type="budgetModeTagType(latestExecutionContract.budget?.budget_mode)">
                  {{ latestExecutionContract.budget?.budget_mode || "NORMAL" }}
                </el-tag>
                <el-tag size="small" effect="light" :type="impactRiskTagType(latestExecutionContract.risk_level)">
                  {{ latestExecutionContract.risk_level || "LOW" }}
                </el-tag>
              </div>
            </div>
            <div class="mt-2 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
              <div><strong>Validation:</strong> {{ humanizeToken(latestExecutionContract.validation_state) }}</div>
              <div><strong>Retry:</strong> {{ humanizeToken(latestExecutionContract.retry_state) }}</div>
              <div><strong>File budget:</strong> {{ latestExecutionContract.file_budget }}/{{ latestExecutionContract.hard_file_budget }}</div>
              <div><strong>Allowed files:</strong> {{ latestExecutionContract.allowed_file_count }}</div>
              <div><strong>Token budget:</strong> {{ formatBudgetTokenUsage(latestExecutionContract.budget?.used_tokens, latestExecutionContract.budget?.max_tokens) }}</div>
              <div><strong>Cost budget:</strong> {{ formatBudgetCents(latestExecutionContract.budget?.used_cost_cents) }} / {{ formatBudgetCents(latestExecutionContract.budget?.max_cost_cents) }}</div>
              <div><strong>Recovery reserve:</strong> {{ formatBudgetCents(latestExecutionContract.budget?.remaining_recovery_cost_cents) }} / {{ formatBudgetCents(latestExecutionContract.budget?.recovery_reserve_cost_cents) }}</div>
              <div><strong>Budget partition:</strong> {{ humanizeToken(latestExecutionContract.budget?.active_budget_partition || "main") }}</div>
              <div><strong>Model cap:</strong> {{ latestExecutionContract.budget?.model_tier_cap || "open" }}</div>
              <div><strong>Completion cap:</strong> {{ latestExecutionContract.budget?.completion_token_cap ?? "—" }}</div>
            </div>
            <div class="mt-2 text-slate-600">
              <strong>Target files:</strong>
              {{ latestExecutionContract.target_files?.join(", ") || "—" }}
            </div>
            <div class="mt-2 text-slate-600">
              <strong>Validation steps:</strong>
              {{ latestExecutionContract.validation_steps?.join(", ") || "—" }}
            </div>
            <div class="mt-2 text-slate-600">
              <strong>Commands:</strong>
              {{ executionContractCommands(latestExecutionContract) }}
            </div>
            <div
              v-if="latestExecutionContract.budget?.escalation_reason"
              class="mt-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700"
            >
              {{ humanizeToken(latestExecutionContract.budget.escalation_reason) }}
            </div>
          </div>
          <div class="text-sm text-slate-600">
            <strong>Latest failure:</strong>
            {{ runNarrative.working_context.latest_failure || "None recorded." }}
          </div>
          <div class="text-sm text-slate-600">
            <strong>Latest warning:</strong>
            {{ runNarrative.working_context.latest_warning || "None recorded." }}
          </div>
          <div v-if="runNarrative.working_context.feedback_text" class="mission-subcard p-3 text-sm">
            <div class="flex flex-wrap items-center gap-2">
              <div class="text-xs uppercase tracking-wide text-slate-400">Feedback Fork</div>
              <el-tag size="small" effect="light" type="warning">
                {{ runNarrative.working_context.feedback_mode || "feedback" }}
              </el-tag>
            </div>
            <div class="mt-2 text-slate-700">
              {{ runNarrative.working_context.feedback_text }}
            </div>
            <div class="mt-2 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
              <div><strong>Parent run:</strong> {{ runNarrative.working_context.parent_run_id || "—" }}</div>
              <div><strong>Source:</strong> {{ runNarrative.working_context.feedback_source || "—" }}</div>
              <div class="sm:col-span-2">
                <strong>Target files:</strong>
                {{ runNarrative.working_context.target_files?.join(", ") || "—" }}
              </div>
              <div>
                <strong>Edit scope:</strong>
                {{ runNarrative.working_context.edit_scope_mode || "—" }}
              </div>
              <div>
                <strong>Max files:</strong>
                {{ runNarrative.working_context.edit_scope_max_files ?? "—" }}
              </div>
            </div>
          </div>
          <div class="text-sm text-slate-600">
            <strong>API runtime auth:</strong>
            {{ formatRuntimeGitAuthSummary(runNarrative.working_context) }}
            <span v-if="runtimeGitAuthMissing(runNarrative.working_context).length">
              (missing {{ runtimeGitAuthMissing(runNarrative.working_context).join(", ") }})
            </span>
          </div>
          <div class="grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
            <div><strong>Recovery count:</strong> {{ runNarrative.working_context.recovery_count }}</div>
            <div><strong>Blocking failures:</strong> {{ runNarrative.working_context.blocking_failure_count }}</div>
            <div><strong>Warnings:</strong> {{ runNarrative.working_context.warning_failure_count }}</div>
            <div><strong>Workspace:</strong> {{ runNarrative.working_context.workspace_status || "—" }}</div>
            <div><strong>Branch:</strong> {{ runNarrative.working_context.branch_name || "—" }}</div>
            <div><strong>Confidence:</strong> {{ formatConfidence(runNarrative.working_context.confidence_score) }}</div>
            <div><strong>Runtime mode:</strong> {{ runNarrative.working_context.runtime_mode || "—" }}</div>
            <div><strong>Git auth mode:</strong> {{ formatRuntimeGitAuthMode(runNarrative.working_context.runtime_git_auth_mode) }}</div>
            <div v-if="usesGitHubAppRuntimeAuth(runNarrative.working_context)">
              <strong>GitHub env (API):</strong>
              app id {{ formatPresence(runNarrative.working_context.github_app_id_present) }}
              · key {{ formatPresence(runNarrative.working_context.github_private_key_present) }}
              · webhook {{ formatPresence(runNarrative.working_context.github_webhook_secret_present) }}
            </div>
            <div v-else-if="usesSshRuntimeAuth(runNarrative.working_context)">
              <strong>SSH runtime (API):</strong>
              git {{ formatPresence(Boolean(runNarrative.working_context.git_binary)) }}
              · ssh {{ formatPresence(Boolean(runNarrative.working_context.ssh_binary)) }}
            </div>
            <div v-else>
              <strong>Repo auth (API):</strong>
              {{ formatRuntimeGitAuthDetails(runNarrative.working_context) }}
            </div>
          </div>
          <div v-if="runNarrative.working_context.pull_request_url">
            <el-button
              type="primary"
              plain
              size="small"
              @click="openExternal(runNarrative.working_context.pull_request_url)"
            >
              Open Pull Request
            </el-button>
          </div>
        </div>
      </div>
    </section>

    <section v-if="project" class="mission-workbench-grid">
      <TaskQueuePanel :tasks="workbenchTasks" :eta-profiles="missionOverview?.eta_profiles || []" />

      <ExecutionConsolePanel
        :console-data="executionConsole"
        :run-status="latestRun?.status || 'IDLE'"
      />

      <ReviewSurfacePanel
        :patch-artifact="latestPatchArtifact"
        :files="reviewSurfaceFiles"
        :additions="reviewSurfaceAdditions"
        :deletions="reviewSurfaceDeletions"
        :preview-status="previewsAndPrs?.preview_status || latestRun?.status"
        :approval-status="reviewSurfaceApprovalStatus"
        :approval-note="reviewSurfaceApprovalNote"
        :pull-request-url="reviewSurfacePullRequestUrl"
        @preview-diff="openWorkbenchDiff"
        @explain-artifact="openWorkbenchExplain"
        @approve="approveWorkbenchPatch"
        @reject="rejectWorkbenchPatch"
        @request-modification="requestPatchModification"
        @create-pr="openWorkbenchPrFlow"
      />
    </section>

    <section v-if="project" class="grid gap-4">
      <OperatorConsole
        variant="panel"
        title="AI Operator Workbench"
        eyebrow="Persistent Operator"
        context-title="Mission Control assistant"
        context-copy="Ask the system what changed, why a run failed, which files matter, or how the current project is wired. This console stays grounded in real run, artifact, workspace, and repo-map state."
        placeholder="Fix CORS issue in the API. Explain the scheduler service. Show the latest patch. Compare the last two runs."
        hint="This operator is context-aware of the current project and run. It answers from system tools and links you back into the workbench."
      />
    </section>

    <div id="work-intake" v-if="project" class="grid gap-4 xl:grid-cols-[1.4fr,1fr]">
      <div class="premium-card mission-panel p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Work Intake</div>
            <div class="text-xs text-slate-500">
              Incoming requirements enriched with predicted files, modules, and suggested execution plans.
            </div>
          </div>
          <el-tag effect="light" type="info">{{ intakeItems.length }} item{{ intakeItems.length === 1 ? "" : "s" }}</el-tag>
        </div>
        <div class="mt-4 mission-subcard p-4">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-sm font-semibold text-slate-900">Vision Intake</div>
              <div class="text-xs text-slate-500">Paste or drop screenshot + short goal to create a tracked codex run.</div>
            </div>
            <el-tag size="small" effect="light" type="success">codex</el-tag>
          </div>
          <el-input
            v-model="visionGoalText"
            class="mt-3"
            type="textarea"
            :rows="3"
            placeholder="Make hero image full-width background on homepage"
            @paste="onVisionPaste"
          />
          <div class="mt-3 flex flex-wrap items-center gap-2">
            <el-button size="small" plain @click="openVisionFilePicker">Add Screenshot</el-button>
            <el-switch v-model="visionAutoStart" inline-prompt active-text="Auto Start" inactive-text="Manual" />
            <el-switch v-model="visionAutoDeploy" inline-prompt active-text="Auto Deploy" inactive-text="No Deploy" />
          </div>
          <input
            ref="visionFileInput"
            class="hidden"
            type="file"
            accept="image/*"
            multiple
            @change="onVisionFileInput"
          />
          <div
            class="mt-3 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-3 py-4 text-xs text-slate-500"
            @dragover.prevent
            @drop="onVisionDrop"
          >
            Drop screenshots here or paste directly into the goal box.
          </div>
          <div v-if="visionScreenshots.length" class="mt-3 space-y-2">
            <div
              v-for="(item, index) in visionScreenshots"
              :key="`${item.filename}-${index}`"
              class="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600"
            >
              <div class="truncate">
                {{ item.filename }} · {{ Math.max(1, Math.round(item.size_bytes / 1024)) }} KB
              </div>
              <el-button size="small" text type="danger" @click="removeVisionScreenshot(index)">Remove</el-button>
            </div>
          </div>
          <div class="mt-3 flex justify-end">
            <el-button type="primary" size="small" :disabled="!visionReady" :loading="visionSubmitting" @click="submitVisionRun">
              Create Vision Run
            </el-button>
          </div>
        </div>
        <div v-if="intakeItems.length" class="mt-4 grid gap-3">
          <div
            v-for="item in intakeItems"
            :key="item.id"
            class="mission-subcard p-4"
          >
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <div class="text-sm font-semibold text-slate-900">{{ item.title }}</div>
                  <el-tag size="small" effect="light" type="info">{{ item.kind }}</el-tag>
                  <el-tag size="small" effect="light" :type="impactRiskTagType(item.risk_tier)">
                    {{ item.risk_tier }}
                  </el-tag>
                </div>
                <div v-if="item.summary" class="mt-2 text-sm text-slate-600">{{ item.summary }}</div>
                <div class="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
                  <div><strong>Predicted modules:</strong> {{ item.predicted_modules.join(", ") || "—" }}</div>
                  <div><strong>Predicted files:</strong> {{ item.predicted_files.join(", ") || "—" }}</div>
                  <div><strong>Linked tasks:</strong> {{ item.related_task_count }}</div>
                  <div><strong>Confidence:</strong> {{ formatConfidence(item.confidence_score) }}</div>
                  <div><strong>Source:</strong> {{ intakeSourceLabel(item) }}</div>
                  <div><strong>Run:</strong> {{ shortRunId(intakeRunId(item)) }}</div>
                </div>
                <div v-if="item.suggested_plan.length" class="mt-3">
                  <div class="text-xs uppercase tracking-wide text-slate-400">Suggested Plan</div>
                  <ul class="mt-2 space-y-1 text-sm text-slate-600">
                    <li v-for="step in item.suggested_plan" :key="`${item.id}-${step}`">{{ step }}</li>
                  </ul>
                </div>
              </div>
              <div class="flex flex-col gap-2">
                <el-button
                  type="primary"
                  size="small"
                  :loading="intakeRunLoadingId === item.id"
                  :disabled="cancelEnabled"
                  @click="startRunFromIntake(item)"
                >
                  Start Run
                </el-button>
                <div class="text-[11px] text-slate-400">{{ formatTimestamp(item.created_at) }}</div>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="mt-4 text-sm text-slate-500">No work intake signals yet.</div>
      </div>

      <div class="premium-card mission-panel p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Change Impact</div>
            <div class="text-xs text-slate-500">Observed change impact from the latest patch-bearing run.</div>
          </div>
          <el-tag
            v-if="latestChangeImpact"
            effect="light"
            :type="impactRiskTagType(latestChangeImpact.risk_tier)"
          >
            {{ latestChangeImpact.risk_tier }}
          </el-tag>
        </div>
        <div v-if="latestChangeImpact" class="mt-4 space-y-4">
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Confidence</div>
              <div class="mt-1 text-lg font-semibold text-slate-900">
                {{ formatConfidence(latestChangeImpact.confidence_score) }}
              </div>
            </div>
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Patch Delta</div>
              <div class="mt-1 text-slate-900">+{{ latestChangeImpact.additions }} / -{{ latestChangeImpact.deletions }}</div>
            </div>
          </div>
          <div class="text-sm text-slate-600">
            <strong>Modules:</strong> {{ latestChangeImpact.modules_impacted.join(", ") || "—" }}
          </div>
          <div class="text-sm text-slate-600">
            <strong>Tests:</strong> {{ latestChangeImpact.tests_impacted.join(", ") || "—" }}
          </div>
          <div class="text-sm text-slate-600">
            <strong>API impact:</strong> {{ latestChangeImpact.api_impact.join(", ") || "—" }}
          </div>
          <div class="text-sm text-slate-600">
            <strong>Files changed:</strong> {{ latestChangeImpact.files_changed.join(", ") || "—" }}
          </div>
          <div class="flex flex-wrap gap-2">
            <el-button
              v-if="latestChangeImpact.patch_artifact"
              plain
              size="small"
              @click="openDiffDialog(latestChangeImpact.patch_artifact)"
            >
              Preview Diff
            </el-button>
            <el-button
              v-if="latestChangeImpact.patch_artifact"
              plain
              size="small"
              type="success"
              @click="openCreatePrDialog(latestChangeImpact.patch_artifact)"
            >
              Create PR
            </el-button>
          </div>
        </div>
        <div v-else class="mt-4 text-sm text-slate-500">No change impact summary is available yet.</div>
      </div>
    </div>

    <div v-if="project" class="grid gap-4 xl:grid-cols-[1.4fr,1fr]">
      <div class="premium-card mission-panel p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Recent Runs</div>
            <div class="text-xs text-slate-500">Recent run summaries with compare, replay, and diff actions.</div>
          </div>
          <el-tag effect="light" type="info">{{ recentRunCards.length }} recent</el-tag>
        </div>
        <div v-if="recentRunCardsEnhanced.length" class="mt-4 mission-scroll-zone">
          <div class="grid gap-3">
            <div
              v-for="card in recentRunCardsEnhanced"
              :key="card.run_id"
              class="mission-subcard p-4"
            >
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <div class="font-mono text-sm text-slate-900">{{ card.run_id }}</div>
                  <el-tag :type="runStatusTagType(card.outcome_status)" effect="light">{{ card.outcome_label }}</el-tag>
                  <el-tag v-if="card.terminal_quality" :type="runStatusTagType(card.terminal_quality)" effect="light">
                    {{ card.terminal_quality }}
                  </el-tag>
                  <el-tag v-if="card.approval_status" :type="approvalTagType(card.approval_status)" effect="light">
                    {{ card.approval_status }}
                  </el-tag>
                </div>
                <div class="mt-2 text-sm text-slate-600">{{ card.goal_text || "No goal summary recorded." }}</div>
                <div class="mt-2 flex flex-wrap items-center gap-2">
                  <el-tag effect="light" :type="card.governance_mode_tag">{{ card.governance_mode_label }}</el-tag>
                  <span class="text-xs text-slate-500">{{ card.governance_mode_description }}</span>
                </div>
                <div v-if="card.next_action_hint" class="mt-2 text-xs text-slate-500">
                  <strong>Next:</strong> {{ card.next_action_hint }}
                </div>
                <div class="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
                  <div><strong>Executor:</strong> {{ card.executor }}</div>
                  <div><strong>Branch:</strong> {{ card.branch_name || "—" }}</div>
                  <div><strong>Elapsed:</strong> {{ formatElapsed(card.elapsed_seconds) }}</div>
                  <div><strong>Recoveries:</strong> {{ card.recovery_count }}</div>
                  <div><strong>Artifacts:</strong> {{ card.artifact_count }}</div>
                  <div><strong>Confidence:</strong> {{ formatConfidence(card.confidence_score) }}</div>
                  <div v-if="card.terminal_counts"><strong>Critical failed:</strong> {{ card.terminal_counts.critical_failed || 0 }}</div>
                  <div v-if="card.terminal_counts"><strong>Optional failed:</strong> {{ card.terminal_counts.optional_failed || 0 }}</div>
                </div>
                <div v-if="card.execution_contract" class="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
                  <div><strong>Contract:</strong> {{ humanizeToken(card.execution_contract.lifecycle_state) }}</div>
                  <div><strong>Budget mode:</strong> {{ card.execution_contract.budget?.budget_mode || "NORMAL" }}</div>
                  <div><strong>Validation:</strong> {{ humanizeToken(card.execution_contract.validation_state) }}</div>
                  <div><strong>Retry:</strong> {{ humanizeToken(card.execution_contract.retry_state) }}</div>
                  <div><strong>Token budget:</strong> {{ formatBudgetTokenUsage(card.execution_contract.budget?.used_tokens, card.execution_contract.budget?.max_tokens) }}</div>
                  <div><strong>Commands:</strong> {{ executionContractCommands(card.execution_contract) }}</div>
                </div>
              </div>
              <div class="flex flex-col gap-2">
                <el-button plain size="small" @click="openReplayDialog(card.run_id)">Replay</el-button>
                <el-button
                  plain
                  size="small"
                  :disabled="!latestRun?.id || latestRun.id === card.run_id"
                  @click="compareAgainstRun(card.run_id)"
                >
                  Compare
                </el-button>
                <el-button
                  v-if="card.patch_artifact"
                  plain
                  size="small"
                  type="info"
                  @click="openDiffDialog(card.patch_artifact)"
                >
                  Diff
                </el-button>
              </div>
            </div>
          </div>
          </div>
        </div>
        <div v-else class="mt-4 text-sm text-slate-500">No recent run summaries yet.</div>
      </div>

      <div class="premium-card mission-panel p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Previews & PRs</div>
            <div class="text-xs text-slate-500">Repository linkage, preview readiness, and PR state.</div>
          </div>
          <el-tag
            effect="light"
            :type="previewsAndPrs?.repository_connected ? 'success' : 'warning'"
          >
            {{ previewsAndPrs?.repository_connected ? "REPO CONNECTED" : "REPO NOT CONNECTED" }}
          </el-tag>
        </div>
        <div v-if="previewsAndPrs" class="mt-4 space-y-3 text-sm text-slate-600">
          <div><strong>Provider:</strong> {{ previewsAndPrs.provider || "—" }}</div>
          <div><strong>Repository:</strong> {{ previewsAndPrs.repo_full_name || "—" }}</div>
          <div><strong>Branch:</strong> {{ previewsAndPrs.branch_name || "—" }}</div>
          <div><strong>Preview profile:</strong> {{ previewsAndPrs.profile_configured ? "Configured" : "Not configured" }}</div>
          <div>
            <strong>Preview source:</strong>
            <el-tag size="small" effect="light" :type="previewRefreshSuggested ? 'warning' : 'success'">
              {{ previewRefreshSuggested ? "STALE" : "ACTIVE" }}
            </el-tag>
            <span class="ml-2">
              run {{ shortRunId(previewsAndPrs.run_id || latestCompletedRunId || previewRunId) }}
            </span>
          </div>
          <div>
            <strong>Preview:</strong>
            <span class="ml-1">{{ previewsAndPrs.preview_status }}</span>
            <a
              v-if="previewsAndPrs.active_preview_url || previewsAndPrs.preview_url"
              :href="previewsAndPrs.active_preview_url || previewsAndPrs.preview_url"
              target="_blank"
              rel="noreferrer"
              class="ml-2 underline"
            >
              Open
            </a>
          </div>
          <div
            v-if="previewRefreshSuggested"
            class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700"
          >
            Newer run {{ shortRunId(latestCompletedRunId) }} is available. Current preview is from
            run {{ shortRunId(previewsAndPrs.run_id) }}.
            <div class="mt-2 flex flex-wrap gap-2">
              <el-button size="small" type="primary" plain :loading="previewLaunchLoading" @click="refreshPreviewToLatestRun">
                Refresh to Latest
              </el-button>
              <el-button size="small" type="warning" plain :loading="previewLaunchLoading" @click="restartPreviewToLatestRun">
                Restart to Latest
              </el-button>
              <el-button size="small" plain @click="openTimelinePage(latestCompletedRunId)">
                Go to Run
              </el-button>
            </div>
          </div>
          <div v-if="previewsAndPrs.active_preview_url || previewsAndPrs.preview_url" class="mission-preview-embed">
            <div class="mission-preview-embed__top">
              <div class="text-xs uppercase tracking-wide text-slate-400">Live Preview</div>
              <div class="flex items-center gap-2">
                <el-button
                  size="small"
                  plain
                  :type="previewViewport === 'desktop' ? 'primary' : undefined"
                  @click="previewViewport = 'desktop'"
                >
                  Desktop
                </el-button>
                <el-button
                  size="small"
                  plain
                  :type="previewViewport === 'mobile' ? 'primary' : undefined"
                  @click="previewViewport = 'mobile'"
                >
                  Mobile
                </el-button>
                <el-button size="small" plain @click="openExternal(previewsAndPrs.active_preview_url || previewsAndPrs.preview_url)">
                  Open in New Tab
                </el-button>
              </div>
            </div>
            <div class="mission-preview-embed__viewport" :class="`is-${previewViewport}`">
              <iframe
                class="mission-preview-embed__frame"
                :src="previewsAndPrs.active_preview_url || previewsAndPrs.preview_url"
                title="Mission Control preview"
                loading="lazy"
                referrerpolicy="no-referrer"
                sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
              />
            </div>
          </div>
          <div><strong>Preview contract host:</strong> {{ previewsAndPrs.preview_domain_host || "—" }}</div>
          <div><strong>Runtime classification:</strong> {{ previewsAndPrs.runtime_classification || "—" }}</div>
          <div><strong>Preview strategy:</strong> {{ previewsAndPrs.preview_strategy || "—" }}</div>
          <div><strong>Active preview command:</strong> <span class="font-mono text-xs">{{ previewsAndPrs.active_preview_command || "—" }}</span></div>
          <div><strong>Upstream preview port:</strong> {{ previewsAndPrs.upstream_preview_port || "—" }}</div>
          <div><strong>Frontend install status:</strong> {{ previewsAndPrs.frontend_install_status || "—" }}</div>
          <div><strong>Backend install status:</strong> {{ previewsAndPrs.backend_install_status || "—" }}</div>
          <div><strong>Runtime boot duration:</strong> {{ previewsAndPrs.runtime_boot_duration_seconds != null ? `${previewsAndPrs.runtime_boot_duration_seconds}s` : "—" }}</div>
          <div><strong>Dependency repair attempts:</strong> {{ previewsAndPrs.dependency_repair_attempts ?? 0 }}</div>
          <div><strong>Cached hydration:</strong> {{ previewsAndPrs.cached_hydration_state ? JSON.stringify(previewsAndPrs.cached_hydration_state) : "—" }}</div>
          <div v-if="previewsAndPrs.active_preview_url"><strong>Active preview URL:</strong> <a :href="previewsAndPrs.active_preview_url" target="_blank" rel="noreferrer" class="underline">{{ previewsAndPrs.active_preview_url }}</a></div>
          <div v-if="previewsAndPrs.stale_preview_url"><strong>Stale preview URL:</strong> <span class="font-mono text-xs">{{ previewsAndPrs.stale_preview_url }}</span></div>
          <div v-if="previewsAndPrs.frontend_url"><strong>Frontend:</strong> <a :href="previewsAndPrs.frontend_url" target="_blank" rel="noreferrer" class="underline">{{ previewsAndPrs.frontend_url }}</a></div>
          <div v-if="previewsAndPrs.backend_url"><strong>Backend:</strong> <a :href="previewsAndPrs.backend_url" target="_blank" rel="noreferrer" class="underline">{{ previewsAndPrs.backend_url }}</a></div>
          <div><strong>Preview port:</strong> {{ previewPortLabel }}</div>
          <div><strong>Last health check:</strong> {{ previewLastHealthCheckLabel }}</div>
          <div
            v-if="authoritativePreviewDiagnostics && Object.keys(authoritativePreviewDiagnostics).length"
            class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700"
          >
            <div class="font-semibold text-slate-900">Preview diagnostics</div>
            <div><strong>MIME validation:</strong> {{ authoritativePreviewDiagnostics.mime_validation_passed ? "passed" : "failed" }}</div>
            <div><strong>Root HTML:</strong> {{ authoritativePreviewDiagnostics.root_html_ok ? "ok" : "failed" }}</div>
            <div><strong>Vite client:</strong> {{ authoritativePreviewDiagnostics.vite_client_ok ? "ok" : "failed" }}</div>
            <div><strong>Entry module:</strong> {{ authoritativePreviewDiagnostics.entry_mime_ok ? "ok" : "failed" }}</div>
            <div><strong>Frontend dependencies ready:</strong> {{ authoritativePreviewDiagnostics.dependencies_ready_frontend ? "yes" : "no" }}</div>
            <div><strong>Backend dependencies ready:</strong> {{ authoritativePreviewDiagnostics.dependencies_ready_backend ? "yes" : "no" }}</div>
            <div><strong>Frontend runtime ready:</strong> {{ authoritativePreviewDiagnostics.preview_runtime_ready ? "yes" : "no" }}</div>
            <div><strong>Backend runtime ready:</strong> {{ authoritativePreviewDiagnostics.backend_runtime_ready ? "yes" : "no" }}</div>
            <div v-if="authoritativePreviewDiagnostics.diagnostic_code"><strong>Diagnostic code:</strong> {{ authoritativePreviewDiagnostics.diagnostic_code }}</div>
            <div v-if="authoritativePreviewDiagnostics.diagnostic_detail"><strong>Diagnostic detail:</strong> {{ authoritativePreviewDiagnostics.diagnostic_detail }}</div>
            <div v-if="authoritativePreviewDiagnostics.root_probe?.content_type"><strong>`/` Content-Type:</strong> {{ authoritativePreviewDiagnostics.root_probe.content_type }}</div>
            <div v-if="authoritativePreviewDiagnostics.vite_client_probe?.content_type"><strong>`/@vite/client` Content-Type:</strong> {{ authoritativePreviewDiagnostics.vite_client_probe.content_type }}</div>
            <div v-if="authoritativePreviewDiagnostics.entry_probe?.content_type !== undefined"><strong>{{ authoritativePreviewDiagnostics.entry_path || "/src/main.ts" }} Content-Type:</strong> {{ authoritativePreviewDiagnostics.entry_probe.content_type || "missing" }}</div>
            <div v-if="authoritativePreviewDiagnostics.health_probe?.status !== undefined"><strong>`/health` status:</strong> {{ authoritativePreviewDiagnostics.health_probe.status }}</div>
          </div>
          <div v-if="previewsAndPrs.frontend_log_path"><strong>Frontend log:</strong> <span class="font-mono text-xs">{{ previewsAndPrs.frontend_log_path }}</span></div>
          <div v-if="previewsAndPrs.backend_log_path"><strong>Backend log:</strong> <span class="font-mono text-xs">{{ previewsAndPrs.backend_log_path }}</span></div>
          <div v-if="previewsAndPrs.preview_expires_at"><strong>Expires:</strong> {{ formatTimestamp(previewsAndPrs.preview_expires_at) }}</div>
          <div v-if="authoritativeVerificationNote" class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            {{ authoritativeVerificationNote }}
            <div v-if="previewRepairAvailable" class="mt-2 flex flex-wrap gap-2">
              <el-button size="small" type="warning" plain :loading="previewLaunchLoading" @click="repairPreviewRoot">
                Repair Preview Root
              </el-button>
              <el-button size="small" type="primary" plain :loading="previewLaunchLoading" @click="repairPreviewEntrypoint">
                Repair Entrypoint
              </el-button>
            </div>
          </div>
          <div v-if="previewLaunchError" class="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {{ previewLaunchError }}
          </div>
          <div v-if="previewLaunchInfo" class="rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-700">
            {{ previewLaunchInfo }}
          </div>
          <div v-if="deployError" class="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {{ deployError }}
          </div>
          <div v-if="deployInfo" class="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
            {{ deployInfo }}
          </div>
          <div><strong>Patch size:</strong> {{ previewsAndPrs.file_count }} files · +{{ previewsAndPrs.additions }} / -{{ previewsAndPrs.deletions }}</div>
          <div>
            <strong>Approval:</strong>
            <el-tag v-if="previewsAndPrs.approval_status" :type="approvalTagType(previewsAndPrs.approval_status)" effect="light" size="small">
              {{ previewsAndPrs.approval_status }}
            </el-tag>
            <span v-else>—</span>
          </div>
          <div>
            <strong>PR:</strong>
            <a
              v-if="previewsAndPrs.pull_request_url"
              :href="previewsAndPrs.pull_request_url"
              target="_blank"
              rel="noreferrer"
              class="underline"
            >
              {{ previewsAndPrs.pull_request_url }}
            </a>
            <span v-else>—</span>
          </div>
          <div class="flex flex-wrap gap-2 pt-1">
            <el-button
              plain
              size="small"
              :loading="previewLaunchLoading"
              :disabled="!previewRunId || !previewsAndPrs.profile_configured || previewsAndPrs.requires_verification"
              @click="startPreviewLaunch"
            >
              {{ previewsAndPrs.preview_url ? "Refresh Preview" : "Launch Preview" }}
            </el-button>
            <el-button
              plain
              size="small"
              type="warning"
              :loading="previewLaunchLoading"
              :disabled="!previewRunId || !previewsAndPrs.profile_configured || previewsAndPrs.requires_verification"
              @click="restartPreviewLaunch"
            >
              Restart Preview
            </el-button>
            <el-button
              plain
              size="small"
              type="info"
              :loading="previewLaunchLoading"
              :disabled="!previewRunId || !previewsAndPrs.profile_configured"
              @click="repairPreviewRoot"
            >
              Repair Root
            </el-button>
            <el-button
              plain
              size="small"
              type="primary"
              :loading="previewLaunchLoading"
              :disabled="!previewRunId || !previewsAndPrs.profile_configured"
              @click="repairPreviewEntrypoint"
            >
              Repair Entrypoint
            </el-button>
            <el-button
              plain
              size="small"
              type="danger"
              :loading="previewLaunchLoading"
              :disabled="!previewRunId || !['STARTING', 'READY', 'FAILED', 'STOPPED'].includes(previewsAndPrs.preview_status)"
              @click="stopPreviewLaunch"
            >
              Stop Preview
            </el-button>
            <el-button
              v-if="previewsAndPrs.patch_artifact"
              plain
              size="small"
              @click="openDiffDialog(previewsAndPrs.patch_artifact)"
            >
              Preview Diff
            </el-button>
            <el-button
              v-if="previewsAndPrs.patch_artifact"
              plain
              size="small"
              type="success"
              @click="openCreatePrDialog(previewsAndPrs.patch_artifact, previewRunId)"
            >
              Open PR Flow
            </el-button>
            <el-button
              plain
              size="small"
              :disabled="!forkEnabled"
              @click="openImproveDialog()"
            >
              Report Issue / Improve
            </el-button>
            <el-button
              plain
              size="small"
              type="primary"
              :loading="deployLoading"
              :disabled="!previewsAndPrs.pull_request_url && !previewRunId"
              @click="deployLatestRun('vercel')"
            >
              One-Click Deploy (Vercel)
            </el-button>
            <el-button
              plain
              size="small"
              :loading="deployLoading"
              :disabled="!previewsAndPrs.pull_request_url && !previewRunId"
              @click="deployLatestRun('render')"
            >
              One-Click Deploy (Render)
            </el-button>
          </div>
          <div v-if="latestDeployment?.deployment_url" class="text-xs text-slate-600">
            <strong>Last deployment bootstrap:</strong>
            <a :href="latestDeployment.deployment_url" target="_blank" rel="noreferrer" class="underline">
              {{ latestDeployment.deployment_url }}
            </a>
          </div>
        </div>
      </div>
    </div>

    <div v-if="project" class="premium-card mission-panel p-6">
      <div class="flex items-center justify-between gap-3">
        <div>
          <div class="text-sm uppercase tracking-wide text-slate-400">Deployment Governance</div>
          <div class="text-xs text-slate-500">Provider status, confidence, promotion, rollback, and event timeline.</div>
        </div>
        <el-button size="small" plain :loading="deploymentOpsLoading" @click="loadDeploymentOps">Refresh</el-button>
      </div>
      <div v-if="deploymentOpsError" class="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
        {{ deploymentOpsError }}
      </div>
      <div v-if="deploymentPreflight" class="mt-3 rounded-lg border px-3 py-2 text-xs" :class="deploymentPreflight.ok ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-800'">
        <strong>Preflight:</strong> {{ deploymentPreflight.ok ? "PASS" : "BLOCKED" }}
        <span v-if="deploymentPreflight.errors?.length"> · {{ deploymentPreflight.errors.join("; ") }}</span>
      </div>
      <div v-if="deploymentLatest" class="mt-4 mission-subcard px-3 py-3 text-sm text-slate-700">
        <div><strong>Provider:</strong> {{ deploymentLatest.provider }} · <strong>Env:</strong> {{ deploymentLatest.environment }} · <strong>Strategy:</strong> {{ deploymentLatest.deployment_strategy }}</div>
        <div><strong>Status:</strong> {{ deploymentLatest.status }} · <strong>Confidence:</strong> {{ Math.round(Number(deploymentLatest.deployment_confidence_score || 0) * 100) }}%</div>
        <div v-if="deploymentLatest.deployment_url"><strong>URL:</strong> <a :href="deploymentLatest.deployment_url" target="_blank" rel="noreferrer" class="underline">{{ deploymentLatest.deployment_url }}</a></div>
        <div class="mt-2 flex flex-wrap gap-2">
          <el-button size="small" plain :loading="deploymentOpsLoading" @click="retryDeploymentNow">Retry Deploy</el-button>
          <el-button size="small" plain type="warning" :loading="deploymentOpsLoading" @click="rollbackDeploymentNow">Rollback</el-button>
          <el-button size="small" plain type="primary" :loading="deploymentOpsLoading" @click="promoteDeploymentNow('STAGING')">Promote to STAGING</el-button>
          <el-button
            size="small"
            plain
            type="success"
            :disabled="deploymentReadinessContract ? !deploymentReadinessContract.safe_to_production : false"
            :loading="deploymentOpsLoading"
            @click="promoteDeploymentNow('PRODUCTION')"
          >
            Promote to PRODUCTION
          </el-button>
        </div>
      </div>
      <div v-if="deploymentIntelligence" class="mt-3 mission-subcard px-3 py-3 text-xs text-slate-700">
        <div><strong>Deploy Intelligence:</strong> {{ deploymentIntelligence.total_deployments }} deployments · {{ Math.round((deploymentIntelligence.success_rate || 0) * 100) }}% success · {{ Math.round((deploymentIntelligence.avg_confidence || 0) * 100) }}% avg confidence</div>
        <div v-if="deploymentIntelligence.top_failure_clusters?.length" class="mt-1">
          <strong>Top failures:</strong>
          {{ deploymentIntelligence.top_failure_clusters.map((c: any) => `${c.cluster} (${c.count})`).join(', ') }}
        </div>
        <div v-if="deploymentIntelligence.recent_manual_degrade_reasons?.length" class="mt-1">
          <strong>Manual degrade reasons:</strong>
          {{ deploymentIntelligence.recent_manual_degrade_reasons.join(' | ') }}
        </div>
      </div>
      <DeploymentTrustSurfaceCard v-if="deploymentReadinessContract" class="mt-3" :contract="deploymentReadinessContract" />
      <div v-else-if="deploymentTrustSurface" class="mt-3 mission-subcard px-3 py-3 text-xs text-slate-700">
        <div>
          <strong>Trust Surface:</strong> {{ deploymentTrustSurface.tier }}
          · confidence {{ deploymentTrustSurface.confidencePct }}%
          · rollback confidence {{ deploymentTrustSurface.rollbackConfidencePct }}%
        </div>
        <div class="mt-1">
          <strong>Evidence:</strong> {{ deploymentTrustSurface.evidence }}
        </div>
        <div v-if="deploymentTrustSurface.blockers.length" class="mt-1">
          <strong>Blockers:</strong> {{ deploymentTrustSurface.blockers.join(" | ") }}
        </div>
      </div>
      <div class="mt-3 mission-subcard px-3 py-3 text-xs text-slate-700">
        <div>
          <strong>Environment Readiness:</strong> {{ missionEnvironmentReadiness.scorePct }}% overall
        </div>
        <div class="mt-1 flex flex-wrap gap-2">
          <span v-for="env in missionEnvironmentReadiness.environments" :key="env.environment" class="topbar-chip">
            {{ env.environment }} {{ env.scorePct }}% · user blockers {{ env.userPending }}
          </span>
        </div>
        <div v-if="missionEnvironmentReadiness.nextUserActions.length" class="mt-1">
          <strong>Next user actions:</strong>
          {{ missionEnvironmentReadiness.nextUserActions.map((item) => item.label).join(" | ") }}
        </div>
        <div class="mt-2">
          <el-button size="small" plain @click="goToEnvironmentCenter">Open Environment Center</el-button>
        </div>
      </div>
      <div class="mt-3 flex flex-wrap gap-2 text-xs">
        <button type="button" class="topbar-chip" :style="deploymentEventFilter === 'all' ? activeFilterStyle : undefined" @click="deploymentEventFilter = 'all'">All</button>
        <button type="button" class="topbar-chip" :style="deploymentEventFilter === 'health' ? activeFilterStyle : undefined" @click="deploymentEventFilter = 'health'">Health</button>
        <button type="button" class="topbar-chip" :style="deploymentEventFilter === 'rollback' ? activeFilterStyle : undefined" @click="deploymentEventFilter = 'rollback'">Rollback</button>
        <button type="button" class="topbar-chip" :style="deploymentEventFilter === 'promotion' ? activeFilterStyle : undefined" @click="deploymentEventFilter = 'promotion'">Promotion</button>
        <button type="button" class="topbar-chip" :style="deploymentEventFilter === 'manual' ? activeFilterStyle : undefined" @click="deploymentEventFilter = 'manual'">Manual</button>
      </div>
      <div v-if="filteredDeploymentEvents.length" class="mt-4 max-h-52 overflow-auto rounded-lg border border-slate-200">
        <button
          v-for="evt in filteredDeploymentEvents"
          :key="evt.id"
          type="button"
          class="block w-full border-b border-slate-100 px-3 py-2 text-left text-xs text-slate-700 hover:bg-slate-50"
          @click="openDeploymentEventDetail(evt)"
        >
          <div class="font-medium text-slate-900">{{ evt.event_type || evt.action_type }}</div>
          <div>{{ formatTimestamp(evt.created_at) }} · {{ evt.action_type }}</div>
        </button>
      </div>
      <div v-else-if="!deploymentOpsLoading" class="mt-4 text-xs text-slate-500">No deployment events yet.</div>
    </div>

    <div v-if="project" class="premium-card mission-panel p-6">
      <div class="flex items-center justify-between gap-3">
        <div>
          <div class="text-sm uppercase tracking-wide text-slate-400">Project Evolution Timeline</div>
          <div class="text-xs text-slate-500">Cross-domain memory stream for runs, recovery, requirements, and deployment signals.</div>
        </div>
        <el-button size="small" plain :loading="memoryTimelineLoading" @click="loadMemoryTimeline">Refresh</el-button>
      </div>
      <div v-if="memoryTimelineError" class="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
        {{ memoryTimelineError }}
      </div>
      <div v-else-if="memoryTimelineLoading" class="mt-4 text-sm text-slate-500">Loading timeline...</div>
      <div v-else-if="memoryTimeline.length" class="mt-4 mission-scroll-zone">
        <div class="space-y-2">
          <div v-for="event in memoryTimeline" :key="event.id" class="mission-subcard px-3 py-3">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="text-sm font-semibold text-slate-900">{{ event.title }}</span>
                  <el-tag size="small" effect="light" :type="memoryEventTagType(event.severity)">{{ event.severity }}</el-tag>
                  <el-tag size="small" effect="light" type="info">{{ event.domain }}</el-tag>
                </div>
                <div class="mt-1 text-xs text-slate-500">{{ event.summary || "No summary provided." }}</div>
                <div class="mt-1 text-[11px] text-slate-400">
                  {{ formatTimestamp(event.event_at) }} · {{ event.event_type }}
                  <span v-if="event.run_id"> · run {{ shortRunId(event.run_id) }}</span>
                  <span v-if="event.requirement_id"> · req {{ event.requirement_id }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="mt-4 text-sm text-slate-500">No memory timeline events yet.</div>
    </div>

    <div v-if="project" class="grid gap-4 xl:grid-cols-3">
      <div class="premium-card mission-panel p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Strategy Learning</div>
            <div class="text-xs text-slate-500">Observed strategy performance from prior runs in this project.</div>
          </div>
          <el-button plain size="small" :disabled="!forkEnabled" @click="openStrategyDialog">
            Open Strategy Lab
          </el-button>
        </div>
        <div v-if="strategyLearning.length" class="mt-4 space-y-3">
          <div
            v-for="strategy in strategyLearning"
            :key="strategy.strategy_type"
            class="mission-subcard p-4"
          >
            <div class="flex items-center justify-between gap-3">
              <div>
                <div class="text-sm font-semibold text-slate-900">{{ strategy.label }}</div>
                <div class="text-xs text-slate-500">{{ strategy.strategy_type }}</div>
              </div>
              <el-tag effect="light" :type="strategy.success_rate >= 0.75 ? 'success' : strategy.success_rate >= 0.4 ? 'warning' : 'info'">
                {{ Math.round(strategy.success_rate * 100) }}% success
              </el-tag>
            </div>
            <div class="mt-2 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
              <div><strong>Uses:</strong> {{ strategy.uses }}</div>
              <div><strong>Avg elapsed:</strong> {{ formatElapsed(strategy.average_elapsed_seconds) }}</div>
            </div>
          </div>
        </div>
        <div v-else class="mt-4 text-sm text-slate-500">No strategy history yet.</div>
      </div>

      <div class="premium-card mission-panel p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">System Insights</div>
        <div v-if="systemInsights" class="mt-4 space-y-4">
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Success Rate</div>
              <div class="mt-1 text-lg font-semibold text-slate-900">
                {{ Math.round(systemInsights.success_rate * 100) }}%
              </div>
            </div>
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Avg Fix Time</div>
              <div class="mt-1 text-lg font-semibold text-slate-900">
                {{ formatElapsed(systemInsights.average_fix_time_seconds) }}
              </div>
            </div>
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Recoveries</div>
              <div class="mt-1 text-lg font-semibold text-slate-900">
                {{ systemInsights.average_recovery_count.toFixed(1) }}
              </div>
            </div>
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">PRs Created</div>
              <div class="mt-1 text-lg font-semibold text-slate-900">
                {{ systemInsights.total_pull_requests }}
              </div>
            </div>
          </div>
          <div class="grid gap-4 sm:grid-cols-2">
            <div>
              <div class="text-xs uppercase tracking-wide text-slate-400">Most Impacted Modules</div>
              <ul class="mt-2 space-y-1 text-sm text-slate-600">
                <li v-for="item in systemInsights.most_impacted_modules" :key="item.name">
                  {{ item.name }} · {{ item.count }}
                </li>
              </ul>
            </div>
            <div>
              <div class="text-xs uppercase tracking-wide text-slate-400">Most Impacted Files</div>
              <ul class="mt-2 space-y-1 text-sm text-slate-600">
                <li v-for="item in systemInsights.most_impacted_files" :key="item.name">
                  {{ item.name }} · {{ item.count }}
                </li>
              </ul>
            </div>
          </div>
        </div>
        <div v-else class="mt-4 text-sm text-slate-500">No system insights yet.</div>
      </div>

      <div class="premium-card mission-panel p-6">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Contract Violations</div>
            <div class="text-xs text-slate-500">Recent design-rule violations observed by patch guard.</div>
          </div>
          <el-tag
            v-if="violationInsights"
            effect="light"
            :type="violationSummaryTagType(violationInsights)"
          >
            {{
              violationInsights.latest_run_blocking > 0
                ? "BLOCKING"
                : violationInsights.latest_run_warning > 0
                ? "WARNINGS"
                : "CLEAN"
            }}
          </el-tag>
        </div>
        <div v-if="violationInsights" class="mt-4 space-y-4">
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Latest Run</div>
              <div class="mt-1 text-lg font-semibold text-slate-900">{{ violationInsights.latest_run_total }}</div>
            </div>
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Recent Window</div>
              <div class="mt-1 text-lg font-semibold text-slate-900">
                {{ violationInsights.recent_total }} / {{ violationInsights.recent_run_window }} runs
              </div>
            </div>
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Blocking</div>
              <div class="mt-1 text-lg font-semibold text-rose-600">{{ violationInsights.latest_run_blocking }}</div>
            </div>
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Warnings</div>
              <div class="mt-1 text-lg font-semibold text-amber-600">{{ violationInsights.latest_run_warning }}</div>
            </div>
          </div>
          <div class="grid gap-4 sm:grid-cols-3">
            <div>
              <div class="text-xs uppercase tracking-wide text-slate-400">Top Rules</div>
              <ul class="mt-2 space-y-1 text-sm text-slate-600">
                <li v-for="item in violationInsights.top_rules" :key="`rule-${item.name}`">
                  {{ humanizeToken(item.name) }} · {{ item.count }}
                </li>
                <li v-if="!violationInsights.top_rules.length">—</li>
              </ul>
            </div>
            <div>
              <div class="text-xs uppercase tracking-wide text-slate-400">Top Types</div>
              <ul class="mt-2 space-y-1 text-sm text-slate-600">
                <li v-for="item in violationInsights.top_types" :key="`type-${item.name}`">
                  {{ humanizeToken(item.name) }} · {{ item.count }}
                </li>
                <li v-if="!violationInsights.top_types.length">—</li>
              </ul>
            </div>
            <div>
              <div class="text-xs uppercase tracking-wide text-slate-400">Top Files</div>
              <ul class="mt-2 space-y-1 text-sm text-slate-600">
                <li v-for="item in violationInsights.top_files" :key="`file-${item.name}`">
                  {{ item.name }} · {{ item.count }}
                </li>
                <li v-if="!violationInsights.top_files.length">—</li>
              </ul>
            </div>
          </div>
          <div>
            <div class="text-xs uppercase tracking-wide text-slate-400">Recent Samples</div>
            <div v-if="violationInsights.recent_samples.length" class="mt-2 space-y-2">
              <div
                v-for="(sample, index) in violationInsights.recent_samples"
                :key="`${sample.run_id}-${sample.rule}-${index}`"
                class="mission-subcard p-3 text-xs text-slate-600"
              >
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <div class="font-mono text-[11px] text-slate-700">
                    {{ shortRunId(sample.run_id) }} · {{ sample.work_item_type || "WORK_ITEM" }}
                  </div>
                  <el-tag size="small" effect="light" :type="sample.blocking ? 'danger' : 'warning'">
                    {{ sample.blocking ? "BLOCKING" : "WARN" }}
                  </el-tag>
                </div>
                <div class="mt-1">
                  {{ sample.message || `${humanizeToken(sample.rule)} triggered` }}
                </div>
                <div class="mt-1 text-[11px] text-slate-500">
                  Rule: {{ humanizeToken(sample.rule) }}
                  <span v-if="sample.file"> · File: {{ sample.file }}</span>
                  <span v-if="sample.value"> · Value: {{ sample.value }}</span>
                </div>
              </div>
            </div>
            <div v-else class="mt-2 text-sm text-slate-500">No recent violations captured.</div>
          </div>
        </div>
        <div v-else class="mt-4 text-sm text-slate-500">No violation insights yet.</div>
      </div>
    </div>

    <div v-if="project" class="grid gap-4 lg:grid-cols-2">
      <AgentPanel :agents="agentRows" />

      <div class="premium-card mission-panel p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Project Signals</div>
        <div class="mt-4 grid gap-3 sm:grid-cols-2">
          <div class="mission-subcard p-4">
            <div class="text-xs uppercase text-slate-400">Run Completion</div>
            <div class="mt-1 text-xl font-semibold text-slate-900">
              {{ lifecycleScore?.execution?.completed_runs ?? 0 }}/{{ lifecycleScore?.execution?.total_runs ?? 0 }}
            </div>
          </div>
          <div class="mission-subcard p-4">
            <div class="text-xs uppercase text-slate-400">Trace Coverage</div>
            <div class="mt-1 text-xl font-semibold text-slate-900">
              {{ coveragePercent }}
            </div>
          </div>
          <div class="mission-subcard p-4">
            <div class="text-xs uppercase text-slate-400">Graph Cycles</div>
            <div class="mt-1 text-xl font-semibold text-slate-900">
              {{ health?.counts?.cycles ?? 0 }}
            </div>
          </div>
          <div class="mission-subcard p-4">
            <div class="text-xs uppercase text-slate-400">Orphan Tasks</div>
            <div class="mt-1 text-xl font-semibold text-slate-900">
              {{ health?.counts?.orphan_tasks ?? 0 }}
            </div>
          </div>
        </div>
        <div class="mission-subcard mt-3 p-4">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="text-xs uppercase text-slate-400">Frontend Topology Plan</div>
            <el-tag
              size="small"
              effect="light"
              :type="frontendTopologyPlan ? 'success' : 'info'"
            >
              {{ frontendTopologyPlan ? 'Planned' : 'Not planned yet' }}
            </el-tag>
          </div>
          <div v-if="frontendTopologyPlan" class="mt-2 space-y-2 text-xs text-slate-600">
            <div>
              <strong class="text-slate-800">Stage:</strong>
              {{ frontendTopologyPlan.planner_stage || "PLAN_FRONTEND_TOPOLOGY_V1" }}
            </div>
            <div>
              <strong class="text-slate-800">Root:</strong>
              <span class="font-mono">{{ frontendTopologyPlan.root_file || "index.html" }}</span>
            </div>
            <div>
              <strong class="text-slate-800">Sections:</strong>
              {{ frontendTopologySectionsLabel }}
            </div>
            <div>
              <strong class="text-slate-800">Component Files:</strong>
              {{ frontendTopologyComponentFilesLabel }}
            </div>
          </div>
          <div v-else class="mt-2 text-xs text-slate-500">
            Topology plan will appear when static frontend execution is prepared.
          </div>
        </div>
      </div>
    </div>

    <ExecutionTimeline
      :logs="timelineLogs"
      :tasks="displayWorkItemsDeduped"
      :current-stage="currentStage"
      :run-status="latestRun?.status || 'IDLE'"
      :run-id="latestRun?.id"
    />

    <div class="grid gap-4 xl:grid-cols-[2fr,1fr]">
      <div class="premium-card mission-panel p-6 mission-data-panel">
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
          v-if="displayWorkItemsDeduped.length"
          :data="displayWorkItemsDeduped"
          class="mt-4"
          style="width: 100%"
        >
          <el-table-column label="Step" min-width="260">
            <template #default="{ row }">
              <div class="flex flex-wrap items-center gap-2">
                <span>{{ row.title }}</span>
                <el-tag v-if="row.attempt_count > 1" size="small" type="info" effect="light">
                  {{ row.attempt_count }} attempts
                </el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="agent" label="Agent" min-width="140" />
          <el-table-column prop="executor" label="Executor" min-width="120" />
          <el-table-column label="Lineage" min-width="210">
            <template #default="{ row }">
              <div class="text-xs text-slate-700">{{ row.source_surface || "mission_control" }}</div>
              <div class="font-mono text-xs text-slate-500">
                task {{ shortRunId(row.task_id) }} · run {{ shortRunId(row.run_id) }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="Status" width="130">
            <template #default="{ row }">
              <el-tag :type="workItemStatusTagType(row.rawStatus, row.blocking)" effect="light">
                {{ row.rawStatus }}
              </el-tag>
              <el-tag v-if="row.blocking === false" class="ml-2" type="warning" effect="light">OPTIONAL</el-tag>
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

      <div class="premium-card mission-panel p-6 mission-data-panel">
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
                  type="info"
                  @click="openDiffDialog(row)"
                >
                  Preview Diff
                </el-button>
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

    <div class="grid gap-4 xl:grid-cols-[1.5fr,1fr]">
      <div class="premium-card mission-panel p-6">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Similar Past Runs</div>
            <div class="text-xs text-slate-500">Run memory suggestions based on the latest goal and failure signal.</div>
          </div>
          <div class="flex items-center gap-2">
            <el-button plain size="small" :loading="runMemoryLoading" @click="loadSimilarRuns">Refresh</el-button>
            <el-button
              v-if="similarRunMatches.length > similarCollapsedCount"
              plain
              size="small"
              @click="similarExpanded = !similarExpanded"
            >
              {{ similarExpanded ? "Collapse" : "View all" }}
            </el-button>
          </div>
        </div>
        <div v-if="runMemoryLoading" class="mt-4 text-sm text-slate-500">Searching prior runs...</div>
        <div v-else-if="similarRunsDisplay.length" class="mt-4 mission-content-scroll">
          <div class="space-y-3">
            <div
              v-for="match in similarRunsDisplay"
              :key="match.run_id"
              class="mission-subcard p-4"
            >
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div class="font-mono text-sm text-slate-900">{{ match.run_id }}</div>
                <div class="text-xs text-slate-500 mission-line-clamp-3" :title="match.goal || 'No goal summary'">
                  {{ match.goal || "No goal summary" }}
                </div>
              </div>
              <div class="flex items-center gap-2">
                <el-tag effect="light" type="info">Score {{ match.score.toFixed(1) }}</el-tag>
                <el-button plain size="small" :disabled="!latestRun?.id" @click="compareAgainstRun(match.run_id)">
                  Compare
                </el-button>
              </div>
            </div>
            <div class="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
              <div><strong>Status:</strong> {{ match.status }}</div>
              <div><strong>Elapsed:</strong> {{ formatElapsed(match.elapsed_seconds) }}</div>
              <div><strong>Recoveries:</strong> {{ match.recovery_count }}</div>
              <div><strong>Files:</strong> {{ match.files_changed.length }}</div>
            </div>
            <div v-if="match.last_error" class="mt-2 text-xs text-slate-500">
              <strong>Error:</strong> {{ match.last_error }}
            </div>
            <div v-if="match.files_changed.length" class="mt-2 text-xs text-slate-500">
              <strong>Changed:</strong> {{ match.files_changed.join(", ") }}
            </div>
          </div>
          </div>
        </div>
        <div v-else class="mt-4 text-sm text-slate-500">No similar runs found yet.</div>
        <div v-if="runMemoryError" class="mt-3 text-sm text-rose-600">{{ runMemoryError }}</div>
      </div>

      <div class="premium-card mission-panel p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Replay Shortcut</div>
        <div class="mt-2 text-sm text-slate-600">
          Open the deterministic replay for the latest run, or jump to the full timeline page.
        </div>
        <div class="mt-4 space-y-3">
          <div class="mission-subcard p-3 text-xs text-slate-500">
            Latest replay target
            <div class="mt-1 font-mono text-slate-800">{{ latestRun?.id || "—" }}</div>
          </div>
          <el-button class="w-full" plain :disabled="!forkEnabled" @click="openReplayDialog()">
            Open Replay
          </el-button>
          <el-button class="w-full" :disabled="!forkEnabled" @click="openTimelinePage()">
            Open Timeline Page
          </el-button>
        </div>
      </div>
    </div>

    <el-dialog v-model="deploymentEventDialogOpen" title="Deployment Event Detail" width="760px">
      <div v-if="selectedDeploymentEvent" class="space-y-3 text-sm text-slate-700">
        <div><strong>Type:</strong> {{ selectedDeploymentEvent.event_type || selectedDeploymentEvent.action_type }}</div>
        <div><strong>Action:</strong> {{ selectedDeploymentEvent.action_type }}</div>
        <div><strong>Time:</strong> {{ formatTimestamp(selectedDeploymentEvent.created_at) }}</div>
        <div><strong>Actor:</strong> {{ selectedDeploymentEvent.actor || "system" }}</div>
        <div>
          <strong>Metadata</strong>
          <pre class="mt-1 max-h-72 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">{{
            JSON.stringify(selectedDeploymentEvent.extra_metadata || {}, null, 2)
          }}</pre>
        </div>
      </div>
      <div v-else class="text-sm text-slate-500">No event selected.</div>
    </el-dialog>

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
        <div class="mission-subcard px-3 py-2 text-xs text-slate-500">
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

    <el-dialog v-model="budgetDialogOpen" title="Increase Budget & Continue" width="520px">
      <div class="space-y-4">
        <div class="text-sm text-slate-600">
          This run is paused due to budget exhaustion. Approve additional budget to continue execution.
        </div>
        <label class="space-y-1 text-sm text-slate-700">
          <span class="block font-medium text-slate-800">Additional Tokens</span>
          <input
            v-model.number="budgetAdditionalTokens"
            type="number"
            min="1"
            step="1000"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </label>
        <label class="space-y-1 text-sm text-slate-700">
          <span class="block font-medium text-slate-800">Additional Cost (cents)</span>
          <input
            v-model.number="budgetAdditionalCostCents"
            type="number"
            min="0.01"
            step="0.01"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </label>
        <label class="space-y-1 text-sm text-slate-700">
          <span class="block font-medium text-slate-800">Reason</span>
          <input
            v-model="budgetExtensionReason"
            type="text"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="Operator approval reason"
          />
        </label>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <el-button :disabled="budgetExtendLoading" @click="budgetDialogOpen = false">Cancel</el-button>
          <el-button type="warning" :loading="budgetExtendLoading" @click="approveBudgetExtension">
            Approve & Continue
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

        <div
          v-if="compareResult && comparisonHeadlineLines.length"
          class="mission-highlight p-4 text-sm"
        >
          <div class="text-xs uppercase tracking-wide text-indigo-500">Quick Read</div>
          <ul class="mt-2 space-y-1">
            <li v-for="line in comparisonHeadlineLines" :key="line">{{ line }}</li>
          </ul>
        </div>

        <div v-if="compareResult" class="grid gap-4 md:grid-cols-2">
          <div class="mission-subcard p-4">
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

          <div class="mission-subcard p-4">
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

        <div v-if="compareResult" class="premium-card mission-panel p-4 text-sm text-slate-700">
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

    <el-dialog v-model="replayDialogOpen" title="Replay Run" width="860px">
      <div class="space-y-4">
        <div class="grid gap-4 sm:grid-cols-[1fr,auto]">
          <label class="space-y-1 text-sm text-slate-700">
            <span class="block font-medium text-slate-800">Run</span>
            <select
              v-model="replayRunId"
              class="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              @change="loadReplayTimeline"
            >
              <option v-for="option in compareRunOptions" :key="option.id" :value="option.id">
                {{ option.label }}
              </option>
            </select>
          </label>
          <div class="flex items-end gap-2">
            <el-button plain :loading="replayLoading" @click="loadReplayTimeline">Refresh</el-button>
            <el-button :disabled="!replayRunId" @click="openTimelinePage(replayRunId)">Open Page</el-button>
          </div>
        </div>

        <div v-if="replayResult" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div class="mission-subcard p-3 text-sm">
            <div class="text-xs uppercase tracking-wide text-slate-400">Goal</div>
            <div class="mt-1 text-slate-800">{{ replayResult.summary.goal_text || "—" }}</div>
          </div>
          <div class="mission-subcard p-3 text-sm">
            <div class="text-xs uppercase tracking-wide text-slate-400">Elapsed</div>
            <div class="mt-1 text-slate-800">{{ formatElapsed(replayResult.summary.elapsed_seconds) }}</div>
          </div>
          <div class="mission-subcard p-3 text-sm">
            <div class="text-xs uppercase tracking-wide text-slate-400">Recoveries</div>
            <div class="mt-1 text-slate-800">{{ replayResult.summary.recovery_count }}</div>
          </div>
          <div class="mission-subcard p-3 text-sm">
            <div class="text-xs uppercase tracking-wide text-slate-400">PR</div>
            <div class="mt-1 break-all text-slate-800">{{ replayResult.summary.pull_request_url || "—" }}</div>
          </div>
        </div>

        <div v-if="replayLoading" class="text-sm text-slate-500">Loading replay timeline...</div>
        <el-timeline v-else-if="replayResult?.steps?.length" class="max-h-[28rem] overflow-y-auto pr-2">
          <el-timeline-item
            v-for="step in replayResult.steps"
            :key="step.id"
            :timestamp="formatTimestamp(step.ts)"
            placement="top"
          >
            <div class="mission-subcard p-3">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div class="font-medium text-slate-900">{{ step.title }}</div>
                  <div class="text-xs uppercase tracking-wide text-slate-400">{{ step.kind }}</div>
                </div>
                <el-tag :type="timelineStatusTagType(step.status)" effect="light">
                  {{ step.status }}
                </el-tag>
              </div>
              <div v-if="step.message" class="mt-2 text-sm text-slate-600">{{ step.message }}</div>
              <div v-if="step.changed_files?.length" class="mt-2 text-xs text-slate-500">
                <strong>Files:</strong> {{ step.changed_files.join(", ") }}
              </div>
              <div v-if="step.work_item_key || step.artifact_type" class="mt-2 text-xs text-slate-500">
                <span v-if="step.work_item_key"><strong>Work item:</strong> {{ step.work_item_key }}</span>
                <span v-if="step.artifact_type" class="ml-2"><strong>Artifact:</strong> {{ step.artifact_type }}</span>
              </div>
            </div>
          </el-timeline-item>
        </el-timeline>
        <div v-else class="text-sm text-slate-500">No replay steps available for this run yet.</div>
        <div v-if="replayError" class="text-sm text-rose-600">{{ replayError }}</div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <el-button :disabled="replayLoading" @click="replayDialogOpen = false">Close</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="improveDialogOpen" title="Report Issue / Improve" width="720px">
      <div class="space-y-4">
        <div class="text-sm text-slate-600">
          Describe what you noticed in preview, QA, or review. Mission Control will fork from the latest run, reuse its workspace, and launch one focused improvement run.
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <div class="mission-subcard p-3 text-sm">
            <div class="text-xs uppercase tracking-wide text-slate-400">Source Run</div>
            <div class="mt-1 font-mono text-slate-900">{{ latestRun?.id || "—" }}</div>
            <div class="mt-1 text-xs text-slate-500">Executor {{ latestRun?.executor || "—" }}</div>
          </div>
          <div class="mission-subcard p-3 text-sm">
            <div class="text-xs uppercase tracking-wide text-slate-400">Workspace Reuse</div>
            <div class="mt-1 text-slate-900">{{ latestRun?.workspace_status || "PENDING" }}</div>
            <div class="mt-1 text-xs text-slate-500">Forks the latest seeded repo state instead of restarting from scratch.</div>
          </div>
        </div>
        <label class="space-y-1 text-sm text-slate-700">
          <span class="block font-medium text-slate-800">Issue / Improvement Request</span>
          <textarea
            v-model="improveIssueText"
            rows="4"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="Projects section is missing below the hero on mobile preview."
          />
        </label>
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="space-y-1 text-sm text-slate-700">
            <span class="block font-medium text-slate-800">Files (optional)</span>
            <input
              v-model="improveFilesInput"
              type="text"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              placeholder="index.html, styles.css"
            />
          </label>
          <label class="space-y-1 text-sm text-slate-700">
            <span class="block font-medium text-slate-800">Executor</span>
            <select
              v-model="improveExecutor"
              class="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              <option value="">Use source executor</option>
              <option v-for="option in forkExecutorOptions" :key="option" :value="option">
                {{ option }}
              </option>
            </select>
          </label>
        </div>
        <label class="flex items-center gap-2 text-sm text-slate-700">
          <input v-model="improveStartNow" type="checkbox" class="rounded border-slate-300" />
          Start the improvement run immediately
        </label>
        <div v-if="improveError" class="text-sm text-rose-600">{{ improveError }}</div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <el-button :disabled="improveLoading" @click="improveDialogOpen = false">Cancel</el-button>
          <el-button
            type="primary"
            :loading="improveLoading"
            :disabled="!improveReady"
            @click="submitImproveRun"
          >
            Create Improvement Run
          </el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="strategyDialogOpen" title="Strategy Lab" width="760px">
      <div class="space-y-4">
        <div class="text-sm text-slate-600">
          Create labeled candidate runs on top of the latest run, then use comparison and recommendation to select the best result.
        </div>
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="space-y-1 text-sm text-slate-700">
            <span class="block font-medium text-slate-800">Goal</span>
            <textarea
              v-model="strategyGoal"
              rows="3"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              placeholder="Fix failing authentication tests"
            />
          </label>
          <label class="space-y-1 text-sm text-slate-700">
            <span class="block font-medium text-slate-800">Error Signal</span>
            <textarea
              v-model="strategyErrorText"
              rows="3"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              placeholder="pytest import error"
            />
          </label>
        </div>
        <div class="grid gap-4 sm:grid-cols-3">
          <label class="space-y-1 text-sm text-slate-700 sm:col-span-2">
            <span class="block font-medium text-slate-800">Files</span>
            <input
              v-model="strategyFilesInput"
              type="text"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              placeholder="app/auth_service.py, tests/test_auth.py"
            />
          </label>
          <label class="space-y-1 text-sm text-slate-700">
            <span class="block font-medium text-slate-800">Executor</span>
            <select
              v-model="strategyExecutor"
              class="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              <option value="">Use source executor</option>
              <option v-for="option in forkExecutorOptions" :key="option" :value="option">
                {{ option }}
              </option>
            </select>
          </label>
        </div>
        <div class="flex flex-wrap items-center gap-4">
          <label class="flex items-center gap-2 text-sm text-slate-700">
            <input v-model="strategyStartNow" type="checkbox" class="rounded border-slate-300" />
            Start candidate runs immediately
          </label>
          <label class="flex items-center gap-2 text-sm text-slate-700">
            <span class="font-medium text-slate-800">Candidates</span>
            <select
              v-model="strategyLimit"
              class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              <option :value="2">2</option>
              <option :value="3">3</option>
            </select>
          </label>
        </div>

        <div
          v-if="strategyResult?.recommendation"
          class="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900"
        >
          <div class="text-xs uppercase tracking-wide text-emerald-600">Recommended Strategy</div>
          <div class="mt-2 font-semibold">
            {{ strategyResult.recommendation.label }}
            <span class="ml-2 font-mono text-xs text-emerald-700">
              {{ strategyResult.recommendation.run_id }}
            </span>
          </div>
          <div class="mt-1 text-xs text-emerald-800">
            Score {{ strategyResult.recommendation.score.toFixed(1) }}
          </div>
          <ul class="mt-2 space-y-1 text-sm">
            <li v-for="line in strategyResult.recommendation.rationale" :key="line">{{ line }}</li>
          </ul>
        </div>

        <div v-if="strategyResult" class="premium-card mission-panel p-4">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div class="text-xs uppercase tracking-wide text-slate-400">Strategy Group</div>
              <div class="font-mono text-sm text-slate-800">{{ strategyResult.group_id }}</div>
            </div>
            <el-button plain size="small" :loading="strategyRefreshing" @click="refreshStrategyGroup">
              Refresh Recommendation
            </el-button>
          </div>
          <div class="mt-3 space-y-2">
            <div
              v-for="candidate in strategyResult.candidates"
              :key="candidate.run_id"
              class="mission-subcard p-3"
            >
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div class="text-sm font-semibold text-slate-900">{{ candidate.label }}</div>
                  <div class="text-xs text-slate-500">{{ candidate.rationale }}</div>
                </div>
                <div class="flex items-center gap-2">
                  <el-tag :type="runStatusTagType(candidate.status)" effect="light">
                    {{ candidate.status }}
                  </el-tag>
                  <el-tag v-if="strategyResult.recommendation?.run_id === candidate.run_id" type="success" effect="light">
                    Best
                  </el-tag>
                </div>
              </div>
              <div class="mt-2 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
                <div><strong>Run:</strong> <span class="font-mono">{{ candidate.run_id }}</span></div>
                <div><strong>Branch:</strong> {{ candidate.branch_name || "—" }}</div>
                <div><strong>Type:</strong> {{ candidate.strategy_type }}</div>
                <div><strong>Score:</strong> {{ candidate.score?.toFixed(1) ?? "Pending" }}</div>
              </div>
              <div v-if="candidate.prompt_hint" class="mt-2 text-xs text-slate-500">
                <strong>Hint:</strong> {{ candidate.prompt_hint }}
              </div>
            </div>
          </div>
        </div>

        <div v-if="strategyErrorMessage" class="text-sm text-rose-600">{{ strategyErrorMessage }}</div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <el-button :disabled="strategyLoading || strategyRefreshing" @click="strategyDialogOpen = false">Close</el-button>
          <el-button
            type="primary"
            :loading="strategyLoading"
            :disabled="!forkEnabled"
            @click="submitStrategyPlan"
          >
            Create Candidate Runs
          </el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="diffDialogOpen" title="Patch Preview" width="920px">
      <div class="space-y-4">
        <div v-if="diffLoading" class="text-sm text-slate-500">Loading diff preview...</div>
        <template v-else-if="diffResult">
          <div class="grid gap-3 sm:grid-cols-4">
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Files</div>
              <div class="mt-1 font-semibold text-slate-900">{{ diffResult.file_count }}</div>
            </div>
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-emerald-500">Additions</div>
              <div class="mt-1 font-semibold text-emerald-700">+{{ diffResult.additions }}</div>
            </div>
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-rose-500">Deletions</div>
              <div class="mt-1 font-semibold text-rose-700">-{{ diffResult.deletions }}</div>
            </div>
            <div class="mission-subcard p-3 text-sm">
              <div class="text-xs uppercase tracking-wide text-slate-400">Artifact</div>
              <div class="mt-1 font-mono text-[11px] text-slate-700">{{ shortenUri(diffResult.uri) }}</div>
            </div>
          </div>

          <div class="space-y-3">
            <div
              v-for="file in diffResult.files"
              :key="`${file.path}-${file.old_path}-${file.new_path}`"
              class="overflow-hidden rounded-2xl border border-slate-200 bg-white"
            >
              <div class="border-b border-slate-200 bg-slate-50 px-4 py-3">
                <div class="font-mono text-sm text-slate-900">{{ file.path }}</div>
                <div class="mt-1 text-xs text-slate-500">
                  +{{ file.additions }} / -{{ file.deletions }}
                </div>
              </div>
              <pre class="max-h-72 overflow-auto bg-slate-950 px-4 py-3 text-xs text-slate-100">{{ file.patch }}</pre>
            </div>
          </div>
        </template>
        <div v-if="diffError" class="text-sm text-rose-600">{{ diffError }}</div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <el-button :disabled="diffLoading" @click="diffDialogOpen = false">Close</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="createPrDialogOpen" title="Create Pull Request" width="620px">
      <div class="space-y-4">
        <div class="text-sm text-slate-600">
          Create a GitHub pull request from the selected patch artifact and the latest run workspace.
        </div>
        <div class="mission-subcard px-3 py-2 text-xs text-slate-500">
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
        <div class="premium-card mission-panel px-3 py-3 text-sm text-slate-700">
          <div class="text-xs uppercase tracking-wide text-slate-400">Approval Gate</div>
          <div class="mt-2 flex flex-wrap items-center gap-2">
            <el-tag :type="approvalTagType(latestArtifactApprovalStatus)" effect="light">
              {{ latestArtifactApprovalStatus || "PENDING" }}
            </el-tag>
            <span v-if="latestArtifactApproval" class="text-xs text-slate-500">
              {{ latestArtifactApproval.decided_by || "system" }}
              ·
              {{ formatTimestamp(latestArtifactApproval.updated_at || latestArtifactApproval.created_at) }}
            </span>
            <span v-else class="text-xs text-slate-500">
              Approve this patch before opening a pull request.
            </span>
          </div>
          <div v-if="latestArtifactApproval?.comment" class="mt-2 text-xs text-slate-500">
            <strong>Latest note:</strong> {{ latestArtifactApproval.comment }}
          </div>
          <label class="mt-3 block space-y-1 text-sm text-slate-700">
            <span class="block font-medium text-slate-800">Decision Note</span>
            <textarea
              v-model="createPrApprovalComment"
              rows="2"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              placeholder="Why this patch is approved or rejected"
            />
          </label>
          <div class="mt-3 flex flex-wrap gap-2">
            <el-button plain :loading="createPrApprovalLoading" @click="submitArtifactApproval('REJECTED')">
              Reject
            </el-button>
            <el-button type="success" :loading="createPrApprovalLoading" @click="submitArtifactApproval('APPROVED')">
              Approve Patch
            </el-button>
          </div>
          <div v-if="createPrApprovalError" class="mt-2 text-sm text-rose-600">{{ createPrApprovalError }}</div>
        </div>
        <div v-if="createPrDiffLoading" class="text-sm text-slate-500">Loading PR preview...</div>
        <div
          v-else-if="createPrDiffPreview"
          class="mission-subcard px-3 py-3 text-sm text-slate-700"
        >
          <div class="text-xs uppercase tracking-wide text-slate-400">PR Preview</div>
          <div class="mt-2 flex flex-wrap gap-3 text-xs text-slate-600">
            <span><strong>Files:</strong> {{ createPrDiffPreview.file_count }}</span>
            <span><strong>Additions:</strong> +{{ createPrDiffPreview.additions }}</span>
            <span><strong>Deletions:</strong> -{{ createPrDiffPreview.deletions }}</span>
          </div>
          <div v-if="createPrDiffPreview.files.length" class="mt-2 text-xs text-slate-500">
            {{ createPrDiffPreview.files.map((file) => file.path).join(", ") }}
          </div>
        </div>
        <div v-if="createPrChangeSummary" class="mission-subcard px-3 py-3 text-sm text-slate-700">
          <div class="text-xs uppercase tracking-wide text-slate-400">Change Summary</div>
          <div class="mt-2 text-sm font-medium text-slate-800">{{ createPrChangeSummary.title }}</div>
          <div v-if="createPrChangeSummary.goal" class="mt-1 text-xs text-slate-600">
            {{ createPrChangeSummary.goal }}
          </div>
          <ul class="mt-3 space-y-1 text-xs text-slate-600">
            <li><strong>Scope:</strong> {{ createPrChangeSummary.scope }}</li>
            <li><strong>Files touched:</strong> {{ createPrChangeSummary.filesTouched }}</li>
            <li><strong>Diff:</strong> {{ createPrChangeSummary.diff }}</li>
            <li><strong>Risk:</strong> {{ createPrChangeSummary.risk }}</li>
          </ul>
        </div>
        <div v-if="createPrDiffError" class="text-sm text-rose-600">{{ createPrDiffError }}</div>
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
        <div v-if="createPrBlockingReason" class="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {{ createPrBlockingReason }}
        </div>
        <div v-if="createPrError" class="text-sm text-rose-600">{{ createPrError }}</div>
        <div
          v-if="createPrRemediationHint"
          class="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800"
        >
          {{ createPrRemediationHint }}
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <el-button :disabled="createPrLoading" @click="createPrDialogOpen = false">Cancel</el-button>
          <el-button
            type="primary"
            :loading="createPrLoading"
            :disabled="!createPrReady || Boolean(createPrResult?.pull_request_url)"
            @click="submitCreatePr"
          >
            Create PR
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>

  <div v-else class="rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-800">
    Select a project to open Mission Control.
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";

import AgentPanel from "../components/AgentPanel.vue";
import AppIcon from "../components/AppIcon.vue";
import ExecutionTimeline from "../components/ExecutionTimeline.vue";
import MetricCard from "../components/MetricCard.vue";
import StageBadge from "../components/StageBadge.vue";
import DeploymentTrustSurfaceCard from "../components/DeploymentTrustSurfaceCard.vue";
import OperatorConsole from "../components/operator/OperatorConsole.vue";
import ExecutionConsolePanel from "../components/workbench/ExecutionConsolePanel.vue";
import ReviewSurfacePanel from "../components/workbench/ReviewSurfacePanel.vue";
import TaskQueuePanel from "../components/workbench/TaskQueuePanel.vue";
import {
  applyArchitectureDriftFixAndOpenPr,
  bootstrapProjectContract,
  compareRuns,
  createApproval,
  listApprovals,
  createRun,
  createVisionRun,
  createRunStrategies,
  createRunPullRequest,
  createProjectDeployment,
  listProjectDeployments,
  listDeploymentEvents,
  retryProjectDeployment,
  rollbackProjectDeployment,
  promoteProjectDeployment,
  preflightProjectDeployment,
  fetchProjectDeploymentIntelligence,
  fetchProjectDeploymentReadiness,
  discardRun,
  deleteRunPreview,
  explainArtifact,
  fetchArtifactDiff,
  fetchRunExecutionConsole,
  fetchMissionControlOverview,
  fetchProjectMemoryTimeline,
  fetchRunNarrative,
  fetchRunStrategies,
  fetchHealth,
  getActiveTenantId,
  fetchLifecycleScore,
  fetchProjectMeta,
  getProjectEnvironmentChecklists,
  fetchRunTimeline,
  getOrCreateActionRequestKey,
  findSimilarRuns,
  hasRunMemorySearchContext,
  forkRun,
  launchRunPreview,
  listArtifacts,
  listRunEvents,
  listRuns,
  listWorkItems,
  patchProjectContract,
  reportRunIssue,
  extendRunBudget,
  retryRunPush,
  resumeRun,
  updateRunStatus,
} from "../api/lifecycle";
import { buildDeploymentTrustSummary, clampPercent } from "../composables/deploymentTrust";
import { buildEnvironmentReadiness } from "../composables/environmentReadiness";
import { updateProjectContext } from "../state/projectContext";

const route = useRoute();
const router = useRouter();
const DENSITY_STORAGE_KEY = "mission-control-density-mode";

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
const missionOverview = ref<any | null>(null);
const memoryTimeline = ref<any[]>([]);
const memoryTimelineLoading = ref(false);
const memoryTimelineError = ref("");
const runs = ref<any[]>([]);
const workItems = ref<any[]>([]);
const runEvents = ref<any[]>([]);
const artifacts = ref<any[]>([]);
const executionConsole = ref<any | null>(null);
const loading = ref(false);
const error = ref("");
const overviewError = ref("");
const artifactError = ref("");
const artifactDialogOpen = ref(false);
const artifactExplainLoading = ref(false);
const artifactExplainError = ref("");
const artifactExplainResult = ref<any | null>(null);
const diffDialogOpen = ref(false);
const diffLoading = ref(false);
const diffError = ref("");
const diffResult = ref<any | null>(null);
const selectedDiffArtifact = ref<any | null>(null);
const createPrDialogOpen = ref(false);
const createPrLoading = ref(false);
const createPrError = ref("");
const createPrResult = ref<any | null>(null);
const selectedPrArtifact = ref<any | null>(null);
const selectedPrRunId = ref("");
const createPrTitle = ref("");
const createPrBody = ref("");
const createPrBranch = ref("");
const createPrDiffLoading = ref(false);
const createPrDiffError = ref("");
const createPrDiffPreview = ref<any | null>(null);
const createPrApprovalLoading = ref(false);
const createPrApprovalError = ref("");
const createPrApprovalComment = ref("");
const createPrApprovals = ref<any[]>([]);
const previewLaunchLoading = ref(false);
const previewLaunchError = ref("");
const previewLaunchInfo = ref("");
const deployLoading = ref(false);
const deployError = ref("");
const deployInfo = ref("");
const latestDeployment = ref<any | null>(null);
const deploymentRows = ref<any[]>([]);
const deploymentEvents = ref<any[]>([]);
const deploymentOpsLoading = ref(false);
const deploymentOpsError = ref("");
const deploymentPreflight = ref<any | null>(null);
const deploymentIntelligence = ref<any | null>(null);
const deploymentReadinessContract = ref<any | null>(null);
const environmentChecklistSummary = ref<any | null>(null);
const deploymentEventDialogOpen = ref(false);
const selectedDeploymentEvent = ref<any | null>(null);
const deploymentEventFilter = ref<"all" | "health" | "rollback" | "promotion" | "manual">("all");
const previewViewport = ref<"desktop" | "mobile">("desktop");
const forkDialogOpen = ref(false);
const forkLoading = ref(false);
const forkError = ref("");
const forkExecutor = ref("codex");
const forkBranchName = ref("");
const forkNotes = ref("");
const forkStartNow = ref(true);
const compareDialogOpen = ref(false);
const compareLoading = ref(false);
const compareError = ref("");
const compareResult = ref<any | null>(null);
const compareRunAId = ref("");
const compareRunBId = ref("");
const strategyDialogOpen = ref(false);
const strategyLoading = ref(false);
const strategyRefreshing = ref(false);
const strategyErrorMessage = ref("");
const strategyResult = ref<any | null>(null);
const densityMode = ref<"compact" | "comfortable">("comfortable");
const reflectionsExpanded = ref(false);
const similarExpanded = ref(false);
const reflectionsCollapsedCount = 3;
const similarCollapsedCount = 3;
const strategyGoal = ref("");
const strategyErrorText = ref("");
const strategyFilesInput = ref("");
const strategyStartNow = ref(true);
const strategyLimit = ref(3);
const strategyExecutor = ref("");
const improveDialogOpen = ref(false);
const improveLoading = ref(false);
const improveError = ref("");
const improveSuccessMessage = ref("");
const improveIssueText = ref("");
const improveFilesInput = ref("");
const improveStartNow = ref(true);
const improveExecutor = ref("");
const runMemoryLoading = ref(false);
const runMemoryError = ref("");
const runMemoryResult = ref<any | null>(null);
const intakeRunLoadingId = ref("");
const visionGoalText = ref("");
const visionAutoStart = ref(true);
const visionAutoDeploy = ref(false);
const visionSubmitting = ref(false);
const visionScreenshots = ref<Array<{ filename: string; content_type: string; data_base64: string; size_bytes: number }>>([]);
const visionFileInput = ref<HTMLInputElement | null>(null);
const replayDialogOpen = ref(false);
const replayLoading = ref(false);
const replayError = ref("");
const replayResult = ref<any | null>(null);
const replayRunId = ref("");
const resumeLoading = ref(false);
const budgetExtendLoading = ref(false);
const budgetDialogOpen = ref(false);
const budgetAdditionalTokens = ref(20000);
const budgetAdditionalCostCents = ref(25);
const budgetExtensionReason = ref("Operator approved from Mission Control");
const retryPushLoading = ref(false);
const discardLoading = ref(false);
const retryPushStrategy = ref("runtime_default");
const runNarrativeLoading = ref(false);
const runNarrativeError = ref("");
const runNarrative = ref<any | null>(null);
const projectContractBootstrapLoading = ref(false);
const projectContractEnforcementLoading = ref(false);
const projectContractStrictLoading = ref(false);
const projectContractActionError = ref("");
const architectureDriftFixLoading = ref(false);
const architectureDriftFixError = ref("");
const pinnedRunId = ref("");

const projectId = computed(() => (route.params.projectId as string) || "");
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
function canonicalizeRuns(runList: any[]) {
  const rows = Array.isArray(runList) ? [...runList] : [];
  return rows.sort((a, b) => {
    const aStatus = String(a?.status || "").toUpperCase();
    const bStatus = String(b?.status || "").toUpperCase();
    const aPriority = runStatusPriority[aStatus] ?? 99;
    const bPriority = runStatusPriority[bStatus] ?? 99;
    if (aPriority !== bPriority) return aPriority - bPriority;
    const byTime = timestampScore(b) - timestampScore(a);
    if (byTime !== 0) return byTime;
    return String(b?.id || "").localeCompare(String(a?.id || ""));
  });
}
const canonicalRunId = computed(() => {
  if (pinnedRunId.value) {
    const selected = runs.value.find((run) => run?.id === pinnedRunId.value);
    if (selected?.id) return selected.id;
  }
  // Default focus should follow recency to avoid jumping back to older paused runs.
  // Sticky focus is only applied when the operator explicitly pins a run.
  const latestByUpdatedAt = [...runs.value].sort((a, b) => timestampScore(b) - timestampScore(a))[0];
  return latestByUpdatedAt?.id || "";
});

const latestRun = computed(() => runs.value.find((run) => run?.id === canonicalRunId.value) || null);
const latestTerminalQuality = computed(() => String(latestRun.value?.summary?.terminal_quality || "").trim().toUpperCase());
const latestTerminalQualityLabel = computed(() => latestTerminalQuality.value || "IN_PROGRESS");
const latestTerminalCounts = computed(() => {
  const counts = latestRun.value?.summary?.terminal_counts;
  return counts && typeof counts === "object" ? counts : {};
});
const linkedRequirementId = computed(
  () =>
    latestRun.value?.summary?.requirement_id ||
    (Array.isArray(latestRun.value?.summary?.requirement_ids) ? latestRun.value?.summary?.requirement_ids[0] : null) ||
    null
);
const linkedRequirementHealth = computed(() => latestRun.value?.summary?.requirement_context_pack?.snapshot?.intelligence?.health_score ?? null);
const linkedRequirementRetries = computed(() => latestRun.value?.summary?.requirement_context_pack?.snapshot?.intelligence?.retry_count ?? 0);
const linkedRequirementUnresolved = computed(
  () => latestRun.value?.summary?.requirement_context_pack?.snapshot?.intelligence?.unresolved_count ?? 0
);
const hasRun = computed(() => Boolean(latestRun.value?.id));
const forkEnabled = computed(() => Boolean(latestRun.value?.id));
const resumeEnabled = computed(() => Boolean(latestRun.value?.id && latestRun.value?.summary?.resume_state?.can_resume));
const operatorConfirmationPaused = computed(() => {
  const run = latestRun.value;
  const status = String(run?.status || "").toUpperCase();
  const reason = String(run?.summary?.operator_confirmation_pause?.reason || "").toLowerCase();
  const failedError = String(run?.summary?.resume_state?.failed_error || "").toLowerCase();
  return status === "PAUSED" && (
    reason === "operator_confirmation_required" || failedError.includes("operator confirmation")
  );
});
const resumeActionEnabled = computed(() => Boolean(latestRun.value?.id) && (resumeEnabled.value || operatorConfirmationPaused.value));
const resumeActionLabel = computed(() => (operatorConfirmationPaused.value ? "Confirm & Resume" : "Resume Run"));
const resumeBlockedReason = computed(() => String(latestRun.value?.summary?.resume_state?.resume_blocked_reason || ""));
const resumeBlockedHint = computed(() => {
  if (operatorConfirmationPaused.value) return "";
  if (resumeEnabled.value || !latestRun.value?.id) return "";
  const reason = resumeBlockedReason.value.toLowerCase();
  if (!reason) return "Run is not resumable yet.";
  if (reason === "run_not_terminal") return "Run is not in a resumable state yet.";
  if (reason === "workspace_error") return "Workspace is in error state. Discard run or replay.";
  if (reason === "active_work_items_present") return "Some work items are still active. Wait for them to settle.";
  if (reason === "no_safe_checkpoint") return "No safe checkpoint available for resume.";
  return reason.replace(/_/g, " ");
});
const compareEnabled = computed(() => runs.value.length >= 2);
const currentStage = computed(() => project.value?.status || "UNKNOWN");
const lifecycleWarnings = computed<string[]>(() => lifecycleScore.value?.warnings || []);
const cancelEnabled = computed(() => ["QUEUED", "RUNNING"].includes(latestRun.value?.status || ""));
const budgetPaused = computed(
  () =>
    String(latestRun.value?.status || "").toUpperCase() === "PAUSED"
    && String(latestRun.value?.summary?.budget_pause?.reason || "").toLowerCase() === "run_budget_exhausted"
);
const manualPushRequired = computed(
  () => Boolean(latestRun.value?.id && latestRun.value?.summary?.delivery_manual_push_required)
);
const budgetWarningHint = computed(() => {
  const budget = latestRun.value?.summary?.execution_contract?.budget || {};
  const remainingTokens = typeof budget.remaining_tokens === "number" ? budget.remaining_tokens : "—";
  const remainingCost = typeof budget.remaining_cost_cents === "number" ? budget.remaining_cost_cents : "—";
  return `Run paused because budget was exhausted. Remaining tokens: ${remainingTokens}. Remaining cost cents: ${remainingCost}.`;
});
const operatorConfirmationHint = computed(() => {
  const failedError = String(latestRun.value?.summary?.resume_state?.failed_error || "").trim();
  return failedError || "Patch execution requires operator confirmation before mutating the repository.";
});
const budgetTelemetry = computed(() => {
  const budget = latestRun.value?.summary?.execution_contract?.budget || {};
  return {
    maxTokens: Number(budget.max_tokens || 0),
    usedTokens: Number(budget.used_tokens || 0),
    remainingTokens: Number(budget.remaining_tokens || 0),
    maxCostCents: Number(budget.max_cost_cents || 0),
    usedCostCents: Number(budget.used_cost_cents || 0),
    remainingCostCents: Number(budget.remaining_cost_cents || 0),
  };
});
const manualPushHint = computed(
  () => String(latestRun.value?.summary?.remote_branch_push_error || "Push failed due to repository credentials or permissions.")
);
const manualPushCommands = computed(() => {
  const repoPath = String(latestRun.value?.repo_path || "<repo_path>");
  const branch = String(latestRun.value?.branch_name || `run/${String(latestRun.value?.id || "").slice(0, 8)}`);
  return `git -C ${repoPath} status\ngit -C ${repoPath} push origin ${branch}`;
});
const latestErrorHint = computed(() => {
  const erroredItem = workItems.value.find((item) => item.last_error);
  if (erroredItem?.last_error) return String(erroredItem.last_error);
  const failedEvent = runEvents.value.find((event) => typeof event.message === "string" && /fail|error/i.test(event.message));
  return failedEvent?.message || "";
});
const internalPolicyBlockHint = computed(() => {
  const latestFailedItem = [...workItems.value]
    .reverse()
    .find((item: any) => String(item?.status || "").toUpperCase() === "FAILED");
  const itemResult = latestFailedItem?.result && typeof latestFailedItem.result === "object" ? latestFailedItem.result : {};
  const itemStopReason = String(itemResult?.stop_reason || "").toLowerCase();
  const itemApprovalRequired = itemResult?.approval_required;
  if (itemStopReason === "human_review_required" && itemApprovalRequired === false) {
    return "Runtime policy blocked this step internally (human_review_required). No manual approval prompt was required, so this can look like silent drift.";
  }

  const latestFailedEvent = [...runEvents.value]
    .reverse()
    .find((event: any) => String(event?.event_type || "").toUpperCase() === "WORK_ITEM_FAILED");
  const payload = latestFailedEvent?.payload && typeof latestFailedEvent.payload === "object" ? latestFailedEvent.payload : {};
  const stopReason = String(payload?.stop_reason || payload?.message || payload?.error || "").toLowerCase();
  const approvalRequired = payload?.approval_required;
  if (stopReason.includes("human_review_required") && approvalRequired === false) {
    return "Runtime policy blocked this step internally (human_review_required). No manual approval prompt was required, so this can look like silent drift.";
  }

  const runCompletedWithFailure = String(latestRun.value?.status || "").toUpperCase() === "COMPLETED"
    && Number(latestTerminalCounts.value.critical_failed || 0) > 0;
  if (runCompletedWithFailure && stopReason.includes("human_review_required")) {
    return "Run finished with degraded completion after internal policy blocks. Check failed work item details before rerun.";
  }
  return "";
});
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
const runSelectorOptions = computed(() =>
  runs.value.map((run) => ({
    id: run.id,
    label: runOptionLabel(run),
  }))
);
const improveReady = computed(() => Boolean(latestRun.value?.id && improveIssueText.value.trim()));
const similarRunMatches = computed(() =>
  (runMemoryResult.value?.matches || []).filter((match: any) => match.run_id !== latestRun.value?.id)
);
const intakeItems = computed(() => missionOverview.value?.work_intake || []);
const visionReady = computed(() => Boolean(projectId.value && visionGoalText.value.trim() && visionScreenshots.value.length));
const recentRunCards = computed(() => missionOverview.value?.recent_runs || []);
const stalledRuns = computed(() => missionOverview.value?.stalled_runs || []);
const recentRunCardsEnhanced = computed(() =>
  recentRunCards.value.map((card: any) => {
    const recoveryCount = Number(card?.recovery_count || 0);
    const status = String(card?.status || "");
    const completedWithRecovery = status === "COMPLETED" && recoveryCount > 0;
    const outcomeStatus = completedWithRecovery ? "COMPLETED_WITH_RECOVERY" : status;
    const outcomeLabel = completedWithRecovery ? "COMPLETED (RECOVERY)" : status;
    let nextActionHint = "";
    if (status === "RUNNING") nextActionHint = "Monitor execution timeline and preview readiness.";
    else if ((status === "FAILED" || status === "CANCELED") && recoveryCount > 0) nextActionHint = "Replay from this run if outcome is incomplete.";
    else if (status === "FAILED" || status === "CANCELED") nextActionHint = "Open logs, then retry failed step or replay the run.";
    else if (status === "COMPLETED" && card?.patch_artifact && !card?.pull_request_url) nextActionHint = "Approve patch and create PR.";
    else if (status === "COMPLETED" && card?.pull_request_url) nextActionHint = "Open PR and merge when ready.";
    const rawGovernance = String(card?.runtime_governance_mode || card?.summary?.runtime_governance_mode || "").trim().toLowerCase();
    const governance = rawGovernance === "stability" || rawGovernance === "governed" ? rawGovernance : "";
    const rawMode = String(card?.repository_state || card?.summary?.repository_state || "").trim().toUpperCase();
    const mode = rawMode === "GENESIS" || rawMode === "EARLY_BUILD" || rawMode === "PRODUCTION_CRITICAL" || rawMode === "ACTIVE_PRODUCT"
      ? rawMode
      : "ACTIVE_PRODUCT";
    const governanceModeLabel = governance === "stability"
      ? "Governance mode: Stability"
      : governance === "governed"
      ? "Governance mode: Governed"
      : mode === "GENESIS"
      ? "Genesis Mode"
      : mode === "EARLY_BUILD"
      ? "Early Build Mode"
      : mode === "PRODUCTION_CRITICAL"
      ? "Production Critical Mode"
      : "Active Product Mode";
    const governanceModeDescription = governance === "stability"
      ? "Prioritizes working app output with safety rails."
      : governance === "governed"
      ? "Strict mutation authority and quality policy enforcement."
      : mode === "GENESIS"
      ? "Broad scaffolding and bootstrap operations are allowed."
      : mode === "EARLY_BUILD"
      ? "Larger bounded mutations are allowed while architecture is evolving."
      : mode === "PRODUCTION_CRITICAL"
      ? "Strict governance and production protections are enforced."
      : "Stricter governance, decomposition, and validation protections are enforced.";
    const governanceModeTag = governance === "stability"
      ? "warning"
      : governance === "governed"
      ? "info"
      : mode === "GENESIS"
      ? "success"
      : mode === "EARLY_BUILD"
      ? "warning"
      : mode === "PRODUCTION_CRITICAL"
      ? "danger"
      : "info";
    return {
      ...card,
      outcome_status: outcomeStatus,
      outcome_label: outcomeLabel,
      next_action_hint: nextActionHint,
      governance_mode: governance || mode,
      governance_mode_label: governanceModeLabel,
      governance_mode_description: governanceModeDescription,
      governance_mode_tag: governanceModeTag,
    };
  })
);
const latestChangeImpact = computed(() => missionOverview.value?.latest_change_impact || null);
const previewsAndPrs = computed(() => missionOverview.value?.previews_and_prs || null);
const deploymentLatest = computed(() => deploymentRows.value[0] || latestDeployment.value || null);
const filteredDeploymentEvents = computed(() => {
  const mode = deploymentEventFilter.value;
  if (mode === "all") return deploymentEvents.value;
  return deploymentEvents.value.filter((evt) => {
    const type = String(evt?.event_type || "").toUpperCase();
    const action = String(evt?.action_type || "").toLowerCase();
    if (mode === "health") {
      return type.includes("HEALTH") || action.includes("health");
    }
    if (mode === "rollback") {
      return type.includes("ROLLBACK") || action.includes("rollback");
    }
    if (mode === "promotion") {
      return type.includes("PROMOTION") || action.includes("promot");
    }
    if (mode === "manual") {
      return type.includes("MANUAL") || action.includes("degraded") || action.includes("manual");
    }
    return true;
  });
});
const deploymentTrustSurface = computed(() => {
  const confidence = Number(
    deploymentLatest.value?.deployment_confidence_score ?? deploymentIntelligence.value?.avg_confidence ?? 0
  );
  const confidencePct = clampPercent(confidence * 100);
  const successRate = Number(deploymentIntelligence.value?.success_rate ?? 1);
  const successPct = clampPercent(successRate * 100);
  const preflightErrors = Array.isArray(deploymentPreflight.value?.errors) ? deploymentPreflight.value.errors : [];
  const topFailures = Array.isArray(deploymentIntelligence.value?.top_failure_clusters)
    ? deploymentIntelligence.value.top_failure_clusters
    : [];
  const manualDegrades = Array.isArray(deploymentIntelligence.value?.recent_manual_degrade_reasons)
    ? deploymentIntelligence.value.recent_manual_degrade_reasons
    : [];
  const blockers: string[] = [
    ...preflightErrors.map((err: any) => String(err)),
    ...topFailures.slice(0, 2).map((row: any) => `${row?.cluster} (${row?.count})`),
    ...(preflightErrors.length || topFailures.length ? [] : manualDegrades.slice(0, 2).map((row: any) => String(row))),
  ];
  const evidence = `${successPct}% deploy success, ${topFailures.length} failure clusters, ${manualDegrades.length} manual degradations`;
  return buildDeploymentTrustSummary({
    confidencePct: deploymentPreflight.value?.ok ? confidencePct : Math.min(confidencePct, 55),
    successPct,
    blockerSignals: blockers,
    evidence,
  });
});
const missionEnvironmentReadiness = computed(() => {
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
  const provider = String(deploymentLatest.value?.provider || "").toLowerCase();
  const hasProvider = provider === "vercel" || provider === "render";
  const hasRepo = Boolean(previewsAndPrs.value?.repo_full_name || previewsAndPrs.value?.repo_url);
  const foundationMissing = deploymentPreflight.value?.errors || [];
  return buildEnvironmentReadiness({
    hasRepo,
    hasDeploymentConnector: hasProvider,
    deploymentProviders: hasProvider ? [provider] : [],
    foundationMissing,
    previewReady: String(previewsAndPrs.value?.preview_status || "").toUpperCase() === "READY",
    deploymentPreflightOk: deploymentPreflight.value?.ok ?? null,
  });
});
const architectureProfile = computed(() => missionOverview.value?.architecture_profile || null);
const projectContract = computed(() => missionOverview.value?.project_contract || null);
const projectContractProfileExists = computed(() => Boolean(projectContract.value?.profile_exists));
const projectContractActionInFlight = computed(
  () =>
    projectContractBootstrapLoading.value
    || projectContractEnforcementLoading.value
    || projectContractStrictLoading.value
);

const architectureDriftFixResult = ref<any | null>(null);
const projectContractEnforcementMode = computed<"off" | "warn" | "strict">(() => {
  const rawMode = String(projectContract.value?.enforcement_mode || "").toLowerCase();
  if (rawMode === "warn" || rawMode === "strict" || rawMode === "off") {
    return rawMode;
  }
  return projectContract.value?.enforcement_enabled ? "warn" : "off";
});
const latestExecutionContract = computed(
  () => missionOverview.value?.latest_execution_contract || executionConsole.value?.summary?.execution_contract || null
);
const frontendTopologyPlan = computed(() => {
  const runSummaryPlan = latestRun.value?.summary?.frontend_topology_plan;
  if (runSummaryPlan && typeof runSummaryPlan === "object") return runSummaryPlan as any;
  const consolePlan = executionConsole.value?.summary?.frontend_topology_plan;
  if (consolePlan && typeof consolePlan === "object") return consolePlan as any;
  const overviewPlan = missionOverview.value?.frontend_topology_plan;
  if (overviewPlan && typeof overviewPlan === "object") return overviewPlan as any;
  return null;
});
const frontendTopologySectionsLabel = computed(() => {
  const rows = Array.isArray(frontendTopologyPlan.value?.sections)
    ? frontendTopologyPlan.value.sections.filter((item: any) => typeof item === "string" && item.trim())
    : [];
  return rows.length ? rows.slice(0, 8).join(" · ") : "—";
});
const frontendTopologyComponentFilesLabel = computed(() => {
  const rows = Array.isArray(frontendTopologyPlan.value?.component_files)
    ? frontendTopologyPlan.value.component_files.filter((item: any) => typeof item === "string" && item.trim())
    : [];
  if (!rows.length) return "—";
  if (rows.length <= 3) return rows.join(" · ");
  return `${rows.slice(0, 3).join(" · ")} · +${rows.length - 3} more`;
});
const previewRunId = computed(
  () => previewsAndPrs.value?.run_id || latestChangeImpact.value?.run_id || latestRun.value?.id || ""
);
const latestCompletedRunId = computed(() => {
  const completed = runs.value
    .filter((run) => String(run?.status || "").toUpperCase() === "COMPLETED")
    .sort((a, b) => timestampScore(b) - timestampScore(a))[0];
  return completed?.id || "";
});
const previewRefreshSuggested = computed(() => {
  const previewUrl = String(previewsAndPrs.value?.preview_url || "");
  const previewSourceRunId = String(previewsAndPrs.value?.run_id || "");
  return Boolean(previewUrl && latestCompletedRunId.value && previewSourceRunId && previewSourceRunId !== latestCompletedRunId.value);
});
const authoritativePreviewDiagnostics = computed<Record<string, any>>(() => {
  const raw = previewsAndPrs.value?.preview_diagnostics;
  if (!raw || typeof raw !== "object") return {};
  const directTerminal = raw.terminal_diagnostics;
  if (directTerminal && typeof directTerminal === "object") {
    return directTerminal as Record<string, any>;
  }
  const runtimeState = raw.preview_runtime_state;
  if (runtimeState && typeof runtimeState === "object" && runtimeState.checks && typeof runtimeState.checks === "object") {
    return runtimeState.checks as Record<string, any>;
  }
  return raw as Record<string, any>;
});
const previewTerminalState = computed<Record<string, any> | null>(() => {
  const raw = previewsAndPrs.value?.preview_diagnostics;
  if (!raw || typeof raw !== "object") return null;
  const terminal = raw.preview_terminal_state;
  if (!terminal || typeof terminal !== "object") return null;
  return terminal as Record<string, any>;
});
const authoritativeVerificationNote = computed<string>(() => {
  const previewStatus = String(previewsAndPrs.value?.preview_status || "").toUpperCase();
  const terminalStatus = String(previewTerminalState.value?.status || "").toUpperCase();
  if (previewStatus === "READY" || terminalStatus === "READY") return "";
  return String(previewsAndPrs.value?.verification_note || "").trim();
});
const previewRepairAvailable = computed(() => {
  const strategy = String(previewsAndPrs.value?.preview_strategy || "").toUpperCase();
  const note = String(authoritativeVerificationNote.value || "").trim();
  return strategy === "VITE_DEV" && Boolean(previewRunId.value) && Boolean(note);
});
const previewPortLabel = computed(() => {
  const explicitFrontendPort = previewsAndPrs.value?.frontend_port;
  const explicitBackendPort = previewsAndPrs.value?.backend_port;
  if (explicitFrontendPort || explicitBackendPort) {
    const frontendLabel = explicitFrontendPort ? `frontend ${explicitFrontendPort}` : null;
    const backendLabel = explicitBackendPort ? `backend ${explicitBackendPort}` : null;
    return [frontendLabel, backendLabel].filter(Boolean).join(" · ");
  }
  const frontendPort = extractPort(previewsAndPrs.value?.frontend_url);
  const backendPort = extractPort(previewsAndPrs.value?.backend_url);
  if (frontendPort || backendPort) {
    const frontendLabel = frontendPort ? `frontend ${frontendPort}` : null;
    const backendLabel = backendPort ? `backend ${backendPort}` : null;
    return [frontendLabel, backendLabel].filter(Boolean).join(" · ");
  }
  return "—";
});
const previewLastHealthCheckLabel = computed(() => {
  const raw =
    previewsAndPrs.value?.last_health_check_at ||
    previewsAndPrs.value?.preview_checked_at ||
    previewsAndPrs.value?.verified_at ||
    previewsAndPrs.value?.updated_at;
  return raw ? formatTimestamp(raw) : "—";
});
const strategyLearning = computed(() => missionOverview.value?.strategy_learning || []);
const systemInsights = computed(() => missionOverview.value?.system_insights || null);
const violationInsights = computed(() => missionOverview.value?.violation_insights || null);
const importedReferences = computed(() => missionOverview.value?.imported_references || []);
const latestArtifactApproval = computed(() => createPrApprovals.value[0] || null);
const latestArtifactApprovalStatus = computed(() => latestArtifactApproval.value?.status || null);
const createPrChangeSummary = computed(() => {
  const run = selectedPrRunId.value ? findRunById(selectedPrRunId.value) : latestRun.value;
  const summary = run?.summary || {};
  const diffPreview = createPrDiffPreview.value;
  const fileCount = Number(diffPreview?.file_count || 0);
  const additions = Number(diffPreview?.additions || 0);
  const deletions = Number(diffPreview?.deletions || 0);
  const files = Array.isArray(diffPreview?.files) ? diffPreview.files : [];
  const taskTitle = String(summary?.task_title || "").trim();
  const goal = String(summary?.goal || "").trim();
  const diffSummary = String(summary?.diff_summary || "").trim();
  if (!taskTitle && !goal && !diffSummary && !fileCount && !files.length) return null;
  const touchedFiles = files
    .map((file: any) => String(file?.path || "").trim())
    .filter(Boolean);
  const scopeLabel = touchedFiles.length
    ? touchedFiles.join(", ")
    : diffSummary || "Patch scoped to selected artifact.";
  const risk = fileCount <= 1 ? "Low (small focused patch)." : "Medium (multi-file patch; review carefully).";
  return {
    title: taskTitle || "Patch update",
    goal,
    scope: scopeLabel,
    filesTouched: fileCount || touchedFiles.length || 0,
    diff: `+${additions} / -${deletions}`,
    risk,
  };
});
const createPrBlockingReason = computed(() => {
  if (!selectedPrArtifact.value) return "Select a patch artifact before creating a pull request.";
  if (latestArtifactApprovalStatus.value !== "APPROVED") {
    return "Approve this patch before creating a pull request.";
  }
  const provider = String(previewsAndPrs.value?.provider || "").toLowerCase();
  if (provider === "github") {
    const env = executionConsole.value?.environment;
    if (!env?.github_app_id_present || !env?.github_private_key_present) {
      return "GitHub App integration is not configured. Set GITHUB_APP_ID and GITHUB_PRIVATE_KEY in API runtime env.";
    }
  }
  return "";
});
const createPrReady = computed(
  () => Boolean(selectedPrArtifact.value) && latestArtifactApprovalStatus.value === "APPROVED" && !createPrBlockingReason.value
);
const createPrRemediationHint = computed(() => {
  const message = String(createPrError.value || "").toLowerCase();
  if (!message) return "";
  if (message.includes("github app installation is required")) {
    return "Reconnect this repository using GitHub App strategy, then retry Create PR.";
  }
  if (message.includes("git clone auth strategy")) {
    return "Switch repository auth strategy to GitHub App in Connect Repository, save, and rerun Test Clone.";
  }
  if (message.includes("permission") || message.includes("forbidden") || message.includes("403")) {
    return "GitHub permissions are insufficient. Verify app installation access and repository write scope.";
  }
  if (
    message.includes("dns")
    || message.includes("network")
    || message.includes("timed out")
    || message.includes("connection refused")
    || message.includes("temporarily unavailable")
  ) {
    return "Network/connectivity issue detected. Verify internet stability, then retry Create PR.";
  }
  if (message.includes("already exists") || message.includes("422") || message.includes("conflict")) {
    return "Branch or PR may already exist. Use a new branch name or open the existing PR from GitHub.";
  }
  if (message.includes("no repository changes available")) {
    return "No diff remains to open a PR. Refresh preview/diff and ensure a patch artifact is selected.";
  }
  return "Open PR Flow checks: repository connected, patch approved, and GitHub app access still valid.";
});
const comparisonHeadlineLines = computed(() => {
  const result = compareResult.value;
  if (!result) return [];
  const lines: string[] = [];
  if (result.summary.faster_run_id && typeof result.summary.faster_by_seconds === "number") {
    const fasterLabel = comparisonSummaryLabel(result.summary.faster_run_id);
    const slower =
      result.summary.faster_run_id === result.run_a.id ? result.run_b : result.run_a;
    const pct =
      typeof slower.elapsed_seconds === "number" && slower.elapsed_seconds > 0
        ? Math.round((result.summary.faster_by_seconds / slower.elapsed_seconds) * 100)
        : null;
    lines.push(
      pct !== null
        ? `${fasterLabel} was ${pct}% faster.`
        : `${fasterLabel} finished ${formatElapsed(result.summary.faster_by_seconds)} sooner.`
    );
  }
  if (result.run_a.recovery_count !== result.run_b.recovery_count) {
    const lower =
      result.run_a.recovery_count < result.run_b.recovery_count
        ? { label: "Run A", count: result.run_b.recovery_count - result.run_a.recovery_count }
        : { label: "Run B", count: result.run_a.recovery_count - result.run_b.recovery_count };
    lines.push(`${lower.label} needed ${lower.count} fewer recovery ${lower.count === 1 ? "step" : "steps"}.`);
  }
  if (result.summary.pull_request_run_id) {
    lines.push(`${comparisonSummaryLabel(result.summary.pull_request_run_id)} produced the PR-ready result.`);
  }
  const fileDelta = Math.abs(result.run_a.files_changed.length - result.run_b.files_changed.length);
  if (fileDelta > 0) {
    const label = result.run_a.files_changed.length > result.run_b.files_changed.length ? "Run A" : "Run B";
    lines.push(`${label} changed ${fileDelta} more file${fileDelta === 1 ? "" : "s"}.`);
  }
  return lines;
});
const coveragePercent = computed(() => {
  const ratio = lifecycleScore.value?.coverage?.coverage_ratio;
  return typeof ratio === "number" ? `${Math.round(ratio * 100)}%` : "—";
});
const healthTone = computed<"neutral" | "success" | "warning" | "danger">(() => {
  const risk = String(lifecycleScore.value?.risk_level || "").toUpperCase();
  if (risk === "HIGH") return "danger";
  if (risk === "MEDIUM" || risk === "MODERATE") return "warning";
  if (risk === "LOW") return "success";
  return "neutral";
});
const healthTagType = computed(() => (healthTone.value === "neutral" ? "info" : healthTone.value));
const runStatusTone = computed<"neutral" | "success" | "warning" | "danger">(() => {
  const status = String(latestRun.value?.status || "").toUpperCase();
  if (status === "FAILED" || status === "CANCELED") return "danger";
  if (status === "RUNNING" || status === "QUEUED" || status === "CLAIMED") return "warning";
  if (status === "COMPLETED" || status === "DONE") return "success";
  return "neutral";
});

let pollHandle: ReturnType<typeof setTimeout> | null = null;
let pollDelayMs: number | null = null;
let pollInFlight = false;

const displayWorkItems = computed(() =>
  workItems.value.map((wi) => {
    const payload = wi.payload || {};
    return {
      task_id: wi.id,
      run_id: wi.run_id || latestRun.value?.id || null,
      title: payload.title || WORK_ITEM_LABELS[wi.type] || humanizeToken(wi.key || wi.type || "work_item"),
      agent: payload.agent || WORK_ITEM_LABELS[wi.type] || humanizeToken(wi.type || wi.executor || "agent"),
      executor: wi.executor,
      source_surface: payload.source_surface || payload.source || "mission_control",
      status: normalizeTimelineStatus(wi.status),
      rawStatus: wi.status,
      blocking: payload.blocking !== false,
      depends_on: Array.isArray(payload.depends_on) ? payload.depends_on : [],
      depends_on_count: wi.depends_on_count || 0,
      outputs: Array.isArray(payload.outputs) ? payload.outputs : [],
      parallel_group: payload.parallel_group || null,
      started_at: wi.started_at,
      finished_at: wi.finished_at,
      last_error: wi.last_error,
      work_item_type: wi.type,
    };
  })
);

function normalizeWorkItemTitleKey(title: string) {
  return String(title || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

const displayWorkItemsDeduped = computed(() => {
  const deduped: Array<any> = [];
  const byKey = new Map<string, number>();
  displayWorkItems.value.forEach((item) => {
    const key = `${item.work_item_type || ""}::${normalizeWorkItemTitleKey(item.title)}`;
    const existingIndex = byKey.get(key);
    if (existingIndex === undefined) {
      deduped.push({ ...item, attempt_count: 1 });
      byKey.set(key, deduped.length - 1);
      return;
    }
    const existing = deduped[existingIndex];
    deduped[existingIndex] = {
      ...existing,
      ...item,
      attempt_count: (existing.attempt_count || 1) + 1,
      title: existing.title,
    };
  });
  return deduped;
});

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
  displayWorkItemsDeduped.value.map((item) => ({
    name: item.title,
    status: panelStatusFor(item.rawStatus, item.blocking, latestRun.value?.status),
    taskCount: item.attempt_count || 1,
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
    blocked: 0,
    warnings: 0,
    canceled: 0,
  };
  displayWorkItemsDeduped.value.forEach((wi) => {
    if (wi.status === "QUEUED") counts.queued += 1;
    else if (wi.status === "CLAIMED" || wi.status === "RUNNING") counts.running += 1;
    else if (wi.status === "DONE") counts.done += 1;
    else if (wi.status === "FAILED" && wi.blocking === false) counts.warnings += 1;
    else if (wi.status === "FAILED") counts.blocked += 1;
    else if (wi.status === "CANCELED") counts.canceled += 1;
  });
  return counts;
});

const latestArtifacts = computed(() => {
  if (!latestRun.value?.id) return [];
  return artifacts.value.filter((artifact) => artifact.run_id === latestRun.value.id);
});
const latestPatchArtifact = computed(() => {
  if (latestChangeImpact.value?.patch_artifact) return latestChangeImpact.value.patch_artifact;
  if (previewsAndPrs.value?.patch_artifact) return previewsAndPrs.value.patch_artifact;
  return latestArtifacts.value.find((artifact) => artifact.type === "git_diff") || null;
});
const planStepCounts = computed(() => {
  const steps = Array.isArray(runNarrative.value?.plan?.steps) ? runNarrative.value.plan.steps : [];
  return {
    total: steps.length,
    done: steps.filter((step: any) => step.status === "DONE").length,
    active: steps.filter((step: any) => ["RUNNING", "CLAIMED"].includes(step.status)).length,
    queued: steps.filter((step: any) => step.status === "QUEUED").length,
  };
});
const taskDecompositionCounts = computed(() => {
  const subtasks = Array.isArray(runNarrative.value?.task_decomposition?.subtasks)
    ? runNarrative.value.task_decomposition.subtasks
    : [];
  return {
    total: subtasks.length,
    done: subtasks.filter((step: any) => step.status === "DONE").length,
    active: subtasks.filter((step: any) => ["RUNNING", "CLAIMED"].includes(step.status)).length,
    queued: subtasks.filter((step: any) => step.status === "QUEUED").length,
  };
});
const recentNarrativeReflections = computed(() =>
  Array.isArray(runNarrative.value?.reflections) ? runNarrative.value.reflections.slice(-4).reverse() : []
);
const reflectionsDisplay = computed(() =>
  reflectionsExpanded.value
    ? recentNarrativeReflections.value
    : recentNarrativeReflections.value.slice(0, reflectionsCollapsedCount)
);
const similarRunsDisplay = computed(() =>
  similarExpanded.value
    ? similarRunMatches.value
    : similarRunMatches.value.slice(0, similarCollapsedCount)
);
const reviewSurfaceFiles = computed(() => {
  if (Array.isArray(latestChangeImpact.value?.files_changed) && latestChangeImpact.value.files_changed.length) {
    return latestChangeImpact.value.files_changed;
  }
  if (Array.isArray(createPrDiffPreview.value?.files) && createPrDiffPreview.value.files.length) {
    return createPrDiffPreview.value.files.map((file: any) => file.path);
  }
  return [];
});
const reviewSurfaceAdditions = computed(() => {
  if (typeof latestChangeImpact.value?.additions === "number") return latestChangeImpact.value.additions;
  return typeof createPrDiffPreview.value?.additions === "number" ? createPrDiffPreview.value.additions : 0;
});
const reviewSurfaceDeletions = computed(() => {
  if (typeof latestChangeImpact.value?.deletions === "number") return latestChangeImpact.value.deletions;
  return typeof createPrDiffPreview.value?.deletions === "number" ? createPrDiffPreview.value.deletions : 0;
});
const reviewSurfaceApprovalStatus = computed(
  () => latestArtifactApprovalStatus.value || previewsAndPrs.value?.approval_status || null
);
const reviewSurfaceApprovalNote = computed(
  () => latestArtifactApproval.value?.comment || createPrApprovalError.value || null
);
const reviewSurfacePullRequestUrl = computed(
  () => createPrResult.value?.pull_request_url || previewsAndPrs.value?.pull_request_url || null
);
const primaryActionCard = computed(() => {
  const runStatus = String(latestRun.value?.status || "");
  const previewUrl = String(previewsAndPrs.value?.preview_url || "");
  const prUrl = String(previewsAndPrs.value?.pull_request_url || "");
  const hasPatch = Boolean(previewsAndPrs.value?.patch_artifact || latestPatchArtifact.value);
  const approved = String(previewsAndPrs.value?.approval_status || latestArtifactApprovalStatus.value || "") === "APPROVED";

  if (runStatus === "RUNNING") {
    return {
      kind: "monitor",
      title: "Run is in progress",
      description: "Track live steps and open preview once ready.",
      badge: "RUNNING",
      tone: "warning",
      buttonLabel: "Open Timeline",
      buttonType: "warning",
    };
  }
  if (prUrl) {
    return {
      kind: "open-pr",
      title: "Pull request is ready",
      description: "Review the PR and merge when checks and preview look good.",
      badge: "DELIVERY",
      tone: "success",
      buttonLabel: "Open PR",
      buttonType: "success",
      href: prUrl,
    };
  }
  if (approved && hasPatch) {
    return {
      kind: "create-pr",
      title: "Patch approved, ready for PR",
      description: "Create a pull request from the approved patch artifact.",
      badge: "READY",
      tone: "success",
      buttonLabel: "Create PR",
      buttonType: "primary",
    };
  }
  if (previewUrl) {
    return {
      kind: "open-preview",
      title: "Preview is ready",
      description: "Validate UX and behavior in preview before PR creation.",
      badge: "PREVIEW",
      tone: "info",
      buttonLabel: "Open Preview",
      buttonType: "primary",
      href: previewUrl,
    };
  }
  if (runStatus === "FAILED" || runStatus === "CANCELED") {
    return {
      kind: "replay",
      title: "Run needs recovery",
      description: "Replay the run or retry the failed step from latest artifacts.",
      badge: "NEEDS ACTION",
      tone: "danger",
      buttonLabel: "Replay Run",
      buttonType: "danger",
    };
  }
  if (runStatus === "COMPLETED" && hasPatch) {
    return {
      kind: "approve-patch",
      title: "Patch ready for review",
      description: "Review diff and approve the artifact to enable PR creation.",
      badge: "REVIEW",
      tone: "info",
      buttonLabel: "Open Diff",
      buttonType: "primary",
    };
  }
  return null;
});

function findRunById(runId: string) {
  return runs.value.find((run) => run.id === runId) || null;
}

const latestLogMessageByTask = computed(() => {
  const map = new Map<string, string>();
  for (const log of timelineLogs.value) {
    const taskId = log.details?.task_id;
    if (typeof taskId === "string" && taskId && typeof log.message === "string" && log.message.trim()) {
      map.set(taskId, log.message.trim());
    }
  }
  return map;
});
const latestStrategyByTask = computed(() => {
  const map = new Map<
    string,
    {
      selected_strategy?: string | null;
      effective_strategy?: string | null;
      transition_reason?: string | null;
      drift_risk_score?: number | null;
      execution_zone?: string | null;
    }
  >();
  for (const log of timelineLogs.value) {
    const taskId = log.details?.task_id;
    if (typeof taskId !== "string" || !taskId) continue;
    const details = log.details || {};
    const selected = typeof details.selected_strategy === "string" ? details.selected_strategy : null;
    const effective = typeof details.effective_strategy === "string" ? details.effective_strategy : null;
    const transition = typeof details.transition_reason === "string" ? details.transition_reason : null;
    const zone = typeof details.execution_zone === "string" ? details.execution_zone : null;
    const driftRaw = details.drift_risk_score;
    const drift = typeof driftRaw === "number" ? driftRaw : Number.isFinite(Number(driftRaw)) ? Number(driftRaw) : null;
    if (selected || effective || transition || zone || drift !== null) {
      map.set(taskId, {
        selected_strategy: selected,
        effective_strategy: effective,
        transition_reason: transition,
        drift_risk_score: drift,
        execution_zone: zone,
      });
    }
  }
  return map;
});
const workbenchTasks = computed(() =>
  displayWorkItemsDeduped.value.map((item) => {
    const relatedArtifacts = latestArtifacts.value
      .filter((artifact) => artifact.work_item_id === item.task_id)
      .map((artifact) => (artifact.type === "git_diff" ? "patch.diff" : shortenUri(artifact.uri)))
      .slice(0, 3);
    return {
      id: item.task_id,
      title: item.title,
      rawStatus: item.rawStatus,
      blocking: item.blocking,
      agent: item.agent,
      executor: item.executor,
      workItemType: item.work_item_type,
      progress: workbenchProgressForStatus(item.rawStatus),
      logLine:
        item.last_error ||
        latestLogMessageByTask.value.get(item.task_id) ||
        workbenchStatusMessage(item.rawStatus, item.blocking),
      changedArtifacts: relatedArtifacts,
      startedAt: item.started_at || null,
      finishedAt: item.finished_at || null,
      startedAtLabel: item.started_at ? `Started ${formatTimestamp(item.started_at)}` : "Not started",
      finishedAtLabel: item.finished_at ? `Finished ${formatTimestamp(item.finished_at)}` : "Awaiting completion",
      selectedStrategy: latestStrategyByTask.value.get(item.task_id)?.selected_strategy || null,
      effectiveStrategy: latestStrategyByTask.value.get(item.task_id)?.effective_strategy || null,
      transitionReason: latestStrategyByTask.value.get(item.task_id)?.transition_reason || null,
      driftRiskScore: latestStrategyByTask.value.get(item.task_id)?.drift_risk_score ?? null,
      executionZone: latestStrategyByTask.value.get(item.task_id)?.execution_zone || null,
    };
  })
);
const missionStatusBanner = computed(() => {
  const inProgressTask = workbenchTasks.value.find((task) => ["RUNNING", "CLAIMED"].includes(String(task.rawStatus || "").toUpperCase()));
  return {
    queue: runtimeCounts.value.queued,
    inProgress: runtimeCounts.value.running,
    completed: runtimeCounts.value.done,
    total: workbenchTasks.value.length,
    inProgressTaskName: inProgressTask?.title || "None",
  };
});
const etaProfilesByType = computed(() => {
  const map = new Map<string, number>();
  for (const item of missionOverview.value?.eta_profiles || []) {
    const key = String(item?.work_item_type || "").toUpperCase();
    const median = Number(item?.median_seconds || 0);
    if (key && Number.isFinite(median) && median > 0) {
      map.set(key, Math.max(15, Math.round(median)));
    }
  }
  return map;
});
const runEtaSeconds = computed(() => {
  const nowMs = Date.now();
  let total = 0;
  for (const task of workbenchTasks.value) {
    const status = String(task.rawStatus || "").toUpperCase();
    if (status === "DONE" || status === "FAILED") continue;
    const baseline = baselineSecondsForType(task.workItemType);
    if (status === "QUEUED") {
      total += baseline;
      continue;
    }
    if (status === "RUNNING" || status === "CLAIMED") {
      const startedMs = task.startedAt ? Date.parse(task.startedAt) : NaN;
      if (Number.isFinite(startedMs)) {
        const elapsed = Math.max(0, Math.floor((nowMs - startedMs) / 1000));
        total += Math.max(15, baseline - elapsed);
      } else {
        total += baseline;
      }
    }
  }
  return Math.max(0, Math.round(total));
});
const runEtaLabel = computed(() => {
  const status = String(latestRun.value?.status || "").toUpperCase();
  if (!hasRun.value) return "—";
  if (status === "DONE" || status === "SUCCEEDED" || status === "COMPLETED") {
    return formatElapsed(latestRun.value?.elapsed_seconds);
  }
  if (status === "FAILED" || status === "CANCELED") return "Run ended";
  const seconds = runEtaSeconds.value;
  if (seconds <= 0) return "Finishing soon";
  return `~${formatElapsed(seconds)} remaining`;
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

watch(densityMode, (mode) => {
  try {
    window.localStorage.setItem(DENSITY_STORAGE_KEY, mode);
  } catch {
    // Ignore storage failures; preference stays in-memory.
  }
});

onMounted(() => {
  try {
    const savedDensity = window.localStorage.getItem(DENSITY_STORAGE_KEY);
    if (savedDensity === "compact" || savedDensity === "comfortable") {
      densityMode.value = savedDensity;
    }
  } catch {
    // Ignore storage failures and keep default.
  }
  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", syncPolling);
  }
  window.addEventListener("agentic:tenant-changed", handleTenantChanged as EventListener);
});

onBeforeUnmount(() => {
  if (typeof document !== "undefined") {
    document.removeEventListener("visibilitychange", syncPolling);
  }
  window.removeEventListener("agentic:tenant-changed", handleTenantChanged as EventListener);
  stopPolling();
});

function handleTenantChanged() {
  resetState();
  if (!getActiveTenantId()) {
    void router.replace({
      path: "/",
      query: { tenantRequired: "1", requestedProject: projectId.value || undefined },
    });
  }
}

function resetState() {
  stopPolling();
  project.value = null;
  health.value = null;
  lifecycleScore.value = null;
  missionOverview.value = null;
  runs.value = [];
  workItems.value = [];
  runEvents.value = [];
  artifacts.value = [];
  executionConsole.value = null;
  error.value = "";
  overviewError.value = "";
  artifactError.value = "";
  artifactDialogOpen.value = false;
  artifactExplainLoading.value = false;
  artifactExplainError.value = "";
  artifactExplainResult.value = null;
  diffDialogOpen.value = false;
  diffLoading.value = false;
  diffError.value = "";
  diffResult.value = null;
  selectedDiffArtifact.value = null;
  createPrDialogOpen.value = false;
  createPrLoading.value = false;
  createPrError.value = "";
  createPrResult.value = null;
  selectedPrArtifact.value = null;
  createPrTitle.value = "";
  createPrBody.value = "";
  createPrBranch.value = "";
  createPrDiffLoading.value = false;
  createPrDiffError.value = "";
  createPrDiffPreview.value = null;
  createPrApprovalLoading.value = false;
  createPrApprovalError.value = "";
  createPrApprovalComment.value = "";
  createPrApprovals.value = [];
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
  strategyDialogOpen.value = false;
  strategyLoading.value = false;
  strategyRefreshing.value = false;
  strategyErrorMessage.value = "";
  strategyResult.value = null;
  strategyGoal.value = "";
  strategyErrorText.value = "";
  strategyFilesInput.value = "";
  strategyStartNow.value = true;
  strategyLimit.value = 3;
  strategyExecutor.value = "";
  improveDialogOpen.value = false;
  improveLoading.value = false;
  improveError.value = "";
  improveSuccessMessage.value = "";
  improveIssueText.value = "";
  improveFilesInput.value = "";
  improveStartNow.value = true;
  improveExecutor.value = "";
  runMemoryLoading.value = false;
  runMemoryError.value = "";
  runMemoryResult.value = null;
  intakeRunLoadingId.value = "";
  visionGoalText.value = "";
  visionAutoStart.value = true;
  visionAutoDeploy.value = false;
  visionSubmitting.value = false;
  visionScreenshots.value = [];
  replayDialogOpen.value = false;
  replayLoading.value = false;
  replayError.value = "";
  replayResult.value = null;
  replayRunId.value = "";
  resumeLoading.value = false;
  runNarrativeLoading.value = false;
  runNarrativeError.value = "";
  runNarrative.value = null;
  projectContractBootstrapLoading.value = false;
  projectContractEnforcementLoading.value = false;
  projectContractStrictLoading.value = false;
  projectContractActionError.value = "";
  latestDeployment.value = null;
  deploymentRows.value = [];
  deploymentEvents.value = [];
  deploymentOpsLoading.value = false;
  deploymentOpsError.value = "";
  deploymentPreflight.value = null;
  deploymentIntelligence.value = null;
  deploymentReadinessContract.value = null;
  deploymentEventDialogOpen.value = false;
  selectedDeploymentEvent.value = null;
  deploymentEventFilter.value = "all";
  pinnedRunId.value = "";
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

function normalizePinnedRunSelection() {
  if (!pinnedRunId.value) return;
  if (!runs.value.some((run) => run?.id === pinnedRunId.value)) {
    pinnedRunId.value = "";
  }
}

async function onPinnedRunChange() {
  await loadRunRuntime();
  void loadSimilarRuns();
  void loadMemoryTimeline();
  syncContext();
  syncPolling();
}

async function loadAll() {
  if (!projectId.value.trim()) {
    error.value = "Project ID is required.";
    return;
  }
  error.value = "";
  overviewError.value = "";
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
    runs.value = canonicalizeRuns(runList);
    normalizePinnedRunSelection();
    await loadRunRuntime();
    // Load heavier surfaces in background to avoid blocking the first render.
    void loadSimilarRuns();
    void loadMissionOverview();
    void loadMemoryTimeline();
    void loadDeploymentOps();
    syncContext();
    syncPolling();
  } catch (err: any) {
    error.value = err?.message || "Failed to load Mission Control data.";
  } finally {
    loading.value = false;
  }
}

async function loadMissionOverview() {
  if (!projectId.value) {
    missionOverview.value = null;
    return;
  }
  try {
    missionOverview.value = await fetchMissionControlOverview(projectId.value, { includeHeavy: true });
    overviewError.value = "";
    previewLaunchError.value = "";
  } catch (err: any) {
    // Keep the last successful payload rendered to avoid full-card flicker.
    overviewError.value = err?.message || "Failed to load Mission Control overview.";
  }
}

async function refreshOverviewSurface() {
  if (!projectId.value.trim()) return;
  runs.value = canonicalizeRuns(await listRuns(projectId.value));
  normalizePinnedRunSelection();
  void loadMissionOverview();
  syncContext();
  syncPolling();
}

async function loadMemoryTimeline() {
  if (!projectId.value) {
    memoryTimeline.value = [];
    return;
  }
  memoryTimelineLoading.value = true;
  memoryTimelineError.value = "";
  try {
    const payload = await fetchProjectMemoryTimeline(projectId.value, {
      limit: 40,
      run_id: latestRun.value?.id || undefined,
    });
    memoryTimeline.value = Array.isArray(payload?.items) ? payload.items : [];
  } catch (err: any) {
    memoryTimeline.value = [];
    memoryTimelineError.value = err?.message || "Failed to load memory timeline.";
  } finally {
    memoryTimelineLoading.value = false;
  }
}

async function bootstrapProjectContractFromMissionControl() {
  if (!projectId.value) return;
  projectContractBootstrapLoading.value = true;
  projectContractActionError.value = "";
  try {
    await bootstrapProjectContract(projectId.value, {
      created_by: "ui-user",
    });
    void loadMissionOverview();
    ElMessage.success("Project contract initialized.");
  } catch (err: any) {
    projectContractActionError.value = err?.message || "Failed to initialize project contract.";
  } finally {
    projectContractBootstrapLoading.value = false;
  }
}

async function fixArchitectureDriftAndOpenPr() {
  if (!projectId.value) return;
  architectureDriftFixLoading.value = true;
  architectureDriftFixError.value = "";
  try {
    const result = await applyArchitectureDriftFixAndOpenPr(projectId.value, { updated_by: "ui-user" });
    architectureDriftFixResult.value = result;
    await loadMissionOverview();
    const prUrl = String(result?.pr_url || "").trim();
    if (prUrl) {
      ElMessage.success("Architecture drift fixed and PR opened.");
    } else {
      ElMessage.success("Architecture drift fixed. No PR opened because no repository changes were detected.");
    }
  } catch (err: any) {
    architectureDriftFixError.value = err?.message || "Failed to fix architecture drift and open PR.";
  } finally {
    architectureDriftFixLoading.value = false;
  }
}

async function enableProjectContractEnforcement() {
  if (!projectId.value) return;
  projectContractEnforcementLoading.value = true;
  projectContractActionError.value = "";
  const shouldBootstrap = !projectContractProfileExists.value;
  try {
    if (shouldBootstrap) {
      await bootstrapProjectContract(projectId.value, {
        created_by: "ui-user",
      });
    }
    await patchProjectContract(projectId.value, {
      sections: {
        enforcement: {
          enabled: true,
          mode: "warn",
          disallow_inline_styles: true,
          enforce_color_tokens: true,
          require_known_css_variables: false,
        },
        design_system: {
          rules: {
            enabled: true,
            mode: "warn",
            disallow_inline_styles: true,
            enforce_color_tokens: true,
            require_known_css_variables: false,
          },
        },
      },
      updated_by: "ui-user",
    });
    void loadMissionOverview();
    ElMessage.success(
      shouldBootstrap
        ? "Project contract initialized and WARN enforcement enabled."
        : "Project contract WARN enforcement enabled."
    );
  } catch (err: any) {
    projectContractActionError.value = err?.message || "Failed to enable project contract enforcement.";
  } finally {
    projectContractEnforcementLoading.value = false;
  }
}

async function upgradeProjectContractEnforcementToStrict() {
  if (!projectId.value) return;
  projectContractStrictLoading.value = true;
  projectContractActionError.value = "";
  const shouldBootstrap = !projectContractProfileExists.value;
  try {
    if (shouldBootstrap) {
      await bootstrapProjectContract(projectId.value, {
        created_by: "ui-user",
      });
    }
    await patchProjectContract(projectId.value, {
      sections: {
        enforcement: {
          enabled: true,
          mode: "strict",
          disallow_inline_styles: true,
          enforce_color_tokens: true,
          require_known_css_variables: true,
        },
        design_system: {
          rules: {
            enabled: true,
            mode: "strict",
            disallow_inline_styles: true,
            enforce_color_tokens: true,
            require_known_css_variables: true,
          },
        },
      },
      updated_by: "ui-user",
    });
    void loadMissionOverview();
    ElMessage.success(
      shouldBootstrap
        ? "Project contract initialized and STRICT enforcement enabled."
        : "Project contract upgraded to STRICT enforcement."
    );
  } catch (err: any) {
    projectContractActionError.value = err?.message || "Failed to upgrade enforcement to strict mode.";
  } finally {
    projectContractStrictLoading.value = false;
  }
}

async function startPreviewLaunch() {
  if (!previewRunId.value) return;
  previewLaunchLoading.value = true;
  previewLaunchError.value = "";
  previewLaunchInfo.value = "";
  try {
    const currentStatus = String(previewsAndPrs.value?.preview_status || "").toUpperCase();
    const shouldReuse = currentStatus === "READY";
    await launchRunPreview(previewRunId.value, { reuse_if_healthy: shouldReuse });
    void loadMissionOverview();
  } catch (err: any) {
    previewLaunchError.value = err?.message || "Failed to launch preview.";
  } finally {
    previewLaunchLoading.value = false;
  }
}

async function stopPreviewLaunch() {
  if (!previewRunId.value) return;
  previewLaunchLoading.value = true;
  previewLaunchError.value = "";
  previewLaunchInfo.value = "";
  try {
    await deleteRunPreview(previewRunId.value);
    void loadMissionOverview();
  } catch (err: any) {
    previewLaunchError.value = err?.message || "Failed to stop preview.";
  } finally {
    previewLaunchLoading.value = false;
  }
}

async function restartPreviewLaunch() {
  if (!previewRunId.value) return;
  previewLaunchLoading.value = true;
  previewLaunchError.value = "";
  previewLaunchInfo.value = "Restarting preview (stop + fresh launch)…";
  try {
    try {
      await deleteRunPreview(previewRunId.value);
    } catch {
      // stale/missing process state should not block a fresh launch
    }
    await launchRunPreview(previewRunId.value, { reuse_if_healthy: false });
    await refreshPreviewStateUntilSettled();
    await refreshOverviewSurface();
    const status = String(previewsAndPrs.value?.preview_status || "").toUpperCase();
    previewLaunchInfo.value = status === "READY"
      ? "Preview restarted and healthy."
      : `Preview restart finished with status ${status || "UNKNOWN"}.`;
  } catch (err: any) {
    previewLaunchError.value = err?.message || "Failed to restart preview.";
    previewLaunchInfo.value = "";
  } finally {
    previewLaunchLoading.value = false;
  }
}

async function refreshPreviewToLatestRun() {
  if (!latestCompletedRunId.value) return;
  previewLaunchLoading.value = true;
  previewLaunchError.value = "";
  previewLaunchInfo.value = `Refreshing preview for run ${shortRunId(latestCompletedRunId.value)}…`;
  try {
    await launchRunPreview(latestCompletedRunId.value, { reuse_if_healthy: false });
    await refreshOverviewSurface();
    previewLaunchInfo.value = "Preview switched to latest run.";
  } catch (err: any) {
    previewLaunchError.value = err?.message || "Failed to refresh preview to latest run.";
    previewLaunchInfo.value = "";
  } finally {
    previewLaunchLoading.value = false;
  }
}

async function restartPreviewToLatestRun() {
  if (!latestCompletedRunId.value) return;
  previewLaunchLoading.value = true;
  previewLaunchError.value = "";
  previewLaunchInfo.value = `Restarting preview for run ${shortRunId(latestCompletedRunId.value)}…`;
  try {
    try {
      await deleteRunPreview(latestCompletedRunId.value);
    } catch {
      // stale/missing state should not block restart
    }
    await launchRunPreview(latestCompletedRunId.value, { reuse_if_healthy: false });
    await refreshOverviewSurface();
    previewLaunchInfo.value = "Latest run preview restarted.";
  } catch (err: any) {
    previewLaunchError.value = err?.message || "Failed to restart latest run preview.";
    previewLaunchInfo.value = "";
  } finally {
    previewLaunchLoading.value = false;
  }
}

async function runPreviewRepair(repairAction: string, message: string) {
  if (!previewRunId.value) return;
  previewLaunchLoading.value = true;
  previewLaunchError.value = "";
  previewLaunchInfo.value = message;
  try {
    await launchRunPreview(previewRunId.value, {
      reuse_if_healthy: false,
      repair_action: repairAction,
    });
    await refreshPreviewStateUntilSettled();
    await refreshOverviewSurface();
    previewLaunchInfo.value = "Preview repair completed.";
  } catch (err: any) {
    previewLaunchError.value = err?.message || "Failed to repair preview.";
    previewLaunchInfo.value = "";
  } finally {
    previewLaunchLoading.value = false;
  }
}

async function repairPreviewRoot() {
  await runPreviewRepair("repair_frontend_root", "Repairing preview root mapping…");
}

async function repairPreviewEntrypoint() {
  await runPreviewRepair("repair_frontend_entrypoint", "Repairing frontend entrypoint…");
}

async function refreshPreviewStateUntilSettled() {
  const maxPolls = 8;
  for (let i = 0; i < maxPolls; i += 1) {
    // Avoid sequentially stalling the loop on expensive overview calls.
    await loadMissionOverview();
    const status = String(previewsAndPrs.value?.preview_status || "").toUpperCase();
    if (status === "READY" || status === "FAILED" || status === "STOPPED" || status === "EXPIRED") return;
    await sleep(800);
  }
}

async function deployLatestRun(provider: "vercel" | "render" = "vercel") {
  if (!projectId.value) return;
  deployLoading.value = true;
  deployError.value = "";
  deployInfo.value = "";
  try {
    const requestKey = getOrCreateActionRequestKey(
      "create_deployment",
      `mission_control:deploy:${provider}:${projectId.value}:${previewRunId.value || latestRun.value?.id || "project"}`
    );
    const deployment = await createProjectDeployment(projectId.value, {
      provider,
      target: "user_app",
      run_id: previewRunId.value || latestRun.value?.id || null,
      request_key: requestKey,
      repository_url: previewsAndPrs.value?.repo_url || undefined,
      repository_full_name: previewsAndPrs.value?.repo_full_name || undefined,
      branch_name: previewsAndPrs.value?.branch_name || latestRun.value?.branch_name || undefined,
      created_by: "ui-user",
    });
    latestDeployment.value = deployment;
    await loadDeploymentOps();
    const url = String(deployment?.deployment_url || "");
    deployInfo.value = url
      ? `Deployment bootstrap created (${provider}). Opening provider import…`
      : `Deployment record created for ${provider}.`;
    if (url) {
      openExternal(url);
    }
  } catch (err: any) {
    deployError.value = err?.message || "Failed to create deployment.";
  } finally {
    deployLoading.value = false;
  }
}

async function loadDeploymentOps() {
  if (!projectId.value) return;
  deploymentOpsLoading.value = true;
  deploymentOpsError.value = "";
  try {
    const rows = await listProjectDeployments(projectId.value, 20);
    deploymentRows.value = Array.isArray(rows) ? rows : [];
    const current = deploymentRows.value[0] || null;
    latestDeployment.value = current;
    deploymentEvents.value = current?.id ? await listDeploymentEvents(current.id, 80) : [];
    if (current) {
      deploymentPreflight.value = await preflightProjectDeployment(projectId.value, {
        provider: current.provider || "vercel",
        environment: current.environment || "PREVIEW",
        deployment_strategy: current.deployment_strategy || "static_frontend",
        repository_url: current?.extra_metadata?.repository_url || null,
        repository_full_name: current?.extra_metadata?.repository_full_name || null,
        branch_name: current?.extra_metadata?.branch_name || null,
      });
    } else {
      deploymentPreflight.value = null;
    }
    deploymentIntelligence.value = await fetchProjectDeploymentIntelligence(projectId.value, 80);
    try {
      environmentChecklistSummary.value = await getProjectEnvironmentChecklists(projectId.value, false);
    } catch {
      environmentChecklistSummary.value = null;
    }
    try {
      deploymentReadinessContract.value = await fetchProjectDeploymentReadiness(projectId.value, "PRODUCTION");
    } catch {
      deploymentReadinessContract.value = null;
    }
  } catch (err: any) {
    deploymentOpsError.value = err?.message || "Failed to load deployment governance data.";
  } finally {
    deploymentOpsLoading.value = false;
  }
}

async function retryDeploymentNow() {
  const current = deploymentLatest.value;
  if (!current?.id) return;
  deploymentOpsLoading.value = true;
  try {
    await retryProjectDeployment(current.id, { force: true });
    await loadDeploymentOps();
    ElMessage.success("Deployment re-queued.");
  } catch (err: any) {
    deploymentOpsError.value = err?.message || "Failed to retry deployment.";
  } finally {
    deploymentOpsLoading.value = false;
  }
}

async function rollbackDeploymentNow() {
  const current = deploymentLatest.value;
  if (!current?.id) return;
  deploymentOpsLoading.value = true;
  try {
    await rollbackProjectDeployment(current.id, {
      reason: "Operator-triggered rollback from Mission Control",
      trigger: "manual",
      request_key: getOrCreateActionRequestKey("rollback_deployment", `mission_control:rollback:${current.id}`),
      created_by: "ui-user",
    });
    await loadDeploymentOps();
    ElMessage.success("Rollback requested.");
  } catch (err: any) {
    deploymentOpsError.value = err?.message || "Failed to request rollback.";
  } finally {
    deploymentOpsLoading.value = false;
  }
}

async function promoteDeploymentNow(targetEnvironment: "STAGING" | "PRODUCTION") {
  const current = deploymentLatest.value;
  if (!current?.id) return;
  deploymentOpsLoading.value = true;
  try {
    await promoteProjectDeployment(current.id, {
      target_environment: targetEnvironment,
      reason: `Promoted from Mission Control to ${targetEnvironment}`,
      request_key: getOrCreateActionRequestKey(
        "promote_deployment",
        `mission_control:promote:${current.id}:${targetEnvironment}`
      ),
      created_by: "ui-user",
    });
    await loadDeploymentOps();
    ElMessage.success(`Promotion to ${targetEnvironment} queued.`);
  } catch (err: any) {
    deploymentOpsError.value = err?.message || `Failed to promote to ${targetEnvironment}.`;
  } finally {
    deploymentOpsLoading.value = false;
  }
}

function openDeploymentEventDetail(evt: any) {
  selectedDeploymentEvent.value = evt;
  deploymentEventDialogOpen.value = true;
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function extractPort(url?: string | null): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.port || null;
  } catch {
    return null;
  }
}

async function loadRunRuntime() {
  if (!latestRun.value?.id) {
    workItems.value = [];
    runEvents.value = [];
    artifacts.value = [];
    executionConsole.value = null;
    runNarrative.value = null;
    runNarrativeError.value = "";
    runNarrativeLoading.value = false;
    return;
  }
  artifactError.value = "";
  runNarrativeError.value = "";
  runNarrativeLoading.value = true;
  try {
    const [items, events, projectArtifacts, consoleResult, narrativeResult] = await Promise.all([
      listWorkItems(projectId.value, latestRun.value.id),
      listRunEvents(latestRun.value.id),
      listArtifacts(projectId.value),
      fetchRunExecutionConsole(latestRun.value.id).catch(() => null),
      fetchRunNarrative(latestRun.value.id).catch((err: any) => {
        runNarrativeError.value = err?.message || "Failed to load run narrative.";
        return null;
      }),
    ]);
    workItems.value = items;
    runEvents.value = events;
    artifacts.value = Array.isArray(projectArtifacts) ? projectArtifacts : [];
    executionConsole.value = consoleResult;
    runNarrative.value = narrativeResult;
  } finally {
    runNarrativeLoading.value = false;
  }
}

async function loadSimilarRuns() {
  const summary = latestRun.value?.summary || {};
  const goal =
    (typeof summary.goal === "string" && summary.goal.trim()) ||
    (typeof summary.strategy_goal === "string" && summary.strategy_goal.trim()) ||
    "";
  const errorText = latestErrorHint.value?.trim() || "";
  const files = Array.isArray(summary.changed_files) ? summary.changed_files.filter((file: any) => typeof file === "string" && file.trim()) : [];
  if (!projectId.value || !latestRun.value?.id || !hasRunMemorySearchContext({ goal, error: errorText, files })) {
    runMemoryLoading.value = false;
    runMemoryResult.value = null;
    runMemoryError.value = "";
    return;
  }
  runMemoryLoading.value = true;
  runMemoryError.value = "";
  try {
    runMemoryResult.value = await findSimilarRuns(projectId.value, {
      goal: goal || undefined,
      error: errorText || undefined,
      files,
      limit: 5,
    });
  } catch (err: any) {
    runMemoryError.value = err?.message || "Failed to load similar runs.";
  } finally {
    runMemoryLoading.value = false;
  }
}

async function refreshRuntime(force = false) {
  if (!projectId.value.trim() || (pollInFlight && !force)) return;
  pollInFlight = true;
  try {
    runs.value = canonicalizeRuns(await listRuns(projectId.value));
    normalizePinnedRunSelection();
    await loadRunRuntime();
    if (!["QUEUED", "RUNNING", "CLAIMED"].includes(latestRun.value?.status || "")) {
      const [projectHealth, score] = await Promise.all([
        fetchHealth(projectId.value),
        fetchLifecycleScore(projectId.value),
      ]);
      health.value = projectHealth;
      lifecycleScore.value = score;
    }
    // Keep refresh snappy; hydrate heavy cards asynchronously.
    void loadSimilarRuns();
    void loadMissionOverview();
    void loadMemoryTimeline();
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
  const intervalMs = pollIntervalMs();
  if (intervalMs === null) {
    stopPolling();
    return;
  }
  if (pollHandle !== null && pollDelayMs === intervalMs) {
    return;
  }
  stopPolling();
  pollDelayMs = intervalMs;
  pollHandle = setTimeout(async () => {
    pollHandle = null;
    pollDelayMs = null;
    await refreshRuntime();
  }, intervalMs);
}

function stopPolling() {
  if (pollHandle !== null) {
    clearTimeout(pollHandle);
    pollHandle = null;
  }
  pollDelayMs = null;
}

function pollIntervalMs() {
  const status = String(latestRun.value?.status || "").toUpperCase();
  if (status !== "QUEUED" && status !== "RUNNING" && status !== "CLAIMED") {
    return null;
  }
  const hidden = typeof document !== "undefined" && document.hidden;
  if (status === "QUEUED") {
    return hidden ? 9000 : 3500;
  }
  if (status === "CLAIMED") {
    return hidden ? 7000 : 3000;
  }
  return hidden ? 6000 : 2500;
}

function openVisionFilePicker() {
  visionFileInput.value?.click();
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      const marker = "base64,";
      const idx = result.indexOf(marker);
      if (idx < 0) {
        reject(new Error("Failed to parse pasted image."));
        return;
      }
      resolve(result.slice(idx + marker.length));
    };
    reader.onerror = () => reject(new Error("Failed to read image."));
    reader.readAsDataURL(file);
  });
}

async function addVisionFile(file: File) {
  if (!file.type.startsWith("image/")) return;
  const data_base64 = await fileToBase64(file);
  visionScreenshots.value.push({
    filename: file.name || `screenshot-${visionScreenshots.value.length + 1}.png`,
    content_type: file.type || "image/png",
    data_base64,
    size_bytes: file.size || 0,
  });
}

async function onVisionFileInput(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files || []);
  for (const file of files) {
    await addVisionFile(file);
  }
  if (input) input.value = "";
}

async function onVisionDrop(event: DragEvent) {
  event.preventDefault();
  const files = Array.from(event.dataTransfer?.files || []);
  for (const file of files) {
    await addVisionFile(file);
  }
}

async function onVisionPaste(event: ClipboardEvent) {
  const files = Array.from(event.clipboardData?.files || []);
  if (!files.length) return;
  for (const file of files) {
    await addVisionFile(file);
  }
}

function removeVisionScreenshot(index: number) {
  visionScreenshots.value.splice(index, 1);
}

async function submitVisionRun() {
  if (!projectId.value || !visionReady.value) return;
  visionSubmitting.value = true;
  overviewError.value = "";
  try {
    const response = await createVisionRun({
      project_id: projectId.value,
      goal_text: visionGoalText.value.trim(),
      screenshots: visionScreenshots.value.map((item) => ({
        filename: item.filename,
        content_type: item.content_type,
        data_base64: item.data_base64,
      })),
      page_url: typeof window !== "undefined" ? window.location.href : null,
      preferred_executor: "codex",
      auto_start: visionAutoStart.value,
      auto_deploy: visionAutoDeploy.value,
      metadata: { source_surface: "mission_control" },
    });
    visionGoalText.value = "";
    visionScreenshots.value = [];
    ElMessage.success(`Vision run created: task ${response.task_id}`);
    await refreshRuntime(true);
  } catch (err: any) {
    overviewError.value = err?.message || "Failed to create vision run.";
  } finally {
    visionSubmitting.value = false;
  }
}

async function startRunFromIntake(item: any) {
  if (!projectId.value || cancelEnabled.value) return;
  intakeRunLoadingId.value = item.id;
  overviewError.value = "";
  try {
    const executor = "codex";
    const requestKey = getOrCreateActionRequestKey("start_run", `mission_control:intake:${projectId.value}:${item?.id || "unknown"}`);
    const createdRun = await createRun(projectId.value, executor, null, null, { request_key: requestKey });
    if (createdRun?.id) {
      runs.value = canonicalizeRuns([createdRun, ...runs.value.filter((run) => run?.id !== createdRun.id)]);
      ElMessage.success(`Run started: ${String(createdRun.id).slice(0, 8)}`);
      syncContext();
      syncPolling();
    } else {
      ElMessage.success("Run started.");
    }
    await refreshRuntime(true);
  } catch (err: any) {
    overviewError.value = err?.message || "Failed to start run from work intake.";
  } finally {
    intakeRunLoadingId.value = "";
  }
}

async function cancelLatestRun() {
  if (!latestRun.value?.id || !cancelEnabled.value) return;
  error.value = "";
  try {
    await updateRunStatus(latestRun.value.id, "CANCELED");
    await refreshRuntime(true);
  } catch (err: any) {
    error.value = err?.message || "Failed to cancel run.";
  }
}

async function discardLatestRunWorkspace() {
  if (!latestRun.value?.id || discardLoading.value) return;
  const shouldDiscard = window.confirm(
    "Discard this run workspace? This will stop preview, cancel active execution, and remove temp workspace files."
  );
  if (!shouldDiscard) return;
  discardLoading.value = true;
  error.value = "";
  try {
    const result = await discardRun(latestRun.value.id);
    await refreshRuntime(true);
    ElMessage.success(result?.detail || "Run workspace discarded.");
  } catch (err: any) {
    error.value = err?.message || "Failed to discard run workspace.";
  } finally {
    discardLoading.value = false;
  }
}

async function resumeLatestRun() {
  if (!latestRun.value?.id || !resumeActionEnabled.value) return;
  resumeLoading.value = true;
  error.value = "";
  try {
    await resumeRun(latestRun.value.id, { start_now: true });
    await refreshRuntime(true);
    ElMessage.success(
      operatorConfirmationPaused.value
        ? "Operator confirmation accepted. Run resumed."
        : "Run resumed from the last safe checkpoint."
    );
  } catch (err: any) {
    error.value = err?.message || "Failed to resume run.";
  } finally {
    resumeLoading.value = false;
  }
}

function openBudgetDialog() {
  if (!latestRun.value?.id || budgetExtendLoading.value) return;
  const b = budgetTelemetry.value;
  const tokenGap = Math.max(0, b.usedTokens - b.maxTokens);
  const costGap = Math.max(0, b.usedCostCents - b.maxCostCents);
  const tokenBuffer = Math.max(5000, Math.round(Math.max(b.maxTokens, b.usedTokens, 10000) * 0.2));
  const costBuffer = Math.max(10, Math.round(Math.max(b.maxCostCents, b.usedCostCents, 25) * 0.2 * 100) / 100);
  budgetAdditionalTokens.value = Math.max(1000, tokenGap + tokenBuffer);
  budgetAdditionalCostCents.value = Math.max(1, Math.round((costGap + costBuffer) * 100) / 100);
  budgetDialogOpen.value = true;
}

async function approveBudgetExtension() {
  if (!latestRun.value?.id || budgetExtendLoading.value) return;
  if (!Number.isFinite(budgetAdditionalTokens.value) || budgetAdditionalTokens.value <= 0) {
    ElMessage.warning("Additional tokens must be greater than 0.");
    return;
  }
  if (!Number.isFinite(budgetAdditionalCostCents.value) || budgetAdditionalCostCents.value <= 0) {
    ElMessage.warning("Additional cost must be greater than 0.");
    return;
  }
  budgetExtendLoading.value = true;
  error.value = "";
  try {
    await extendRunBudget(latestRun.value.id, {
      additional_tokens: Math.round(budgetAdditionalTokens.value),
      additional_cost_cents: Number(budgetAdditionalCostCents.value),
      auto_resume: true,
      reason: budgetExtensionReason.value?.trim() || "Operator approved from Mission Control",
    });
    budgetDialogOpen.value = false;
    await refreshRuntime(true);
    ElMessage.success("Budget extended. Run resumed.");
  } catch (err: any) {
    error.value = err?.message || "Failed to extend budget.";
  } finally {
    budgetExtendLoading.value = false;
  }
}

async function retryLatestRunPush() {
  if (!latestRun.value?.id || !manualPushRequired.value) return;
  retryPushLoading.value = true;
  error.value = "";
  try {
    await retryRunPush(latestRun.value.id, { auth_strategy: retryPushStrategy.value || "runtime_default" });
    await refreshRuntime(true);
    ElMessage.success("Branch push succeeded.");
  } catch (err: any) {
    error.value = err?.message || "Failed to push branch.";
  } finally {
    retryPushLoading.value = false;
  }
}

async function copyManualPushCommands() {
  try {
    await navigator.clipboard.writeText(manualPushCommands.value);
    ElMessage.success("Manual push commands copied.");
  } catch {
    ElMessage.warning("Clipboard unavailable. Copy commands from the panel.");
  }
}

function openForkDialog() {
  if (!latestRun.value?.id) return;
  forkDialogOpen.value = true;
  forkError.value = "";
  forkExecutor.value = latestRun.value.executor || "codex";
  forkBranchName.value = latestRun.value.branch_name ? `${latestRun.value.branch_name}-fork` : "";
  forkNotes.value = "";
  forkStartNow.value = true;
}

async function openReplayDialog(runId = latestRun.value?.id || "") {
  if (!runId) return;
  replayRunId.value = runId;
  replayDialogOpen.value = true;
  replayError.value = "";
  replayResult.value = null;
  await loadReplayTimeline();
}

async function loadReplayTimeline() {
  if (!replayRunId.value) return;
  replayLoading.value = true;
  replayError.value = "";
  try {
    replayResult.value = await fetchRunTimeline(replayRunId.value);
  } catch (err: any) {
    replayError.value = err?.message || "Failed to load replay timeline.";
  } finally {
    replayLoading.value = false;
  }
}

function openTimelinePage(runId = replayRunId.value || latestRun.value?.id || "") {
  if (!projectId.value) return;
  router.push({
    path: `/projects/${projectId.value}/timeline`,
    query: runId ? { run: runId } : {},
  });
}

async function submitForkRun() {
  if (!latestRun.value?.id) return;
  forkLoading.value = true;
  forkError.value = "";
  try {
    const requestKey = getOrCreateActionRequestKey("fork_run", `mission_control:fork:${latestRun.value.id}`);
    await forkRun(latestRun.value.id, {
      executor: forkExecutor.value || undefined,
      branch_name: forkBranchName.value.trim() || undefined,
      start_now: forkStartNow.value,
      request_key: requestKey,
      summary_overrides: forkNotes.value.trim()
        ? {
            fork_notes: forkNotes.value.trim(),
          }
        : {},
    });
    forkDialogOpen.value = false;
    await refreshRuntime(true);
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

function compareAgainstRun(runId: string) {
  if (!latestRun.value?.id || latestRun.value.id === runId) return;
  compareDialogOpen.value = true;
  compareError.value = "";
  compareResult.value = null;
  compareRunAId.value = latestRun.value.id;
  compareRunBId.value = runId;
  void submitRunComparison();
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

async function openStrategyDialog() {
  if (!latestRun.value?.id) return;
  strategyDialogOpen.value = true;
  strategyErrorMessage.value = "";
  strategyGoal.value =
    latestRun.value?.summary?.goal ||
    latestRun.value?.summary?.strategy_goal ||
    `Improve run ${latestRun.value.id}`;
  strategyErrorText.value = latestErrorHint.value || latestRun.value?.summary?.strategy_error || "";
  strategyFilesInput.value = Array.isArray(latestRun.value?.summary?.strategy_files)
    ? latestRun.value.summary.strategy_files.join(", ")
    : "";
  strategyStartNow.value = true;
  strategyLimit.value = 3;
  strategyExecutor.value = "";
  try {
    strategyResult.value = await fetchRunStrategies(latestRun.value.id);
  } catch {
    strategyResult.value = null;
  }
}

function defaultImproveGoal() {
  return (
    latestRun.value?.summary?.goal ||
    latestRun.value?.summary?.strategy_goal ||
    `Improve run ${latestRun.value?.id || ""}`
  );
}

function parseCommaSeparatedList(value: string) {
  return value
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function openImproveDialog(issueText = "", files: string[] = []) {
  if (!latestRun.value?.id) return;
  improveDialogOpen.value = true;
  improveLoading.value = false;
  improveError.value = "";
  improveIssueText.value = issueText;
  improveFilesInput.value = files.join(", ");
  improveStartNow.value = true;
  improveExecutor.value = "";
}

function parsedStrategyFiles() {
  return parseCommaSeparatedList(strategyFilesInput.value);
}

function parsedImproveFiles() {
  return parseCommaSeparatedList(improveFilesInput.value);
}

async function submitImproveRun() {
  if (!latestRun.value?.id || !improveIssueText.value.trim()) return;
  improveLoading.value = true;
  improveError.value = "";
  improveSuccessMessage.value = "";
  try {
    const issueText = improveIssueText.value.trim();
    const result = await reportRunIssue(latestRun.value.id, {
      goal: issueText || defaultImproveGoal(),
      issue: issueText,
      files: parsedImproveFiles(),
      executor: improveExecutor.value || undefined,
      start_now: improveStartNow.value,
    });
    strategyResult.value = result;
    improveDialogOpen.value = false;
    const createdRun = result?.candidates?.[0];
    improveSuccessMessage.value = createdRun?.run_id
      ? `Created improvement run ${createdRun.run_id} on ${createdRun.branch_name || "a forked branch"}.`
      : "Created a focused improvement run from the latest workspace.";
    await refreshRuntime(true);
    ElMessage.success("Improvement run created.");
  } catch (err: any) {
    improveError.value = err?.message || "Failed to create improvement run.";
  } finally {
    improveLoading.value = false;
  }
}

async function submitStrategyPlan() {
  if (!latestRun.value?.id) return;
  strategyLoading.value = true;
  strategyErrorMessage.value = "";
  try {
    strategyResult.value = await createRunStrategies(latestRun.value.id, {
      goal: strategyGoal.value.trim() || undefined,
      error: strategyErrorText.value.trim() || undefined,
      files: parsedStrategyFiles(),
      executor: strategyExecutor.value || undefined,
      start_now: strategyStartNow.value,
      limit: strategyLimit.value,
    });
    await refreshRuntime(true);
  } catch (err: any) {
    strategyErrorMessage.value = err?.message || "Failed to create strategy candidates.";
  } finally {
    strategyLoading.value = false;
  }
}

async function refreshStrategyGroup() {
  const anchorRunId = strategyResult.value?.source_run_id || latestRun.value?.id;
  if (!anchorRunId) return;
  strategyRefreshing.value = true;
  strategyErrorMessage.value = "";
  try {
    strategyResult.value = await fetchRunStrategies(anchorRunId);
    await refreshRuntime(true);
  } catch (err: any) {
    strategyErrorMessage.value = err?.message || "Failed to refresh strategy recommendation.";
  } finally {
    strategyRefreshing.value = false;
  }
}

function goToOverview() {
  router.push(`/projects/${projectId.value}`);
}

function goToEnvironmentCenter() {
  router.push(`/projects/${projectId.value}/environments`);
}

function openApprovalsView() {
  router.push(`/projects/${projectId.value}/approvals`);
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

async function openDiffDialog(artifact: any) {
  selectedDiffArtifact.value = artifact;
  diffDialogOpen.value = true;
  diffResult.value = null;
  diffError.value = "";
  diffLoading.value = true;
  try {
    diffResult.value = await fetchArtifactDiff(projectId.value, artifact.id);
  } catch (err: any) {
    diffError.value = err?.message || "Failed to load patch preview.";
  } finally {
    diffLoading.value = false;
  }
}

async function loadCreatePrReviewState(artifact: any) {
  createPrDiffLoading.value = true;
  createPrDiffError.value = "";
  createPrApprovalComment.value = "";
  createPrApprovalError.value = "";
  createPrApprovalLoading.value = true;
  try {
    const [preview, approvals] = await Promise.all([
      fetchArtifactDiff(projectId.value, artifact.id),
      listApprovals(projectId.value, {
        target_type: "artifact",
        target_id: artifact.id,
      }),
    ]);
    createPrDiffPreview.value = preview;
    createPrApprovals.value = Array.isArray(approvals) ? approvals : [];
  } catch (err: any) {
    createPrDiffError.value = err?.message || "Failed to load PR preview diff.";
    createPrApprovalError.value = err?.message || "Failed to load approval state.";
  } finally {
    createPrDiffLoading.value = false;
    createPrApprovalLoading.value = false;
  }
}

async function ensureSelectedPrArtifact(artifact: any) {
  if (!artifact?.id) return;
  const artifactChanged = selectedPrArtifact.value?.id !== artifact.id;
  if (artifactChanged) {
    selectedPrArtifact.value = artifact;
    createPrTitle.value = `Agentic SDLC run ${latestRun.value?.id || ""}`;
    createPrBody.value = `Automated patch generated from run ${latestRun.value?.id || "unknown"}.`;
    createPrBranch.value = latestRun.value?.branch_name || "";
    createPrDiffPreview.value = null;
    createPrApprovals.value = [];
  }
  if (artifactChanged || !createPrDiffPreview.value) {
    await loadCreatePrReviewState(artifact);
  }
}

async function openCreatePrDialog(artifact: any, runId = latestRun.value?.id || "") {
  selectedPrArtifact.value = artifact;
  selectedPrRunId.value = runId;
  createPrDialogOpen.value = true;
  createPrError.value = "";
  createPrResult.value = null;
  const selectedRun = runId ? findRunById(runId) : null;
  createPrTitle.value = `Agentic SDLC run ${runId || latestRun.value?.id || ""}`;
  createPrBody.value = `Automated patch generated from run ${runId || latestRun.value?.id || "unknown"}.`;
  createPrBranch.value =
    (selectedRun?.branch_name as string | undefined) ||
    (previewsAndPrs.value?.run_id === runId ? previewsAndPrs.value?.branch_name : "") ||
    latestRun.value?.branch_name ||
    "";
  createPrDiffPreview.value = null;
  await loadCreatePrReviewState(artifact);
}

async function submitArtifactApproval(status: "APPROVED" | "REJECTED") {
  if (!selectedPrArtifact.value?.id) return;
  createPrApprovalLoading.value = true;
  createPrApprovalError.value = "";
  try {
    await createApproval(projectId.value, {
      target_type: "artifact",
      target_id: selectedPrArtifact.value.id,
      status,
      decided_by: "mission-control",
      comment: createPrApprovalComment.value.trim() || undefined,
    });
    createPrApprovals.value = await listApprovals(projectId.value, {
      target_type: "artifact",
      target_id: selectedPrArtifact.value.id,
    });
    createPrApprovalComment.value = "";
    await refreshOverviewSurface();
  } catch (err: any) {
    createPrApprovalError.value = err?.message || `Failed to ${status === "APPROVED" ? "approve" : "reject"} patch.`;
  } finally {
    createPrApprovalLoading.value = false;
  }
}

function workbenchProgressForStatus(status?: string | null) {
  const normalized = String(status || "").toUpperCase();
  if (normalized === "DONE") return 100;
  if (normalized === "FAILED" || normalized === "CANCELED") return 100;
  if (normalized === "RUNNING" || normalized === "CLAIMED") return 68;
  if (normalized === "QUEUED") return 18;
  return 0;
}

function workbenchStatusMessage(status?: string | null, blocking = true) {
  const normalized = String(status || "").toUpperCase();
  if (normalized === "RUNNING" || normalized === "CLAIMED") return "AI is actively working through this step.";
  if (normalized === "QUEUED") return "Queued for execution in the current run.";
  if (normalized === "DONE") return "Completed successfully and attached to the run record.";
  if (normalized === "FAILED" && !blocking) return "Optional step failed, but the run can still complete.";
  if (normalized === "FAILED") return "This step failed. Inspect the replay and healing path.";
  if (normalized === "CANCELED") return "Execution stopped before this step could finish.";
  return "Waiting for runtime signal.";
}

async function openWorkbenchDiff() {
  if (!latestPatchArtifact.value) return;
  await openDiffDialog(latestPatchArtifact.value);
}

async function openWorkbenchExplain() {
  if (!latestPatchArtifact.value) return;
  await openArtifactExplain(latestPatchArtifact.value);
}

async function approveWorkbenchPatch() {
  if (!latestPatchArtifact.value) return;
  await ensureSelectedPrArtifact(latestPatchArtifact.value);
  await submitArtifactApproval("APPROVED");
}

async function requestRunConfirmation() {
  if (!projectId.value || !latestRun.value?.id) {
    openApprovalsView();
    return;
  }
  error.value = "";
  try {
    const summaryTaskId = String(latestRun.value?.summary?.task_id || "").trim();
    const artifactId = String(latestPatchArtifact.value?.id || "").trim();

    let targetType = "";
    let targetId = "";
    if (summaryTaskId) {
      targetType = "task";
      targetId = summaryTaskId;
    } else if (artifactId) {
      targetType = "artifact";
      targetId = artifactId;
    }

    if (!targetType || !targetId) {
      ElMessage.warning("No task/artifact target found for confirmation. Opening Approvals.");
      openApprovalsView();
      return;
    }

    const existing = await listApprovals(projectId.value, { target_type: targetType, target_id: targetId });
    const hasPending = Array.isArray(existing)
      && existing.some((row: any) => String(row?.status || "").toUpperCase() === "PENDING");

    if (!hasPending) {
      await createApproval(projectId.value, {
        target_type: targetType,
        target_id: targetId,
        status: "PENDING",
        decided_by: "ui-user",
        comment: "Operator confirmation required before patch execution.",
      });
      ElMessage.success("Confirmation request created.");
    } else {
      ElMessage.info("Confirmation request is already pending.");
    }
  } catch (err: any) {
    error.value = err?.message || "Failed to create confirmation request.";
  } finally {
    openApprovalsView();
  }
}

async function rejectWorkbenchPatch() {
  if (!latestPatchArtifact.value) return;
  await ensureSelectedPrArtifact(latestPatchArtifact.value);
  await submitArtifactApproval("REJECTED");
}

function requestPatchModification() {
  const files = Array.isArray(latestRun.value?.summary?.changed_files)
    ? latestRun.value.summary.changed_files.filter((file: any) => typeof file === "string" && file.trim())
    : [];
  openImproveDialog(
    latestArtifactApproval.value?.comment ||
      createPrApprovalError.value ||
      "Review feedback requested changes on the latest patch.",
    files,
  );
}

async function openWorkbenchPrFlow() {
  if (!latestPatchArtifact.value) return;
  await openCreatePrDialog(latestPatchArtifact.value);
}

async function submitCreatePr() {
  if (!selectedPrRunId.value || !selectedPrArtifact.value?.id) return;
  createPrLoading.value = true;
  createPrError.value = "";
  try {
    const requestKey = getOrCreateActionRequestKey(
      "create_pr",
      `mission_control:create_pr:${selectedPrRunId.value}:${selectedPrArtifact.value.id}`
    );
    createPrResult.value = await createRunPullRequest(selectedPrRunId.value, {
      artifact_id: selectedPrArtifact.value.id,
      title: createPrTitle.value.trim() || undefined,
      body: createPrBody.value.trim() || undefined,
      branch_name: createPrBranch.value.trim() || undefined,
      request_key: requestKey,
    });
    createPrLoading.value = false;
    void refreshOverviewSurface().catch(() => {
      // Keep PR success visible even if follow-up refresh fails.
    });
    return;
  } catch (err: any) {
    createPrError.value = err?.message || "Failed to create pull request.";
  } finally {
    createPrLoading.value = false;
  }
}

async function handlePrimaryAction() {
  const action = primaryActionCard.value;
  if (!action) return;
  if (action.kind === "open-pr" || action.kind === "open-preview") {
    if (action.href) window.open(action.href, "_blank", "noopener,noreferrer");
    return;
  }
  if (action.kind === "create-pr") {
    if (latestPatchArtifact.value) await openCreatePrDialog(latestPatchArtifact.value);
    return;
  }
  if (action.kind === "approve-patch") {
    if (latestPatchArtifact.value) openDiffDialog(latestPatchArtifact.value);
    return;
  }
  if (action.kind === "replay") {
    if (latestRun.value?.id) openReplayDialog(latestRun.value.id);
    return;
  }
  if (action.kind === "monitor") {
    if (latestRun.value?.id) openTimelinePage(latestRun.value.id);
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
  if (status === "COMPLETED_CLEAN") return "success";
  if (status === "COMPLETED_WITH_RECOVERY") return "success";
  if (status === "DEGRADED_COMPLETION") return "warning";
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

function workItemStatusTagType(status?: string | null, blocking = true) {
  if (status === "RUNNING" || status === "CLAIMED") return "warning";
  if (status === "DONE") return "success";
  if (status === "FAILED" && !blocking) return "warning";
  if (status === "FAILED" || status === "CANCELED") return "danger";
  if (status === "QUEUED") return "info";
  return "default";
}

function approvalTagType(status?: string | null) {
  if (status === "APPROVED") return "success";
  if (status === "REJECTED") return "danger";
  if (status === "PENDING") return "warning";
  return "info";
}

function impactRiskTagType(riskTier?: string | null) {
  if (riskTier === "HIGH") return "danger";
  if (riskTier === "MEDIUM") return "warning";
  return "success";
}

function memoryEventTagType(severity?: string | null) {
  const value = String(severity || "").toLowerCase();
  if (value === "critical") return "danger";
  if (value === "warning") return "warning";
  return "info";
}

function violationSummaryTagType(insights?: any | null) {
  if (!insights) return "info";
  if ((insights.latest_run_blocking || 0) > 0) return "danger";
  if ((insights.latest_run_warning || 0) > 0) return "warning";
  return "success";
}

function budgetModeTagType(mode?: string | null) {
  if (mode === "BLOCKED") return "danger";
  if (mode === "CONSTRAINED") return "warning";
  if (mode === "NORMAL") return "success";
  return "info";
}

function verificationStatusTagType(status?: string | null) {
  if (status === "REQUIRES_CONFIRMATION") return "warning";
  if (status === "READY") return "success";
  if (status === "NO_SCOPE") return "info";
  return "default";
}

function verificationFindingTagType(severity?: string | null) {
  if (severity === "high") return "danger";
  if (severity === "warning") return "warning";
  return "info";
}

function verificationScopeLabel(scopeMatch?: boolean | null) {
  if (scopeMatch === true) return "Matched";
  if (scopeMatch === false) return "Drifted";
  return "Unknown";
}

function timelineStatusTagType(status?: string | null) {
  switch ((status || "").toLowerCase()) {
    case "success":
      return "success";
    case "failed":
      return "danger";
    case "recovery":
      return "warning";
    case "running":
      return "primary";
    default:
      return "info";
  }
}

function narrativeStatusTagType(status?: string | null, blocking = true) {
  if (status === "RUNNING" || status === "CLAIMED") return "warning";
  if (status === "DONE" || status === "COMPLETED") return "success";
  if (status === "WARNING") return "warning";
  if (status === "SKIPPED") return "warning";
  if (status === "FAILED" && !blocking) return "warning";
  if (status === "FAILED" || status === "CANCELED") return "danger";
  if (status === "QUEUED" || status === "PENDING") return "info";
  return "default";
}

function panelStatusFor(status?: string | null, blocking = true, runStatus?: string | null) {
  if (status === "RUNNING" || status === "CLAIMED") return "Running";
  if (status === "DONE") return "Completed";
  if (status === "WARNING") return "Warning";
  if (status === "SKIPPED") return "Skipped";
  if (status === "CANCELED" && runStatus === "COMPLETED") return "Skipped";
  if (status === "FAILED" && !blocking) return "Warning";
  if (status === "FAILED" || status === "CANCELED") return "Blocked";
  return "Waiting";
}

function normalizeTimelineStatus(status?: string | null) {
  if (status === "QUEUED") return "PENDING";
  if (status === "CLAIMED" || status === "RUNNING") return "RUNNING";
  if (status === "DONE") return "DONE";
  if (status === "SKIPPED") return "SKIPPED";
  if (status === "FAILED") return "FAILED";
  if (status === "CANCELED") return "CANCELED";
  return status || "PENDING";
}

function mapEventMessage(eventType: string, title?: string) {
  const itemTitle = title || "Work item";
  if (eventType === "RUN_CREATED") return "Run created";
  if (eventType === "RUN_GOVERNANCE_TRANSITION") return "Governance profile elevated";
  if (eventType === "RUN_DESIGN_GOVERNANCE_VIOLATION") return "Design governance violation detected";
  if (eventType === "RUN_BOOTSTRAP_STARTED") return "Planner bootstrap started";
  if (eventType === "RUN_RUNNING") return "Run started";
  if (eventType === "RUN_COMPLETED") return "Run completed";
  if (eventType === "RUN_FAILED") return "Run failed";
  if (eventType === "RUN_CANCELED") return "Run canceled";
  if (eventType === "RUN_FORKED") return "Run forked";
  if (eventType === "RUN_EXECUTION_HANDOFF") return "Execution handoff decided";
  if (eventType === "WORK_DAG_CREATED") return "Work DAG created";
  if (eventType === "WORK_ITEM_CREATED") return `Task ${itemTitle} created`;
  if (eventType === "WORK_ITEM_CLAIMED") return `Task ${itemTitle} claimed`;
  if (eventType === "WORK_ITEM_STARTED") return `Task ${itemTitle} started`;
  if (eventType === "WORK_ITEM_DONE") return `Task ${itemTitle} completed`;
  if (eventType === "WORK_ITEM_SKIPPED") return `Task ${itemTitle} skipped`;
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

function shortRunId(runId?: string | null) {
  if (!runId) return "—";
  return String(runId).slice(0, 8);
}

function formatElapsed(seconds?: number | null) {
  if (typeof seconds !== "number") return "—";
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}m ${remainder}s`;
}

function baselineSecondsForType(type?: string | null) {
  const normalized = String(type || "").toUpperCase();
  const profiled = etaProfilesByType.value.get(normalized);
  if (typeof profiled === "number" && profiled > 0) return profiled;
  if (normalized.includes("PLAN")) return 45;
  if (normalized === "CODE_FRONTEND") return 180;
  if (normalized === "WRITE_TESTS") return 90;
  if (normalized === "RUN_TESTS") return 120;
  if (normalized.includes("REVIEW")) return 70;
  if (normalized.includes("FIX_TEST_FAILURE")) return 150;
  return 90;
}

function formatConfidence(score?: number | null) {
  if (typeof score !== "number") return "—";
  return `${Math.round(score * 100)}%`;
}

function formatBudgetCents(value?: number | null) {
  if (typeof value !== "number") return "—";
  return `${value.toFixed(2)}c`;
}

function formatBudgetTokenUsage(used?: number | null, max?: number | null) {
  if (typeof max !== "number") return "—";
  return `${typeof used === "number" ? used : 0}/${max}`;
}

function executionContractCommands(contract?: any) {
  const commands = [contract?.build_command, contract?.test_command, contract?.lint_command].filter(
    (value) => typeof value === "string" && value.trim()
  );
  return commands.length ? commands.join(" · ") : "—";
}

function normalizeRuntimeGitAuthMode(value?: string | null) {
  const normalized = String(value || "auto").trim().toLowerCase();
  if (normalized === "github_app_https" || normalized === "ssh" || normalized === "none" || normalized === "auto") {
    return normalized;
  }
  return "auto";
}

function formatRuntimeGitAuthMode(value?: string | null) {
  const normalized = normalizeRuntimeGitAuthMode(value);
  if (normalized === "github_app_https") return "GitHub App";
  if (normalized === "ssh") return "SSH";
  if (normalized === "none") return "Plain";
  if (normalized === "auto") return "Auto";
  return "Unknown";
}

function runtimeGitAuthMissing(context?: any) {
  const runtimeMissing = Array.isArray(context?.runtime_git_auth_missing)
    ? context.runtime_git_auth_missing.filter((value: any) => typeof value === "string" && value.trim())
    : [];
  if (runtimeMissing.length) return runtimeMissing;
  if (normalizeRuntimeGitAuthMode(context?.runtime_git_auth_mode) !== "github_app_https") return [];
  return Array.isArray(context?.github_clone_auth_missing)
    ? context.github_clone_auth_missing.filter((value: any) => typeof value === "string" && value.trim())
    : [];
}

function runtimeGitAuthStatus(context?: any) {
  return String(context?.runtime_git_auth_status || context?.github_clone_auth_status || "UNKNOWN");
}

function formatRuntimeGitAuthSummary(context?: any) {
  const modeLabel = formatRuntimeGitAuthMode(context?.runtime_git_auth_mode);
  const status = runtimeGitAuthStatus(context);
  return modeLabel === "Unknown" ? status : `${modeLabel} ${status}`;
}

function usesGitHubAppRuntimeAuth(context?: any) {
  return normalizeRuntimeGitAuthMode(context?.runtime_git_auth_mode) === "github_app_https";
}

function usesSshRuntimeAuth(context?: any) {
  return normalizeRuntimeGitAuthMode(context?.runtime_git_auth_mode) === "ssh";
}

function formatRuntimeGitAuthDetails(context?: any) {
  const mode = normalizeRuntimeGitAuthMode(context?.runtime_git_auth_mode);
  if (mode === "ssh") {
    return `git ${formatPresence(Boolean(context?.git_binary))} · ssh ${formatPresence(Boolean(context?.ssh_binary))}`;
  }
  if (mode === "github_app_https") {
    return [
      `app id ${formatPresence(context?.github_app_id_present)}`,
      `key ${formatPresence(context?.github_private_key_present)}`,
      `webhook ${formatPresence(context?.github_webhook_secret_present)}`,
    ].join(" · ");
  }
  if (mode === "auto") {
    return [
      `git ${formatPresence(Boolean(context?.git_binary))}`,
      context?.github_clone_auth_ready ? "GitHub App env ready" : "GitHub App env optional",
    ].join(" · ");
  }
  return `git ${formatPresence(Boolean(context?.git_binary))}`;
}

function formatPresence(value?: boolean | null) {
  return value ? "yes" : "no";
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

function openExternal(url?: string | null) {
  if (!url) return;
  window.open(url, "_blank", "noopener,noreferrer");
}

function scrollToWorkIntake() {
  const anchor = document.getElementById("work-intake");
  anchor?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function intakeSourceLabel(item: any) {
  return String(item?.source_surface || item?.source || item?.kind || "mission_control");
}

function intakeRunId(item: any) {
  return String(item?.run_id || item?.linked_run_id || "");
}

function timestampScore(run: any) {
  const values = [run?.updated_at, run?.finished_at, run?.started_at, run?.created_at];
  for (const value of values) {
    const ts = Date.parse(String(value || ""));
    if (!Number.isNaN(ts) && ts > 0) return ts;
  }
  return 0;
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

<style scoped>
.mission-control-page {
  position: relative;
}

.mission-control-page::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(1200px 600px at 8% -10%, rgba(56, 189, 248, 0.14), transparent 55%),
    radial-gradient(1100px 560px at 92% 0%, rgba(99, 102, 241, 0.12), transparent 52%);
}

.mission-panel {
  border-radius: 24px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: linear-gradient(160deg, rgba(255, 255, 255, 0.82), rgba(248, 250, 252, 0.72));
  backdrop-filter: blur(10px);
  box-shadow:
    0 20px 40px rgba(15, 23, 42, 0.1),
    0 2px 10px rgba(15, 23, 42, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.45);
}

.mission-subcard {
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.26);
  background: linear-gradient(165deg, rgba(255, 255, 255, 0.68), rgba(241, 245, 249, 0.62));
  box-shadow:
    0 10px 24px rgba(15, 23, 42, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.45);
}

.mission-scroll-zone {
  max-height: 38rem;
  overflow-y: auto;
  padding-right: 0.3rem;
  scrollbar-width: thin;
}

.mission-scroll-zone::-webkit-scrollbar {
  width: 10px;
}

.mission-scroll-zone::-webkit-scrollbar-thumb {
  border-radius: 9999px;
  background: linear-gradient(180deg, rgba(100, 116, 139, 0.4), rgba(148, 163, 184, 0.5));
  border: 2px solid rgba(255, 255, 255, 0.2);
}

.mission-line-clamp-3 {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
}

.mission-primary-top {
  position: sticky;
  top: 0.75rem;
  z-index: 8;
}

.mission-content-scroll {
  max-height: 42rem;
  overflow-y: auto;
  padding-right: 0.25rem;
  scrollbar-width: thin;
}

.mission-content-scroll::-webkit-scrollbar {
  width: 10px;
}

.mission-content-scroll::-webkit-scrollbar-thumb {
  border-radius: 9999px;
  background: linear-gradient(180deg, rgba(100, 116, 139, 0.35), rgba(148, 163, 184, 0.5));
}

.mission-hero__controls {
  min-width: 20rem;
  max-width: 36rem;
}

.mission-hero__controls-label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  color: var(--text-muted);
  margin-bottom: 0.5rem;
}

.mission-density-toggle {
  display: flex;
  gap: 0.4rem;
  margin-bottom: 0.5rem;
}

.mission-run-picker {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.mission-run-picker__label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--text-muted);
  white-space: nowrap;
}

.mission-run-picker__select {
  min-width: 16rem;
}

.mission-hero__controls-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem;
  max-height: 14rem;
  overflow-y: auto;
  padding-right: 0.2rem;
}

.mission-hero__rail {
  overflow-x: auto;
  padding-bottom: 0.2rem;
}

.density-compact .mission-hero .premium-hero__title {
  font-size: clamp(2rem, 3.6vw, 3rem);
  line-height: 1.1;
}

.density-compact .mission-hero .premium-hero__copy {
  font-size: 0.97rem;
  line-height: 1.55;
}

.density-compact .mission-panel {
  border-radius: 18px;
}

.density-compact .mission-subcard {
  border-radius: 14px;
}

.density-compact .mission-content-scroll {
  max-height: 30rem;
}

@media (max-width: 1024px) {
  .mission-hero__controls {
    max-width: 100%;
  }

  .mission-hero__controls-grid {
    grid-template-columns: 1fr;
    max-height: 12rem;
  }

  .mission-run-picker {
    flex-direction: column;
    align-items: flex-start;
  }

  .mission-run-picker__select {
    width: 100%;
    min-width: 0;
  }

  .mission-primary-top {
    position: static;
  }
}

@media (max-width: 768px) {
  .mission-panel {
    border-radius: 18px;
  }

  .mission-subcard {
    border-radius: 14px;
  }
}

.mission-inline-code {
  margin: 0;
  padding: 0.75rem 0.9rem;
  border: 1px solid var(--border-soft);
  border-radius: 8px;
  background: var(--surface-soft);
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
}

.mission-inline-actions {
  margin-top: -0.25rem;
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.mission-inline-select {
  width: 180px;
}

.mission-preview-embed {
  border: 1px solid var(--border-soft);
  border-radius: 14px;
  padding: 0.7rem;
  background: rgba(255, 255, 255, 0.65);
}

.mission-preview-embed__top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.65rem;
}

.mission-preview-embed__viewport {
  border: 1px solid var(--border-soft);
  background: #0f172a;
  border-radius: 12px;
  padding: 0.45rem;
}

.mission-preview-embed__viewport.is-mobile {
  max-width: 420px;
  margin: 0 auto;
}

.mission-preview-embed__frame {
  width: 100%;
  height: 360px;
  border: 0;
  border-radius: 10px;
  background: #fff;
}

.mission-preview-embed__viewport.is-mobile .mission-preview-embed__frame {
  width: min(100%, 390px);
  margin: 0 auto;
  display: block;
  height: 760px;
}
</style>
