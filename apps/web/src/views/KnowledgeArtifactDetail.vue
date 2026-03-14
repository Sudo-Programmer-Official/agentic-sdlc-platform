<template>
  <div class="page-stack">
    <section class="premium-hero knowledge-hero">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="max-w-3xl space-y-3">
          <button type="button" class="topbar-chip" @click="goBack">
            <AppIcon name="artifact" size="sm" />
            Back to Knowledge
          </button>
          <div>
            <h1 class="text-3xl font-semibold" style="color: var(--text-strong);">
              {{ artifact?.title || "Knowledge Artifact" }}
            </h1>
            <p class="mt-2 text-sm leading-6" style="color: var(--text-muted);">
              Inspect the official published version, earlier proposal decisions, and the publication timeline for this artifact.
            </p>
          </div>
        </div>

        <button type="button" class="utility-button" @click="loadArtifact" :disabled="loading">
          <AppIcon name="status" />
        </button>
      </div>
    </section>

    <div v-if="error" class="rounded-2xl border px-4 py-3 text-sm" style="border-color: rgba(239, 68, 68, 0.24); background: rgba(239, 68, 68, 0.08); color: var(--danger);">
      {{ error }}
    </div>

    <template v-else-if="artifact">
      <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Version" :value="String(artifact.current_version || 0)" helper="Current official revision" tone="success" />
        <MetricCard label="Type" :value="artifact.artifact_type" helper="Knowledge artifact class" tone="neutral" />
        <MetricCard label="Last Verified By" :value="artifact.last_verified_by || '—'" helper="Most recent human verification" tone="warning" />
        <MetricCard label="Status" :value="artifact.status" helper="Artifact lifecycle state" tone="neutral" />
      </section>

      <section class="knowledge-review-grid">
        <div class="premium-card p-0 overflow-hidden">
          <div class="knowledge-panel-header">Official Canonical Content</div>
          <pre class="knowledge-code-panel">{{ artifact.canonical_content || "No official content has been published yet." }}</pre>
        </div>

        <div class="premium-card p-5">
          <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">History</div>
          <div v-if="artifact.history?.length" class="mt-4 space-y-3">
            <article v-for="item in artifact.history" :key="item.proposal.id" class="knowledge-history-card">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div class="font-semibold" style="color: var(--text-strong);">{{ item.proposal.artifact_title }}</div>
                  <div class="text-sm" style="color: var(--text-muted);">
                    {{ item.proposal.proposal_type }} · {{ item.proposal.review_status }}
                  </div>
                </div>
                <button type="button" class="utility-button" @click="openProposal(item.proposal.id)">
                  <AppIcon name="approvals" />
                </button>
              </div>
              <div class="mt-3 text-sm" style="color: var(--text-muted);">
                Created {{ formatDate(item.proposal.created_at) }}
              </div>
              <div v-if="item.publication" class="mt-2 text-sm" style="color: var(--text-muted);">
                Published as version {{ item.publication.artifact_version }} by {{ item.publication.published_by || "system" }}
              </div>
              <div v-if="item.reviews?.length" class="mt-3 flex flex-wrap gap-2">
                <span v-for="review in item.reviews" :key="review.id" class="knowledge-pill">
                  {{ review.action }} · {{ review.reviewer_user_id }}
                </span>
              </div>
            </article>
          </div>
          <div v-else class="mt-4 premium-empty">
            No proposal history exists for this artifact yet.
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
import { fetchKnowledgeArtifact } from "../api/knowledge";

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const error = ref("");
const artifact = ref<any | null>(null);
const projectId = computed(() => String(route.params.projectId || ""));

watch(
  () => route.params.artifactId,
  () => {
    void loadArtifact();
  },
  { immediate: true }
);

async function loadArtifact() {
  if (!projectId.value) return;
  const artifactId = String(route.params.artifactId || "");
  if (!artifactId) return;
  loading.value = true;
  error.value = "";
  try {
    artifact.value = await fetchKnowledgeArtifact(projectId.value, artifactId);
  } catch (err: any) {
    error.value = err?.message || "Failed to load artifact history.";
  } finally {
    loading.value = false;
  }
}

function goBack() {
  router.push(`/projects/${route.params.projectId}/knowledge`);
}

function openProposal(proposalId: string) {
  router.push(`/projects/${route.params.projectId}/knowledge/proposals/${proposalId}`);
}

function formatDate(value?: string) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString();
}
</script>
