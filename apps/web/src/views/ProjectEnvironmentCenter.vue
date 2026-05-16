<template>
  <div class="page-stack" v-if="projectId">
    <section class="premium-card p-6">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div class="text-sm uppercase tracking-wide text-slate-400">Environment Center</div>
          <h1 class="mt-1 text-2xl font-semibold text-slate-900">Project Environment Control Plane</h1>
          <div class="mt-1 text-sm text-slate-500">Manage variables, run validation checks, and sync to deployment providers.</div>
        </div>
        <div class="flex items-center gap-2">
          <el-button plain @click="goToOverview">Project Overview</el-button>
          <el-button plain :loading="loading" @click="loadAll">Refresh</el-button>
        </div>
      </div>
      <div v-if="error" class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-600">
        {{ error }}
      </div>
    </section>

    <section class="surface-grid md:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="Overall Readiness" :value="`${centerScorePct}%`" detail="Aggregated across PREVIEW/STAGING/PRODUCTION.">
        <template #icon><AppIcon name="status" /></template>
      </MetricCard>
      <MetricCard label="Variables" :value="variablesTotal" detail="Configured and pending env variables.">
        <template #icon><AppIcon name="workspace" /></template>
      </MetricCard>
      <MetricCard label="Validation Results" :value="validationResults.length" detail="Latest checks in this session.">
        <template #icon><AppIcon name="spark" /></template>
      </MetricCard>
      <MetricCard label="Sync Status" :value="lastSyncLabel" detail="Most recent provider sync outcome.">
        <template #icon><AppIcon name="mission" /></template>
      </MetricCard>
    </section>

    <section class="premium-card p-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="text-sm uppercase tracking-wide text-slate-400">Environment Scope</div>
        <el-segmented v-model="selectedEnvironment" :options="environmentOptions" size="small" />
      </div>
      <div class="mt-3 text-xs text-slate-500">
        Prompt2PR handles orchestration, retries, and recovery. You provide credentials, domains, integrations, and approvals.
      </div>
      <div class="mt-3 grid gap-2 text-xs text-slate-600 md:grid-cols-3">
        <div class="rounded-xl border border-slate-200 bg-slate-50 p-3">Score: <span class="font-semibold">{{ currentEnvSummary.scorePct }}%</span></div>
        <div class="rounded-xl border border-slate-200 bg-slate-50 p-3">User blockers: <span class="font-semibold">{{ currentEnvSummary.userPending }}</span></div>
        <div class="rounded-xl border border-slate-200 bg-slate-50 p-3">Items: <span class="font-semibold">{{ currentEnvSummary.completed }}/{{ currentEnvSummary.total }}</span></div>
      </div>
      <div class="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
        <div class="font-semibold text-slate-900">Status Panel · {{ selectedEnvironment }}</div>
        <div class="mt-1">
          Variables configured: {{ currentEnvironmentProfile.variables_configured }}/{{ currentEnvironmentProfile.variables_total }}
          · Validation passed: {{ currentEnvironmentProfile.validation_passed }}/{{ currentEnvironmentProfile.validation_total }}
          · Sync healthy: {{ currentEnvironmentProfile.sync_healthy }}/{{ currentEnvironmentProfile.sync_total }}
        </div>
      </div>
      <div class="mt-3 grid gap-2 md:grid-cols-[1fr,auto] md:items-center">
        <div>
          <div class="text-xs uppercase tracking-wide text-slate-400">Environment Template</div>
          <div class="mt-1 text-xs text-slate-600">{{ activeTemplateDescription }}</div>
        </div>
        <div class="flex items-center gap-2">
          <el-select v-model="selectedTemplateKey" class="w-60" placeholder="Select template">
            <el-option v-for="tpl in templateOptions" :key="tpl.key" :label="tpl.name" :value="tpl.key" />
          </el-select>
          <el-switch v-model="includeOptionalTemplateVars" active-text="Include optional" />
          <el-button size="small" type="primary" :disabled="!selectedTemplateKey" :loading="templateApplyLoading" @click="applyTemplate">
            Apply Template
          </el-button>
        </div>
      </div>
    </section>

    <section class="grid gap-4 xl:grid-cols-[1.2fr,0.8fr]">
      <article class="premium-card p-6">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="text-sm uppercase tracking-wide text-slate-400">Environment Variables</div>
          <div class="flex items-center gap-2">
            <el-button size="small" plain @click="openVariableDialog">Add / Update Variable</el-button>
            <el-button size="small" plain @click="loadEnvironmentVariables">Reload</el-button>
          </div>
        </div>
        <div v-if="variables.length" class="mt-4 overflow-auto rounded-xl border border-slate-200">
          <table class="w-full text-left text-xs">
            <thead class="bg-slate-50 text-slate-500">
              <tr>
                <th class="px-3 py-2">Key</th>
                <th class="px-3 py-2">Scope</th>
                <th class="px-3 py-2">Required/Optional</th>
                <th class="px-3 py-2">Masked Status</th>
                <th class="px-3 py-2">Source</th>
                <th class="px-3 py-2">Sync Status</th>
                <th class="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in variables" :key="row.id" class="border-t border-slate-100">
                <td class="px-3 py-2 font-mono text-slate-800">{{ row.var_key }}</td>
                <td class="px-3 py-2 text-slate-600">{{ inferScope(row.var_key) }}</td>
                <td class="px-3 py-2 text-slate-600">{{ row.required ? "Required" : "Optional" }}</td>
                <td class="px-3 py-2">
                  <span class="topbar-chip" :class="row.has_value ? 'text-emerald-700' : 'text-amber-700'">{{ row.has_value ? "Configured" : "Missing" }}</span>
                </td>
                <td class="px-3 py-2 text-slate-600">{{ normalizeSource(row.source) }}</td>
                <td class="px-3 py-2 text-slate-600">{{ rowSyncStatus() }}</td>
                <td class="px-3 py-2">
                  <div class="flex flex-wrap gap-2">
                    <el-button size="small" plain @click="prefillVariableDialog(row)">Edit</el-button>
                    <el-button size="small" plain type="primary" @click="openSecretDialog(row)">Set Secret</el-button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="premium-empty mt-4">No variables configured for this environment yet.</div>
      </article>

      <article class="premium-card p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Validate + Sync</div>
        <div class="mt-4 grid gap-3">
          <el-button :loading="validateLoading" @click="runValidation">Validate Environment</el-button>
          <div class="grid grid-cols-2 gap-2">
            <el-button plain size="small" :loading="syncLoading === 'vercel'" @click="runSync('vercel')">Sync to Vercel</el-button>
            <el-button plain size="small" :loading="syncLoading === 'render'" @click="runSync('render')">Sync to Render</el-button>
          </div>
        </div>

        <div class="mt-4">
          <div class="text-xs uppercase tracking-wide text-slate-400">Missing Vars</div>
          <div v-if="missingRequiredVars.length" class="mt-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            {{ missingRequiredVars.join(", ") }}
          </div>
          <div v-else class="mt-2 text-xs text-emerald-700">No required variables missing for {{ selectedEnvironment }}.</div>
        </div>

        <div class="mt-4">
          <div class="text-xs uppercase tracking-wide text-slate-400">Validation Results</div>
          <div v-if="validationResults.length" class="mt-2 space-y-2">
            <div v-for="result in validationResults" :key="result.id" class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
              <div class="font-semibold" :class="String(result.status).toLowerCase() === 'pass' ? 'text-emerald-700' : 'text-rose-700'">
                {{ result.check_key }} · {{ result.status }}
              </div>
              <div class="text-slate-500">{{ result.message || "Validation passed." }}</div>
            </div>
          </div>
          <div v-else class="mt-2 text-xs text-slate-500">No validation results yet.</div>
        </div>

        <div class="mt-4">
          <div class="text-xs uppercase tracking-wide text-slate-400">Provider Sync Result</div>
          <div v-if="lastSyncResult" class="mt-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
            <div class="font-semibold text-slate-900">{{ lastSyncResult.provider }} · {{ lastSyncResult.status }}</div>
            <div class="text-slate-500">{{ lastSyncResult.message || "Sync complete." }}</div>
          </div>
          <div v-else class="mt-2 text-xs text-slate-500">No provider sync result yet.</div>
        </div>

        <div class="mt-4">
          <div class="text-xs uppercase tracking-wide text-slate-400">Next User Action</div>
          <div v-if="nextUserActions.length" class="mt-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
            {{ nextUserActions.join(" | ") }}
          </div>
          <div v-else class="mt-2 text-xs text-emerald-700">No user-owned blockers for {{ selectedEnvironment }}.</div>
        </div>
      </article>
    </section>

    <section class="premium-card p-6">
      <div class="text-sm uppercase tracking-wide text-slate-400">Deploy Readiness</div>
      <div class="mt-2 text-xs text-slate-600">Flow: Project → Environments → Variables → Validate → Sync → Deploy</div>
      <DeploymentTrustSurfaceCard v-if="deploymentReadinessContract" class="mt-3" :contract="deploymentReadinessContract" />
      <div class="mt-2 grid gap-2 text-xs md:grid-cols-2">
        <div class="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div class="font-semibold text-slate-900">What Blocks Production</div>
          <div class="mt-1 text-slate-600">{{ productionBlockerText }}</div>
        </div>
        <div class="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div class="font-semibold text-slate-900">What Can Be Synced / Deployed Now</div>
          <div class="mt-1 text-slate-600">{{ syncDeployNowText }}</div>
        </div>
      </div>
    </section>

    <el-dialog v-model="variableDialogOpen" title="Environment Variable" width="560px">
      <div class="space-y-3">
        <el-input v-model="variableForm.var_key" placeholder="Variable key (e.g. DATABASE_URL)" />
        <el-input v-model="variableForm.vault_ref" placeholder="Vault ref (optional; auto-generated if empty)" />
        <el-switch v-model="variableForm.required" active-text="Required" inactive-text="Optional" />
        <el-select v-model="variableForm.source" class="w-full" placeholder="Source">
          <el-option label="Project" value="project" />
          <el-option label="Workspace" value="workspace" />
          <el-option label="Platform" value="platform" />
        </el-select>
        <div v-if="variableDialogError" class="text-sm text-rose-600">{{ variableDialogError }}</div>
      </div>
      <template #footer>
        <el-button @click="variableDialogOpen = false">Cancel</el-button>
        <el-button type="primary" :loading="variableDialogLoading" @click="saveVariable">Save</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="secretDialogOpen" title="Set Secret" width="560px">
      <div class="space-y-3">
        <div class="text-xs text-slate-500">{{ secretDialogLabel }}</div>
        <el-input v-model="secretValue" type="textarea" :rows="4" placeholder="Paste secret value" show-password />
        <div class="text-xs text-slate-500">Secret values are never shown after save.</div>
        <div v-if="secretDialogError" class="text-sm text-rose-600">{{ secretDialogError }}</div>
      </div>
      <template #footer>
        <el-button @click="secretDialogOpen = false">Cancel</el-button>
        <el-button type="primary" :loading="secretDialogLoading" @click="saveSecret">Write Secret</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";

import AppIcon from "../components/AppIcon.vue";
import DeploymentTrustSurfaceCard from "../components/DeploymentTrustSurfaceCard.vue";
import MetricCard from "../components/MetricCard.vue";
import {
  applyProjectEnvironmentTemplate,
  fetchProjectDeploymentReadiness,
  getProjectEnvironmentCenter,
  getProjectEnvironmentChecklists,
  listProjectEnvironmentTemplates,
  listProjectEnvironmentVariables,
  syncProjectEnvironment,
  upsertProjectEnvironmentVariable,
  validateProjectEnvironment,
  writeProjectEnvironmentVariableSecret,
  type EnvironmentSyncStatusRow,
  type EnvironmentTemplate,
  type EnvironmentValidationResultRow,
  type ProjectEnvironmentVariableRow,
} from "../api/lifecycle";

const route = useRoute();
const router = useRouter();

const projectId = computed(() => String(route.params.projectId || ""));
const loading = ref(false);
const error = ref("");

const selectedEnvironment = ref<"PREVIEW" | "STAGING" | "PRODUCTION">("PREVIEW");
const environmentOptions = [
  { label: "PREVIEW", value: "PREVIEW" },
  { label: "STAGING", value: "STAGING" },
  { label: "PRODUCTION", value: "PRODUCTION" },
];

const environmentCenter = ref<any | null>(null);
const environmentChecklist = ref<any | null>(null);
const variables = ref<ProjectEnvironmentVariableRow[]>([]);
const templates = ref<EnvironmentTemplate[]>([]);
const validationResults = ref<EnvironmentValidationResultRow[]>([]);
const lastSyncResult = ref<EnvironmentSyncStatusRow | null>(null);
const deploymentReadinessContract = ref<any | null>(null);
const validateLoading = ref(false);
const syncLoading = ref<"" | "vercel" | "render">("");
const selectedTemplateKey = ref("");
const includeOptionalTemplateVars = ref(true);
const templateApplyLoading = ref(false);

const variableDialogOpen = ref(false);
const variableDialogLoading = ref(false);
const variableDialogError = ref("");
const variableForm = ref({
  var_key: "",
  vault_ref: "",
  required: true,
  source: "project",
  validation_regex: "",
});

const secretDialogOpen = ref(false);
const secretDialogLoading = ref(false);
const secretDialogError = ref("");
const secretTarget = ref<ProjectEnvironmentVariableRow | null>(null);
const secretValue = ref("");

const centerScorePct = computed(() => Number(environmentChecklist.value?.score_pct || 0));
const variablesTotal = computed(() => variables.value.length);
const lastSyncLabel = computed(() => {
  if (!lastSyncResult.value) return "No sync yet";
  return `${lastSyncResult.value.provider}:${lastSyncResult.value.status}`;
});

const currentEnvSummary = computed(() => {
  const env = selectedEnvironment.value;
  const row = Array.isArray(environmentChecklist.value?.environments)
    ? environmentChecklist.value.environments.find((item: any) => String(item?.environment || "").toUpperCase() === env)
    : null;
  return {
    scorePct: Number(row?.score_pct || 0),
    userPending: Number(row?.user_pending || 0),
    completed: Number(row?.completed || 0),
    total: Number(row?.total || 0),
  };
});

const currentEnvironmentProfile = computed(() => {
  const env = selectedEnvironment.value;
  const row = Array.isArray(environmentCenter.value?.environments)
    ? environmentCenter.value.environments.find((item: any) => String(item?.environment || "").toUpperCase() === env)
    : null;
  return {
    variables_configured: Number(row?.variables_configured || 0),
    variables_total: Number(row?.variables_total || 0),
    validation_passed: Number(row?.validation_passed || 0),
    validation_total: Number(row?.validation_total || 0),
    sync_healthy: Number(row?.sync_healthy || 0),
    sync_total: Number(row?.sync_total || 0),
  };
});

const secretDialogLabel = computed(() => {
  if (!secretTarget.value) return "";
  return `${secretTarget.value.environment} · ${secretTarget.value.var_key}`;
});

const templateOptions = computed(() => templates.value.map((tpl) => ({ key: tpl.key, name: tpl.name })));
const activeTemplateDescription = computed(() => {
  const selected = templates.value.find((tpl) => tpl.key === selectedTemplateKey.value);
  if (!selected) return "Select a template to preseed required environment variables and validation rules.";
  const providerHint = selected.deployment_targets.length ? ` Targets: ${selected.deployment_targets.join(", ")}.` : "";
  return `${selected.description}.${providerHint}`;
});

const missingRequiredVars = computed(() => variables.value.filter((row) => Boolean(row.required) && !row.has_value).map((row) => row.var_key));

const nextUserActions = computed(() => {
  const env = selectedEnvironment.value;
  const rows = Array.isArray(environmentChecklist.value?.items) ? environmentChecklist.value.items : [];
  return rows
    .filter((row: any) => String(row?.environment || "").toUpperCase() === env)
    .filter((row: any) => String(row?.owner || "").toLowerCase() === "user")
    .filter((row: any) => String(row?.status || "").toLowerCase() !== "done")
    .map((row: any) => String(row?.label || row?.item_key || "Complete required setup"));
});

const productionBlockerText = computed(() => {
  const blockers: string[] = [];
  if (missingRequiredVars.value.length) blockers.push(`Missing required variables: ${missingRequiredVars.value.join(", ")}`);
  if (currentEnvSummary.value.userPending > 0) blockers.push(`${currentEnvSummary.value.userPending} user-owned checklist blockers`);
  if (lastSyncResult.value && String(lastSyncResult.value.status || "").toLowerCase() === "failed") {
    blockers.push(`Provider sync failed (${lastSyncResult.value.provider})`);
  }
  return blockers.length ? blockers.join(" | ") : "No active blockers detected for this environment.";
});

const syncDeployNowText = computed(() => {
  if (missingRequiredVars.value.length) return "Add missing required variables, then re-run validation.";
  if (!validationResults.value.length) return "Run Validate Environment to produce evidence before deploy.";
  const hasValidationFailure = validationResults.value.some((row) => String(row.status || "").toLowerCase() !== "pass");
  if (hasValidationFailure) return "Resolve validation failures before sync/deploy.";
  if (!lastSyncResult.value) return "Validation passed. Sync to provider now.";
  if (String(lastSyncResult.value.status || "").toLowerCase() === "failed") return "Fix provider connector or secret and retry sync.";
  return "Synced and validated. Safe to continue to deploy and promote.";
});

function normalizeSource(source?: string | null) {
  const value = String(source || "").trim().toLowerCase();
  if (value === "workspace") return "workspace";
  if (value === "platform") return "platform";
  return "project";
}

function inferScope(varKey: string) {
  const key = String(varKey || "").toUpperCase();
  if (key.startsWith("NEXT_PUBLIC_") || key.startsWith("VITE_") || key.startsWith("REACT_APP_")) return "frontend";
  if (key.startsWith("API_") || key.startsWith("BACKEND_") || key.startsWith("SERVER_")) return "backend";
  return "shared";
}

function rowSyncStatus() {
  if (!lastSyncResult.value) return "Not synced";
  const status = String(lastSyncResult.value.status || "").toLowerCase();
  if (status === "failed") return "Sync failed";
  if (lastSyncResult.value.drift_detected) return "Drift detected";
  return "Synced";
}

function goToOverview() {
  if (!projectId.value) return;
  router.push(`/projects/${projectId.value}`);
}

async function loadEnvironmentVariables() {
  if (!projectId.value) return;
  try {
    variables.value = await listProjectEnvironmentVariables(projectId.value, selectedEnvironment.value);
  } catch (err: any) {
    variables.value = [];
    error.value = err?.message || "Failed to load environment variables.";
  }
}

async function loadAll() {
  if (!projectId.value) return;
  loading.value = true;
  error.value = "";
  try {
    const [center, checklist] = await Promise.all([
      getProjectEnvironmentCenter(projectId.value),
      getProjectEnvironmentChecklists(projectId.value, false),
    ]);
    environmentCenter.value = center;
    environmentChecklist.value = checklist;
    try {
      templates.value = await listProjectEnvironmentTemplates(projectId.value);
      if (!selectedTemplateKey.value && templates.value.length) selectedTemplateKey.value = templates.value[0].key;
    } catch {
      templates.value = [];
    }
    await loadEnvironmentVariables();
    try {
      deploymentReadinessContract.value = await fetchProjectDeploymentReadiness(projectId.value, selectedEnvironment.value);
    } catch {
      deploymentReadinessContract.value = null;
    }
  } catch (err: any) {
    environmentCenter.value = { environments: [] };
    environmentChecklist.value = { score_pct: 0, environments: [], items: [] };
    variables.value = [];
    validationResults.value = [];
    lastSyncResult.value = null;
    deploymentReadinessContract.value = null;
    error.value = err?.message || "Failed to load environment center.";
  } finally {
    loading.value = false;
  }
}

async function applyTemplate() {
  if (!projectId.value || !selectedTemplateKey.value) return;
  templateApplyLoading.value = true;
  try {
    await applyProjectEnvironmentTemplate(projectId.value, selectedTemplateKey.value, {
      environment: selectedEnvironment.value,
      include_optional: includeOptionalTemplateVars.value,
    });
    await loadAll();
    ElMessage.success(`Template applied to ${selectedEnvironment.value}.`);
  } catch (err: any) {
    error.value = err?.message || "Failed to apply environment template.";
  } finally {
    templateApplyLoading.value = false;
  }
}

function openVariableDialog() {
  variableDialogError.value = "";
  variableForm.value = {
    var_key: "",
    vault_ref: "",
    required: true,
    source: "project",
    validation_regex: "",
  };
  variableDialogOpen.value = true;
}

function prefillVariableDialog(row: ProjectEnvironmentVariableRow) {
  variableDialogError.value = "";
  variableForm.value = {
    var_key: row.var_key,
    vault_ref: row.vault_ref || "",
    required: Boolean(row.required),
    source: normalizeSource(row.source),
    validation_regex: row.validation_regex || "",
  };
  variableDialogOpen.value = true;
}

async function saveVariable() {
  if (!projectId.value) return;
  const key = variableForm.value.var_key.trim();
  if (!key) {
    variableDialogError.value = "Variable key is required.";
    return;
  }
  variableDialogLoading.value = true;
  variableDialogError.value = "";
  try {
    const fallbackVaultRef = `workspace/project/${projectId.value}/${selectedEnvironment.value}/${key}`.toLowerCase();
    await upsertProjectEnvironmentVariable(projectId.value, selectedEnvironment.value, key, {
      value_kind: "secret",
      vault_ref: variableForm.value.vault_ref || fallbackVaultRef,
      required: Boolean(variableForm.value.required),
      source: variableForm.value.source || "project",
      validation_regex: variableForm.value.validation_regex || null,
    });
    variableDialogOpen.value = false;
    await loadAll();
    const saved = variables.value.find((row) => row.var_key === key);
    if (saved) openSecretDialog(saved);
    ElMessage.success("Variable metadata saved. Use Set Secret to write the value.");
  } catch (err: any) {
    variableDialogError.value = err?.message || "Failed to save variable.";
  } finally {
    variableDialogLoading.value = false;
  }
}

function openSecretDialog(row: ProjectEnvironmentVariableRow) {
  secretTarget.value = row;
  secretValue.value = "";
  secretDialogError.value = "";
  secretDialogOpen.value = true;
}

async function saveSecret() {
  if (!projectId.value || !secretTarget.value) return;
  if (!secretValue.value.trim()) {
    secretDialogError.value = "Secret value is required.";
    return;
  }
  secretDialogLoading.value = true;
  secretDialogError.value = "";
  try {
    await writeProjectEnvironmentVariableSecret(
      projectId.value,
      selectedEnvironment.value,
      secretTarget.value.var_key,
      secretValue.value.trim()
    );
    secretDialogOpen.value = false;
    secretValue.value = "";
    await loadAll();
    ElMessage.success("Secret written to vault reference.");
  } catch (err: any) {
    secretDialogError.value = err?.message || "Failed to write secret.";
  } finally {
    secretDialogLoading.value = false;
  }
}

async function runValidation() {
  if (!projectId.value) return;
  validateLoading.value = true;
  try {
    validationResults.value = await validateProjectEnvironment(projectId.value, selectedEnvironment.value, {});
    ElMessage.success("Validation checks completed.");
  } catch (err: any) {
    validationResults.value = [];
    error.value = err?.message || "Validation failed.";
  } finally {
    validateLoading.value = false;
  }
}

async function runSync(provider: "vercel" | "render") {
  if (!projectId.value) return;
  syncLoading.value = provider;
  try {
    lastSyncResult.value = await syncProjectEnvironment(projectId.value, selectedEnvironment.value, provider, {});
    ElMessage.success(`Sync requested for ${provider}.`);
  } catch (err: any) {
    lastSyncResult.value = null;
    error.value = err?.message || `Sync failed for ${provider}.`;
  } finally {
    syncLoading.value = "";
  }
}

onMounted(async () => {
  await loadAll();
});

watch(selectedEnvironment, async () => {
  validationResults.value = [];
  lastSyncResult.value = null;
  await loadEnvironmentVariables();
  if (projectId.value) {
    try {
      deploymentReadinessContract.value = await fetchProjectDeploymentReadiness(projectId.value, selectedEnvironment.value);
    } catch {
      deploymentReadinessContract.value = null;
    }
  }
});
</script>
