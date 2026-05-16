<template>
  <div class="mx-auto w-full max-w-4xl px-4 py-10 text-slate-800">
    <h1 class="text-3xl font-semibold text-slate-900">Terms of Service</h1>
    <p class="mt-3 text-sm text-slate-600">Effective date: {{ effectiveDate }}</p>
    <div class="mt-6 space-y-4 text-sm leading-7">
      <p>By using Prompt2PR, you agree to use the platform lawfully and in accordance with your organization’s security and compliance requirements.</p>
      <p>You are responsible for credentials, provider accounts, deployment targets, and production release approvals in your environment.</p>
      <p>Prompt2PR provides governed automation and policy controls, but final production ownership remains with your organization.</p>
      <p>For enterprise agreements and support terms, contact <a class="underline text-sky-700" href="mailto:legal@sudoprogrammer.com">legal@sudoprogrammer.com</a>.</p>
    </div>
  </div>
</template>

<script setup lang="ts">
const effectiveDate = "2026-05-15";
</script>
