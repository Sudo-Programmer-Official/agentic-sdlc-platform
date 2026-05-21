<template>
  <section class="hero">
    <p class="eyebrow">Governed growth system</p>
    <h1>Launch campaigns fast without losing architectural control.</h1>
    <p class="body">
      This starter runtime ships with a componentized frontend shell, a FastAPI backend, and preview-aware governance
      so feature generation can begin immediately.
    </p>
    <div class="actions">
      <a href="#capture" class="primary">Start building</a>
      <span class="secondary">Preview-ready monorepo foundation</span>
    </div>
  </section>
</template>

<style scoped>
.hero {
  display: grid;
  gap: 1rem;
}

.eyebrow {
  margin: 0;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  font-size: 0.78rem;
  color: var(--accent-deep);
}

h1 {
  margin: 0;
  max-width: 11ch;
  font-size: clamp(3rem, 8vw, 5.5rem);
  line-height: 0.95;
}

.body {
  margin: 0;
  max-width: 44rem;
  font-size: 1.1rem;
  line-height: 1.7;
  color: var(--muted);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.9rem;
  align-items: center;
}

.primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.95rem 1.4rem;
  border-radius: 999px;
  background: var(--accent);
  color: #fff8f2;
  text-decoration: none;
  font-weight: 700;
}

.secondary {
  color: var(--muted);
}
</style>
