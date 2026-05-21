<script setup lang="ts">
import SectionContainer from "../ui/SectionContainer.vue";
import PrimaryButton from "../ui/PrimaryButton.vue";
</script>

<template>
  <SectionContainer>
    <div id="cta" class="rounded-2xl border border-slate-200 bg-white p-8 text-center sm:p-10">
      <h2 class="text-2xl font-semibold text-slate-900 sm:text-3xl">Ready to scale reliable delivery?</h2>
      <p class="mx-auto mt-3 max-w-2xl text-sm leading-7 text-slate-600">
        Start with deterministic foundation topology, then evolve features safely inside zones.
      </p>
      <div class="mt-6">
        <PrimaryButton>Request a demo</PrimaryButton>
      </div>
    </div>
  </SectionContainer>
</template>
