<template>
  <div class="page-stack">
    <section class="premium-hero knowledge-hero">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="max-w-3xl space-y-3">
          <div class="topbar-chip">
            <AppIcon name="knowledge" size="sm" />
            Engineering Memory
          </div>
          <div>
            <h1 class="text-3xl font-semibold" style="color: var(--text-strong);">Knowledge Verification Inbox</h1>
            <p class="mt-2 text-sm leading-6" style="color: var(--text-muted);">
              Repo changes become AI-generated knowledge drafts here. Nothing becomes official until a reviewer approves the proposed artifact update.
            </p>
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <button type="button" class="utility-button" @click="triggerSync" :disabled="syncing || !projectId" title="Sync knowledge now">
            <AppIcon name="spark" />
          </button>
          <button type="button" class="utility-button" @click="loadPage" :disabled="loading" title="Refresh">
            <AppIcon name="status" />
          </button>
        </div>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="Pending Drafts" :value="String(inboxItems.length)" helper="Awaiting human verification" tone="warning" />
      <MetricCard label="High Risk" :value="String(highRiskCount)" helper="Needs careful review" tone="danger" />
      <MetricCard label="Low Confidence" :value="String(lowConfidenceCount)" helper="Likely requires edits" tone="neutral" />
      <MetricCard label="Official Artifacts" :value="String(artifactCount)" helper="Published knowledge base entries" tone="success" />
    </section>

    <section class="premium-card p-5">
      <div class="knowledge-toolbar">
        <div class="search-shell">
          <AppIcon name="search" />
          <input v-model="searchTerm" type="text" placeholder="Search by event, module, or artifact" />
        </div>

        <div class="knowledge-filter-grid">
          <el-select v-model="reviewStatus" size="small" style="width: 150px">
            <el-option label="Pending" value="pending" />
            <el-option label="Published" value="published" />
            <el-option label="Deferred" value="deferred" />
            <el-option label="Rejected" value="rejected" />
            <el-option label="Superseded" value="superseded" />
          </el-select>
          <el-select v-model="changeType" size="small" style="width: 150px" clearable placeholder="Change type">
            <el-option v-for="item in changeOptions" :key="item" :label="item" :value="item" />
          </el-select>
          <el-select v-model="artifactType" size="small" style="width: 170px" clearable placeholder="Artifact type">
            <el-option v-for="item in artifactOptions" :key="item" :label="item" :value="item" />
          </el-select>
          <el-select v-model="riskLevel" size="small" style="width: 140px" clearable placeholder="Risk">
            <el-option label="Low" value="low" />
            <el-option label="Medium" value="medium" />
            <el-option label="High" value="high" />
          </el-select>
        </div>
      </div>

      <div v-if="error" class="mt-4 rounded-2xl border px-4 py-3 text-sm" style="border-color: rgba(239, 68, 68, 0.24); background: rgba(239, 68, 68, 0.08); color: var(--danger);">
        {{ error }}
      </div>

      <div v-else-if="filteredItems.length" class="mt-5 knowledge-list">
        <article
          v-for="item in filteredItems"
          :key="item.proposal_id"
          class="knowledge-list-item"
          @click="openProposal(item.proposal_id)"
        >
          <div class="knowledge-list-item__main">
            <div class="flex flex-wrap items-center gap-2">
              <div class="topbar-chip">{{ item.source_type }}</div>
              <div class="status-ring" :style="riskStyle(item.risk_level)">
                <span class="soft-dot" />
                {{ item.risk_level }}
              </div>
              <div class="status-ring" :style="statusStyle(item.review_status)">
                <span class="soft-dot" />
                {{ item.review_status }}
              </div>
            </div>
            <div class="mt-3 text-lg font-semibold" style="color: var(--text-strong);">
              {{ item.event_title || item.proposal_target }}
            </div>
            <div class="mt-2 text-sm" style="color: var(--text-muted);">
              {{ item.proposal_target }} · {{ item.artifact_type }} · {{ item.repo_full_name || "Connected repo" }}
            </div>
            <div class="mt-4 flex flex-wrap gap-2">
              <span v-for="moduleName in item.impacted_modules.slice(0, 4)" :key="moduleName" class="knowledge-pill">
                {{ moduleName }}
              </span>
            </div>
          </div>

          <div class="knowledge-list-item__meta">
            <div class="knowledge-stat">
              <span>Confidence</span>
              <strong>{{ Math.round((item.confidence_score || 0) * 100) }}%</strong>
            </div>
            <div class="knowledge-stat">
              <span>Change</span>
              <strong>{{ item.change_type }}</strong>
            </div>
            <div class="knowledge-stat">
              <span>Detected</span>
              <strong>{{ formatDate(item.detected_at) }}</strong>
            </div>
          </div>
        </article>
      </div>

      <div v-else class="mt-5 premium-empty">
        No proposals match the current filters.
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppIcon from "../components/AppIcon.vue";
import MetricCard from "../components/MetricCard.vue";
import { fetchProjectMeta } from "../api/lifecycle";
import { fetchKnowledgeArtifacts, fetchKnowledgeInbox, triggerKnowledgeManualSync } from "../api/knowledge";
import { updateProjectContext } from "../state/projectContext";

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const syncing = ref(false);
const error = ref("");
const inboxItems = ref<any[]>([]);
const artifactCount = ref(0);
const searchTerm = ref("");
const reviewStatus = ref("pending");
const changeType = ref("");
const artifactType = ref("");
const riskLevel = ref("");

const changeOptions = ["feature", "bugfix", "refactor", "infra", "docs", "test", "config", "schema", "api", "unknown"];
const artifactOptions = ["module_doc", "changelog", "architecture_note", "runbook", "adr", "release_note", "onboarding_note", "api_note", "db_note"];
const projectId = computed(() => String(route.params.projectId || ""));

const filteredItems = computed(() => {
  const query = searchTerm.value.trim().toLowerCase();
  if (!query) return inboxItems.value;
  return inboxItems.value.filter((item) => {
    const haystack = [
      item.event_title,
      item.proposal_target,
      item.artifact_type,
      item.change_type,
      ...(item.impacted_modules || []),
      item.repo_full_name,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  });
});

const highRiskCount = computed(() => inboxItems.value.filter((item) => item.risk_level === "high").length);
const lowConfidenceCount = computed(() => inboxItems.value.filter((item) => Number(item.confidence_score || 0) < 0.6).length);

watch(
  [projectId, reviewStatus, changeType, artifactType, riskLevel],
  () => {
    void loadPage();
  },
  { immediate: true }
);

async function loadPage() {
  if (!projectId.value) return;
  loading.value = true;
  error.value = "";
  try {
    const [project, inbox, artifacts] = await Promise.all([
      fetchProjectMeta(projectId.value),
      fetchKnowledgeInbox({
        project_id: projectId.value,
        review_status: reviewStatus.value,
        change_type: changeType.value || undefined,
        artifact_type: artifactType.value || undefined,
        risk_level: riskLevel.value || undefined,
      }),
      fetchKnowledgeArtifacts({ project_id: projectId.value }),
    ]);
    inboxItems.value = Array.isArray(inbox?.items) ? inbox.items : [];
    artifactCount.value = Array.isArray(artifacts?.items) ? artifacts.items.length : 0;
    updateProjectContext({
      projectId: projectId.value,
      projectName: project?.name || "Project",
      stage: project?.status || "UNKNOWN",
      updatedAt: new Date().toISOString(),
    });
  } catch (err: any) {
    error.value = err?.message || "Failed to load the knowledge inbox.";
  } finally {
    loading.value = false;
  }
}

async function triggerSync() {
  if (!projectId.value) return;
  syncing.value = true;
  error.value = "";
  try {
    await triggerKnowledgeManualSync({ project_id: projectId.value });
    await loadPage();
  } catch (err: any) {
    error.value = err?.message || "Manual knowledge sync failed.";
  } finally {
    syncing.value = false;
  }
}

function openProposal(proposalId: string) {
  router.push(`/projects/${projectId.value}/knowledge/proposals/${proposalId}`);
}

function formatDate(value?: string) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString();
}

function riskStyle(risk?: string) {
  if (risk === "high") return { background: "rgba(239, 68, 68, 0.12)", color: "var(--danger)" };
  if (risk === "medium") return { background: "rgba(245, 158, 11, 0.12)", color: "var(--warning)" };
  return { background: "rgba(34, 197, 94, 0.12)", color: "var(--success)" };
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
