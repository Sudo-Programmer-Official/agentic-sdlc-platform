<script setup lang="ts">
import SectionContainer from "../ui/SectionContainer.vue";
import ContentGrid from "../ui/ContentGrid.vue";
import SectionHeading from "../ui/SectionHeading.vue";

const testimonials = [
  {
    name: "Avery Patel",
    role: "VP Growth, Northline",
    quote: "We went from fragile page rewrites to safe zone-level delivery in one sprint.",
  },
  {
    name: "Mina Torres",
    role: "Demand Gen Lead, ArcFold",
    quote: "Every preview now reflects intended structure without hidden composition drift.",
  },
  {
    name: "Jordan Kim",
    role: "Marketing Ops, Crestway",
    quote: "Runtime stabilization let our team ship experiments every day with confidence.",
  },
];
</script>

<template>
  <SectionContainer>
    <div id="testimonials">
      <SectionHeading>
        <template #title>What Our Customers Say</template>
        <template #subtitle>Visible, validated content rendered by stable primitives.</template>
      </SectionHeading>
      <ContentGrid>
        <article
          v-for="testimonial in testimonials"
          :key="testimonial.name"
          class="rounded-xl border border-slate-200 bg-white p-6"
        >
          <p class="text-sm leading-7 text-slate-700">"{{ testimonial.quote }}"</p>
          <p class="mt-4 text-sm font-semibold text-slate-900">{{ testimonial.name }}</p>
          <p class="text-xs text-slate-500">{{ testimonial.role }}</p>
        </article>
      </ContentGrid>
    </div>
  </SectionContainer>
</template>
