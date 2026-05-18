<template>
  <section class="rounded-2xl border border-sky-200 bg-sky-50 p-6">
    <h2 class="text-2xl font-semibold text-sky-900">
      <ContentSlot :project-id="projectId" :content-key="titleKey" fallback="Ready to accelerate delivery?" />
    </h2>
    <button type="button" class="mt-4 rounded bg-sky-600 px-4 py-2 text-white">
      <ContentSlot :project-id="projectId" :content-key="buttonKey" fallback="Start now" />
    </button>
  </section>
</template>

<script setup lang="ts">
import ContentSlot from "../ContentSlot.vue";

defineProps<{
  projectId: string;
  titleKey?: string;
  buttonKey?: string;
}>();
</script>
