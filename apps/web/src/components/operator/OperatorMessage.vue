<template>
  <article class="operator-message" :class="[`is-${message.role}`]">
    <div class="operator-message__role">
      <AppIcon :name="message.role === 'assistant' ? 'operator' : 'user'" size="sm" />
      <span>{{ message.role === "assistant" ? "AI Operator" : "You" }}</span>
      <span v-if="message.status && message.role === 'assistant'" class="operator-message__status">
        {{ message.status }}
      </span>
    </div>

    <div class="operator-message__text">{{ message.answer }}</div>

    <div v-if="message.groundingTools?.length" class="operator-message__tool-row">
      <span class="operator-message__tool-label">Grounded in</span>
      <span
        v-for="tool in message.groundingTools"
        :key="`${message.id}-${tool}`"
        class="operator-message__tool-chip"
      >
        {{ tool }}
      </span>
    </div>

    <div v-if="message.references?.length" class="operator-message__references">
      <button
        v-for="reference in message.references"
        :key="`${message.id}-${reference.label}-${reference.path || reference.url || reference.id || ''}`"
        type="button"
        class="operator-message__chip"
        @click="$emit('open-reference', reference)"
      >
        {{ reference.label }}
      </button>
    </div>

    <OperatorActionChips :actions="message.actions || []" @run-action="$emit('run-action', $event)" />
  </article>
</template>

<script setup lang="ts">
import type { OperatorAction, OperatorReference } from "../../api/lifecycle";
import AppIcon from "../AppIcon.vue";
import OperatorActionChips from "./OperatorActionChips.vue";

defineProps<{
  message: {
    id: string;
    role: "assistant" | "user";
    answer: string;
    status?: string;
    groundingTools?: string[];
    references?: OperatorReference[];
    actions?: OperatorAction[];
  };
}>();

defineEmits<{
  (e: "open-reference", reference: OperatorReference): void;
  (e: "run-action", action: OperatorAction): void;
}>();
</script>

<style scoped>
.operator-message {
  padding: 0.95rem 1rem;
  border-radius: 18px;
  border: 1px solid var(--border-soft);
  background: rgba(255, 255, 255, 0.03);
}

.operator-message.is-user {
  background: rgba(91, 156, 255, 0.08);
  border-color: rgba(91, 156, 255, 0.18);
}

.operator-message__role {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--text-muted);
}

.operator-message__status {
  margin-left: 0.25rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  padding: 0.12rem 0.4rem;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.operator-message__text {
  margin-top: 0.55rem;
  white-space: pre-wrap;
  line-height: 1.55;
}

.operator-message__tool-row {
  margin-top: 0.75rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
}

.operator-message__tool-label {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-soft);
}

.operator-message__tool-chip {
  border-radius: 999px;
  border: 1px solid rgba(91, 156, 255, 0.18);
  background: rgba(91, 156, 255, 0.08);
  color: var(--accent);
  padding: 0.28rem 0.58rem;
  font-size: 0.72rem;
  font-weight: 600;
}

.operator-message__references {
  margin-top: 0.85rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
}

.operator-message__chip {
  border-radius: 999px;
  border: 1px solid var(--border-soft);
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-strong);
  padding: 0.45rem 0.75rem;
  font-size: 0.78rem;
  transition: transform 160ms ease, border-color 160ms ease, background-color 160ms ease;
}

.operator-message__chip:hover {
  transform: translateY(-1px);
  border-color: rgba(91, 156, 255, 0.28);
  background: rgba(91, 156, 255, 0.08);
}
</style>
