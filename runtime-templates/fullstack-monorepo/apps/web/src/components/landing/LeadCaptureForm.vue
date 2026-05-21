<template>
  <section id="capture" class="capture">
    <div>
      <p class="label">Starter workflow</p>
      <h2>Wire lead capture to the governed API contract.</h2>
    </div>
    <form class="form" @submit.prevent>
      <label>
        <span>Name</span>
        <input type="text" placeholder="Ada Lovelace" />
      </label>
      <label>
        <span>Email</span>
        <input type="email" placeholder="ada@example.com" />
      </label>
      <button type="submit">Connect submission flow</button>
    </form>
  </section>
</template>

<style scoped>
.capture {
  display: grid;
  gap: 1.2rem;
  padding: 1.5rem;
  border: 1px solid var(--line);
  border-radius: 1.5rem;
  background: var(--panel);
  backdrop-filter: blur(10px);
}

.label {
  margin: 0 0 0.35rem;
  font-size: 0.84rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--accent-deep);
}

h2 {
  margin: 0;
  font-size: clamp(1.6rem, 4vw, 2.4rem);
}

.form {
  display: grid;
  gap: 0.9rem;
}

label {
  display: grid;
  gap: 0.45rem;
}

input {
  width: 100%;
  padding: 0.95rem 1rem;
  border-radius: 0.95rem;
  border: 1px solid rgba(27, 28, 32, 0.12);
  background: rgba(255, 255, 255, 0.92);
}

button {
  width: fit-content;
  padding: 0.95rem 1.2rem;
  border: 0;
  border-radius: 999px;
  background: #1b1c20;
  color: #f8f5ef;
  font-weight: 700;
  cursor: pointer;
}
</style>
