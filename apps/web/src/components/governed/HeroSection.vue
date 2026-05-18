<template>
  <section class="governed-hero rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
    <h1 class="text-3xl font-semibold text-slate-900">
      <ContentSlot :project-id="projectId" :content-key="titleKey" fallback="Ship governed software faster." />
    </h1>
    <p class="mt-3 text-slate-600">
      <ContentSlot :project-id="projectId" :content-key="subtitleKey" fallback="Composable runtime architecture with deterministic controls." />
    </p>
  </section>
</template>

<script setup lang="ts">
import ContentSlot from "../ContentSlot.vue";

defineProps<{
  projectId: string;
  titleKey?: string;
  subtitleKey?: string;
}>();
</script>
