<template>
  <div v-if="actions.length" class="operator-actions">
    <button
      v-for="action in actions"
      :key="`${action.type}-${action.target_id || action.path || action.prompt || action.label}`"
      type="button"
      class="operator-actions__chip"
      @click="$emit('run-action', action)"
    >
      {{ action.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
import type { OperatorAction } from "../../api/lifecycle";

defineProps<{
  actions: OperatorAction[];
}>();

defineEmits<{
  (e: "run-action", action: OperatorAction): void;
}>();
</script>

<style scoped>
.operator-actions {
  margin-top: 0.85rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
}

.operator-actions__chip {
  border-radius: 999px;
  border: 1px solid rgba(91, 156, 255, 0.22);
  background: rgba(91, 156, 255, 0.08);
  color: var(--accent);
  padding: 0.45rem 0.75rem;
  font-size: 0.78rem;
  font-weight: 600;
  transition: transform 160ms ease, border-color 160ms ease, background-color 160ms ease;
}

.operator-actions__chip:hover {
  transform: translateY(-1px);
  border-color: rgba(91, 156, 255, 0.34);
  background: rgba(91, 156, 255, 0.14);
}
</style>
