<template>
  <header class="mb-6 sm:mb-8">
    <h2 class="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
      <slot name="title">Section title</slot>
    </h2>
    <p class="mt-2 text-base leading-7 text-slate-600">
      <slot name="subtitle">Section subtitle</slot>
    </p>
  </header>
</template>
