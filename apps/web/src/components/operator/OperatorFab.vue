<template>
  <button type="button" class="operator-fab" :class="{ 'is-open': open }" @click="$emit('open')">
    <span class="operator-fab__icon">
      <AppIcon name="operator" />
    </span>
    <span class="operator-fab__copy">
      <span class="operator-fab__label">Ask System</span>
      <span class="operator-fab__hint">{{ enabled ? "Operator console" : "Open a project first" }}</span>
    </span>
  </button>
</template>

<script setup lang="ts">
import AppIcon from "../AppIcon.vue";

defineProps<{
  open: boolean;
  enabled: boolean;
}>();

defineEmits<{
  (e: "open"): void;
}>();
</script>

<style scoped>
.operator-fab {
  display: inline-flex;
  align-items: center;
  gap: 0.85rem;
  padding: 0.95rem 1rem;
  border-radius: 18px;
  border: 1px solid rgba(91, 156, 255, 0.22);
  background:
    radial-gradient(circle at top left, rgba(91, 156, 255, 0.24), transparent 55%),
    linear-gradient(180deg, color-mix(in srgb, var(--surface-1) 96%, transparent), color-mix(in srgb, var(--surface-2) 96%, transparent));
  color: var(--text-strong);
  box-shadow: var(--shadow-elevated);
  transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
}

.operator-fab:hover {
  transform: translateY(-2px) scale(1.01);
  box-shadow: var(--shadow-elevated);
  border-color: rgba(91, 156, 255, 0.4);
}

.operator-fab.is-open {
  border-color: rgba(91, 156, 255, 0.48);
}

.operator-fab__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 2.8rem;
  width: 2.8rem;
  border-radius: 16px;
  background: rgba(91, 156, 255, 0.14);
  color: var(--accent);
}

.operator-fab__copy {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

.operator-fab__label {
  font-size: 0.94rem;
  font-weight: 700;
}

.operator-fab__hint {
  margin-top: 0.1rem;
  font-size: 0.72rem;
  color: var(--text-soft);
}

@media (max-width: 900px) {
  .operator-fab__copy {
    display: none;
  }
}
</style>
