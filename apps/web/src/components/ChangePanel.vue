<template>
  <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
    <div class="text-sm uppercase tracking-wide text-slate-400">Change Requests</div>
    <div class="mt-4 space-y-3">
      <div class="grid gap-2 md:grid-cols-2">
        <el-input v-model="summary" placeholder="Change summary" />
        <el-select v-model="source" placeholder="Source">
          <el-option label="USER" value="USER" />
          <el-option label="PROD_FEEDBACK" value="PROD_FEEDBACK" />
          <el-option label="BUG" value="BUG" />
          <el-option label="OPS" value="OPS" />
        </el-select>
        <el-select v-model="area" placeholder="Area">
          <el-option label="UI" value="UI" />
          <el-option label="BACKEND" value="BACKEND" />
          <el-option label="BOTH" value="BOTH" />
        </el-select>
        <el-select v-model="severity" placeholder="Severity">
          <el-option label="LOW" value="LOW" />
          <el-option label="MEDIUM" value="MEDIUM" />
          <el-option label="HIGH" value="HIGH" />
        </el-select>
        <el-select v-model="stage" placeholder="Suggested Stage">
          <el-option label="REQUIREMENTS" value="REQUIREMENTS" />
          <el-option label="DESIGN" value="DESIGN" />
          <el-option label="IMPLEMENTATION" value="IMPLEMENTATION" />
        </el-select>
        <el-button type="primary" :disabled="!summary.trim()" @click="submit">Create</el-button>
      </div>
      <div v-if="changes.length === 0" class="text-sm text-slate-500">
        No change requests yet.
      </div>
      <div
        v-for="change in changes"
        :key="change.id"
        class="flex flex-col gap-2 rounded-lg border border-slate-100 p-4"
      >
        <div class="flex items-center justify-between">
          <div class="text-sm font-semibold text-slate-900">{{ change.summary }}</div>
          <el-tag :type="statusTagType(change.status)" effect="light">
            {{ change.status }}
          </el-tag>
        </div>
        <div class="text-xs text-slate-500">
          {{ change.source }} · {{ change.affected_area }} · {{ change.severity }} ·
          {{ change.suggested_stage }}
        </div>
        <div class="flex gap-2">
          <el-button size="small" @click="$emit('accept', change.id)">Accept</el-button>
          <el-button size="small" @click="$emit('reject', change.id)">Reject</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";

defineProps<{ changes: any[] }>();

const emit = defineEmits<{
  (e: "create", payload: {
    summary: string;
    source: string;
    affected_area: string;
    severity: string;
    suggested_stage: string;
  }): void;
  (e: "accept", id: string): void;
  (e: "reject", id: string): void;
}>();

const summary = ref("");
const source = ref("USER");
const area = ref("UI");
const severity = ref("LOW");
const stage = ref("REQUIREMENTS");

function submit() {
  if (!summary.value.trim()) return;
  emit("create", {
    summary: summary.value,
    source: source.value,
    affected_area: area.value,
    severity: severity.value,
    suggested_stage: stage.value
  });
  summary.value = "";
}

function statusTagType(status: string) {
  if (status === "OPEN") return "warning";
  if (status === "ACCEPTED") return "success";
  if (status === "REJECTED") return "danger";
  if (status === "APPLIED") return "info";
  return "default";
}
</script>
