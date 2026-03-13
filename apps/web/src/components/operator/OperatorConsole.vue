<template>
  <div class="operator-console" :class="[`is-${variant}`]">
    <div class="operator-console__header">
      <div>
        <div class="operator-console__eyebrow">{{ eyebrow }}</div>
        <div class="operator-console__title">{{ title }}</div>
        <div class="operator-console__meta">
          {{ currentProjectName }}
          <span v-if="currentRunId" class="operator-console__meta-sep">•</span>
          <span v-if="currentRunId">Run {{ shortId(currentRunId) }}</span>
        </div>
      </div>
      <button v-if="closable" type="button" class="operator-console__close" @click="$emit('close')">Close</button>
    </div>

    <div class="operator-console__body">
      <div class="operator-console__context-card">
        <div class="operator-console__context-copy">
          <div class="operator-console__context-title">{{ contextTitle }}</div>
          <p>{{ contextCopy }}</p>
        </div>
        <div class="operator-console__context-status">
          <span class="status-ring">{{ currentRunStatus }}</span>
        </div>
      </div>

      <div class="operator-console__quick-prompts" v-if="currentProjectId">
        <button
          v-for="prompt in starterPrompts"
          :key="prompt.prompt"
          type="button"
          class="operator-console__quick-chip"
          @click="runPrompt(prompt.prompt)"
        >
          {{ prompt.label }}
        </button>
      </div>

      <div class="operator-console__messages">
        <OperatorMessage
          v-for="message in messages"
          :key="message.id"
          :message="message"
          @open-reference="openReference"
          @run-action="runAction"
        />

        <article v-if="loading" class="operator-message">
          <div class="operator-message__role">
            <AppIcon name="operator" size="sm" />
            <span>AI Operator</span>
          </div>
          <div class="operator-console__loading">
            <span class="soft-dot pulse-dot" />
            Pulling grounded tool outputs…
          </div>
        </article>
      </div>
    </div>

    <div class="operator-console__composer">
      <div v-if="!currentProjectId" class="operator-console__empty">
        Open a project to ask about runs, artifacts, comparisons, project health, workspace state, and the repo map.
      </div>
      <template v-else>
        <div class="operator-console__composer-row">
          <textarea
            v-model="draft"
            class="operator-console__input"
            rows="3"
            :placeholder="placeholder"
            @keydown.enter.exact.prevent="submit()"
          />
          <button type="button" class="operator-console__send" :disabled="loading || !draft.trim()" @click="submit()">
            Send
          </button>
        </div>
        <div class="operator-console__composer-hint">
          {{ hint }}
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

import AppIcon from "../AppIcon.vue";
import OperatorMessage from "./OperatorMessage.vue";
import { useOperatorConsole } from "../../composables/useOperatorConsole";

const props = withDefaults(
  defineProps<{
    variant?: "drawer" | "panel";
    title?: string;
    eyebrow?: string;
    contextTitle?: string;
    contextCopy?: string;
    placeholder?: string;
    hint?: string;
    closable?: boolean;
  }>(),
  {
    variant: "drawer",
    title: "AI Operator",
    eyebrow: "System Operator",
    contextTitle: "Tool-grounded operator console",
    contextCopy:
      "Ask about project status, run failures, patch explanations, run comparison, project health, workspace state, and repo structure.",
    placeholder:
      "Why did the latest run fail? Explain the latest patch. Show repo map. Find the login component.",
    hint: "Read-only phase. The operator responds only from actual tool results and never changes system state.",
    closable: false,
  }
);

defineEmits<{
  (e: "close"): void;
}>();

const {
  currentProjectId,
  currentProjectName,
  currentRunId,
  currentRunStatus,
  draft,
  loading,
  messages,
  shortId,
  starterPrompts,
  submit,
  runPrompt,
  openReference,
  runAction,
} = useOperatorConsole();

const variant = computed(() => props.variant);
const title = computed(() => props.title);
const eyebrow = computed(() => props.eyebrow);
const contextTitle = computed(() => props.contextTitle);
const contextCopy = computed(() => props.contextCopy);
const placeholder = computed(() => props.placeholder);
const hint = computed(() => props.hint);
</script>

<style scoped>
.operator-console {
  height: 100%;
  display: grid;
  grid-template-rows: auto 1fr auto;
  color: var(--text-strong);
}

.operator-console.is-drawer {
  background:
    radial-gradient(circle at top left, rgba(91, 156, 255, 0.12), transparent 26%),
    linear-gradient(180deg, rgba(13, 17, 26, 0.98), rgba(17, 22, 33, 0.98));
  border-left: 1px solid rgba(255, 255, 255, 0.08);
}

.operator-console.is-panel {
  border: 1px solid var(--border-soft);
  border-radius: 24px;
  background:
    radial-gradient(circle at top left, rgba(91, 156, 255, 0.12), transparent 32%),
    linear-gradient(180deg, rgba(19, 24, 35, 0.92), rgba(14, 18, 27, 0.96));
  box-shadow: var(--shadow-elevated);
  min-height: 42rem;
}

[data-theme="light"] .operator-console.is-panel {
  background:
    radial-gradient(circle at top left, rgba(91, 156, 255, 0.12), transparent 32%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.95), rgba(245, 248, 252, 0.98));
}

.operator-console__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.2rem 1.2rem 1rem;
  border-bottom: 1px solid var(--border-soft);
}

.operator-console__eyebrow {
  font-size: 0.68rem;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: var(--text-soft);
}

.operator-console__title {
  margin-top: 0.35rem;
  font-size: 1.3rem;
  font-weight: 700;
}

.operator-console__meta {
  margin-top: 0.3rem;
  font-size: 0.82rem;
  color: var(--text-soft);
}

.operator-console__meta-sep {
  margin: 0 0.4rem;
}

.operator-console__close {
  border: 1px solid var(--border-soft);
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  padding: 0.45rem 0.85rem;
}

.operator-console__body {
  min-height: 0;
  overflow: auto;
  padding: 1rem 1.2rem;
}

.operator-console__context-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.9rem;
  padding: 0.95rem 1rem;
  border-radius: 18px;
  border: 1px solid var(--border-soft);
  background: rgba(255, 255, 255, 0.03);
}

.operator-console__context-title {
  font-weight: 700;
}

.operator-console__context-copy p {
  margin: 0.4rem 0 0;
  font-size: 0.83rem;
  line-height: 1.5;
  color: var(--text-soft);
}

.operator-console__quick-prompts,
.operator-console__messages {
  margin-top: 1rem;
  display: grid;
  gap: 0.85rem;
}

.operator-console__quick-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
}

.operator-console__quick-chip {
  border-radius: 999px;
  border: 1px solid var(--border-soft);
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-strong);
  padding: 0.45rem 0.75rem;
  font-size: 0.78rem;
  transition: transform 160ms ease, border-color 160ms ease, background-color 160ms ease;
}

.operator-console__quick-chip:hover {
  transform: translateY(-1px);
  border-color: rgba(91, 156, 255, 0.28);
  background: rgba(91, 156, 255, 0.08);
}

.operator-console__loading {
  margin-top: 0.6rem;
  display: inline-flex;
  align-items: center;
  gap: 0.6rem;
  color: var(--text-soft);
}

.operator-console__composer {
  padding: 1rem 1.2rem 1.2rem;
  border-top: 1px solid var(--border-soft);
  background: rgba(8, 10, 16, 0.38);
}

[data-theme="light"] .operator-console__composer {
  background: rgba(242, 246, 251, 0.72);
}

.operator-console__composer-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.8rem;
  align-items: end;
}

.operator-console__input {
  width: 100%;
  resize: none;
  border-radius: 16px;
  border: 1px solid var(--border-soft);
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-strong);
  padding: 0.9rem 1rem;
  font: inherit;
}

.operator-console__input:focus {
  outline: none;
  border-color: rgba(91, 156, 255, 0.36);
  box-shadow: 0 0 0 3px rgba(91, 156, 255, 0.14);
}

.operator-console__send {
  min-width: 92px;
  border-radius: 14px;
  border: 1px solid rgba(91, 156, 255, 0.3);
  background: linear-gradient(180deg, rgba(91, 156, 255, 0.28), rgba(91, 156, 255, 0.18));
  color: var(--text-strong);
  padding: 0.8rem 1rem;
  font-weight: 700;
}

.operator-console__send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.operator-console__composer-hint,
.operator-console__empty {
  margin-top: 0.6rem;
  font-size: 0.76rem;
  color: var(--text-soft);
  line-height: 1.45;
}
</style>
