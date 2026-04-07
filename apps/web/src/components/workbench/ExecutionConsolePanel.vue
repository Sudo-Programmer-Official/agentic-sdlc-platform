<template>
  <section class="execution-console">
    <div class="execution-console__header">
      <div>
        <div class="execution-console__eyebrow">Live Runtime Console</div>
        <h2 class="execution-console__title">See the workspace, commands, and output as the run executes.</h2>
        <p class="execution-console__copy">
          This panel shows how the environment is being prepared, which command is active, and what the runtime emitted most recently.
        </p>
      </div>
      <div class="execution-console__summary">
        <div class="execution-console__summary-label">Active commands</div>
        <div class="execution-console__summary-value">{{ summary.active_command_count || 0 }}</div>
        <div class="execution-console__summary-meta">{{ summary.run_status || runStatus }}</div>
      </div>
    </div>

    <div class="execution-console__environment">
      <div class="execution-console__env-card">
        <div class="execution-console__env-label">Branch</div>
        <div class="execution-console__env-value">{{ environment.branch_name || "Not assigned yet" }}</div>
        <div class="execution-console__env-meta">{{ environment.repo_branch || "Base branch pending" }}</div>
      </div>
      <div class="execution-console__env-card">
        <div class="execution-console__env-label">Workspace</div>
        <div class="execution-console__env-value">{{ environment.workspace_status || "PENDING" }}</div>
        <div class="execution-console__env-meta">{{ environment.repo_auth_mode || "Auth mode pending" }}</div>
      </div>
      <div class="execution-console__env-card">
        <div class="execution-console__env-label">Repo path</div>
        <div class="execution-console__env-value execution-console__path">{{ environment.repo_path || "Not prepared yet" }}</div>
        <div class="execution-console__env-meta">{{ environment.workspace_root || "Workspace root pending" }}</div>
      </div>
      <div class="execution-console__env-card">
        <div class="execution-console__env-label">Allowed tools</div>
        <div class="execution-console__env-value">{{ allowedToolCount }}</div>
        <div class="execution-console__env-meta">{{ allowedToolPreview }}</div>
      </div>
      <div class="execution-console__env-card">
        <div class="execution-console__env-label">API Repo Auth</div>
        <div class="execution-console__env-value">{{ runtimeGitAuthValue }}</div>
        <div class="execution-console__env-meta">{{ runtimeGitAuthMeta }}</div>
      </div>
    </div>

    <div class="execution-console__grid">
      <article class="execution-console__terminal">
        <div class="execution-console__terminal-top">
          <div>
            <div class="execution-console__terminal-label">{{ headline }}</div>
            <div class="execution-console__terminal-meta">
              {{ terminalMeta }}
            </div>
          </div>
          <span class="execution-console__status-pill" :class="statusClass(primaryStatus)">
            {{ primaryStatusLabel }}
          </span>
        </div>

        <div class="execution-console__step">
          <div class="execution-console__step-label">Current step</div>
          <div class="execution-console__step-value">{{ summary.current_step || "Preparing execution context" }}</div>
          <div class="execution-console__step-meta">{{ summary.current_executor || "runtime" }}</div>
        </div>

        <div v-if="primaryCommand" class="execution-console__shell">
          <div class="execution-console__shell-header">Shell</div>
          <div class="execution-console__shell-command">
            <span class="execution-console__prompt">$</span>
            <code>{{ formatCommand(primaryCommand.command) }}</code>
          </div>
        </div>
        <div v-else class="execution-console__shell execution-console__shell--empty">
          <div class="execution-console__shell-header">Shell</div>
          <div class="execution-console__shell-empty">
            No shell command is active yet. The runtime is likely still preparing the workspace or waiting for the next runnable step.
          </div>
        </div>

        <div class="execution-console__output">
          <div class="execution-console__output-header">Recent output</div>
          <pre v-if="primaryOutput" class="execution-console__output-body">{{ primaryOutput }}</pre>
          <div v-else class="execution-console__output-empty">
            Command output will appear here once the runtime writes command logs.
          </div>
        </div>
      </article>

      <aside class="execution-console__sidebar">
        <section class="execution-console__sidebar-card">
          <div class="execution-console__sidebar-title">Recent commands</div>
          <div v-if="commandRows.length" class="execution-console__sidebar-list">
            <article
              v-for="command in commandRows"
              :key="command.command_id"
              class="execution-console__sidebar-item"
            >
              <div class="execution-console__sidebar-item-top">
                <div class="execution-console__sidebar-item-title">{{ command.label }}</div>
                <span class="execution-console__mini-pill" :class="statusClass(command.status)">
                  {{ command.status }}
                </span>
              </div>
              <div class="execution-console__sidebar-item-command">{{ formatCommand(command.command) }}</div>
              <div class="execution-console__sidebar-item-meta">{{ formatCommandMeta(command) }}</div>
            </article>
          </div>
          <div v-else class="execution-console__sidebar-empty">
            No command audit entries yet.
          </div>
        </section>

        <section class="execution-console__sidebar-card">
          <div class="execution-console__sidebar-title">Recent steps</div>
          <div v-if="stepRows.length" class="execution-console__sidebar-list">
            <article
              v-for="step in stepRows"
              :key="step.work_item_id"
              class="execution-console__sidebar-item"
            >
              <div class="execution-console__sidebar-item-top">
                <div class="execution-console__sidebar-item-title">{{ step.title }}</div>
                <span class="execution-console__mini-pill" :class="statusClass(step.status)">
                  {{ step.status }}
                </span>
              </div>
              <div class="execution-console__sidebar-item-command">{{ step.executor }} · {{ step.type }}</div>
              <div class="execution-console__sidebar-item-meta">
                {{ step.summary || "Waiting for the next runtime update." }}
              </div>
            </article>
          </div>
          <div v-else class="execution-console__sidebar-empty">
            No step activity yet.
          </div>
        </section>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

const props = withDefaults(
  defineProps<{
    consoleData?: any | null;
    runStatus?: string;
  }>(),
  {
    consoleData: null,
    runStatus: "IDLE",
  }
);

const nowTick = ref(Date.now());
let ticker: ReturnType<typeof setInterval> | null = null;

onMounted(() => {
  ticker = setInterval(() => {
    nowTick.value = Date.now();
  }, 1000);
});

onBeforeUnmount(() => {
  if (ticker !== null) {
    clearInterval(ticker);
    ticker = null;
  }
});

const summary = computed(() => props.consoleData?.summary || {});
const environment = computed(() => props.consoleData?.environment || {});
const commandRows = computed(() => (Array.isArray(props.consoleData?.commands) ? props.consoleData.commands : []));
const stepRows = computed(() => (Array.isArray(props.consoleData?.steps) ? props.consoleData.steps : []));
const primaryCommand = computed(() => commandRows.value.find((command: any) => command.status === "RUNNING") || commandRows.value[0] || null);
const primaryStatus = computed(() => String(primaryCommand.value?.status || summary.value.run_status || props.runStatus || "IDLE"));
const primaryStatusLabel = computed(() => humanizeStatus(primaryStatus.value));
const allowedToolCount = computed(() => {
  const prefixes = Array.isArray(environment.value.allowed_command_prefixes) ? environment.value.allowed_command_prefixes : [];
  return `${prefixes.length} allowed`;
});
const allowedToolPreview = computed(() => {
  const prefixes = Array.isArray(environment.value.allowed_command_prefixes) ? environment.value.allowed_command_prefixes : [];
  if (!prefixes.length) return "No command policy loaded yet";
  return prefixes.slice(0, 5).join(", ");
});
const runtimeGitAuthMode = computed(() => normalizeRuntimeGitAuthMode(environment.value.runtime_git_auth_mode));
const runtimeGitAuthStatus = computed(() => String(environment.value.runtime_git_auth_status || environment.value.github_clone_auth_status || "UNKNOWN"));
const runtimeGitAuthMissing = computed(() => {
  const missing = Array.isArray(environment.value.runtime_git_auth_missing)
    ? environment.value.runtime_git_auth_missing.filter((value: any) => typeof value === "string" && value.trim())
    : [];
  if (missing.length) return missing;
  if (runtimeGitAuthMode.value !== "github_app_https") return [];
  return Array.isArray(environment.value.github_clone_auth_missing)
    ? environment.value.github_clone_auth_missing.filter((value: any) => typeof value === "string" && value.trim())
    : [];
});
const runtimeGitAuthValue = computed(() => {
  const modeLabel = formatRuntimeGitAuthMode(runtimeGitAuthMode.value);
  return modeLabel === "Unknown" ? runtimeGitAuthStatus.value : `${modeLabel} ${runtimeGitAuthStatus.value}`;
});
const runtimeGitAuthMeta = computed(() => {
  const missing = runtimeGitAuthMissing.value;
  const modeLabel = formatRuntimeGitAuthMode(runtimeGitAuthMode.value);
  if (missing.length) {
    return `API snapshot · mode ${modeLabel} · missing ${missing.join(", ")}`;
  }
  if (runtimeGitAuthMode.value === "ssh") {
    return [
      "API snapshot",
      "mode SSH",
      `git ${formatPresence(Boolean(environment.value.git_binary))}`,
      `ssh ${formatPresence(Boolean(environment.value.ssh_binary))}`,
    ].join(" · ");
  }
  if (runtimeGitAuthMode.value === "github_app_https") {
    return [
      "API snapshot",
      "mode GitHub App",
      `app id ${formatPresence(environment.value.github_app_id_present)}`,
      `key ${formatPresence(environment.value.github_private_key_present)}`,
      `webhook ${formatPresence(environment.value.github_webhook_secret_present)}`,
    ].join(" · ");
  }
  if (runtimeGitAuthMode.value === "auto") {
    return [
      "API snapshot",
      "mode Auto",
      `git ${formatPresence(Boolean(environment.value.git_binary))}`,
      environment.value.github_clone_auth_ready ? "GitHub App env ready" : "GitHub App env optional",
    ].join(" · ");
  }
  return [
    "API snapshot",
    `mode ${modeLabel}`,
    `git ${formatPresence(Boolean(environment.value.git_binary))}`,
  ].join(" · ");
});

const headline = computed(() => {
  if (primaryCommand.value?.status === "RUNNING") {
    return `Running command for ${formatDuration(primaryCommand.value, true)}`;
  }
  if (primaryCommand.value) {
    return `${humanizeStatus(primaryCommand.value.status)} command ${formatDuration(primaryCommand.value)}`;
  }
  if (String(environment.value.workspace_status || "").toUpperCase() === "ERROR") {
    return "Workspace preparation is blocked";
  }
  if (summary.value.current_step) {
    return "Preparing the next execution step";
  }
  return "Waiting for runtime activity";
});

const terminalMeta = computed(() => {
  const parts: string[] = [];
  if (environment.value.repo_auth_mode) parts.push(`auth ${environment.value.repo_auth_mode}`);
  if (environment.value.simulation_mode) parts.push(`mode ${environment.value.simulation_mode}`);
  if (summary.value.last_updated_at) parts.push(`updated ${formatTimestamp(summary.value.last_updated_at)}`);
  return parts.join(" · ") || "No runtime metadata yet";
});

const primaryOutput = computed(() => {
  const command = primaryCommand.value;
  if (!command) return "";
  const sections: string[] = [];
  if (typeof command.stdout_tail === "string" && command.stdout_tail.trim()) {
    sections.push(command.stdout_tail.trim());
  }
  if (typeof command.stderr_tail === "string" && command.stderr_tail.trim()) {
    sections.push(`--- STDERR ---\n${command.stderr_tail.trim()}`);
  }
  return sections.join("\n\n");
});

function humanizeStatus(value: string) {
  return String(value || "unknown")
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatPresence(value?: boolean | null) {
  return value ? "yes" : "no";
}

function normalizeRuntimeGitAuthMode(value?: string | null) {
  const normalized = String(value || "auto").trim().toLowerCase();
  if (normalized === "github_app_https" || normalized === "ssh" || normalized === "none" || normalized === "auto") {
    return normalized;
  }
  return "auto";
}

function formatRuntimeGitAuthMode(value?: string | null) {
  const normalized = normalizeRuntimeGitAuthMode(value);
  if (normalized === "github_app_https") return "GitHub App";
  if (normalized === "ssh") return "SSH";
  if (normalized === "none") return "Plain";
  if (normalized === "auto") return "Auto";
  return "Unknown";
}

function statusClass(status?: string | null) {
  const normalized = String(status || "").toUpperCase();
  if (normalized === "RUNNING" || normalized === "CLAIMED") return "is-running";
  if (normalized === "SUCCEEDED" || normalized === "DONE" || normalized === "COMPLETED" || normalized === "READY") return "is-success";
  if (normalized === "SKIPPED") return "is-neutral";
  if (normalized === "FAILED" || normalized === "CANCELED" || normalized === "ERROR" || normalized === "TIMEOUT" || normalized === "BLOCKED") return "is-danger";
  return "is-neutral";
}

function formatCommand(command: any) {
  if (!Array.isArray(command) || !command.length) return "Command pending";
  return command.join(" ");
}

function formatTimestamp(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDuration(command: any, runningLabel = false) {
  if (!command) return "pending";
  if (typeof command.duration_ms === "number" && command.duration_ms >= 0) {
    return humanDuration(command.duration_ms);
  }
  if (command.started_at) {
    const startedAt = new Date(command.started_at).getTime();
    if (!Number.isNaN(startedAt)) {
      const durationMs = Math.max(nowTick.value - startedAt, 0);
      return runningLabel ? humanDuration(durationMs) : `after ${humanDuration(durationMs)}`;
    }
  }
  return runningLabel ? "0s" : "pending";
}

function formatCommandMeta(command: any) {
  const parts: string[] = [];
  if (command.cwd) parts.push(command.cwd);
  if (command.exit_code !== null && command.exit_code !== undefined) parts.push(`exit ${command.exit_code}`);
  if (command.blocked_reason) parts.push(command.blocked_reason);
  else parts.push(formatDuration(command));
  return parts.join(" · ");
}

function humanDuration(durationMs: number) {
  const totalSeconds = Math.max(Math.floor(durationMs / 1000), 0);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m`;
}
</script>

<style scoped>
.execution-console {
  border: 1px solid var(--border-soft);
  border-radius: 24px;
  padding: 1.35rem;
  background:
    radial-gradient(circle at top left, rgba(91, 156, 255, 0.18), transparent 28%),
    linear-gradient(180deg, rgba(16, 18, 27, 0.96), rgba(10, 12, 18, 0.98));
  box-shadow: var(--shadow-elevated);
  color: rgba(237, 242, 247, 0.96);
  container-type: inline-size;
}

[data-theme="light"] .execution-console {
  background:
    radial-gradient(circle at top left, rgba(91, 156, 255, 0.12), transparent 28%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(246, 248, 252, 0.98));
  color: var(--text-strong);
}

.execution-console__header,
.execution-console__terminal-top,
.execution-console__sidebar-item-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.execution-console__eyebrow,
.execution-console__env-label,
.execution-console__step-label,
.execution-console__terminal-label,
.execution-console__output-header,
.execution-console__shell-header,
.execution-console__sidebar-title,
.execution-console__summary-label {
  font-size: 0.68rem;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--text-soft);
}

.execution-console__title {
  margin: 0.4rem 0 0;
  font-size: 1.18rem;
  font-weight: 700;
}

.execution-console__copy {
  margin: 0.55rem 0 0;
  max-width: 40rem;
  font-size: 0.84rem;
  line-height: 1.55;
  color: var(--text-soft);
}

.execution-console__summary {
  min-width: 7rem;
  border-radius: 18px;
  border: 1px solid rgba(91, 156, 255, 0.18);
  background: rgba(91, 156, 255, 0.1);
  padding: 0.85rem 0.95rem;
}

.execution-console__summary-value {
  margin-top: 0.2rem;
  font-size: 1.5rem;
  font-weight: 700;
}

.execution-console__summary-meta {
  margin-top: 0.2rem;
  font-size: 0.8rem;
  color: var(--text-soft);
}

.execution-console__environment {
  margin-top: 1rem;
  display: grid;
  gap: 0.8rem;
  grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
}

.execution-console__env-card,
.execution-console__step,
.execution-console__sidebar-card {
  border-radius: 18px;
  border: 1px solid var(--border-soft);
  background: rgba(255, 255, 255, 0.04);
  padding: 0.95rem 1rem;
}

[data-theme="light"] .execution-console__env-card,
[data-theme="light"] .execution-console__step,
[data-theme="light"] .execution-console__sidebar-card {
  background: rgba(255, 255, 255, 0.84);
}

.execution-console__env-value,
.execution-console__step-value {
  margin-top: 0.45rem;
  font-weight: 700;
}

.execution-console__env-meta,
.execution-console__step-meta,
.execution-console__terminal-meta,
.execution-console__sidebar-item-command,
.execution-console__sidebar-item-meta,
.execution-console__output-empty,
.execution-console__shell-empty {
  margin-top: 0.25rem;
  font-size: 0.8rem;
  line-height: 1.5;
  color: var(--text-soft);
}

.execution-console__path {
  word-break: break-all;
}

.execution-console__grid {
  margin-top: 1rem;
  display: grid;
  gap: 1rem;
  grid-template-columns: minmax(0, 1.3fr) minmax(20rem, 0.9fr);
  align-items: start;
}

.execution-console__terminal {
  min-width: 0;
  border-radius: 22px;
  border: 1px solid rgba(91, 156, 255, 0.18);
  background: rgba(8, 11, 18, 0.82);
  padding: 1rem;
}

[data-theme="light"] .execution-console__terminal {
  background: rgba(19, 24, 37, 0.96);
  color: rgba(237, 242, 247, 0.96);
}

.execution-console__status-pill,
.execution-console__mini-pill {
  border-radius: 999px;
  border: 1px solid transparent;
  padding: 0.3rem 0.65rem;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.execution-console__status-pill.is-running,
.execution-console__mini-pill.is-running {
  border-color: rgba(245, 158, 11, 0.28);
  background: rgba(245, 158, 11, 0.14);
  color: #fbbf24;
}

.execution-console__status-pill.is-success,
.execution-console__mini-pill.is-success {
  border-color: rgba(34, 197, 94, 0.24);
  background: rgba(34, 197, 94, 0.14);
  color: #86efac;
}

.execution-console__status-pill.is-danger,
.execution-console__mini-pill.is-danger {
  border-color: rgba(239, 68, 68, 0.24);
  background: rgba(239, 68, 68, 0.12);
  color: #fca5a5;
}

.execution-console__status-pill.is-neutral,
.execution-console__mini-pill.is-neutral {
  border-color: rgba(148, 163, 184, 0.22);
  background: rgba(148, 163, 184, 0.1);
  color: rgba(226, 232, 240, 0.95);
}

.execution-console__step,
.execution-console__shell,
.execution-console__output {
  margin-top: 1rem;
}

.execution-console__shell,
.execution-console__output {
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(255, 255, 255, 0.03);
  padding: 0.9rem 1rem;
}

.execution-console__shell-command {
  margin-top: 0.55rem;
  display: flex;
  gap: 0.75rem;
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.84rem;
  line-height: 1.6;
  overflow-x: auto;
}

.execution-console__prompt {
  color: #67e8f9;
}

.execution-console__output-body {
  margin: 0.7rem 0 0;
  max-height: 22rem;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.81rem;
  line-height: 1.55;
}

.execution-console__sidebar {
  min-width: 0;
  display: grid;
  gap: 1rem;
  align-content: start;
}

.execution-console__sidebar-list {
  margin-top: 0.8rem;
  display: grid;
  gap: 0.75rem;
}

.execution-console__sidebar-item {
  min-width: 0;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(255, 255, 255, 0.03);
  padding: 0.8rem 0.85rem;
}

.execution-console__sidebar-item-title {
  font-weight: 700;
}

.execution-console__sidebar-empty {
  margin-top: 0.8rem;
  font-size: 0.84rem;
  color: var(--text-soft);
}

@container (max-width: 900px) {
  .execution-console__grid {
    grid-template-columns: 1fr;
  }
}

@container (max-width: 640px) {
  .execution-console__header,
  .execution-console__terminal-top,
  .execution-console__sidebar-item-top {
    flex-direction: column;
  }

  .execution-console__environment {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 1180px) {
  .execution-console__environment {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .execution-console__grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .execution-console__header,
  .execution-console__terminal-top,
  .execution-console__sidebar-item-top {
    flex-direction: column;
  }

  .execution-console__environment {
    grid-template-columns: 1fr;
  }
}
</style>
