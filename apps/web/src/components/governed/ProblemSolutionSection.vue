<template>
  <section class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
    <h3 class="text-xl font-semibold text-slate-900">
      <ContentSlot :project-id="projectId" :content-key="problemKey" fallback="Current systems fragment delivery." />
    </h3>
    <p class="mt-2 text-slate-600">
      <ContentSlot :project-id="projectId" :content-key="solutionKey" fallback="Prompt2PR unifies execution, governance, and promotion." />
    </p>
  </section>
</template>

<script setup lang="ts">
import ContentSlot from "../ContentSlot.vue";

defineProps<{
  projectId: string;
  problemKey?: string;
  solutionKey?: string;
}>();
</script>
