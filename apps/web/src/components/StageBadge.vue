<template>
  <el-tag :type="tagType" effect="light">
    {{ label }}
  </el-tag>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ label: string }>();

const tagType = computed(() => {
  const value = props.label.toUpperCase();
  if (value.includes("REQUIREMENTS") || value.includes("INTAKE")) return "info";
  if (value.includes("DESIGN")) return "warning";
  if (value.includes("PLAN") || value.includes("IMPLEMENT")) return "primary";
  if (value.includes("TEST") || value.includes("REVIEW")) return "success";
  if (value.includes("MERGED") || value.includes("DEPLOY")) return "success";
  return "default";
});
</script>
