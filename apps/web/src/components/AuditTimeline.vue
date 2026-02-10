<template>
  <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
    <div class="text-sm uppercase tracking-wide text-slate-400">Audit Timeline</div>
    <el-timeline class="mt-4">
      <el-timeline-item
        v-for="log in logs"
        :key="log.timestamp + log.message"
        :timestamp="log.timestamp"
        placement="top"
      >
        <div class="text-sm font-semibold text-slate-900">
          {{ log.agent }} · {{ log.tool }}
        </div>
        <div class="text-xs text-slate-500">{{ log.message }}</div>
      </el-timeline-item>
    </el-timeline>
    <div v-if="logs.length === 0" class="text-sm text-slate-500">No audit logs yet.</div>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{ logs: any[] }>();
</script>
