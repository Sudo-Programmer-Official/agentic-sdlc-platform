<template>
  <div class="page-stack">
    <section class="premium-hero knowledge-hero">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="max-w-3xl space-y-3">
          <button type="button" class="topbar-chip" @click="goBack">
            <AppIcon name="timeline" size="sm" />
            Back to Knowledge
          </button>
          <div>
            <h1 class="text-3xl font-semibold" style="color: var(--text-strong);">
              {{ eventDetail?.title || "Knowledge Event" }}
            </h1>
            <p class="mt-2 text-sm leading-6" style="color: var(--text-muted);">
              Inspect what changed, why the system generated knowledge work, and which proposals are linked to this event.
            </p>
          </div>
        </div>

        <button type="button" class="utility-button" @click="loadEvent" :disabled="loading">
          <AppIcon name="status" />
        </button>
      </div>
    </section>

    <div v-if="error" class="rounded-2xl border px-4 py-3 text-sm" style="border-color: rgba(239, 68, 68, 0.24); background: rgba(239, 68, 68, 0.08); color: var(--danger);">
      {{ error }}
    </div>

    <template v-else-if="eventDetail">
      <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Source" :value="eventDetail.source_type" helper="Event source type" tone="neutral" />
        <MetricCard label="Status" :value="eventDetail.status" helper="Pipeline state" tone="warning" />
        <MetricCard label="PR / Commit" :value="eventIdentity" helper="External source id" tone="success" />
        <MetricCard label="Risk" :value="eventDetail.change?.risk_level || 'medium'" helper="Derived analysis risk" tone="danger" />
      </section>

      <section class="knowledge-review-grid">
        <div class="space-y-4">
          <div class="premium-card p-5">
            <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Event Intelligence</div>
            <div class="mt-4 grid gap-4 md:grid-cols-2">
              <div class="knowledge-meta-card">
                <div class="knowledge-meta-card__label">Plain-language Summary</div>
                <div class="knowledge-meta-card__meta">{{ eventDetail.change?.summary || "No summary available." }}</div>
              </div>
              <div class="knowledge-meta-card">
                <div class="knowledge-meta-card__label">Technical Summary</div>
                <div class="knowledge-meta-card__meta">{{ eventDetail.change?.technical_summary || "No technical summary available." }}</div>
              </div>
            </div>
            <div class="mt-4 text-sm" style="color: var(--text-muted);">
              <strong style="color: var(--text-strong);">Business summary:</strong> {{ eventDetail.change?.business_summary }}
            </div>
            <div class="mt-4 flex flex-wrap gap-2">
              <span v-for="moduleName in eventDetail.change?.impacted_modules || []" :key="moduleName" class="knowledge-pill">
                {{ moduleName }}
              </span>
            </div>
          </div>

          <div class="premium-card p-5">
            <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Changed Files</div>
            <div v-if="eventDetail.change?.impacted_files?.length" class="mt-4 flex flex-wrap gap-2">
              <span v-for="file in eventDetail.change.impacted_files" :key="file" class="knowledge-pill">
                {{ file }}
              </span>
            </div>
            <div v-else class="mt-4 premium-empty">
              No changed files were captured for this event.
            </div>
          </div>

          <div class="premium-card p-0 overflow-hidden">
            <div class="knowledge-panel-header">Raw Event Payload</div>
            <pre class="knowledge-code-panel">{{ prettyPayload }}</pre>
          </div>
        </div>

        <div class="premium-card p-5">
          <div class="text-xs uppercase tracking-[0.24em]" style="color: var(--text-soft);">Linked Proposals</div>
          <div v-if="eventDetail.proposals?.length" class="mt-4 space-y-3">
            <article v-for="proposal in eventDetail.proposals" :key="proposal.id" class="knowledge-history-card">
              <div class="flex items-center justify-between gap-3">
                <div>
                  <div class="font-semibold" style="color: var(--text-strong);">{{ proposal.artifact_title }}</div>
                  <div class="text-sm" style="color: var(--text-muted);">
                    {{ proposal.artifact_type }} · {{ proposal.review_status }}
                  </div>
                </div>
                <button type="button" class="utility-button" @click="openProposal(proposal.id)">
                  <AppIcon name="approvals" />
                </button>
              </div>
            </article>
          </div>
          <div v-else class="mt-4 premium-empty">
            No proposals were linked to this event.
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
import { fetchKnowledgeEvent } from "../api/knowledge";

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const error = ref("");
const eventDetail = ref<any | null>(null);
const projectId = computed(() => String(route.params.projectId || ""));

const eventIdentity = computed(() => {
  if (!eventDetail.value) return "—";
  if (eventDetail.value.pr_number) return `PR #${eventDetail.value.pr_number}`;
  if (eventDetail.value.commit_sha) return eventDetail.value.commit_sha.slice(0, 8);
  return "—";
});

const prettyPayload = computed(() => {
  if (!eventDetail.value?.raw_payload_json) return "No raw payload recorded.";
  try {
    return JSON.stringify(eventDetail.value.raw_payload_json, null, 2);
  } catch {
    return "Failed to render payload.";
  }
});

watch(
  () => route.params.eventId,
  () => {
    void loadEvent();
  },
  { immediate: true }
);

async function loadEvent() {
  if (!projectId.value) return;
  const eventId = String(route.params.eventId || "");
  if (!eventId) return;
  loading.value = true;
  error.value = "";
  try {
    eventDetail.value = await fetchKnowledgeEvent(projectId.value, eventId);
  } catch (err: any) {
    error.value = err?.message || "Failed to load event detail.";
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
</script>
