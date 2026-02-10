<template>
  <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
    <div class="text-sm uppercase tracking-wide text-slate-400">Task Table</div>
    <el-table v-if="tasks.length" :data="tasks" style="width: 100%" class="mt-4">
      <el-table-column prop="task_id" label="Task ID" width="130" />
      <el-table-column prop="agent" label="Agent" width="140" />
      <el-table-column prop="title" label="Title" />
      <el-table-column label="Status" width="140">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" effect="light">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
    </el-table>
    <div v-else class="mt-4 text-sm text-slate-500">No tasks found.</div>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{ tasks: any[] }>();

function statusTagType(status: string) {
  if (status === "RUNNING") return "warning";
  if (status === "DONE") return "success";
  if (status === "FAILED") return "danger";
  if (status === "CANCELED") return "info";
  return "default";
}
</script>
