<template>
  <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm text-xs text-slate-700">
    <div class="flex items-center justify-between gap-2">
      <div class="text-xs uppercase tracking-wide text-slate-400">Deployment Trust Surface</div>
      <span class="font-semibold" :class="scoreTone">{{ contract.score_pct }}%</span>
    </div>
    <div class="mt-2 text-sm font-semibold text-slate-900">{{ contract.environment }} · confidence {{ Math.round((contract.confidence_score || 0) * 100) }}%</div>
    <div class="mt-1">
      You can still: <span class="font-semibold text-emerald-700">{{ contract.safe_to_preview ? '✅ Deploy preview' : '❌ Deploy preview' }}</span>
      · <span class="font-semibold" :class="contract.safe_to_production ? 'text-emerald-700' : 'text-rose-700'">{{ contract.safe_to_production ? '✅ Promote to production' : '❌ Promote to production' }}</span>
    </div>
    <div v-if="contract.blockers?.length" class="mt-2">
      <div class="font-semibold text-rose-700">Blockers</div>
      <div>{{ contract.blockers.join(' | ') }}</div>
    </div>
    <div v-if="contract.warnings?.length" class="mt-2">
      <div class="font-semibold text-amber-700">Warnings</div>
      <div>{{ contract.warnings.join(' | ') }}</div>
    </div>
    <div v-if="contract.recommended_actions?.length" class="mt-2">
      <div class="font-semibold text-slate-900">Recommended Actions</div>
      <div>{{ contract.recommended_actions.join(' | ') }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { DeploymentReadinessContract } from "../api/lifecycle";

const props = defineProps<{ contract: DeploymentReadinessContract }>();

const scoreTone = computed(() => {
  if (props.contract.score_pct < 60) return "text-rose-700";
  if (props.contract.score_pct < 80) return "text-amber-700";
  return "text-emerald-700";
});
</script>
