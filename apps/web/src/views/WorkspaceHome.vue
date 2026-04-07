<template>
  <div class="page-stack">
    <section class="premium-hero">
      <div class="premium-hero__eyebrow">AI Engineering Control Plane</div>
      <h1 class="premium-hero__title">Operate software delivery like a live automation system.</h1>
      <p class="premium-hero__copy">
        Create governed SDLC runs, connect repositories, track healing paths, and turn engineering goals into reviewable outcomes.
      </p>
      <div class="mt-6 flex flex-wrap gap-3">
        <el-button type="primary" size="large" :loading="loading" @click="handlePrimaryCreateAction">
          Create Project
        </el-button>
        <el-button size="large" plain @click="focusProjectInput">
          Open Existing Project
        </el-button>
      </div>
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
        <div class="text-sm uppercase tracking-wide text-slate-400">System Status</div>
        <div class="mt-4 space-y-3">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div class="text-xs uppercase tracking-wide text-slate-400">What this platform does</div>
            <div class="mt-2 text-sm text-slate-600">
              Goal intake, repo-backed runs, self-healing execution, artifact explainability, run comparison, and PR creation.
            </div>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div class="text-xs uppercase tracking-wide text-slate-400">Recommended next action</div>
            <div class="mt-2 text-sm text-slate-600">
              Create a project, connect a repository, and start a run to watch the automation loop come alive.
            </div>
          </div>
        </div>
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
