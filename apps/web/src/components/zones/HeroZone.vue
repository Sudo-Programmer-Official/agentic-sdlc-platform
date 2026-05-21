<script setup lang="ts">
import SectionContainer from "../ui/SectionContainer.vue";
import Stack from "../ui/Stack.vue";
import PrimaryButton from "../ui/PrimaryButton.vue";
</script>

<template>
  <SectionContainer>
    <Stack>
      <p id="hero" class="text-sm font-medium uppercase tracking-[0.14em] text-slate-500">Mission control</p>
      <h1 class="text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">Ship revenue experiments faster.</h1>
      <p class="max-w-2xl text-base leading-7 text-slate-600">
        Deterministic foundation first, reliable feature evolution second.
      </p>
      <div>
        <PrimaryButton>Start now</PrimaryButton>
      </div>
    </Stack>
  </SectionContainer>
</template>
