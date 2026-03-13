<template>
  <div class="operator-shell">
    <div class="operator-shell__fab">
      <OperatorFab :open="open" :enabled="Boolean(currentProjectId)" @open="open = true" />
    </div>

    <el-drawer
      v-model="open"
      direction="rtl"
      size="440px"
      modal-class="operator-shell__backdrop"
      custom-class="operator-shell__drawer"
      :with-header="false"
      :destroy-on-close="false"
    >
      <OperatorConsole variant="drawer" closable @close="open = false" />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";

import { useOperatorConsole } from "../../composables/useOperatorConsole";
import OperatorFab from "./OperatorFab.vue";
import OperatorConsole from "./OperatorConsole.vue";

const open = ref(false);
const { currentProjectId } = useOperatorConsole();
</script>

<style scoped>
.operator-shell {
  position: fixed;
  right: 1.4rem;
  bottom: 1.4rem;
  z-index: 50;
}

.operator-shell__fab {
  display: flex;
  justify-content: flex-end;
}

:global(.operator-shell__drawer) {
  background: transparent !important;
  box-shadow: none !important;
}

@media (max-width: 900px) {
  .operator-shell {
    right: 1rem;
    bottom: 1rem;
  }
}
</style>
