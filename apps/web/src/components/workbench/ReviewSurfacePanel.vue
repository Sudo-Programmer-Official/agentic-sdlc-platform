<template>
  <section class="review-panel">
    <div class="review-panel__header">
      <div>
        <div class="review-panel__eyebrow">Review Surface</div>
        <h2 class="review-panel__title">See exactly what the operator changed before it ships.</h2>
      </div>
      <div class="review-panel__badge" :class="`is-${approvalTone}`">
        {{ approvalLabel }}
      </div>
    </div>

    <div v-if="patchArtifact" class="review-panel__body">
      <div class="review-snapshot">
        <div class="review-snapshot__metric">
          <span class="review-snapshot__label">Files changed</span>
          <span class="review-snapshot__value">{{ fileCount }}</span>
        </div>
        <div class="review-snapshot__metric">
          <span class="review-snapshot__label">Patch delta</span>
          <span class="review-snapshot__value">+{{ additions }} / -{{ deletions }}</span>
        </div>
        <div class="review-snapshot__metric">
          <span class="review-snapshot__label">Preview</span>
          <span class="review-snapshot__value">{{ previewStatus || "Pending" }}</span>
        </div>
      </div>

      <div class="review-panel__artifact">
        <div class="review-panel__artifact-label">Patch Artifact</div>
        <div class="review-panel__artifact-value font-mono">{{ patchArtifact.uri }}</div>
      </div>

      <div v-if="files.length" class="review-panel__files">
        <div class="review-panel__files-label">Files changed</div>
        <div class="review-panel__files-grid">
          <span v-for="file in files" :key="file" class="review-panel__file-chip">{{ file }}</span>
        </div>
      </div>

      <div class="review-panel__actions">
        <button type="button" class="review-action-chip" @click="$emit('preview-diff')">Preview Diff</button>
        <button type="button" class="review-action-chip" @click="$emit('explain-artifact')">Explain Patch</button>
        <button type="button" class="review-action-chip is-success" @click="$emit('approve')">Accept Change</button>
        <button type="button" class="review-action-chip is-danger" @click="$emit('reject')">Reject Change</button>
        <button type="button" class="review-action-chip" @click="$emit('request-modification')">Request Modification</button>
        <button type="button" class="review-action-chip is-primary" @click="$emit('create-pr')">Open PR Flow</button>
      </div>

      <div class="review-panel__foot">
        <div>
          <span class="review-panel__foot-label">PR status</span>
          <a
            v-if="pullRequestUrl"
            :href="pullRequestUrl"
            target="_blank"
            rel="noreferrer"
            class="review-panel__link"
          >
            {{ pullRequestUrl }}
          </a>
          <span v-else class="review-panel__foot-value">No PR yet</span>
        </div>
        <div>
          <span class="review-panel__foot-label">Approval note</span>
          <span class="review-panel__foot-value">{{ approvalNote || "Use accept/reject to record a decision." }}</span>
        </div>
      </div>
    </div>
    <div v-else class="review-panel__empty">
      No patch artifact is ready yet. When the operator produces a diff, this panel becomes the review checkpoint before PR creation.
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  patchArtifact: { uri: string } | null;
  files: string[];
  additions: number;
  deletions: number;
  previewStatus?: string | null;
  approvalStatus?: string | null;
  approvalNote?: string | null;
  pullRequestUrl?: string | null;
}>();

defineEmits<{
  (e: "preview-diff"): void;
  (e: "explain-artifact"): void;
  (e: "approve"): void;
  (e: "reject"): void;
  (e: "request-modification"): void;
  (e: "create-pr"): void;
}>();

const fileCount = computed(() => props.files.length);
const approvalLabel = computed(() => props.approvalStatus || "WAITING APPROVAL");
const approvalTone = computed(() => {
  const status = String(props.approvalStatus || "").toUpperCase();
  if (status === "APPROVED") return "success";
  if (status === "REJECTED") return "danger";
  return "warning";
});
</script>

<style scoped>
.review-panel {
  border: 1px solid var(--border-soft);
  border-radius: 24px;
  padding: 1.35rem;
  background:
    radial-gradient(circle at top right, rgba(34, 197, 94, 0.12), transparent 26%),
    linear-gradient(180deg, rgba(18, 22, 31, 0.92), rgba(14, 17, 25, 0.96));
  box-shadow: var(--shadow-elevated);
}

[data-theme="light"] .review-panel {
  background:
    radial-gradient(circle at top right, rgba(34, 197, 94, 0.1), transparent 26%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(244, 247, 252, 0.98));
}

.review-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.review-panel__eyebrow {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.24em;
  color: var(--text-soft);
}

.review-panel__title {
  margin: 0.4rem 0 0;
  font-size: 1.1rem;
  font-weight: 700;
}

.review-panel__badge {
  border-radius: 999px;
  border: 1px solid var(--border-soft);
  padding: 0.45rem 0.75rem;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.review-panel__badge.is-success {
  border-color: rgba(34, 197, 94, 0.22);
  color: var(--success);
}

.review-panel__badge.is-danger {
  border-color: rgba(239, 68, 68, 0.22);
  color: var(--danger);
}

.review-panel__badge.is-warning {
  border-color: rgba(245, 158, 11, 0.22);
  color: var(--warning);
}

.review-panel__body {
  margin-top: 1rem;
}

.review-snapshot {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.review-snapshot__metric {
  border: 1px solid var(--border-soft);
  border-radius: 18px;
  padding: 0.85rem 0.9rem;
  background: rgba(255, 255, 255, 0.03);
}

.review-snapshot__label,
.review-panel__artifact-label,
.review-panel__files-label,
.review-panel__foot-label {
  display: block;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  color: var(--text-soft);
}

.review-snapshot__value {
  display: block;
  margin-top: 0.35rem;
  font-size: 1rem;
  font-weight: 700;
}

.review-panel__artifact {
  margin-top: 1rem;
}

.review-panel__artifact-value {
  margin-top: 0.4rem;
  font-size: 0.82rem;
  color: var(--text-muted);
  word-break: break-all;
}

.review-panel__files {
  margin-top: 1rem;
}

.review-panel__files-grid {
  margin-top: 0.55rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}

.review-panel__file-chip {
  border-radius: 999px;
  border: 1px solid rgba(91, 156, 255, 0.18);
  background: rgba(91, 156, 255, 0.08);
  padding: 0.3rem 0.6rem;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.review-panel__actions {
  margin-top: 1rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
}

.review-action-chip {
  border-radius: 999px;
  border: 1px solid var(--border-soft);
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-strong);
  padding: 0.48rem 0.8rem;
  font-size: 0.78rem;
  font-weight: 600;
  transition: transform 160ms ease, border-color 160ms ease, background-color 160ms ease;
}

.review-action-chip:hover {
  transform: translateY(-1px);
}

.review-action-chip.is-primary {
  border-color: rgba(91, 156, 255, 0.24);
  background: rgba(91, 156, 255, 0.1);
  color: var(--accent);
}

.review-action-chip.is-success {
  border-color: rgba(34, 197, 94, 0.24);
  background: rgba(34, 197, 94, 0.08);
  color: var(--success);
}

.review-action-chip.is-danger {
  border-color: rgba(239, 68, 68, 0.24);
  background: rgba(239, 68, 68, 0.08);
  color: var(--danger);
}

.review-panel__foot {
  margin-top: 1rem;
  display: grid;
  gap: 0.9rem;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.review-panel__foot-value,
.review-panel__link {
  display: block;
  margin-top: 0.35rem;
  font-size: 0.82rem;
  color: var(--text-muted);
  word-break: break-word;
}

.review-panel__link {
  text-decoration: underline;
}

.review-panel__empty {
  margin-top: 1rem;
  border-radius: 18px;
  border: 1px dashed var(--border-soft);
  padding: 1rem;
  color: var(--text-soft);
  font-size: 0.84rem;
  line-height: 1.5;
}

@media (max-width: 900px) {
  .review-snapshot,
  .review-panel__foot {
    grid-template-columns: 1fr;
  }
}
</style>
