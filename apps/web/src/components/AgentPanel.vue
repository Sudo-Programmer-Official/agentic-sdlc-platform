<template>
  <div class="premium-card p-6">
    <div class="flex items-center justify-between">
      <div>
        <div class="text-sm uppercase tracking-wide text-slate-400">Agent Activity</div>
        <div class="mt-1 text-xs text-slate-500">Live automation actors and queued execution capacity.</div>
      </div>
      <span class="topbar-chip">{{ agents.length }} agent{{ agents.length === 1 ? "" : "s" }}</span>
    </div>

    <div v-if="agents.length" class="mt-4 grid gap-3">
      <div
        v-for="agent in agents"
        :key="agent.name"
        class="mission-subcard p-4 transition duration-200 hover:-translate-y-0.5"
      >
        <div class="flex items-center justify-between gap-3">
          <div class="flex items-center gap-3">
            <div
              class="flex h-11 w-11 items-center justify-center rounded-2xl"
              :style="agentTone(agent.status)"
            >
              <span class="soft-dot" :class="{ 'pulse-dot': agent.status === 'Running' }" />
            </div>
            <div class="min-w-0">
              <div
                class="agent-name-clamp text-sm font-semibold text-slate-900"
                :title="agent.name"
              >
                {{ agent.name }}
              </div>
              <div class="text-xs text-slate-500">{{ agent.taskCount }} task{{ agent.taskCount === 1 ? "" : "s" }}</div>
            </div>
          </div>
          <el-tag :type="statusTagType(agent.status)" effect="light">
            {{ agent.status }}
          </el-tag>
        </div>
      </div>
    </div>

    <div v-else class="premium-empty mt-4">
      <div class="flex flex-col items-center gap-3">
        <div class="mission-activity-orb">
          <span class="soft-dot pulse-dot" />
        </div>
        <div class="text-sm font-medium text-slate-900">Automation standing by</div>
        <div class="max-w-sm text-xs text-slate-500">
          Agents will appear here as soon as a run starts executing. This panel becomes the live handoff view between planning, patching, and verification.
        </div>
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
  if (status === "Completed") return "success";
  if (status === "Blocked") return "danger";
  if (status === "Idle" || status === "Waiting") return "info";
  return "default";
}

function agentTone(status: string) {
  if (status === "Running") return { background: "rgba(245, 158, 11, 0.12)", color: "var(--warning)" };
  if (status === "Completed") return { background: "rgba(34, 197, 94, 0.12)", color: "var(--success)" };
  if (status === "Blocked") return { background: "rgba(239, 68, 68, 0.12)", color: "var(--danger)" };
  return { background: "var(--surface-soft)", color: "var(--text-muted)" };
}
</script>

<style scoped>
.agent-name-clamp {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}
</style>
