<template>
  <span
    class="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em]"
    :style="badgeStyle"
  >
    <span class="soft-dot" />
    {{ label }}
  </span>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ label: string }>();

const badgeStyle = computed(() => {
  const value = props.label.toUpperCase();
  if (value.includes("REQUIREMENTS") || value.includes("INTAKE")) {
    return { background: "rgba(91, 156, 255, 0.12)", color: "var(--accent)" };
  }
  if (value.includes("DESIGN")) {
    return { background: "rgba(245, 158, 11, 0.12)", color: "var(--warning)" };
  }
  if (value.includes("PLAN") || value.includes("IMPLEMENT") || value.includes("RUN")) {
    return { background: "rgba(126, 93, 255, 0.12)", color: "#8b7dff" };
  }
  if (value.includes("TEST") || value.includes("REVIEW") || value.includes("EVALUATE")) {
    return { background: "rgba(34, 197, 94, 0.12)", color: "var(--success)" };
  }
  if (value.includes("DEPLOY") || value.includes("MERGED")) {
    return { background: "rgba(34, 197, 94, 0.12)", color: "var(--success)" };
  }
  return { background: "var(--surface-soft)", color: "var(--text-muted)" };
});
</script>
