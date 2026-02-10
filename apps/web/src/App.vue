<template>
  <div class="app-shell">
    <el-container class="min-h-screen">
      <el-aside width="240px" class="app-sidebar">
        <div class="brand">Agentic SDLC</div>
        <el-menu class="app-menu" :default-active="activePath" router>
          <el-menu-item index="/">Overview</el-menu-item>
          <el-menu-item :index="missionControlPath">Mission Control</el-menu-item>
          <el-menu-item index="/timeline">SDLC Timeline</el-menu-item>
          <el-menu-item index="/approvals">Approvals</el-menu-item>
          <el-menu-item index="/agent-runs">Agent Runs</el-menu-item>
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
const missionControlPath = computed(() =>
  projectContext.projectId ? `/projects/${projectContext.projectId}` : "/"
);
</script>
