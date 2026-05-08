<template>
  <div v-if="projectId" class="page-stack mission-control-page">
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
        <div class="mission-hero__controls">
          <el-button :loading="loading" @click="loadAll">Refresh</el-button>
          <el-button plain :disabled="!forkEnabled" @click="openForkDialog">
            Fork Run
          </el-button>
          <el-button plain :disabled="!forkEnabled" @click="openReplayDialog()">
            Replay Run
          </el-button>
          <el-button plain :disabled="!resumeEnabled" :loading="resumeLoading" @click="resumeLatestRun">
            Resume Run
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
          <el-button @click="goToOverview">Project Overview</el-button>
        </div>
      </div>
      <div class="mission-hero__rail">
        <div class="mission-chip-panel">
          <div class="mission-chip-panel__label">Project ID</div>
          <div class="mission-chip-panel__value font-mono">{{ projectId || "—" }}</div>
        </div>
        <div class="mission-chip-panel">
          <div class="mission-chip-panel__label">Latest Run</div>
          <div class="mission-chip-panel__value font-mono">{{ latestRun?.id || "—" }}</div>
          <div class="mission-chip-panel__meta">{{ latestRun?.executor || "No executor" }}</div>
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

    <div v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
      {{ error }}
    </div>

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
          <div v-else-if="runNarrative" class="mt-4 space-y-4">
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
                  @click="openApprovalsView"
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
                  @click="openApprovalsView"
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
          <el-tag effect="light" type="info">{{ recentNarrativeReflections.length }} latest</el-tag>
        </div>
        <div v-if="runNarrativeLoading" class="mt-4 text-sm text-slate-500">Summarizing latest run decisions…</div>
        <div v-else-if="runNarrativeError" class="mt-4 text-sm text-rose-600">{{ runNarrativeError }}</div>
        <div v-else-if="recentNarrativeReflections.length" class="mt-4 space-y-3">
          <div
            v-for="reflection in recentNarrativeReflections"
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
        <div v-else-if="runNarrative" class="mt-4 space-y-4">
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
      <TaskQueuePanel :tasks="workbenchTasks" />

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

    <div v-if="project" class="grid gap-4 xl:grid-cols-[1.4fr,1fr]">
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
        <div v-if="recentRunCards.length" class="mt-4 grid gap-3">
          <div
            v-for="card in recentRunCards"
            :key="card.run_id"
            class="mission-subcard p-4"
          >
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <div class="font-mono text-sm text-slate-900">{{ card.run_id }}</div>
                  <el-tag :type="runStatusTagType(card.status)" effect="light">{{ card.status }}</el-tag>
                  <el-tag v-if="card.approval_status" :type="approvalTagType(card.approval_status)" effect="light">
                    {{ card.approval_status }}
                  </el-tag>
                </div>
                <div class="mt-2 text-sm text-slate-600">{{ card.goal_text || "No goal summary recorded." }}</div>
                <div class="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
                  <div><strong>Executor:</strong> {{ card.executor }}</div>
                  <div><strong>Branch:</strong> {{ card.branch_name || "—" }}</div>
                  <div><strong>Elapsed:</strong> {{ formatElapsed(card.elapsed_seconds) }}</div>
                  <div><strong>Recoveries:</strong> {{ card.recovery_count }}</div>
                  <div><strong>Artifacts:</strong> {{ card.artifact_count }}</div>
                  <div><strong>Confidence:</strong> {{ formatConfidence(card.confidence_score) }}</div>
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
            <strong>Preview:</strong>
            <span class="ml-1">{{ previewsAndPrs.preview_status }}</span>
            <a
              v-if="previewsAndPrs.preview_url"
              :href="previewsAndPrs.preview_url"
              target="_blank"
              rel="noreferrer"
              class="ml-2 underline"
            >
              Open
            </a>
          </div>
          <div v-if="previewsAndPrs.frontend_url"><strong>Frontend:</strong> <a :href="previewsAndPrs.frontend_url" target="_blank" rel="noreferrer" class="underline">{{ previewsAndPrs.frontend_url }}</a></div>
          <div v-if="previewsAndPrs.backend_url"><strong>Backend:</strong> <a :href="previewsAndPrs.backend_url" target="_blank" rel="noreferrer" class="underline">{{ previewsAndPrs.backend_url }}</a></div>
          <div v-if="previewsAndPrs.frontend_log_path"><strong>Frontend log:</strong> <span class="font-mono text-xs">{{ previewsAndPrs.frontend_log_path }}</span></div>
          <div v-if="previewsAndPrs.backend_log_path"><strong>Backend log:</strong> <span class="font-mono text-xs">{{ previewsAndPrs.backend_log_path }}</span></div>
          <div v-if="previewsAndPrs.preview_expires_at"><strong>Expires:</strong> {{ formatTimestamp(previewsAndPrs.preview_expires_at) }}</div>
          <div v-if="previewsAndPrs.verification_note" class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            {{ previewsAndPrs.verification_note }}
          </div>
          <div v-if="previewLaunchError" class="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {{ previewLaunchError }}
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
          </div>
        </div>
      </div>
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
          <el-button plain size="small" :loading="runMemoryLoading" @click="loadSimilarRuns">Refresh</el-button>
        </div>
        <div v-if="runMemoryLoading" class="mt-4 text-sm text-slate-500">Searching prior runs...</div>
        <div v-else-if="similarRunMatches.length" class="mt-4 space-y-3">
          <div
            v-for="match in similarRunMatches"
            :key="match.run_id"
            class="mission-subcard p-4"
          >
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div class="font-mono text-sm text-slate-900">{{ match.run_id }}</div>
                <div class="text-xs text-slate-500">{{ match.goal || "No goal summary" }}</div>
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
        <div v-if="createPrError" class="text-sm text-rose-600">{{ createPrError }}</div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <el-button :disabled="createPrLoading" @click="createPrDialogOpen = false">Cancel</el-button>
          <el-button type="primary" :loading="createPrLoading" :disabled="!createPrReady" @click="submitCreatePr">
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
import OperatorConsole from "../components/operator/OperatorConsole.vue";
import ExecutionConsolePanel from "../components/workbench/ExecutionConsolePanel.vue";
import ReviewSurfacePanel from "../components/workbench/ReviewSurfacePanel.vue";
import TaskQueuePanel from "../components/workbench/TaskQueuePanel.vue";
import {
  bootstrapProjectContract,
  compareRuns,
  createApproval,
  createRun,
  createRunStrategies,
  createRunPullRequest,
  deleteRunPreview,
  explainArtifact,
  fetchArtifactDiff,
  fetchRunExecutionConsole,
  fetchMissionControlOverview,
  fetchRunNarrative,
  fetchRunStrategies,
  fetchHealth,
  fetchLifecycleScore,
  fetchProjectMeta,
  fetchRunTimeline,
  findSimilarRuns,
  hasRunMemorySearchContext,
  forkRun,
  launchRunPreview,
  listApprovals,
  listArtifacts,
  listRunEvents,
  listRuns,
  listWorkItems,
  patchProjectContract,
  reportRunIssue,
  resumeRun,
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
const missionOverview = ref<any | null>(null);
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
const strategyDialogOpen = ref(false);
const strategyLoading = ref(false);
const strategyRefreshing = ref(false);
const strategyErrorMessage = ref("");
const strategyResult = ref<any | null>(null);
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
const replayDialogOpen = ref(false);
const replayLoading = ref(false);
const replayError = ref("");
const replayResult = ref<any | null>(null);
const replayRunId = ref("");
const resumeLoading = ref(false);
const runNarrativeLoading = ref(false);
const runNarrativeError = ref("");
const runNarrative = ref<any | null>(null);
const projectContractBootstrapLoading = ref(false);
const projectContractEnforcementLoading = ref(false);
const projectContractStrictLoading = ref(false);
const projectContractActionError = ref("");

const projectId = computed(() => (route.params.projectId as string) || "");
const latestRun = computed(() => runs.value[0] || null);
const hasRun = computed(() => Boolean(latestRun.value?.id));
const forkEnabled = computed(() => Boolean(latestRun.value?.id));
const resumeEnabled = computed(() => Boolean(latestRun.value?.id && latestRun.value?.summary?.resume_state?.can_resume));
const compareEnabled = computed(() => runs.value.length >= 2);
const currentStage = computed(() => project.value?.status || "UNKNOWN");
const lifecycleWarnings = computed<string[]>(() => lifecycleScore.value?.warnings || []);
const cancelEnabled = computed(() => ["QUEUED", "RUNNING"].includes(latestRun.value?.status || ""));
const latestErrorHint = computed(() => {
  const erroredItem = workItems.value.find((item) => item.last_error);
  if (erroredItem?.last_error) return String(erroredItem.last_error);
  const failedEvent = runEvents.value.find((event) => typeof event.message === "string" && /fail|error/i.test(event.message));
  return failedEvent?.message || "";
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
const improveReady = computed(() => Boolean(latestRun.value?.id && improveIssueText.value.trim()));
const similarRunMatches = computed(() =>
  (runMemoryResult.value?.matches || []).filter((match: any) => match.run_id !== latestRun.value?.id)
);
const intakeItems = computed(() => missionOverview.value?.work_intake || []);
const recentRunCards = computed(() => missionOverview.value?.recent_runs || []);
const latestChangeImpact = computed(() => missionOverview.value?.latest_change_impact || null);
const previewsAndPrs = computed(() => missionOverview.value?.previews_and_prs || null);
const architectureProfile = computed(() => missionOverview.value?.architecture_profile || null);
const projectContract = computed(() => missionOverview.value?.project_contract || null);
const projectContractProfileExists = computed(() => Boolean(projectContract.value?.profile_exists));
const projectContractActionInFlight = computed(
  () =>
    projectContractBootstrapLoading.value
    || projectContractEnforcementLoading.value
    || projectContractStrictLoading.value
);
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
const previewRunId = computed(
  () => previewsAndPrs.value?.run_id || latestChangeImpact.value?.run_id || latestRun.value?.id || ""
);
const strategyLearning = computed(() => missionOverview.value?.strategy_learning || []);
const systemInsights = computed(() => missionOverview.value?.system_insights || null);
const violationInsights = computed(() => missionOverview.value?.violation_insights || null);
const latestArtifactApproval = computed(() => createPrApprovals.value[0] || null);
const latestArtifactApprovalStatus = computed(() => latestArtifactApproval.value?.status || null);
const createPrReady = computed(
  () => Boolean(selectedPrArtifact.value) && latestArtifactApprovalStatus.value === "APPROVED"
);
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
      title: payload.title || WORK_ITEM_LABELS[wi.type] || humanizeToken(wi.key || wi.type || "work_item"),
      agent: payload.agent || WORK_ITEM_LABELS[wi.type] || humanizeToken(wi.type || wi.executor || "agent"),
      executor: wi.executor,
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
    status: panelStatusFor(item.rawStatus, item.blocking),
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
    blocked: 0,
    warnings: 0,
    canceled: 0,
  };
  displayWorkItems.value.forEach((wi) => {
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
const workbenchTasks = computed(() =>
  displayWorkItems.value.map((item) => {
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
      progress: workbenchProgressForStatus(item.rawStatus),
      logLine:
        item.last_error ||
        latestLogMessageByTask.value.get(item.task_id) ||
        workbenchStatusMessage(item.rawStatus, item.blocking),
      changedArtifacts: relatedArtifacts,
      startedAtLabel: item.started_at ? `Started ${formatTimestamp(item.started_at)}` : "Not started",
      finishedAtLabel: item.finished_at ? `Finished ${formatTimestamp(item.finished_at)}` : "Awaiting completion",
    };
  })
);

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

onMounted(() => {
  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", syncPolling);
  }
});

onBeforeUnmount(() => {
  if (typeof document !== "undefined") {
    document.removeEventListener("visibilitychange", syncPolling);
  }
  stopPolling();
});

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
    runs.value = runList;
    await loadRunRuntime();
    await loadSimilarRuns();
    await loadMissionOverview();
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
    missionOverview.value = await fetchMissionControlOverview(projectId.value);
    overviewError.value = "";
    previewLaunchError.value = "";
  } catch (err: any) {
    missionOverview.value = null;
    overviewError.value = err?.message || "Failed to load Mission Control overview.";
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
    await loadMissionOverview();
    ElMessage.success("Project contract initialized.");
  } catch (err: any) {
    projectContractActionError.value = err?.message || "Failed to initialize project contract.";
  } finally {
    projectContractBootstrapLoading.value = false;
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
    await loadMissionOverview();
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
    await loadMissionOverview();
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
  try {
    await launchRunPreview(previewRunId.value, { reuse_if_healthy: true });
    await loadMissionOverview();
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
  try {
    await deleteRunPreview(previewRunId.value);
    await loadMissionOverview();
  } catch (err: any) {
    previewLaunchError.value = err?.message || "Failed to stop preview.";
  } finally {
    previewLaunchLoading.value = false;
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
    await loadSimilarRuns();
    await loadMissionOverview();
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
  const status = latestRun.value?.status || "";
  if (status !== "QUEUED" && status !== "RUNNING") {
    return null;
  }
  const hidden = typeof document !== "undefined" && document.hidden;
  if (status === "QUEUED") {
    return hidden ? 15000 : 12000;
  }
  return hidden ? 10000 : 6000;
}

async function startRunFromIntake(item: any) {
  if (!projectId.value || cancelEnabled.value) return;
  intakeRunLoadingId.value = item.id;
  overviewError.value = "";
  try {
    const executor = previewsAndPrs.value?.repository_connected ? "codex" : "dummy";
    await createRun(projectId.value, executor);
    await loadAll();
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
    await loadAll();
  } catch (err: any) {
    error.value = err?.message || "Failed to cancel run.";
  }
}

async function resumeLatestRun() {
  if (!latestRun.value?.id || !resumeEnabled.value) return;
  resumeLoading.value = true;
  error.value = "";
  try {
    await resumeRun(latestRun.value.id, { start_now: true });
    await loadAll();
    ElMessage.success("Run resumed from the last safe checkpoint.");
  } catch (err: any) {
    error.value = err?.message || "Failed to resume run.";
  } finally {
    resumeLoading.value = false;
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
    const result = await reportRunIssue(latestRun.value.id, {
      goal: defaultImproveGoal(),
      issue: improveIssueText.value.trim(),
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
    await loadAll();
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
    await loadAll();
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
    await loadAll();
  } catch (err: any) {
    strategyErrorMessage.value = err?.message || "Failed to refresh strategy recommendation.";
  } finally {
    strategyRefreshing.value = false;
  }
}

function goToOverview() {
  router.push(`/projects/${projectId.value}`);
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
    await loadAll();
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
    createPrResult.value = await createRunPullRequest(selectedPrRunId.value, {
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

function panelStatusFor(status?: string | null, blocking = true) {
  if (status === "RUNNING" || status === "CLAIMED") return "Running";
  if (status === "DONE") return "Completed";
  if (status === "WARNING") return "Warning";
  if (status === "SKIPPED") return "Skipped";
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
