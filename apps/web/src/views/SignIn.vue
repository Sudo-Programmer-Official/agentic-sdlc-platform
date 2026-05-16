<template>
  <div class="mx-auto flex min-h-[70vh] w-full max-w-md items-center justify-center px-4">
    <div class="w-full rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h1 class="text-xl font-semibold text-slate-900">{{ isCreateMode ? "Create account" : "Sign in" }}</h1>
      <p class="mt-1 text-sm text-slate-500">
        {{ isCreateMode ? "Create your Prompt2PR operator account." : "Access your Prompt2PR dashboard." }}
      </p>

      <div class="mt-4 inline-flex rounded-xl border border-slate-200 bg-slate-50 p-1">
        <button
          type="button"
          class="rounded-lg px-3 py-1.5 text-sm"
          :class="!isCreateMode ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600'"
          @click="isCreateMode = false"
        >
          Sign in
        </button>
        <button
          type="button"
          class="rounded-lg px-3 py-1.5 text-sm"
          :class="isCreateMode ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600'"
          @click="isCreateMode = true"
        >
          Create account
        </button>
      </div>

      <form class="mt-5 space-y-4" @submit.prevent="submit">
        <label class="block">
          <span class="mb-1 block text-sm text-slate-700">Email</span>
          <input
            v-model="email"
            type="email"
            autocomplete="email"
            class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
            required
          />
        </label>

        <label class="block">
          <span class="mb-1 block text-sm text-slate-700">Password</span>
          <input
            v-model="password"
            type="password"
            :autocomplete="isCreateMode ? 'new-password' : 'current-password'"
            class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
            minlength="6"
            required
          />
        </label>

        <p v-if="error" class="text-sm text-rose-600">{{ error }}</p>

        <button
          type="submit"
          :disabled="loading"
          class="w-full rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {{ loading ? (isCreateMode ? "Creating account..." : "Signing in...") : (isCreateMode ? "Create account" : "Sign in") }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { getAuthToken } from "../api/lifecycle";
import { loginWithEmailPassword, signupWithEmailPassword } from "../auth/firebaseAuth";

const route = useRoute();
const router = useRouter();
const email = ref("");
const password = ref("");
const isCreateMode = ref(false);
const loading = ref(false);
const error = ref("");

async function submit() {
  loading.value = true;
  error.value = "";
  try {
    const normalizedEmail = email.value.trim();
    if (isCreateMode.value) {
      if (password.value.length < 6) {
        error.value = "Password must be at least 6 characters.";
        return;
      }
      await signupWithEmailPassword(normalizedEmail, password.value);
    } else {
      await loginWithEmailPassword(normalizedEmail, password.value);
    }
    const token = getAuthToken();
    const next = typeof route.query.redirect === "string" && route.query.redirect ? route.query.redirect : "/workspace";
    if (!token) {
      error.value = "Session not established yet. Try again.";
      return;
    }
    await router.replace(next);
  } catch (err: any) {
    error.value = err?.message || "Unable to sign in.";
  } finally {
    loading.value = false;
  }
}
</script>
