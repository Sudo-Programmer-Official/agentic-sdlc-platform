<template>
  <article class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
    <h3 class="text-xl font-semibold text-slate-900">
      <ContentSlot :project-id="projectId" :content-key="titleKey" fallback="Enterprise" />
    </h3>
    <p class="mt-2 text-slate-600">
      <ContentSlot :project-id="projectId" :content-key="descriptionKey" fallback="Governed deployment and runtime controls." />
    </p>
  </article>
</template>

<script setup lang="ts">
import ContentSlot from "../ContentSlot.vue";

defineProps<{
  projectId: string;
  titleKey?: string;
  descriptionKey?: string;
}>();
</script>
