<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">Workspace</h1>
      <p class="text-slate-600">Create a project or open an existing one to begin.</p>
    </div>

    <div class="grid gap-6 lg:grid-cols-2">
      <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div class="text-sm uppercase tracking-wide text-slate-400">Create Project</div>
        <div class="mt-4 grid gap-3">
          <el-input v-model="projectName" placeholder="Project name" />
          <el-input v-model="projectDescription" placeholder="Description (optional)" />
          <el-button type="primary" :loading="loading" @click="createProject">
            Create Project
          </el-button>
        </div>
      </div>

      <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div class="text-sm uppercase tracking-wide text-slate-400">Open Project</div>
        <div class="mt-4 grid gap-3">
          <el-input v-model="projectId" placeholder="Project ID" />
          <el-button :loading="loading" @click="openProject">Open Project</el-button>
        </div>
      </div>
    </div>

    <div class="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
      Tip: Once a project is open, you'll see its overview. Mission Control becomes available when a run is active.
    </div>

    <span v-if="error" class="text-sm text-rose-600">{{ error }}</span>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";

import { updateProjectContext } from "../state/projectContext";

const DEFAULT_API_BASE = import.meta.env.DEV
  ? "http://localhost:8000/api/v1"
  : `${window.location.origin}/api/v1`;

// Use the DB-backed persistence routes under /store.
const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;

const router = useRouter();
const projectName = ref("");
const projectDescription = ref("");
const projectId = ref("");
const loading = ref(false);
const error = ref("");

async function createProject() {
  if (!projectName.value.trim()) {
    error.value = "Project name is required.";
    return;
  }
  error.value = "";
  loading.value = true;
  try {
    const response = await fetch(`${API_BASE}/store/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: projectName.value,
        description: projectDescription.value || null
      })
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
      updatedAt: new Date().toISOString()
    });
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
  router.push(`/projects/${projectId.value}`);
}
</script>
