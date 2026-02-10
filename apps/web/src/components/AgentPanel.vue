<template>
  <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
    <div class="flex items-center justify-between">
      <div class="text-sm uppercase tracking-wide text-slate-400">Agent Activity</div>
      <span class="text-xs text-slate-500">Latest run</span>
    </div>
    <div class="mt-4 space-y-3">
      <div
        v-for="agent in agents"
        :key="agent.name"
        class="flex items-center justify-between rounded-lg bg-slate-50 px-4 py-3"
      >
        <div>
          <div class="text-sm font-semibold text-slate-900">{{ agent.name }}</div>
          <div class="text-xs text-slate-500">{{ agent.taskCount }} task(s)</div>
        </div>
        <el-tag :type="statusTagType(agent.status)" effect="light">
          {{ agent.status }}
        </el-tag>
      </div>
      <div v-if="agents.length === 0" class="text-sm text-slate-500">
        No agent activity yet.
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  agents: Array<{ name: string; status: string; taskCount: number }>;
}>();

function statusTagType(status: string) {
  if (status === "Running") return "warning";
  if (status === "Blocked") return "danger";
  if (status === "Idle") return "info";
  return "default";
}
</script>
