<template>
  <div class="page-stack">
    <section class="premium-hero knowledge-hero">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="max-w-3xl space-y-3">
          <button type="button" class="topbar-chip" @click="goBack">
            <AppIcon name="knowledge" size="sm" />
            Back to Inbox
          </button>
          <div>
            <h1 class="text-3xl font-semibold" style="color: var(--text-strong);">
              {{ proposal?.artifact_title || "Knowledge Proposal" }}
            </h1>
            <p class="mt-2 text-sm leading-6" style="color: var(--text-muted);">
              Review the AI-generated draft, inspect the underlying change intelligence, and choose what becomes official project knowledge.
            </p>
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <button type="button" class="utility-button" @click="loadProposal" :disabled="loading">
            <AppIcon name="status" />
          </button>
          <button
            v-if="proposal?.event?.id"
            type="button"
            class="utility-button"
            @click="openEvent"
            title="Open event intelligence"
          >
            <AppIcon name="timeline" />
          </button>
          <button
            v-if="proposal?.artifact_id"
            type="button"
            class="utility-button"
            @click="openArtifact"
            title="Open artifact history"
          >
            <AppIcon name="artifact" />
          </button>
        </div>
      </div>
    </section>

    <div v-if="error" class="rounded-2xl border px-4 py-3 text-sm" style="border-color: rgba(239, 68, 68, 0.24); background: rgba(239, 68, 68, 0.08); color: var(--danger);">
      {{ error }}
    </div>

    <template v-else-if="proposal">
      <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Review Status" :value="proposal.review_status" helper="Draft state" tone="warning" />
        <MetricCard label="Confidence" :value="`${Math.round((proposal.confidence_score || 0) * 100)}%`" helper="Model certainty" tone="neutral" />
        <MetricCard label="Risk" :value="proposal.change?.risk_level || 'medium'" helper="Change impact" tone="danger" />
        <MetricCard label="Source" :value="proposal.event.source_type" helper="Event trigger" tone="success" />
      </section>

      <section class="knowledge-review-grid">
        <div class="space-y-4">
          <div class="premium-card p-5">
            <div class="flex flex-wrap items-center gap-2">
              <div class="topbar-chip">AI-generated draft</div>
              <div class="status-ring" :style="statusStyle(proposal.review_status)">
                <span class="soft-dot" />
                {{ proposal.review_status }}
              </div>
            </div>
            <div class="mt-4 grid gap-4 md:grid-cols-2">
              <div class="knowledge-meta-card">
                <div class="knowledge-meta-card__label">Event</div>
                <div class="knowledge-meta-card__value">{{ proposal.event.title || "Untitled event" }}</div>
                <div class="knowledge-meta-card__meta">
                  {{ proposal.event.repo_full_name || "Connected repo" }} · {{ proposal.event.branch_name || "branch n/a" }}
                </div>
              </div>
              <div class="knowledge-meta-card">
                <div class="knowledge-meta-card__label">Change Summary</div>
                <div class="knowledge-meta-card__value">{{ proposal.change?.change_type || "unknown" }}</div>
                <div class="knowledge-meta-card__meta">
                  {{ proposal.change?.summary || "No change summary available." }}
                </div>
              </div>
            </div>
            <div class="mt-4 space-y-3 text-sm" style="color: var(--text-muted);">
              <div><strong style="color: var(--text-strong);">Technical:</strong> {{ proposal.change?.technical_summary }}</div>
              <div><strong style="color: var(--text-strong);">Business:</strong> {{ proposal.change?.business_summary }}</div>
              <div><strong style="color: var(--text-strong);">Rationale:</strong> {{ proposal.rationale }}</div>
            </div>
            <div class="mt-4 flex flex-wrap gap-2">
              <span v-for="file in proposal.change?.impacted_files || []" :key="file" class="knowledge-pill">
                {{ file }}
              </span>
            </div>
          </div>

          <div class="knowledge-three-up">
            <div class="premium-card p-0 overflow-hidden">
              <div class="knowledge-panel-header">Official Content</div>
              <pre class="knowledge-code-panel">{{ proposal.current_canonical_content || "No official content published yet." }}</pre>
            </div>
            <div class="premium-card p-0 overflow-hidden">
              <div class="knowledge-panel-header">Proposed Content</div>
              <pre class="knowledge-code-panel">{{ proposal.generated_content }}</pre>
            </div>
            <div class="premium-card p-0 overflow-hidden">
              <div class="knowledge-panel-header">Diff Preview</div>
              <pre class="knowledge-code-panel">{{ proposal.diff_preview || "No diff available." }}</pre>
            </div>
          </div>
        </div>

        <div class="space-y-4">
          <div class="premium-card p-5">
            <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Review Action</div>
            <div class="mt-3 text-sm" style="color: var(--text-muted);">
              Edit the draft if needed. Approve publishes the generated content as-is; edit and approve publishes your edited version.
            </div>
            <textarea
              v-model="editedContent"
              class="knowledge-textarea mt-4"
              rows="14"
              :disabled="saving || !isActionable"
              placeholder="Optional edited content before approval"
            />
            <textarea
              v-model="reviewNotes"
              class="knowledge-textarea mt-3"
              rows="4"
              :disabled="saving || !isActionable"
              placeholder="Review notes"
            />
            <div class="mt-4 grid gap-2 sm:grid-cols-2">
              <button type="button" class="knowledge-action is-approve" :disabled="saving || !isActionable" @click="approve">
                Approve
              </button>
              <button
                type="button"
                class="knowledge-action is-edit"
                :disabled="saving || !isActionable || !editedContent.trim()"
                @click="editAndApprove"
              >
                Edit and Approve
              </button>
              <button type="button" class="knowledge-action is-reject" :disabled="saving || !isActionable" @click="reject">
                Reject
              </button>
              <button type="button" class="knowledge-action is-defer" :disabled="saving || !isActionable" @click="defer">
                Defer
              </button>
            </div>
          </div>

          <div class="premium-card p-5">
            <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Review History</div>
            <div v-if="proposal.reviews?.length" class="mt-4 space-y-3">
              <div v-for="review in proposal.reviews" :key="review.id" class="knowledge-history-card">
                <div class="flex items-center justify-between gap-3">
                  <strong style="color: var(--text-strong);">{{ review.action }}</strong>
                  <span class="text-xs" style="color: var(--text-soft);">{{ formatDate(review.created_at) }}</span>
                </div>
                <div class="mt-2 text-sm" style="color: var(--text-muted);">
                  {{ review.review_notes || "No review notes." }}
                </div>
              </div>
            </div>
            <div v-else class="mt-4 premium-empty">
              No review actions recorded yet.
            </div>
          </div>

          <div v-if="proposal.publication" class="premium-card p-5">
            <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Publication</div>
            <div class="mt-3 text-sm" style="color: var(--text-muted);">
              Version {{ proposal.publication.artifact_version }} published by {{ proposal.publication.published_by || "system" }} on
              {{ formatDate(proposal.publication.published_at) }}.
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppIcon from "../components/AppIcon.vue";
import MetricCard from "../components/MetricCard.vue";
import {
  approveKnowledgeProposal,
  deferKnowledgeProposal,
  editAndApproveKnowledgeProposal,
  fetchKnowledgeProposal,
  rejectKnowledgeProposal,
} from "../api/knowledge";

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const saving = ref(false);
const error = ref("");
const proposal = ref<any | null>(null);
const editedContent = ref("");
const reviewNotes = ref("");
const projectId = computed(() => String(route.params.projectId || ""));
const isActionable = computed(() => proposal.value?.review_status === "pending");

watch(
  () => route.params.proposalId,
  () => {
    void loadProposal();
  },
  { immediate: true }
);

async function loadProposal() {
  if (!projectId.value) return;
  const proposalId = String(route.params.proposalId || "");
  if (!proposalId) return;
  loading.value = true;
  error.value = "";
  try {
    const data = await fetchKnowledgeProposal(projectId.value, proposalId);
    proposal.value = data;
    editedContent.value = data?.publication?.published_content || data?.generated_content || "";
  } catch (err: any) {
    error.value = err?.message || "Failed to load proposal detail.";
  } finally {
    loading.value = false;
  }
}

async function approve() {
  await runAction(() =>
    approveKnowledgeProposal(projectId.value, String(route.params.proposalId), {
      review_notes: reviewNotes.value || undefined,
    })
  );
}

async function editAndApprove() {
  await runAction(() =>
    editAndApproveKnowledgeProposal(projectId.value, String(route.params.proposalId), {
      review_notes: reviewNotes.value || undefined,
      edited_content: editedContent.value,
    })
  );
}

async function reject() {
  await runAction(() =>
    rejectKnowledgeProposal(projectId.value, String(route.params.proposalId), {
      review_notes: reviewNotes.value || undefined,
    })
  );
}

async function defer() {
  await runAction(() =>
    deferKnowledgeProposal(projectId.value, String(route.params.proposalId), {
      review_notes: reviewNotes.value || undefined,
    })
  );
}

async function runAction(action: () => Promise<any>) {
  saving.value = true;
  error.value = "";
  try {
    proposal.value = await action();
    editedContent.value = proposal.value?.publication?.published_content || proposal.value?.generated_content || "";
    reviewNotes.value = "";
  } catch (err: any) {
    error.value = err?.message || "Review action failed.";
  } finally {
    saving.value = false;
  }
}

function goBack() {
  router.push(`/projects/${route.params.projectId}/knowledge`);
}

function openArtifact() {
  if (!proposal.value?.artifact_id) return;
  router.push(`/projects/${route.params.projectId}/knowledge/artifacts/${proposal.value.artifact_id}`);
}

function openEvent() {
  if (!proposal.value?.event?.id) return;
  router.push(`/projects/${route.params.projectId}/knowledge/events/${proposal.value.event.id}`);
}

function formatDate(value?: string) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString();
}

function statusStyle(status?: string) {
  if (status === "published" || status === "approved") {
    return { background: "rgba(34, 197, 94, 0.12)", color: "var(--success)" };
  }
  if (status === "rejected") {
    return { background: "rgba(239, 68, 68, 0.12)", color: "var(--danger)" };
  }
  if (status === "deferred" || status === "superseded") {
    return { background: "rgba(148, 163, 184, 0.18)", color: "var(--text-muted)" };
  }
  return { background: "rgba(91, 156, 255, 0.12)", color: "var(--accent)" };
}
</script>
