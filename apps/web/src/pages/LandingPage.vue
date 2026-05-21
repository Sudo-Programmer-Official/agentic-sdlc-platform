<script setup lang="ts">
import PageShell from "../layouts/PageShell.vue";
import HeroZone from "../components/zones/HeroZone.vue";
import FeatureZone from "../components/zones/FeatureZone.vue";
import TestimonialsZone from "../components/zones/TestimonialsZone.vue";
import CTAZone from "../components/zones/CTAZone.vue";
</script>

<template>
  <PageShell>
    <HeroZone />
    <FeatureZone />
    <TestimonialsZone />
    <CTAZone />
  </PageShell>
</template>
