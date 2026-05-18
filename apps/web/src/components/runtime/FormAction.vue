<template>
  <form @submit.prevent="onSubmit">
    <slot />
    <div v-if="error" class="mt-2 rounded-md border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700">
      {{ error }}
    </div>
  </form>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { apiFetch } from "../../api/lifecycle";

type CapabilityResolveResponse = {
  provider: string;
  target?: string | null;
  diagnostics?: Record<string, any>;
};

const props = defineProps<{
  projectId: string;
  environment?: "LOCAL_DEV" | "PREVIEW" | "STAGING" | "PRODUCTION";
  capability: string;
}>();

const emit = defineEmits<{ (e: "submitted", payload: { provider: string; target?: string | null }): void }>();
const error = ref("");

async function onSubmit() {
  error.value = "";
  try {
    const env = props.environment || "PREVIEW";
    const resp = await apiFetch(
      `${import.meta.env.VITE_API_BASE || "http://localhost:8000/api/v1"}/projects/${props.projectId}/capabilities/${props.capability}/resolve?environment=${env}`
    );
    if (!resp.ok) {
      const payload = await resp.json().catch(() => ({}));
      const detail = payload?.detail;
      const message = typeof detail === "string" ? detail : detail?.message || "Capability unresolved. Open Integrations and bind capability.";
      error.value = `${message} Next: Project → Integrations → Bind ${props.capability}.`;
      return;
    }
    const resolved = (await resp.json()) as CapabilityResolveResponse;
    emit("submitted", { provider: resolved.provider, target: resolved.target || undefined });
  } catch {
    error.value = "Capability runtime unavailable. Retry or check Integration health in Environment Center.";
  }
}
</script>
