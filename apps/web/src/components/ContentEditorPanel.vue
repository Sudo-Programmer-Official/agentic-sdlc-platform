<template>
  <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-3">
    <div class="flex items-center justify-between gap-2">
      <div>
        <div class="text-xs uppercase tracking-wide text-slate-400">Content Editor</div>
        <div class="text-sm text-slate-600">Edit and publish content without code generation.</div>
      </div>
      <el-select v-model="environment" size="small" style="width: 130px" @change="load">
        <el-option label="PREVIEW" value="PREVIEW" />
        <el-option label="STAGING" value="STAGING" />
        <el-option label="PRODUCTION" value="PRODUCTION" />
      </el-select>
    </div>

    <div class="grid gap-2 max-h-56 overflow-auto">
      <button
        v-for="item in items"
        :key="item.id"
        type="button"
        class="text-left rounded border px-2 py-1 text-xs"
        :class="selected?.id === item.id ? 'border-sky-400 bg-sky-50' : 'border-slate-200 bg-slate-50'"
        @click="selectItem(item)"
      >
        <div class="font-mono text-slate-700">{{ item.key }}</div>
        <div class="text-slate-500">v{{ item.version }} · {{ item.status }}</div>
      </button>
    </div>

    <div v-if="selected" class="space-y-2">
      <div class="text-xs font-semibold text-slate-700">{{ selected.key }}</div>
      <el-input v-model="draftValue" type="textarea" :rows="4" />
      <div class="flex flex-wrap gap-2">
        <el-button size="small" type="primary" @click="save(false)">Save Draft</el-button>
        <el-button size="small" @click="save(true)">Publish</el-button>
        <el-button size="small" plain :disabled="!selected.version || selected.version < 2" @click="rollback">Rollback</el-button>
      </div>
    </div>
    <div v-else class="text-xs text-slate-500">No content items yet. Seed content via runtime generation or save a new key through API.</div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { fetchContentItems, publishContent, rollbackContentItem, saveContentItem, type ContentItem } from "../api/content";

const props = defineProps<{ projectId: string }>();

const environment = ref<"PREVIEW" | "STAGING" | "PRODUCTION">("PREVIEW");
const items = ref<ContentItem[]>([]);
const selected = ref<ContentItem | null>(null);
const draftValue = ref("");

function selectItem(item: ContentItem) {
  selected.value = item;
  draftValue.value = typeof item.value === "string" ? item.value : JSON.stringify(item.value ?? "", null, 2);
}

async function load() {
  if (!props.projectId) return;
  items.value = await fetchContentItems(props.projectId, environment.value);
  if (selected.value) {
    const next = items.value.find((item) => item.id === selected.value?.id);
    if (next) selectItem(next);
  }
}

async function save(publishNow: boolean) {
  if (!props.projectId || !selected.value) return;
  const saved = await saveContentItem(
    props.projectId,
    { key: selected.value.key, type: selected.value.type, value: draftValue.value, source: "operator" },
    environment.value,
    publishNow
  );
  selected.value = saved;
  await load();
}

async function rollback() {
  if (!props.projectId || !selected.value || selected.value.version < 2) return;
  await rollbackContentItem(props.projectId, selected.value.key, selected.value.version - 1, environment.value);
  await load();
}

async function promoteTo(targetEnvironment: "STAGING" | "PRODUCTION") {
  if (!props.projectId) return;
  await publishContent(props.projectId, environment.value, targetEnvironment);
}

void promoteTo;
onMounted(load);
</script>
