<template>
  <span>{{ resolvedText }}</span>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { fetchContentItems } from "../api/content";

const props = withDefaults(defineProps<{
  projectId: string;
  contentKey: string;
  fallback?: string;
  environment?: "PREVIEW" | "STAGING" | "PRODUCTION";
  refreshMs?: number;
}>(), {
  fallback: "",
  environment: "PREVIEW",
  refreshMs: 0,
});

const value = ref<any>(null);
let timer: number | null = null;

const resolvedText = computed(() => {
  const raw = value.value;
  if (raw === null || raw === undefined || raw === "") return props.fallback;
  if (typeof raw === "string") return raw;
  return JSON.stringify(raw);
});

async function load() {
  if (!props.projectId || !props.contentKey) return;
  const items = await fetchContentItems(props.projectId, props.environment);
  const match = items.find((item) => item.key === props.contentKey);
  value.value = match?.value ?? null;
}

onMounted(async () => {
  await load();
  if (props.refreshMs > 0) {
    timer = window.setInterval(load, props.refreshMs);
  }
});

onUnmounted(() => {
  if (timer !== null) {
    window.clearInterval(timer);
  }
});

watch(() => [props.contentKey, props.projectId, props.environment], async () => {
  await load();
});
</script>
