<template>
  <div class="mx-auto w-full max-w-4xl px-4 py-10 text-slate-800">
    <h1 class="text-3xl font-semibold text-slate-900">Privacy Policy</h1>
    <p class="mt-3 text-sm text-slate-600">Effective date: {{ effectiveDate }}</p>
    <div class="mt-6 space-y-4 text-sm leading-7">
      <p>Prompt2PR (product) by Sudo Programmer (company) is committed to protecting your data and operational privacy.</p>
      <p>We collect account, workspace, project, and usage telemetry required to deliver governed software operations and platform reliability.</p>
      <p>We do not sell personal data. Data access is limited by role, tenancy boundaries, and operational controls.</p>
      <p>If you need data export or deletion support, contact <a class="underline text-sky-700" href="mailto:privacy@sudoprogrammer.com">privacy@sudoprogrammer.com</a>.</p>
    </div>
  </div>
</template>

<script setup lang="ts">
const effectiveDate = "2026-05-15";
</script>
