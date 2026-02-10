<template>
  <div class="space-y-4">
    <h1 class="text-3xl font-semibold text-slate-900">SDLC Timeline</h1>
    <p class="text-slate-600">
      Placeholder for state machine visualization and stage history.
    </p>
    <div class="grid gap-3 md:grid-cols-2">
      <div class="rounded-xl border border-slate-200 bg-white p-4">
        <div class="text-xs uppercase tracking-wide text-slate-400">Current Stage</div>
        <div class="mt-2 text-lg font-medium text-slate-900">Requirements Drafted</div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-4">
        <div class="text-xs uppercase tracking-wide text-slate-400">Awaiting</div>
        <div class="mt-2 text-lg font-medium text-slate-900">Approval Gate</div>
      </div>
    </div>
  </div>
</template>
