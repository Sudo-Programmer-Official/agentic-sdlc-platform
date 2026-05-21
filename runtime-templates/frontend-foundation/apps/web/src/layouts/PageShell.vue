<script setup lang="ts">
import Navbar from "../components/layout/Navbar.vue";
import MobileNav from "../components/layout/MobileNav.vue";
import Footer from "../components/layout/Footer.vue";
</script>

<template>
  <div class="min-h-screen bg-slate-50 text-slate-900">
    <Navbar />
    <MobileNav />
    <main class="py-10 sm:py-12 lg:py-14">
      <slot />
    </main>
    <Footer />
  </div>
</template>
