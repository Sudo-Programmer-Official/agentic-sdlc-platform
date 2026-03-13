<template>
  <div class="metric-card" :style="toneStyle">
    <div class="flex items-start justify-between gap-3">
      <div>
        <div class="metric-card__label">{{ label }}</div>
        <div class="metric-card__value">{{ value }}</div>
      </div>
      <div v-if="$slots.icon" class="metric-card__icon">
        <slot name="icon" />
      </div>
    </div>
    <div v-if="detailText" class="metric-card__detail">{{ detailText }}</div>
    <div v-if="$slots.footer" class="mt-3">
      <slot name="footer" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  label: string;
  value: string | number;
  detail?: string;
  helper?: string;
  tone?: "neutral" | "success" | "warning" | "danger";
}>();

const detailText = computed(() => props.detail || props.helper || "");

const toneStyle = computed(() => {
  switch (props.tone) {
    case "success":
      return {
        borderColor: "rgba(34, 197, 94, 0.18)",
        boxShadow: "0 16px 36px rgba(34, 197, 94, 0.08)",
      };
    case "warning":
      return {
        borderColor: "rgba(245, 158, 11, 0.18)",
        boxShadow: "0 16px 36px rgba(245, 158, 11, 0.08)",
      };
    case "danger":
      return {
        borderColor: "rgba(239, 68, 68, 0.18)",
        boxShadow: "0 16px 36px rgba(239, 68, 68, 0.08)",
      };
    default:
      return {};
  }
});
</script>
