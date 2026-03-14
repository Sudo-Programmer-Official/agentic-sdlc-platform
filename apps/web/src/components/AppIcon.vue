<template>
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    :class="iconClass"
    aria-hidden="true"
  >
    <path v-if="name === 'workspace'" d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z" />
    <path v-else-if="name === 'map'" d="M3 6.5 8.5 4 15.5 6.5 21 4v13l-5.5 2.5L8.5 17 3 19.5z" />
    <path v-if="name === 'map'" d="M8.5 4v13M15.5 6.5v13" />
    <path v-else-if="name === 'project'" d="M4 6h7l2 2h7v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
    <path v-else-if="name === 'artifact'" d="M7 3h7l5 5v13H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" />
    <path v-if="name === 'artifact'" d="M14 3v5h5" />
    <path v-else-if="name === 'branch'" d="M6 4v8a3 3 0 0 0 3 3h9" />
    <circle v-if="name === 'branch'" cx="6" cy="4" r="2" />
    <circle v-if="name === 'branch'" cx="18" cy="15" r="2" />
    <circle v-if="name === 'branch'" cx="6" cy="18" r="2" />
    <path v-else-if="name === 'warning'" d="M12 3 21 19H3z" />
    <path v-if="name === 'warning'" d="M12 9v4M12 17h.01" />
    <path v-else-if="name === 'requirements'" d="M7 5h10M7 10h10M7 15h7M5 5h.01M5 10h.01M5 15h.01" />
    <path v-else-if="name === 'mission'" d="M12 2l2.2 4.8L19 9l-4.8 2.2L12 16l-2.2-4.8L5 9l4.8-2.2z" />
    <path v-else-if="name === 'timeline'" d="M6 6v12M12 9v9M18 4v14" />
    <path v-else-if="name === 'approvals'" d="m5 13 4 4L19 7" />
    <path v-else-if="name === 'knowledge'" d="M6 4h9a3 3 0 0 1 3 3v13H9a3 3 0 0 0-3-3z" />
    <path v-if="name === 'knowledge'" d="M6 4v13a3 3 0 0 1 3 3M18 7h-6" />
    <path v-else-if="name === 'runs'" d="M5 7h14M5 12h9M5 17h6" />
    <path v-else-if="name === 'operator'" d="M8 8a4 4 0 1 1 8 0v1.8a2 2 0 0 0 .5 1.3l1.2 1.4A1.2 1.2 0 0 1 16.8 15H7.2a1.2 1.2 0 0 1-.9-2l1.2-1.4A2 2 0 0 0 8 9.8z" />
    <path v-if="name === 'operator'" d="M10 18h4M12 15v3M18.5 6.5 20 5M4 5l1.5 1.5M12 3V1.5" />
    <path v-else-if="name === 'search'" d="m21 21-4.35-4.35" />
    <circle v-if="name === 'search'" cx="11" cy="11" r="6" />
    <path v-else-if="name === 'bell'" d="M15 17H5.5a1.5 1.5 0 0 1-1.2-2.4l1-1.3A4 4 0 0 0 6 10.9V9a6 6 0 1 1 12 0v1.9c0 .9.3 1.8.8 2.5l1 1.3A1.5 1.5 0 0 1 18.5 17H15" />
    <path v-if="name === 'bell'" d="M9.5 20a2.5 2.5 0 0 0 5 0" />
    <path v-else-if="name === 'user'" d="M18 20a6 6 0 0 0-12 0M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z" />
    <path v-else-if="name === 'sun'" d="M12 3v2.5M12 18.5V21M4.9 4.9l1.7 1.7M17.4 17.4l1.7 1.7M3 12h2.5M18.5 12H21M4.9 19.1l1.7-1.7M17.4 6.6l1.7-1.7" />
    <circle v-if="name === 'sun'" cx="12" cy="12" r="4" />
    <path v-else-if="name === 'moon'" d="M20 14.5A7.5 7.5 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z" />
    <path v-else-if="name === 'spark'" d="M12 3l1.6 3.4L17 8l-3.4 1.6L12 13l-1.6-3.4L7 8l3.4-1.6z" />
    <path v-else-if="name === 'spark'" d="M18 15l.9 1.9L21 18l-2.1 1.1L18 21l-1.1-1.9L15 18l1.9-1.1z" />
    <path v-else-if="name === 'play'" d="m8 6 10 6-10 6z" />
    <path v-else-if="name === 'status'" d="M5 12h14M12 5v14" />
    <path v-else d="M4 12h16" />
  </svg>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    name: string;
    size?: "sm" | "md" | "lg";
  }>(),
  {
    size: "md",
  }
);

const iconClass = computed(() => {
  if (props.size === "sm") return "h-4 w-4";
  if (props.size === "lg") return "h-6 w-6";
  return "h-5 w-5";
});
</script>
