<template>
  <div class="app-shell">
    <el-container class="min-h-screen">
      <el-aside width="240px" class="app-sidebar">
        <div class="brand">Agentic SDLC</div>
        <el-menu class="app-menu" :default-active="activePath" router>
          <el-menu-item index="/">Workspace</el-menu-item>
          <el-menu-item :index="projectPath" :disabled="!hasProject">Project Overview</el-menu-item>
          <el-menu-item :index="requirementsPath" :disabled="!hasProject">Requirements</el-menu-item>
          <el-menu-item :index="missionControlPath" :disabled="!hasRun">Mission Control</el-menu-item>
          <el-menu-item :index="timelinePath" :disabled="!hasProject">SDLC Timeline</el-menu-item>
          <el-menu-item :index="approvalsPath" :disabled="!hasProject">Approvals</el-menu-item>
          <el-menu-item :index="runsPath" :disabled="!hasProject">Agent Runs</el-menu-item>
        </el-menu>
      </el-aside>
      <el-container>
        <el-header class="app-header">
          <TopBar />
        </el-header>
        <el-main class="app-main">
          <router-view />
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

import TopBar from "./components/TopBar.vue";
import { projectContext } from "./state/projectContext";

const route = useRoute();
const activePath = computed(() => route.path);
const projectPath = computed(() =>
  projectContext.projectId ? `/projects/${projectContext.projectId}` : "/"
);
const requirementsPath = computed(() =>
  projectContext.projectId ? `/projects/${projectContext.projectId}/requirements` : "/"
);
const missionControlPath = computed(() =>
  projectContext.projectId ? `/projects/${projectContext.projectId}/run` : "/"
);
const timelinePath = computed(() =>
  projectContext.projectId ? `/projects/${projectContext.projectId}/timeline` : "/"
);
const approvalsPath = computed(() =>
  projectContext.projectId ? `/projects/${projectContext.projectId}/approvals` : "/"
);
const runsPath = computed(() =>
  projectContext.projectId ? `/projects/${projectContext.projectId}/runs` : "/"
);
const hasProject = computed(() => Boolean(projectContext.projectId));
const hasRun = computed(() => Boolean(projectContext.latestRunId));
</script>
