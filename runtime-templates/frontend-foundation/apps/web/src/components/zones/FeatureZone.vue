<script setup lang="ts">
import SectionContainer from "../ui/SectionContainer.vue";
import ContentGrid from "../ui/ContentGrid.vue";
import SectionHeading from "../ui/SectionHeading.vue";
</script>

<template>
  <SectionContainer>
    <div id="features">
      <SectionHeading>
        <template #title>Feature system</template>
        <template #subtitle>Composable sections and governed primitives for predictable mutation.</template>
      </SectionHeading>
      <ContentGrid>
        <article class="rounded-xl border border-slate-200 bg-white p-6">
          <h3 class="text-lg font-semibold text-slate-900">Topology contracts</h3>
          <p class="mt-2 text-sm leading-6 text-slate-600">Prevent unsafe rewrites and keep zone composition stable.</p>
        </article>
        <article class="rounded-xl border border-slate-200 bg-white p-6">
          <h3 class="text-lg font-semibold text-slate-900">Deterministic imports</h3>
          <p class="mt-2 text-sm leading-6 text-slate-600">Resolve components through manifest-backed canonical mapping.</p>
        </article>
        <article class="rounded-xl border border-slate-200 bg-white p-6">
          <h3 class="text-lg font-semibold text-slate-900">Visual safeguards</h3>
          <p class="mt-2 text-sm leading-6 text-slate-600">Ensure rendered content remains visible and responsive.</p>
        </article>
      </ContentGrid>
    </div>
  </SectionContainer>
</template>
