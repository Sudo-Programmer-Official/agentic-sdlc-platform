<template>
  <div class="page-stack">
    <section class="landing-hero premium-hero">
      <span class="landing-badge">Autonomous Software Delivery Control Plane</span>
      <div class="premium-hero__eyebrow">Governed AI Software Operations Platform</div>
      <h1 class="premium-hero__title landing-title">Software delivery that remembers, governs, and recovers.</h1>
      <p class="premium-hero__copy landing-copy">
        Sudo Programmer is AI-native software delivery infrastructure for teams that need reliable autonomous execution, not stateless AI output.
      </p>
      <div class="landing-chip-row">
        <span class="landing-chip">Persistent Engineering Memory</span>
        <span class="landing-chip">Deterministic Recovery</span>
        <span class="landing-chip">Architecture-Aware Execution</span>
      </div>
      <div class="mt-7 flex flex-wrap gap-3">
        <el-button type="primary" size="large" :loading="loading" @click="handlePrimaryCreateAction">Start Control Plane</el-button>
        <el-button size="large" plain @click="focusProjectInput">Open Existing Project</el-button>
      </div>
      <div class="landing-signal-grid">
        <article class="landing-signal-card">
          <div class="landing-signal-card__label">Category</div>
          <div class="landing-signal-card__value">Autonomous Software Delivery Platform</div>
        </article>
        <article class="landing-signal-card">
          <div class="landing-signal-card__label">System Role</div>
          <div class="landing-signal-card__value">Orchestration layer above planning, code, and deployment tools</div>
        </article>
        <article class="landing-signal-card">
          <div class="landing-signal-card__label">Moat</div>
          <div class="landing-signal-card__value">Governed execution + compounding engineering memory</div>
        </article>
      </div>
    </section>

    <section class="landing-actions-grid">
      <article class="premium-card landing-action-card">
        <header>
          <div class="landing-action-card__eyebrow">Fastest Path</div>
          <h3>Launch a New Control Plane</h3>
          <p>Define a mission and begin governed execution with full run lineage.</p>
        </header>
        <el-button type="primary" :loading="loading" @click="focusCreateProjectForm">Create Project</el-button>
      </article>
      <article class="premium-card landing-action-card">
        <header>
          <div class="landing-action-card__eyebrow">Resume Runtime</div>
          <h3>Open Existing Operations</h3>
          <p>Continue from prior project context, artifacts, and recovery history.</p>
        </header>
        <el-button plain @click="focusProjectInput">Open Project</el-button>
      </article>
      <article class="premium-card landing-action-card">
        <header>
          <div class="landing-action-card__eyebrow">Sandbox Run</div>
          <h3>Use Demo Inputs</h3>
          <p>Preload a mission statement and generate a realistic starter loop.</p>
        </header>
        <el-button plain @click="seedDemoContent">Seed Demo</el-button>
      </article>
    </section>

    <section class="surface-grid md:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="Recent Projects" :value="recentProjects.length" detail="Projects available to open right away.">
        <template #icon><AppIcon name="workspace" /></template>
      </MetricCard>
      <MetricCard label="Connected Context" :value="connectedProjects" detail="Projects with active context in local history.">
        <template #icon><AppIcon name="project" /></template>
      </MetricCard>
      <MetricCard label="Automation Status" :value="systemStatusLabel" :detail="systemStatusDetail">
        <template #icon><AppIcon name="mission" /></template>
      </MetricCard>
      <MetricCard label="Environment" :value="envLabel" detail="Current control-plane target.">
        <template #icon><AppIcon name="status" /></template>
      </MetricCard>
    </section>

    <section class="landing-value-grid">
      <article class="landing-value premium-card">
        <h3>Fragmented delivery is the bottleneck</h3>
        <p>Requirements in one tool, PRs in another, docs stale, and AI sessions stateless.</p>
      </article>
      <article class="landing-value premium-card">
        <h3>Governance-first execution loop</h3>
        <p>Every run is tracked with lineage, architecture context, and reviewable outcomes.</p>
      </article>
      <article class="landing-value premium-card">
        <h3>Operational reliability over demos</h3>
        <p>Designed for repeatable execution loops that teams can trust in production delivery.</p>
      </article>
    </section>

    <section class="premium-card landing-guided-flow">
      <header class="landing-guided-flow__header">
        <div>
          <div class="premium-hero__eyebrow">Operator Onboarding</div>
          <h2>Three-step setup with no dead ends.</h2>
        </div>
        <div class="landing-guided-flow__progress">{{ onboardingProgress }}</div>
      </header>
      <div class="landing-guided-flow__grid">
        <article class="landing-step" :class="{ 'is-complete': recentProjects.length > 0 }">
          <span>01</span>
          <h3>Project Genesis</h3>
          <p>Create a project record with mission context and desired delivery scope.</p>
        </article>
        <article class="landing-step" :class="{ 'is-complete': recentProjects.length > 0 }">
          <span>02</span>
          <h3>Context Activation</h3>
          <p>Open the project to hydrate architecture context and recent execution memory.</p>
        </article>
        <article class="landing-step">
          <span>03</span>
          <h3>Governed Run</h3>
          <p>Start mission execution, monitor recovery, and review generated delivery artifacts.</p>
        </article>
      </div>
    </section>

    <section class="grid gap-4 xl:grid-cols-[1.1fr,1fr]">
      <div ref="createProjectSection" class="premium-card p-6">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Create Project</div>
            <div class="mt-1 text-xs text-slate-500">Start a new autonomous SDLC pipeline with a clean project record.</div>
          </div>
          <span class="topbar-chip">New</span>
        </div>
        <div class="mt-5 grid gap-3">
          <el-input ref="projectNameInput" v-model="projectName" placeholder="Project name" />
          <el-input v-model="projectDescription" placeholder="Describe the mission or product area" />
          <div class="flex flex-wrap gap-3">
            <el-button type="primary" :loading="loading" @click="createProject">Create Project</el-button>
            <el-button plain @click="seedDemoContent">Use Demo Values</el-button>
          </div>
          <div v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-600">
            {{ error }}
          </div>
        </div>
      </div>

      <div class="premium-card p-6">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Open Project</div>
            <div class="mt-1 text-xs text-slate-500">Jump into an existing automation workspace by ID or recent history.</div>
          </div>
          <span class="topbar-chip">Live</span>
        </div>
        <div class="mt-5 grid gap-3">
          <el-input ref="projectIdInput" v-model="projectId" placeholder="Paste project ID" />
          <el-button :loading="loading" @click="openProject">Open Project</el-button>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
            Mission Control becomes available as soon as a project has an active or historical run.
          </div>
        </div>
      </div>
    </section>

    <section class="grid gap-4 xl:grid-cols-[1.2fr,0.8fr]">
      <div class="premium-card p-6">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-sm uppercase tracking-wide text-slate-400">Recent Projects</div>
            <div class="mt-1 text-xs text-slate-500">Resume a previous workspace with one click.</div>
          </div>
          <el-button plain size="small" @click="refreshProjects">Refresh</el-button>
        </div>
        <div v-if="recentProjects.length" class="mt-4 grid gap-3">
          <button
            v-for="project in recentProjects"
            :key="project.id"
            type="button"
            class="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-left transition duration-200 hover:-translate-y-0.5"
            @click="openKnownProject(project.id)"
          >
            <div class="flex items-center justify-between gap-3">
              <div>
                <div class="text-sm font-semibold text-slate-900">{{ project.name }}</div>
                <div class="mt-1 font-mono text-xs text-slate-500">{{ project.id }}</div>
              </div>
              <span class="topbar-chip">Open</span>
            </div>
          </button>
        </div>
        <div v-else class="premium-empty mt-4">
          No recent projects yet.
        </div>
      </div>

      <div class="premium-card p-6">
        <div class="text-sm uppercase tracking-wide text-slate-400">Execution Thesis</div>
        <div class="mt-4 space-y-3">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div class="text-xs uppercase tracking-wide text-slate-400">What this platform operates</div>
            <div class="mt-2 text-sm text-slate-600">
              Goal intake, repo-backed runs, deterministic healing, artifact explainability, run comparison, and pull request delivery.
            </div>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div class="text-xs uppercase tracking-wide text-slate-400">Primary operating motion</div>
            <div class="mt-2 text-sm text-slate-600">
              Use this system internally at high volume, capture reliability metrics, and convert execution evidence into sales and investor proof.
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="premium-card landing-roadmap">
      <header>
        <div class="premium-hero__eyebrow">Roadmap Discipline</div>
        <h2>Stability now. Intelligence next. Autonomy after.</h2>
      </header>
      <div class="landing-roadmap-grid">
        <article>
          <span>0-3 Months</span>
          <h3>Stability + Repeatability</h3>
          <p>10 consecutive stable runs, deterministic recovery, zero stuck states, and consistent lineage.</p>
        </article>
        <article>
          <span>3-6 Months</span>
          <h3>Repository Intelligence</h3>
          <p>Impact analysis, semantic repo graph, architecture graph, and validation prediction.</p>
        </article>
        <article>
          <span>6-12 Months</span>
          <h3>Governed Autonomy</h3>
          <p>Requirements decompose, governed runs execute, recover automatically, and deploy safely.</p>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";

import AppIcon from "../components/AppIcon.vue";
import MetricCard from "../components/MetricCard.vue";
import { updateProjectContext } from "../state/projectContext";
import { uiTheme } from "../state/uiTheme";

const DEFAULT_API_BASE = import.meta.env.DEV
  ? "http://localhost:8000/api/v1"
  : "https://api.prompt2pr.com/api/v1";

const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;

const router = useRouter();
const route = useRoute();
const projectIdInput = ref<any | null>(null);
const projectNameInput = ref<any | null>(null);
const createProjectSection = ref<HTMLElement | null>(null);
const projectName = ref("");
const projectDescription = ref("");
const projectId = ref("");
const loading = ref(false);
const error = ref("");
const recentProjects = ref<Array<{ id: string; name: string }>>([]);
const environment = ref("production");

const connectedProjects = computed(() => recentProjects.value.length);
const systemStatusLabel = computed(() => (recentProjects.value.length ? "Ready" : "Bootstrapping"));
const systemStatusDetail = computed(() =>
  recentProjects.value.length
    ? "Recent project context is available."
    : "Create or open a project to initialize the workspace."
);
const envLabel = computed(() => environment.value || (uiTheme.mode === "dark" ? "production" : "local"));
const onboardingProgress = computed(() => (recentProjects.value.length > 0 ? "67% complete" : "33% complete"));

onMounted(() => {
  void hydrateGitHubInstallRedirect();
  void refreshProjects();
  void hydrateEnvironment();
  hydrateMissingProjectNotice();
});

watch(
  () => [route.query.installation_id, route.query.setup_action, route.query.state],
  () => {
    void hydrateGitHubInstallRedirect();
  }
);

watch(
  () => route.query.missingProject,
  () => {
    hydrateMissingProjectNotice();
  }
);

async function refreshProjects() {
  try {
    const response = await fetch(`${API_BASE}/projects`);
    if (!response.ok) return;
    const data = await response.json();
    recentProjects.value = Array.isArray(data)
      ? data.map((item: any) => ({ id: item.id, name: item.name || "Project" })).slice(0, 8)
      : [];
  } catch {
    recentProjects.value = loadRecentProjects();
  }
}

async function hydrateEnvironment() {
  try {
    const detail = await fetch(`${API_BASE}/health/detail`).then((r) => r.json());
    if (typeof detail?.environment === "string" && detail.environment) {
      environment.value = detail.environment;
    }
  } catch {
    environment.value = "production";
  }
}

async function hydrateGitHubInstallRedirect() {
  const rawInstallationId = Array.isArray(route.query.installation_id)
    ? route.query.installation_id[0]
    : route.query.installation_id;
  const installationId = Number.parseInt(String(rawInstallationId || ""), 10);
  if (!Number.isFinite(installationId) || installationId <= 0) return;

  const rawState = Array.isArray(route.query.state) ? route.query.state[0] : route.query.state;
  let targetProjectId = "";
  if (rawState) {
    try {
      const parsed = JSON.parse(window.atob(String(rawState)));
      targetProjectId = typeof parsed?.projectId === "string" ? parsed.projectId : "";
    } catch {
      targetProjectId = "";
    }
  }

  if (!targetProjectId) return;

  await router.replace({
    path: `/projects/${targetProjectId}`,
    query: {
      installation_id: String(installationId),
      setup_action: Array.isArray(route.query.setup_action) ? route.query.setup_action[0] : route.query.setup_action,
    },
  });
}

function hydrateMissingProjectNotice() {
  const rawMissingProject = Array.isArray(route.query.missingProject)
    ? route.query.missingProject[0]
    : route.query.missingProject;

  if (!rawMissingProject) {
    return;
  }

  projectId.value = String(rawMissingProject);
  error.value = `Project ${rawMissingProject} was not found in the current backend. Create a new project or open one from Recent Projects.`;
  window.setTimeout(() => {
    projectIdInput.value?.focus?.();
  }, 120);
}

async function createProject() {
  if (!projectName.value.trim()) {
    error.value = "Project name is required.";
    focusCreateProjectForm();
    ElMessage.warning(error.value);
    return;
  }
  error.value = "";
  loading.value = true;
  try {
    const response = await fetch(`${API_BASE}/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: projectName.value,
        description: projectDescription.value || null,
      }),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const data = await response.json();
    updateProjectContext({
      projectId: data.id,
      projectName: data.name,
      stage: data.current_stage || "INTAKE",
      runStatus: "IDLE",
      latestRunId: "",
      activeAgents: 0,
      updatedAt: new Date().toISOString(),
    });
    saveRecentProjects([{ id: data.id, name: data.name }, ...recentProjects.value]);
    router.push(`/projects/${data.id}`);
  } catch (err: any) {
    error.value = err?.message || "Failed to create project.";
  } finally {
    loading.value = false;
  }
}

function openProject() {
  if (!projectId.value.trim()) {
    error.value = "Project ID is required.";
    return;
  }
  error.value = "";
  router.push(`/projects/${projectId.value.trim()}`);
}

function openKnownProject(id: string) {
  router.push(`/projects/${id}`);
}

function handlePrimaryCreateAction() {
  if (!projectName.value.trim()) {
    error.value = "Enter a project name to create a new workspace.";
    focusCreateProjectForm();
    ElMessage.warning(error.value);
    return;
  }
  void createProject();
}

function focusCreateProjectForm() {
  createProjectSection.value?.scrollIntoView({ behavior: "smooth", block: "center" });
  window.setTimeout(() => {
    projectNameInput.value?.focus?.();
  }, 120);
}

function focusProjectInput() {
  projectIdInput.value?.focus?.();
}

function seedDemoContent() {
  projectName.value = "Autonomous Bug Fix Control Plane";
  projectDescription.value = "Governed repo operator flow with healing, replay, comparison, and PR creation.";
}

function loadRecentProjects() {
  try {
    const stored = localStorage.getItem("recentProjects");
    if (!stored) return [];
    const parsed = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveRecentProjects(projects: Array<{ id: string; name: string }>) {
  const unique = projects.reduce<Array<{ id: string; name: string }>>((acc, project) => {
    if (!project?.id || acc.find((item) => item.id === project.id)) return acc;
    acc.push(project);
    return acc;
  }, []);
  recentProjects.value = unique.slice(0, 8);
  localStorage.setItem("recentProjects", JSON.stringify(recentProjects.value));
}
</script>

<style scoped>
.landing-hero {
  isolation: isolate;
}

.landing-hero::after {
  content: "";
  position: absolute;
  inset: auto -6% -55% auto;
  height: 22rem;
  width: 22rem;
  border-radius: 999px;
  background: radial-gradient(circle, rgba(91, 156, 255, 0.24), transparent 70%);
  z-index: -1;
  pointer-events: none;
}

.landing-badge {
  display: inline-flex;
  margin-bottom: 0.9rem;
  padding: 0.4rem 0.78rem;
  border-radius: 999px;
  border: 1px solid rgba(91, 156, 255, 0.26);
  background: rgba(91, 156, 255, 0.12);
  font-size: 0.72rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-strong);
}

.landing-title {
  max-width: 16ch;
}

.landing-copy {
  max-width: 64ch;
}

.landing-chip-row {
  margin-top: 1rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
}

.landing-chip {
  display: inline-flex;
  padding: 0.35rem 0.7rem;
  border-radius: 999px;
  border: 1px solid var(--border-soft);
  background: var(--surface-soft);
  font-size: 0.76rem;
  color: var(--text-muted);
}

.landing-signal-grid {
  margin-top: 1.5rem;
  display: grid;
  gap: 0.8rem;
}

@media (min-width: 980px) {
  .landing-signal-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.landing-signal-card {
  border: 1px solid var(--border-soft);
  border-radius: 16px;
  background: linear-gradient(180deg, color-mix(in srgb, var(--surface-2) 92%, transparent), color-mix(in srgb, var(--surface-soft) 80%, transparent));
  padding: 0.9rem;
}

.landing-signal-card__label {
  font-size: 0.68rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--text-soft);
}

.landing-signal-card__value {
  margin-top: 0.42rem;
  font-size: 0.9rem;
  line-height: 1.45;
  color: var(--text-strong);
}

.landing-value-grid {
  display: grid;
  gap: 0.9rem;
}

@media (min-width: 980px) {
  .landing-value-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.landing-value {
  padding: 1.1rem;
}

.landing-value h3 {
  margin: 0;
  font-size: 1rem;
  color: var(--text-strong);
}

.landing-value p {
  margin: 0.55rem 0 0;
  font-size: 0.9rem;
  line-height: 1.5;
  color: var(--text-muted);
}

.landing-roadmap {
  padding: 1.2rem;
}

.landing-roadmap h2 {
  margin: 0.75rem 0 0;
  font-size: clamp(1.45rem, 2.2vw, 2.1rem);
  line-height: 1.08;
  font-family: "Space Grotesk", ui-sans-serif, system-ui;
}

.landing-roadmap-grid {
  margin-top: 1rem;
  display: grid;
  gap: 0.9rem;
}

@media (min-width: 980px) {
  .landing-roadmap-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.landing-roadmap-grid article {
  border: 1px solid var(--border-soft);
  border-radius: 18px;
  background: var(--surface-soft);
  padding: 1rem;
}

.landing-roadmap-grid article span {
  font-size: 0.68rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-soft);
}

.landing-roadmap-grid article h3 {
  margin: 0.55rem 0 0;
  font-size: 1rem;
  color: var(--text-strong);
}

.landing-roadmap-grid article p {
  margin: 0.42rem 0 0;
  font-size: 0.88rem;
  line-height: 1.5;
  color: var(--text-muted);
}

.landing-actions-grid {
  display: grid;
  gap: 0.9rem;
}

@media (min-width: 980px) {
  .landing-actions-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.landing-action-card {
  padding: 1.05rem;
  display: grid;
  gap: 0.9rem;
  align-content: space-between;
}

.landing-action-card__eyebrow {
  font-size: 0.66rem;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  color: var(--text-soft);
}

.landing-action-card h3 {
  margin: 0.5rem 0 0;
  font-size: 1rem;
  color: var(--text-strong);
}

.landing-action-card p {
  margin: 0.48rem 0 0;
  font-size: 0.88rem;
  line-height: 1.45;
  color: var(--text-muted);
}

.landing-guided-flow {
  padding: 1.15rem;
}

.landing-guided-flow__header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.9rem;
}

.landing-guided-flow__header h2 {
  margin: 0.65rem 0 0;
  font-family: "Space Grotesk", ui-sans-serif, system-ui;
  font-size: clamp(1.2rem, 2vw, 1.7rem);
  color: var(--text-strong);
}

.landing-guided-flow__progress {
  border: 1px solid var(--border-soft);
  border-radius: 999px;
  background: var(--surface-soft);
  padding: 0.35rem 0.68rem;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.landing-guided-flow__grid {
  margin-top: 1rem;
  display: grid;
  gap: 0.8rem;
}

@media (min-width: 980px) {
  .landing-guided-flow__grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.landing-step {
  border: 1px solid var(--border-soft);
  border-radius: 16px;
  background: var(--surface-soft);
  padding: 0.95rem;
}

.landing-step span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 1.7rem;
  width: 1.7rem;
  border-radius: 999px;
  border: 1px solid var(--border-soft);
  font-size: 0.72rem;
  color: var(--text-soft);
}

.landing-step h3 {
  margin: 0.58rem 0 0;
  font-size: 0.95rem;
  color: var(--text-strong);
}

.landing-step p {
  margin: 0.38rem 0 0;
  font-size: 0.85rem;
  line-height: 1.45;
  color: var(--text-muted);
}

.landing-step.is-complete {
  border-color: rgba(34, 197, 94, 0.26);
  background: linear-gradient(180deg, rgba(34, 197, 94, 0.12), rgba(34, 197, 94, 0.03));
}
</style>
