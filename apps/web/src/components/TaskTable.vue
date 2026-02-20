<template>
  <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
    <div class="text-sm uppercase tracking-wide text-slate-400">Task Table</div>
    <el-table v-if="tasks.length" :data="tasks" style="width: 100%" class="mt-4">
      <el-table-column prop="task_id" label="Task ID" width="130" />
      <el-table-column prop="agent" label="Agent" width="140" />
      <el-table-column prop="title" label="Title" />
      <el-table-column label="Lineage" width="180">
        <template #default="{ row }">
          <div class="flex flex-wrap gap-1">
            <el-tag
              v-if="row.deprecated"
              size="small"
              type="danger"
              effect="plain"
            >
              Deprecated
            </el-tag>
            <el-tag
              v-else-if="row.parent_task_id"
              size="small"
              type="warning"
              effect="plain"
            >
              Regenerated
            </el-tag>
            <el-tag
              v-else
              size="small"
              type="success"
              effect="plain"
            >
              Reused
            </el-tag>
            <el-tag v-if="row.superseded_by" size="small" type="info" effect="plain">
              Superseded → {{ row.superseded_by }}
            </el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="Status" width="140">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" effect="light">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="Requirements" min-width="200">
        <template #default="{ row }">
          <div class="flex flex-wrap gap-2">
            <el-tag
              v-for="req in row.linked_requirements || []"
              :key="req"
              size="small"
              type="info"
              effect="plain"
            >
              {{ req }}
            </el-tag>
            <span v-if="!row.linked_requirements?.length" class="text-xs text-slate-500">—</span>
          </div>
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
