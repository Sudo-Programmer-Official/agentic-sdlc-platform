<template>
  <div class="landing-v2-cinematic">
    <div class="ambient ambient-a" />
    <div class="ambient ambient-b" />
    <div class="ambient ambient-c" />

    <section class="hero-shell">
      <div class="hero-copy glass-panel">
        <div class="hero-brand">
          <img src="/brand/logo-64.png" alt="Prompt2PR logo" class="hero-logo" />
          <div class="eyebrow">Prompt2PR · Agentic SDLC Infrastructure</div>
        </div>
        <h1>Governed Agentic SDLC.<br />From Prompt to Production.</h1>
        <p>
          Operationalize software delivery with governed runtime orchestration, deterministic recovery loops,
          deployment policy gates, and continuous engineering memory.
        </p>
        <div class="hero-proof-strip">
          <span>Governed Runtime</span>
          <span>Deterministic Recovery</span>
          <span>Deployment Readiness 92%</span>
        </div>
        <div class="hero-ctas">
          <el-button type="primary" size="large" @click="goStart">Deploy Your First App</el-button>
          <el-button size="large" plain @click="goMissionControl">Watch Live Flow</el-button>
          <el-button v-if="isSignedIn && lastProjectId" size="large" plain @click="resumeProject">Resume Last Project</el-button>
        </div>
      </div>

      <div class="hero-visual glass-panel">
        <div class="hero-visual-label">Operational AI Infrastructure</div>
        <img
          src="/brand/hero-agentic-sdlc-ad-landscape.png"
          alt="Agentic SDLC mission control showcase"
          class="hero-showcase-image"
        />
        <p class="hero-visual-caption">
          Production-grade orchestration, recovery governance, and runtime policy controls in one operator surface.
        </p>
      </div>
    </section>

    <section class="story-grid">
      <article class="glass-panel story-card">
        <div class="eyebrow">The Problem</div>
        <h3>Software delivery is fragmented by default.</h3>
        <p>Prompts, editors, CI/CD, environments, approvals, and rollback systems operate in disconnected silos.</p>
      </article>
      <article class="glass-panel story-card">
        <div class="eyebrow">The Shift</div>
        <h3>Most AI tools generate code. Prompt2PR operationalizes software.</h3>
        <p>Idea, engineering, recovery, deployment, and production governance become one continuous control loop.</p>
      </article>
    </section>

    <section class="problem-solve glass-panel">
      <div class="eyebrow">System Gap</div>
      <h3>What current systems struggle with, and what Prompt2PR fixes.</h3>
      <div class="problem-lanes">
        <div class="lane-head lane-left">Current System</div>
        <div class="lane-head lane-right">Prompt2PR Outcome</div>
        <div v-for="item in problemSolutionPairs" :key="item.problem" class="lane-row">
          <article class="lane-card lane-problem">
            <div class="lane-label">Problem</div>
            <div class="lane-copy">{{ item.problem }}</div>
          </article>
          <div class="lane-arrow">→</div>
          <article class="lane-card lane-solution">
            <div class="lane-label">Solved By</div>
            <div class="lane-copy">{{ item.solution }}</div>
          </article>
        </div>
      </div>
    </section>

    <section class="capabilities">
      <div class="eyebrow">Platform Capabilities</div>
      <div class="cap-grid">
        <article class="glass-panel cap-card" v-for="cap in capabilities" :key="cap.title">
          <h4>{{ cap.title }}</h4>
          <p>{{ cap.body }}</p>
        </article>
      </div>
    </section>

    <section class="ops-pipeline glass-panel">
      <div class="eyebrow">Operational Lifecycle Pipeline</div>
      <h3>Intent to production, continuously managed with safety and governance.</h3>
      <div class="pipeline-track">
        <div v-for="(stage, idx) in opsPipeline" :key="stage.key" class="pipeline-node" :class="stage.state" :style="{ animationDelay: `${idx * 100}ms` }">
          <div class="pipeline-node__dot" />
          <div class="pipeline-node__label">{{ stage.label }}</div>
          <div class="pipeline-node__hint">{{ stage.hint }}</div>
        </div>
      </div>
      <div class="pipeline-loop">
        <span>Recovery Loop</span>
        <span class="arrow">↺</span>
        <span>Continuous Memory</span>
      </div>
      <div class="pipeline-metrics">
        <div class="metric-pill">Confidence <strong>88%</strong></div>
        <div class="metric-pill">Readiness <strong>92%</strong></div>
        <div class="metric-pill">Governance <strong>ENFORCED</strong></div>
      </div>
    </section>

    <section class="metrics-rail">
      <div class="eyebrow">Operational Metrics</div>
      <h3>Reliability and delivery signals teams can trust.</h3>
      <div class="metrics-grid">
        <article v-for="metric in metrics" :key="metric.label" class="glass-panel metric-card">
          <div class="metric-label">{{ metric.label }}</div>
          <div class="metric-value">{{ metric.value }}</div>
          <div class="metric-detail">{{ metric.detail }}</div>
        </article>
      </div>
    </section>

    <section class="screenshots-rail glass-panel">
      <div class="eyebrow">Product Screenshots</div>
      <h3>Real product surfaces across runtime, deployment, and operations.</h3>
      <div class="screenshots-viewer">
        <div class="screenshots-frame">
          <img :src="activeScreenshot.src" :alt="activeScreenshot.alt" loading="lazy" />
        </div>
        <div class="screenshots-controls">
          <button type="button" class="shot-nav" @click="prevScreenshot">← Previous</button>
          <div class="shot-counter">{{ activeScreenshotIndex + 1 }} / {{ screenshots.length }}</div>
          <button type="button" class="shot-nav" @click="nextScreenshot">Next →</button>
        </div>
        <div class="screenshots-strip-wrap">
          <button type="button" class="strip-nav" aria-label="Scroll thumbnails left" @click="scrollThumbs('prev')">←</button>
          <div ref="thumbRail" class="screenshots-strip" aria-label="Screenshot thumbnails">
            <button
              v-for="(shot, idx) in screenshots"
              :key="shot.src"
              type="button"
              class="shot-thumb"
              :class="{ active: idx === activeScreenshotIndex }"
              @click="activeScreenshotIndex = idx"
            >
              <img :src="shot.src" :alt="shot.alt" loading="lazy" />
            </button>
          </div>
          <button type="button" class="strip-nav" aria-label="Scroll thumbnails right" @click="scrollThumbs('next')">→</button>
        </div>
      </div>
    </section>

    <section class="comparison-rail glass-panel">
      <div class="eyebrow">Prompt2PR vs Manual / Prompt-Only Coding</div>
      <h3>Why governed software operations outperform ad-hoc coding workflows.</h3>
      <div class="comparison-grid">
        <article v-for="row in comparisonMetrics" :key="row.metric" class="comparison-card">
          <div class="comparison-metric">{{ row.metric }}</div>
          <div class="comparison-values">
            <div class="comparison-col">
              <div class="comparison-label">Manual / Prompt-Only</div>
              <div class="comparison-value muted">{{ row.manual }}</div>
            </div>
            <div class="comparison-col">
              <div class="comparison-label">Prompt2PR</div>
              <div class="comparison-value strong">{{ row.prompt2pr }}</div>
            </div>
          </div>
          <div class="comparison-note">{{ row.note }}</div>
        </article>
      </div>
    </section>

    <section class="outcomes-rail glass-panel">
      <div class="eyebrow">What You Can Achieve</div>
      <h3>Turn software delivery into a repeatable revenue engine.</h3>
      <p class="outcomes-lead">
        Build faster, ship safer, and convert execution quality into business outcomes:
        larger contracts, faster launches, and stronger enterprise confidence.
      </p>
      <div class="dream-strip">
        <div class="dream-pill">Dream Bigger</div>
        <div class="dream-pill">Ship Faster</div>
        <div class="dream-pill">Earn Trust</div>
        <div class="dream-pill">Scale Revenue</div>
      </div>
      <div class="outcomes-grid">
        <article v-for="item in outcomes" :key="item.title" class="outcome-card">
          <div class="outcome-tag">{{ item.segment }}</div>
          <h4>{{ item.title }}</h4>
          <p>{{ item.body }}</p>
          <div class="outcome-value">{{ item.value }}</div>
          <div class="outcome-metric">{{ item.metric }}</div>
        </article>
      </div>
    </section>

    <section class="faq-rail glass-panel">
      <div class="eyebrow">FAQ</div>
      <h3>Common questions about Prompt2PR operations and trust.</h3>
      <div class="faq-grid">
        <article v-for="item in faqItems" :key="item.q" class="faq-card">
          <div class="faq-q">{{ item.q }}</div>
          <div class="faq-a">{{ item.a }}</div>
        </article>
      </div>
    </section>

    <section class="journey-rail glass-panel">
      <div class="eyebrow">User Journey</div>
      <h3>What you do in every task lifecycle, step by step.</h3>
      <div class="journey-legend">
        <span class="legend-pill legend-you">You drive</span>
        <span class="legend-pill legend-system">Prompt2PR orchestrates</span>
        <span class="legend-pill legend-shared">Shared control</span>
      </div>
      <div class="journey-timeline">
        <div class="journey-line" />
      </div>
      <div class="journey-grid">
        <article v-for="(step, idx) in userJourney" :key="step.title" class="journey-card">
          <div class="journey-index-wrap">
            <div class="journey-index">{{ String(idx + 1).padStart(2, "0") }}</div>
            <div class="journey-node" />
          </div>
          <div class="journey-title">{{ step.title }}</div>
          <div class="journey-owner" :class="ownerTone(step.owner)">{{ step.owner }}</div>
          <div class="journey-detail">{{ step.detail }}</div>
          <div class="journey-action">Your action: {{ step.action }}</div>
        </article>
      </div>
    </section>

    <section class="business-flow glass-panel">
      <div class="eyebrow">Business To Production</div>
      <h3>How a business requirement becomes a live, governed release.</h3>
      <p class="business-flow-lead">You bring the requirement. Prompt2PR handles execution, safety, and deployment orchestration.</p>
      <div class="business-flow-grid">
        <article v-for="item in businessFlow" :key="item.step" class="business-flow-card">
          <div class="business-flow-step">{{ item.step }}</div>
          <div class="business-flow-title">{{ item.title }}</div>
          <div class="business-flow-owner">{{ item.owner }}</div>
          <p class="business-flow-detail">{{ item.detail }}</p>
          <div class="business-flow-proof">{{ item.proof }}</div>
        </article>
      </div>
    </section>

    <section class="voices-rail glass-panel">
      <div class="eyebrow">What People Are Saying</div>
      <h3>Teams describe Prompt2PR as the bridge between AI output and production trust.</h3>
      <div class="voices-grid">
        <article v-for="voice in voices" :key="voice.role" class="voice-card">
          <p class="voice-quote">"{{ voice.quote }}"</p>
          <div class="voice-meta">
            <div class="voice-role">{{ voice.role }}</div>
            <div class="voice-impact">{{ voice.impact }}</div>
          </div>
        </article>
      </div>
    </section>

    <section class="brand-rail glass-panel">
      <div class="eyebrow">Brand</div>
      <h3>Prompt2PR is the product. Sudo Programmer is the core company.</h3>
      <div class="brand-grid">
        <article class="brand-card">
          <div class="brand-card__label">Product Brand</div>
          <div class="brand-card__title">Prompt2PR</div>
          <div class="brand-card__url">prompt2pr.com</div>
          <p>AI-powered software operationalization platform for governed build-to-production delivery.</p>
        </article>
        <article class="brand-card">
          <div class="brand-card__label">Core Company</div>
          <div class="brand-card__title">Sudo Programmer</div>
          <div class="brand-card__url">sudoprogrammer.com</div>
          <p>Parent company building autonomous software delivery systems and reliability-first AI engineering products.</p>
        </article>
      </div>
    </section>

    <section class="trust-rail glass-panel">
      <div class="eyebrow">Trust Surface</div>
      <div class="trust-grid">
        <div class="trust-item" v-for="item in trustItems" :key="item">{{ item }}</div>
      </div>
    </section>

    <section class="final-cta">
      <h2>Build. Recover. Deploy. Scale.</h2>
      <p>Ship production-ready software in minutes with governed automation and operational intelligence.</p>
      <div class="hero-ctas">
        <el-button type="primary" size="large" @click="goStart">Start Building</el-button>
        <el-button size="large" plain @click="goMissionControl">View Mission Control</el-button>
      </div>
    </section>

    <footer class="legal-rail">
      <div class="legal-brand">Prompt2PR.com · A SudoProgrammer.com product</div>
      <div class="legal-links">
        <router-link to="/security">Security</router-link>
        <router-link to="/privacy">Privacy</router-link>
        <router-link to="/terms">Terms</router-link>
        <router-link to="/data-deletion">Data Deletion</router-link>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { getAuthToken, loadRecentProjectsScoped } from "../api/lifecycle";

const router = useRouter();
const isSignedIn = computed(() => Boolean(getAuthToken()));
const capabilities = [
  {
    title: "Autonomous Runtime",
    body: "Execution intelligence, bounded recovery, safe retries, and decomposition-aware orchestration.",
  },
  {
    title: "Deployment Governance",
    body: "Readiness contracts, environment validation, promotion gating, and rollback safety.",
  },
  {
    title: "Continuous Engineering Memory",
    body: "Timeline synthesis, requirement memory, recovery memory, and project-level understanding.",
  },
  {
    title: "Operational Workspaces",
    body: "Multi-project control, connector surfaces, environment ownership, and policy-backed actions.",
  },
];
const trustItems = [
  "Deployment confidence scoring",
  "Recovery intelligence with bounded loops",
  "Policy enforcement for deploy mutations",
  "Environment readiness evidence",
  "Rollback protection and promotion controls",
  "Operational timeline and auditability",
];
const problemSolutionPairs = [
  {
    problem: "Fragmented flow across prompting, coding, CI/CD, and deployment tools",
    solution: "One continuous lifecycle from intent to production",
  },
  {
    problem: "No unified operational state for validation, recovery, and promotion",
    solution: "Governed loop with validation, recovery, and deployment gates",
  },
  {
    problem: "Deployment actions happen with weak readiness confidence",
    solution: "Readiness contracts with explicit safe/blocked decisions",
  },
  {
    problem: "Rollbacks are manual and often delayed during incidents",
    solution: "Policy-backed rollback and promotion controls",
  },
  {
    problem: "Project learning resets between runs and operators",
    solution: "Continuous engineering memory across runs and outcomes",
  },
];
const metrics = [
  { label: "Deployment Readiness", value: "92%", detail: "Average readiness before deployment actions." },
  { label: "Recovery Reliability", value: "99.1%", detail: "Runs exiting failure paths through bounded recovery." },
  { label: "Preview Lead Time", value: "8 min", detail: "Median time from intent to preview deployment." },
  { label: "Governed Mutations", value: "100%", detail: "Deployment mutations enforced by policy gates." },
  { label: "Rollback Coverage", value: "96%", detail: "Deployments with validated rollback path available." },
  { label: "Operator Clarity", value: "High", detail: "Explicit blockers, warnings, and next actions surfaced." },
];
const screenshots = Array.from({ length: 12 }, (_, idx) => {
  const n = String(idx + 1).padStart(2, "0");
  return {
    src: `/brand/ss-${n}.png`,
    alt: `Prompt2PR product screenshot ${idx + 1}`,
  };
});
const activeScreenshotIndex = ref(0);
const thumbRail = ref<HTMLElement | null>(null);
const activeScreenshot = computed(() => screenshots[activeScreenshotIndex.value] || screenshots[0]);

function nextScreenshot() {
  activeScreenshotIndex.value = (activeScreenshotIndex.value + 1) % screenshots.length;
}

function prevScreenshot() {
  activeScreenshotIndex.value = (activeScreenshotIndex.value - 1 + screenshots.length) % screenshots.length;
}

function scrollThumbs(direction: "prev" | "next") {
  if (!thumbRail.value) return;
  const distance = Math.round(thumbRail.value.clientWidth * 0.72);
  thumbRail.value.scrollBy({ left: direction === "next" ? distance : -distance, behavior: "smooth" });
}
const comparisonMetrics = [
  {
    metric: "Time to first deployable preview",
    manual: "Hours to days",
    prompt2pr: "Minutes",
    note: "Automated pipeline continuity removes handoff latency.",
  },
  {
    metric: "Deployment policy coverage",
    manual: "Inconsistent",
    prompt2pr: "100% gated mutations",
    note: "Create/retry/promote actions are consistently policy-enforced.",
  },
  {
    metric: "Failure recovery speed",
    manual: "Manual triage loops",
    prompt2pr: "Bounded recovery loops",
    note: "Recovery intelligence shortens incident-to-resolution time.",
  },
  {
    metric: "Production promotion confidence",
    manual: "Operator judgement",
    prompt2pr: "Readiness contract backed",
    note: "Safe/blocked decisions are explicit before mutation.",
  },
  {
    metric: "Operational memory retention",
    manual: "Session reset risk",
    prompt2pr: "Continuous project memory",
    note: "Context compounds across requirements, runs, and outcomes.",
  },
  {
    metric: "Rollback safety",
    manual: "Ad-hoc process",
    prompt2pr: "Validated rollback path checks",
    note: "Rollback actions are guarded by explicit safety conditions.",
  },
];
const outcomes = [
  {
    segment: "Agencies",
    title: "Deliver more client projects without burning your team",
    body: "Standardize delivery with governed workflows, clearer handoffs, and reusable operational playbooks across accounts.",
    value: "Higher client throughput + stronger reliability reputation",
    metric: "Outcome target: more monthly retainer capacity",
  },
  {
    segment: "Founders",
    title: "Ship from idea to production with fewer bottlenecks",
    body: "Move quickly from concept to live software while preserving safety through validation, readiness contracts, and rollback controls.",
    value: "Faster launch cycles + lower deployment anxiety",
    metric: "Outcome target: faster time-to-revenue",
  },
  {
    segment: "Enterprise Teams",
    title: "Scale software operations with policy and audit confidence",
    body: "Introduce autonomy with guardrails: policy-gated deployment actions, environment governance, and operational traceability.",
    value: "Governed scale + enterprise trust posture",
    metric: "Outcome target: larger governed delivery programs",
  },
];
const faqItems = [
  {
    q: "Does Prompt2PR only generate code?",
    a: "No. It governs the full software delivery loop: generation, validation, recovery, deployment, promotion, and rollback.",
  },
  {
    q: "Can I still control what gets deployed?",
    a: "Yes. Deployment actions are policy-gated with explicit readiness evidence, blockers, and allowed next actions.",
  },
  {
    q: "How does recovery work during failures?",
    a: "Prompt2PR runs bounded recovery loops, then surfaces operator actions if a safe automated path is unavailable.",
  },
  {
    q: "What do I need to provide?",
    a: "You provide project credentials, provider accounts, environment secrets, and production ownership decisions.",
  },
  {
    q: "Can I use it with existing repos and workflows?",
    a: "Yes. Prompt2PR is built for repo-connected execution and can operate alongside your existing SDLC practices.",
  },
  {
    q: "How is production safety handled?",
    a: "Production promotion is blocked unless readiness policy is satisfied, including validation, sync health, and rollback safety.",
  },
];
const userJourney = [
  {
    title: "Define Intent",
    owner: "You",
    detail: "Create workspace/project context and describe the outcome you want.",
    action: "Set clear goal, constraints, and priority",
  },
  {
    title: "Connect Delivery Context",
    owner: "You + Prompt2PR",
    detail: "Attach repository and environment scope so execution is grounded.",
    action: "Connect repo and required providers",
  },
  {
    title: "Generate and Refine",
    owner: "Prompt2PR",
    detail: "System plans and generates implementation with governed execution.",
    action: "Review run status and generated outputs",
  },
  {
    title: "Configure Environment",
    owner: "You",
    detail: "Provide credentials, domains, and required secrets for target environment.",
    action: "Set required variables and secrets",
  },
  {
    title: "Validate and Sync",
    owner: "Prompt2PR + You",
    detail: "Readiness checks and provider sync produce deployability evidence.",
    action: "Run validation and resolve blockers",
  },
  {
    title: "Deploy Preview",
    owner: "Prompt2PR",
    detail: "Preview deployment is orchestrated with confidence and policy checks.",
    action: "Inspect preview and behavior",
  },
  {
    title: "Promote Production",
    owner: "Prompt2PR + You",
    detail: "Production promotion only proceeds when readiness contract is satisfied.",
    action: "Approve promotion when safe",
  },
  {
    title: "Monitor and Recover",
    owner: "Prompt2PR",
    detail: "Continuous monitoring, recovery loops, memory updates, and rollback safety.",
    action: "Intervene only when prompted",
  },
];
const voices = [
  {
    role: "Agency Delivery Lead",
    quote: "This feels like moving from ad-hoc AI prompts to an actual delivery operating model.",
    impact: "Outcome: higher confidence in client launch timelines",
  },
  {
    role: "Startup Founder",
    quote: "I can go from product idea to deployable preview without getting lost in tooling sprawl.",
    impact: "Outcome: faster experimentation and launch velocity",
  },
  {
    role: "Engineering Manager",
    quote: "The governance layer is the difference. We get speed with safety, not one at the expense of the other.",
    impact: "Outcome: safer promotion and rollback decisions",
  },
];
const businessFlow = [
  {
    step: "01",
    title: "Business Requirement",
    owner: "You",
    detail: "Define outcome, KPI, and constraints (timeline, stack, compliance, and budget).",
    proof: "Output: scoped execution intent",
  },
  {
    step: "02",
    title: "Execution Blueprint",
    owner: "Prompt2PR",
    detail: "Decomposes requirement into build plan, environment needs, and deploy path.",
    proof: "Output: governed implementation plan",
  },
  {
    step: "03",
    title: "Build + Validate",
    owner: "Prompt2PR + You",
    detail: "Generates changes, validates environments, and surfaces blockers with next actions.",
    proof: "Output: readiness evidence",
  },
  {
    step: "04",
    title: "Deploy + Promote",
    owner: "Prompt2PR",
    detail: "Deploys preview, gates production promotion by policy, keeps rollback safety ready.",
    proof: "Output: safe live release",
  },
  {
    step: "05",
    title: "Business Impact Loop",
    owner: "You + Prompt2PR",
    detail: "Monitor outcomes, recover quickly, and iterate faster on new requirements.",
    proof: "Output: repeatable delivery velocity",
  },
];
const opsPipeline = [
  { key: "intent", label: "Intent", hint: "Goal captured with context", state: "done" },
  { key: "plan", label: "Plan", hint: "Safe execution path prepared", state: "done" },
  { key: "build", label: "Build", hint: "Software generated and refined", state: "active" },
  { key: "validate", label: "Validate", hint: "Environment and quality checks", state: "active" },
  { key: "recover", label: "Recover", hint: "Bounded retries and healing", state: "active" },
  { key: "deploy", label: "Deploy", hint: "Preview deployment orchestration", state: "pending" },
  { key: "promote", label: "Promote", hint: "Production governance gate", state: "pending" },
  { key: "learn", label: "Learn", hint: "Continuous delivery memory", state: "pending" },
];
const readinessScore = 92;
const deployConfidence = 88;

const lastProjectId = computed(() => {
  if (typeof window === "undefined") return "";
  try {
    const parsed = loadRecentProjectsScoped();
    if (!Array.isArray(parsed) || !parsed[0]?.id) return "";
    return String(parsed[0].id);
  } catch {
    return "";
  }
});

function goStart() {
  if (isSignedIn.value) router.push("/workspace");
  else router.push("/signin");
}

function goMissionControl() {
  if (lastProjectId.value) router.push(`/projects/${lastProjectId.value}/run`);
  else goStart();
}

function resumeProject() {
  if (!lastProjectId.value) return;
  router.push(`/projects/${lastProjectId.value}`);
}

function ownerTone(owner: string) {
  const normalized = owner.toLowerCase();
  if (normalized.includes("you +")) return "shared";
  if (normalized.includes("you")) return "you";
  return "system";
}
</script>

<style scoped>
.landing-v2-cinematic {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  min-height: 100vh;
  background: radial-gradient(980px 520px at 12% -8%, rgba(59, 130, 246, 0.22) 0%, transparent 62%),
    radial-gradient(920px 460px at 88% 0%, rgba(129, 140, 248, 0.2) 0%, transparent 58%),
    linear-gradient(180deg, #081126 0%, #0b1730 45%, #0d1b38 100%);
  max-width: 1240px;
  margin: 0 auto;
  padding: 32px 16px 96px;
}
.landing-v2-cinematic::before {
  content: "";
  position: fixed;
  inset: 0;
  z-index: -1;
  background: radial-gradient(980px 520px at 12% -8%, rgba(59, 130, 246, 0.22) 0%, transparent 62%),
    radial-gradient(920px 460px at 88% 0%, rgba(129, 140, 248, 0.2) 0%, transparent 58%),
    linear-gradient(180deg, #081126 0%, #0b1730 45%, #0d1b38 100%);
}
.ambient {
  position: absolute;
  border-radius: 9999px;
  filter: blur(36px);
  opacity: 0.4;
  pointer-events: none;
}
.ambient-a { width: 340px; height: 340px; top: 80px; left: -120px; background: #93c5fd; }
.ambient-b { width: 420px; height: 420px; top: 40px; right: -150px; background: #a7f3d0; }
.ambient-c { width: 260px; height: 260px; bottom: 140px; left: 38%; background: #bae6fd; }

.glass-panel {
  backdrop-filter: blur(10px);
  background: linear-gradient(135deg, rgba(255,255,255,0.86), rgba(248,250,252,0.8));
  border: 1px solid rgba(148, 163, 184, 0.25);
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.08);
}
.hero-shell {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 18px;
  grid-template-columns: 1fr;
}
.hero-copy { border-radius: 24px; padding: 28px; }
.hero-copy.glass-panel {
  background: linear-gradient(142deg, rgba(12, 24, 44, 0.86), rgba(14, 26, 48, 0.78));
  border: 1px solid rgba(150, 186, 244, 0.26);
  box-shadow: 0 20px 48px rgba(2, 8, 20, 0.38);
}
.hero-brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
.hero-logo {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.15);
}
.eyebrow {
  font-size: 11px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: #a8c1e6;
  font-weight: 600;
}
h1 {
  margin-top: 12px;
  font-size: clamp(32px, 5vw, 56px);
  line-height: 1.02;
  font-weight: 700;
  color: #f3f8ff;
}
p { margin-top: 14px; color: #334155; font-size: 15px; line-height: 1.7; }
.hero-copy p { color: #c5d5ec; }
.hero-ctas { margin-top: 20px; display: flex; flex-wrap: wrap; gap: 10px; }
.hero-proof-strip {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.hero-proof-strip span {
  border-radius: 999px;
  border: 1px solid rgba(151, 188, 244, 0.38);
  background: rgba(17, 34, 60, 0.72);
  color: #ddeafe;
  padding: 7px 11px;
  font-size: 12px;
  line-height: 1.2;
  font-weight: 600;
}
.hero-image-frame {
  position: relative;
  margin-top: 16px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  overflow: hidden;
  background: linear-gradient(145deg, rgba(15, 23, 42, 0.03), rgba(59, 130, 246, 0.08));
}
.hero-image-glow {
  position: absolute;
  inset: auto 0 0 0;
  height: 44%;
  background: linear-gradient(180deg, transparent 0%, rgba(15, 23, 42, 0.18) 100%);
  pointer-events: none;
}
.hero-motion {
  min-height: 230px;
  padding: 14px;
  background: linear-gradient(145deg, #0f172a, #172554 55%, #0b3a67);
}
.hero-motion-bg {
  position: absolute;
  inset: 0;
  border-radius: 16px;
  background:
    radial-gradient(circle at 20% 25%, rgba(56, 189, 248, 0.25), transparent 35%),
    radial-gradient(circle at 80% 75%, rgba(34, 197, 94, 0.18), transparent 38%);
  animation: driftGlow 7s ease-in-out infinite;
}
.hero-motion-track {
  position: relative;
  z-index: 2;
  margin-top: 48px;
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.motion-node {
  border-radius: 999px;
  padding: 8px 10px;
  text-align: center;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.02em;
  border: 1px solid rgba(148, 163, 184, 0.4);
  background: rgba(15, 23, 42, 0.5);
  color: #cbd5e1;
  backdrop-filter: blur(4px);
}
.motion-node.done {
  color: #86efac;
  border-color: rgba(134, 239, 172, 0.6);
}
.motion-node.active {
  color: #bfdbfe;
  border-color: rgba(147, 197, 253, 0.8);
  box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.25), 0 0 22px rgba(59, 130, 246, 0.35);
  animation: pulseNode 1.8s ease-in-out infinite;
}
.motion-node.pending {
  color: #cbd5e1;
  border-color: rgba(148, 163, 184, 0.45);
}
.hero-motion-pulse {
  position: absolute;
  top: 38%;
  width: 16px;
  height: 16px;
  border-radius: 999px;
  background: #60a5fa;
  box-shadow: 0 0 22px rgba(59, 130, 246, 0.7);
  z-index: 3;
}
.pulse-a {
  left: 8%;
  animation: runLineA 4.8s linear infinite;
}
.pulse-b {
  left: 8%;
  top: 62%;
  background: #34d399;
  box-shadow: 0 0 22px rgba(52, 211, 153, 0.75);
  animation: runLineB 5.2s linear infinite;
}
.hero-motion-caption {
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: 12px;
  z-index: 3;
  border-radius: 10px;
  padding: 8px 10px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  background: rgba(15, 23, 42, 0.56);
  color: #e2e8f0;
  font-size: 13px;
  font-weight: 600;
  text-align: center;
}

.hero-visual {
  position: relative;
  min-height: 420px;
  border-radius: 24px;
  padding: 20px;
}
.hero-visual.glass-panel {
  background: linear-gradient(145deg, rgba(10, 22, 42, 0.9), rgba(10, 22, 42, 0.72));
  border: 1px solid rgba(149, 184, 240, 0.24);
  box-shadow: 0 22px 52px rgba(1, 8, 22, 0.44);
}
.hero-visual-label {
  margin-bottom: 12px;
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #b8d0f1;
  font-weight: 700;
}
.hero-showcase-image {
  width: 100%;
  display: block;
  border-radius: 16px;
  border: 1px solid rgba(153, 188, 244, 0.28);
}
.hero-visual-caption {
  margin-top: 10px;
  margin-bottom: 0;
  color: #c5d5ec;
  font-size: 14px;
  line-height: 1.55;
}
.mc-float {
  position: absolute;
  border-radius: 16px;
  padding: 12px;
  width: 220px;
  animation: floaty 5.5s ease-in-out infinite;
}
.mc-a { top: 8px; left: 8px; }
.mc-b { top: 26px; right: 12px; animation-delay: 0.7s; }
.mc-c { bottom: 10px; left: 28px; animation-delay: 1.2s; }
.card-title { font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: #64748b; }
.card-row { margin-top: 6px; display: flex; align-items: center; justify-content: space-between; font-size: 12px; color: #334155; }
.card-row strong { color: #0f172a; }
.card-row strong.ok { color: #15803d; }
.card-row strong.warn { color: #b45309; }

.lifecycle-canvas {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  width: min(760px, calc(100% - 24px));
  border-radius: 18px;
  padding: 14px;
}
.canvas-title { font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; color: #64748b; }
.lifecycle-track {
  margin-top: 10px;
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.node {
  border-radius: 999px;
  padding: 6px 10px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  font-size: 12px;
  color: #334155;
  animation: rise 0.6s ease-out both;
}
.node.done { border-color: #bbf7d0; color: #166534; background: #f0fdf4; }
.node.done { border-color: #bbf7d0; color: #166534; background: #f0fdf4; }
.node.active { border-color: #bfdbfe; color: #1d4ed8; background: #eff6ff; }
.node.pending { color: #475569; }
.canvas-meta { margin-top: 10px; display: grid; gap: 8px; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.meta-pill {
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  padding: 8px;
  font-size: 11px;
  color: #475569;
}
.meta-pill strong { color: #0f172a; }

.story-grid, .capabilities, .trust-rail, .final-cta { position: relative; z-index: 1; margin-top: 28px; }
.story-grid { display: grid; grid-template-columns: 1fr; gap: 12px; }
.story-card { border-radius: 18px; padding: 18px; }
.story-card h3 { margin-top: 8px; font-size: 20px; color: #0f172a; }
.story-card p { margin-top: 8px; font-size: 14px; }

.problem-solve {
  position: relative;
  z-index: 1;
  margin-top: 28px;
  border-radius: 20px;
  padding: 18px;
}
.problem-solve h3 {
  margin-top: 8px;
  font-size: 22px;
  color: #0f172a;
}
.problem-lanes {
  margin-top: 14px;
  display: grid;
  gap: 10px;
}
.lane-head {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  color: #64748b;
  font-weight: 600;
}
.lane-left { justify-self: start; }
.lane-right { justify-self: end; }
.lane-row {
  display: grid;
  gap: 8px;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
}
.lane-card {
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  padding: 12px;
}
.lane-problem {
  background: linear-gradient(135deg, #fff7ed, #fef3c7);
  border-color: #fed7aa;
}
.lane-solution {
  background: linear-gradient(135deg, #ecfeff, #dbeafe);
  border-color: #bfdbfe;
}
.lane-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: #64748b;
  font-weight: 700;
}
.lane-copy {
  margin-top: 6px;
  font-size: 13px;
  color: #1e293b;
  line-height: 1.45;
}
.lane-arrow {
  font-size: 20px;
  color: #2563eb;
  font-weight: 700;
  opacity: 0.7;
}

.cap-grid { margin-top: 10px; display: grid; gap: 12px; grid-template-columns: 1fr; }
.cap-card { border-radius: 16px; padding: 16px; }
.cap-card h4 { font-size: 16px; color: #0f172a; }
.cap-card p { margin-top: 6px; font-size: 13px; }

.trust-rail { border-radius: 20px; padding: 18px; }
.trust-grid { margin-top: 10px; display: grid; gap: 8px; grid-template-columns: 1fr; }
.trust-item {
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  padding: 10px;
  font-size: 13px;
  color: #334155;
}

.metrics-rail {
  position: relative;
  z-index: 1;
  margin-top: 28px;
}
.metrics-rail h3 {
  margin-top: 8px;
  font-size: 22px;
  color: #0f172a;
}
.metrics-grid {
  margin-top: 12px;
  display: grid;
  gap: 10px;
  grid-template-columns: 1fr;
}
.metric-card {
  border-radius: 16px;
  padding: 14px;
}
.metric-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: #64748b;
  font-weight: 600;
}
.metric-value {
  margin-top: 8px;
  font-size: 30px;
  line-height: 1;
  font-weight: 700;
  color: #0f172a;
}
.metric-detail {
  margin-top: 8px;
  font-size: 12px;
  color: #475569;
  line-height: 1.45;
}

.screenshots-rail {
  margin-top: 28px;
  border-radius: 20px;
  padding: 18px;
  position: relative;
  z-index: 1;
}
.screenshots-rail h3 {
  margin-top: 8px;
  font-size: 22px;
  color: #0f172a;
}
.screenshots-grid {
  margin-top: 12px;
  display: grid;
  gap: 10px;
  grid-template-columns: 1fr;
}
.screenshots-viewer {
  margin-top: 12px;
}
.screenshots-frame {
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid #dbe5f3;
  background: rgba(13, 29, 54, 0.8);
  box-shadow: 0 16px 30px rgba(2, 8, 20, 0.35);
}
.screenshots-frame img {
  display: block;
  width: 100%;
  max-height: 740px;
  object-fit: contain;
  background: #0b172d;
}
.screenshots-controls {
  margin-top: 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.shot-nav {
  border-radius: 10px;
  border: 1px solid rgba(149, 184, 240, 0.35);
  background: rgba(13, 29, 54, 0.8);
  color: #e6efff;
  padding: 7px 12px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.shot-nav:hover {
  border-color: rgba(149, 184, 240, 0.6);
  background: rgba(20, 40, 72, 0.9);
}
.shot-counter {
  font-size: 12px;
  color: #bdd2ee;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-weight: 700;
}
.screenshots-strip-wrap {
  margin-top: 10px;
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 8px;
  align-items: center;
}
.strip-nav {
  border-radius: 10px;
  border: 1px solid rgba(149, 184, 240, 0.35);
  background: rgba(13, 29, 54, 0.8);
  color: #e6efff;
  width: 34px;
  height: 34px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
}
.strip-nav:hover {
  border-color: rgba(149, 184, 240, 0.6);
  background: rgba(20, 40, 72, 0.9);
}
.screenshots-strip {
  margin-top: 10px;
  display: flex;
  gap: 8px;
  overflow-x: auto;
  scroll-behavior: smooth;
  scrollbar-width: thin;
  padding: 2px;
}
.shot-thumb {
  flex: 0 0 160px;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid rgba(149, 184, 240, 0.24);
  padding: 0;
  background: rgba(13, 29, 54, 0.65);
  cursor: pointer;
  opacity: 0.7;
}
.shot-thumb.active {
  opacity: 1;
  border-color: rgba(96, 165, 250, 0.9);
  box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.35);
}
.shot-thumb img {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 10;
  object-fit: cover;
}

.comparison-rail {
  margin-top: 28px;
  border-radius: 20px;
  padding: 18px;
  position: relative;
  z-index: 1;
}
.comparison-rail h3 {
  margin-top: 8px;
  font-size: 22px;
  color: #0f172a;
}
.comparison-grid {
  margin-top: 12px;
  display: grid;
  gap: 10px;
  grid-template-columns: 1fr;
}
.comparison-card {
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  background: linear-gradient(135deg, #ffffff, #f8fafc);
  padding: 12px;
}
.comparison-metric {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}
.comparison-values {
  margin-top: 8px;
  display: grid;
  gap: 8px;
  grid-template-columns: 1fr 1fr;
}
.comparison-col {
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  padding: 8px;
}
.comparison-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: #64748b;
}
.comparison-value {
  margin-top: 6px;
  font-size: 13px;
  font-weight: 600;
}
.comparison-value.muted {
  color: #475569;
}
.comparison-value.strong {
  color: #0f766e;
}
.comparison-note {
  margin-top: 8px;
  font-size: 12px;
  color: #475569;
}

.outcomes-rail {
  margin-top: 28px;
  border-radius: 20px;
  padding: 18px;
  position: relative;
  z-index: 1;
}
.outcomes-rail h3 {
  margin-top: 8px;
  font-size: 22px;
  color: #0f172a;
}
.outcomes-lead {
  margin-top: 8px;
  max-width: 780px;
  font-size: 14px;
  color: #475569;
}
.dream-strip {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.dream-pill {
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  font-weight: 700;
  color: var(--accent);
  border: 1px solid color-mix(in srgb, var(--accent) 32%, var(--border-soft));
  background: linear-gradient(135deg, color-mix(in srgb, var(--accent-soft) 88%, white), #ffffff);
}
.outcomes-grid {
  margin-top: 12px;
  display: grid;
  gap: 10px;
  grid-template-columns: 1fr;
}
.outcome-card {
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  background: linear-gradient(150deg, #ffffff, #f8fafc);
  padding: 12px;
  position: relative;
  overflow: hidden;
}
.outcome-card::after {
  content: "";
  position: absolute;
  width: 160px;
  height: 160px;
  border-radius: 999px;
  right: -70px;
  top: -70px;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.18), transparent 70%);
  pointer-events: none;
}
.outcome-tag {
  display: inline-flex;
  border-radius: 999px;
  padding: 3px 8px;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--accent);
  border: 1px solid color-mix(in srgb, var(--accent) 36%, var(--border-soft));
  background: color-mix(in srgb, var(--accent-soft) 86%, white);
  font-weight: 700;
}
.outcome-card h4 {
  margin-top: 8px;
  font-size: 14px;
  color: #0f172a;
}
.outcome-card p {
  margin-top: 6px;
  font-size: 12px;
  color: #475569;
  line-height: 1.5;
}
.outcome-value {
  margin-top: 8px;
  font-size: 12px;
  color: #0f172a;
  font-weight: 700;
}
.outcome-metric {
  margin-top: 8px;
  border-radius: 10px;
  border: 1px solid #dbeafe;
  background: #eff6ff;
  color: #1e3a8a;
  font-size: 11px;
  font-weight: 600;
  padding: 6px 8px;
}

.faq-rail {
  margin-top: 28px;
  border-radius: 20px;
  padding: 18px;
  position: relative;
  z-index: 1;
}
.faq-rail h3 {
  margin-top: 8px;
  font-size: 22px;
  color: #0f172a;
}
.faq-grid {
  margin-top: 12px;
  display: grid;
  gap: 10px;
  grid-template-columns: 1fr;
}
.faq-card {
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  background: linear-gradient(135deg, #ffffff, #f8fafc);
  padding: 12px;
}
.faq-q {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}
.faq-a {
  margin-top: 6px;
  font-size: 12px;
  color: #475569;
  line-height: 1.5;
}

.journey-rail {
  margin-top: 28px;
  border-radius: 20px;
  padding: 18px;
  position: relative;
  z-index: 1;
}
.journey-rail h3 {
  margin-top: 8px;
  font-size: 22px;
  color: #0f172a;
}
.journey-legend {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.legend-pill {
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  border: 1px solid var(--border-soft);
  background: color-mix(in srgb, var(--accent-soft) 52%, white);
  color: var(--text-muted);
}
.legend-you {
  border-color: color-mix(in srgb, var(--accent) 30%, var(--border-soft));
  background: color-mix(in srgb, var(--accent-soft) 70%, white);
  color: color-mix(in srgb, var(--accent) 82%, #0f172a);
}
.legend-system {
  border-color: color-mix(in srgb, var(--accent) 42%, var(--border-soft));
  background: color-mix(in srgb, var(--accent-soft) 90%, white);
  color: var(--accent);
}
.legend-shared {
  border-color: color-mix(in srgb, var(--accent) 26%, var(--border-soft));
  background: color-mix(in srgb, var(--accent-soft) 62%, white);
  color: color-mix(in srgb, var(--accent) 70%, #0f172a);
}
.journey-timeline {
  position: relative;
  margin-top: 12px;
  height: 12px;
}
.journey-line {
  position: absolute;
  left: 0;
  right: 0;
  top: 5px;
  height: 2px;
  background: linear-gradient(90deg, #f59e0b 0%, #3b82f6 50%, #8b5cf6 100%);
  opacity: 0.5;
}
.journey-grid {
  margin-top: 12px;
  display: grid;
  gap: 10px;
  grid-template-columns: 1fr;
}
.journey-card {
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  background: linear-gradient(160deg, #ffffff, #f8fafc);
  padding: 12px;
  position: relative;
  overflow: hidden;
  transition: transform 200ms ease, box-shadow 200ms ease;
}
.journey-card::after {
  content: "";
  position: absolute;
  width: 120px;
  height: 120px;
  border-radius: 999px;
  right: -50px;
  top: -50px;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.16), transparent 70%);
  pointer-events: none;
}
.journey-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
}
.journey-index-wrap {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.journey-index {
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #1d4ed8;
  font-weight: 700;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  padding: 3px 8px;
}
.journey-node {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: #2563eb;
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.15), 0 0 12px rgba(59, 130, 246, 0.35);
}
.journey-title {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
}
.journey-owner {
  margin-top: 4px;
  font-size: 11px;
  color: #334155;
  font-weight: 600;
  width: fit-content;
  border-radius: 999px;
  padding: 2px 8px;
}
.journey-owner.you {
  background: #fffbeb;
  color: #92400e;
  border: 1px solid #fde68a;
}
.journey-owner.system {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}
.journey-owner.shared {
  background: #f5f3ff;
  color: #6d28d9;
  border: 1px solid #ddd6fe;
}
.journey-detail {
  margin-top: 6px;
  font-size: 12px;
  color: #475569;
  line-height: 1.5;
}
.journey-action {
  margin-top: 8px;
  font-size: 12px;
  color: #0f172a;
  font-weight: 600;
}
.business-flow {
  margin-top: 28px;
  border-radius: 20px;
  padding: 18px;
  position: relative;
  z-index: 1;
}
.business-flow h3 {
  margin-top: 8px;
  font-size: 22px;
  color: #0f172a;
}
.business-flow-lead {
  margin-top: 8px;
  font-size: 14px;
  color: #475569;
}
.business-flow-grid {
  margin-top: 12px;
  display: grid;
  gap: 10px;
  grid-template-columns: 1fr;
}
.business-flow-card {
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  background: linear-gradient(140deg, #ffffff, #f8fafc);
  padding: 12px;
  position: relative;
  overflow: hidden;
}
.business-flow-card::after {
  content: "";
  position: absolute;
  right: -42px;
  top: -42px;
  width: 100px;
  height: 100px;
  border-radius: 999px;
  background: radial-gradient(circle, rgba(37, 99, 235, 0.2), transparent 68%);
}
.business-flow-step {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: #1d4ed8;
}
.business-flow-title {
  margin-top: 6px;
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}
.business-flow-owner {
  margin-top: 4px;
  display: inline-flex;
  border-radius: 999px;
  padding: 3px 8px;
  font-size: 11px;
  color: #1e3a8a;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  font-weight: 600;
}
.business-flow-detail {
  margin-top: 6px;
  font-size: 12px;
  color: #475569;
  line-height: 1.5;
}
.business-flow-proof {
  margin-top: 8px;
  border-radius: 10px;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #0f172a;
  font-size: 12px;
  font-weight: 600;
  padding: 6px 8px;
}

.voices-rail {
  margin-top: 28px;
  border-radius: 20px;
  padding: 18px;
  position: relative;
  z-index: 1;
}
.voices-rail h3 {
  margin-top: 8px;
  font-size: 22px;
  color: #0f172a;
}
.voices-grid {
  margin-top: 12px;
  display: grid;
  gap: 10px;
  grid-template-columns: 1fr;
}
.voice-card {
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  background: linear-gradient(140deg, #ffffff, #f8fafc);
  padding: 12px;
}
.voice-quote {
  margin: 0;
  font-size: 14px;
  line-height: 1.55;
  color: #1e293b;
}
.voice-meta {
  margin-top: 10px;
  border-top: 1px solid #e2e8f0;
  padding-top: 8px;
}
.voice-role {
  font-size: 12px;
  color: #0f172a;
  font-weight: 700;
}
.voice-impact {
  margin-top: 4px;
  font-size: 11px;
  color: #475569;
}

.brand-rail {
  margin-top: 28px;
  border-radius: 20px;
  padding: 18px;
  position: relative;
  z-index: 1;
}
.brand-rail h3 {
  margin-top: 8px;
  font-size: 22px;
  color: #0f172a;
}
.brand-grid {
  margin-top: 12px;
  display: grid;
  gap: 10px;
  grid-template-columns: 1fr;
}
.brand-card {
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  background: linear-gradient(145deg, #ffffff, #f8fafc);
  padding: 12px;
}
.brand-card__label {
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #64748b;
  font-weight: 700;
}
.brand-card__title {
  margin-top: 6px;
  font-size: 18px;
  color: #0f172a;
  font-weight: 700;
}
.brand-card__url {
  margin-top: 3px;
  font-size: 12px;
  color: #2563eb;
  font-weight: 600;
}
.brand-card p {
  margin-top: 8px;
  font-size: 12px;
  color: #475569;
  line-height: 1.5;
}

.ops-pipeline {
  margin-top: 28px;
  border-radius: 20px;
  padding: 18px;
  position: relative;
  z-index: 1;
}
.ops-pipeline h3 {
  margin-top: 8px;
  font-size: 22px;
  color: #0f172a;
}
.pipeline-track {
  margin-top: 14px;
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.pipeline-node {
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  padding: 10px;
  animation: rise 0.6s ease-out both;
}
.pipeline-node__dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  margin-bottom: 8px;
  box-shadow: 0 0 0 4px rgba(148, 163, 184, 0.15);
}
.pipeline-node__label {
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
}
.pipeline-node__hint {
  margin-top: 4px;
  font-size: 12px;
  color: #475569;
}
.pipeline-node.done .pipeline-node__dot {
  background: #16a34a;
  box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.15), 0 0 14px rgba(34, 197, 94, 0.4);
}
.pipeline-node.active .pipeline-node__dot {
  background: #2563eb;
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.18), 0 0 14px rgba(59, 130, 246, 0.45);
  animation: pulseDot 1.8s ease-in-out infinite;
}
.pipeline-node.pending .pipeline-node__dot {
  background: #64748b;
}
.pipeline-loop {
  margin-top: 12px;
  border-radius: 12px;
  border: 1px dashed #cbd5e1;
  background: #f8fafc;
  padding: 8px 10px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #475569;
}
.pipeline-loop .arrow {
  color: #1d4ed8;
  font-size: 14px;
}
.pipeline-metrics {
  margin-top: 12px;
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.metric-pill {
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  padding: 8px;
  font-size: 12px;
  color: #475569;
}
.metric-pill strong { color: #0f172a; }

.final-cta { text-align: center; padding-top: 10px; }
.final-cta h2 { font-size: clamp(28px, 3.5vw, 42px); color: #0f172a; }
.final-cta p { max-width: 760px; margin: 10px auto 0; }
.final-cta .hero-ctas { justify-content: center; }

.legal-rail {
  position: relative;
  z-index: 1;
  margin-top: 34px;
  padding-top: 14px;
  border-top: 1px solid #dbe4f0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.legal-brand {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}
.legal-links {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.legal-links a {
  font-size: 12px;
  color: #334155;
  text-decoration: none;
  border-bottom: 1px solid transparent;
}
.legal-links a:hover {
  color: #1d4ed8;
  border-bottom-color: #93c5fd;
}

/* Dark surface sync: match lower cards with hero visual language */
.story-card,
.problem-solve,
.cap-card,
.ops-pipeline,
.metric-card,
.comparison-rail,
.outcomes-rail,
.faq-rail,
.journey-rail,
.business-flow,
.voices-rail,
.brand-rail,
.trust-rail,
.screenshots-rail {
  background: linear-gradient(145deg, rgba(10, 22, 42, 0.86), rgba(10, 22, 42, 0.74));
  border: 1px solid rgba(149, 184, 240, 0.24);
  box-shadow: 0 20px 48px rgba(1, 8, 22, 0.38);
}

.story-card h3,
.problem-solve h3,
.cap-card h4,
.ops-pipeline h3,
.metrics-rail h3,
.comparison-rail h3,
.outcomes-rail h3,
.faq-rail h3,
.journey-rail h3,
.business-flow h3,
.voices-rail h3,
.brand-rail h3,
.metric-value,
.comparison-metric,
.journey-title,
.business-flow-title,
.voice-role,
.brand-card__title,
.lane-copy,
.business-flow-proof,
.outcome-value {
  color: #e6efff;
}

.story-card p,
.cap-card p,
.pipeline-node__hint,
.metric-detail,
.comparison-note,
.outcomes-lead,
.outcome-card p,
.faq-a,
.journey-detail,
.business-flow-detail,
.voice-impact,
.brand-card p,
.trust-item,
.hero-visual-caption {
  color: #b9cce8;
}

.comparison-card,
.outcome-card,
.faq-card,
.journey-card,
.business-flow-card,
.voice-card,
.brand-card,
.trust-item,
.metric-pill,
.pipeline-loop,
.pipeline-node,
.comparison-col {
  background: rgba(13, 29, 54, 0.72);
  border-color: rgba(149, 184, 240, 0.22);
}

.lane-problem,
.lane-solution {
  background: rgba(13, 29, 54, 0.72);
  border-color: rgba(149, 184, 240, 0.22);
}

.comparison-value.muted,
.journey-owner,
.business-flow-owner,
.pipeline-node__label,
.comparison-label,
.lane-label,
.metric-label,
.brand-card__label,
.business-flow-step,
.faq-q,
.trust-item {
  color: #c7d9f3;
}

.problem-solve .eyebrow,
.comparison-rail .eyebrow,
.outcomes-rail .eyebrow,
.faq-rail .eyebrow,
.journey-rail .eyebrow,
.business-flow .eyebrow,
.voices-rail .eyebrow,
.brand-rail .eyebrow,
.trust-rail .eyebrow,
.metrics-rail .eyebrow,
.screenshots-rail .eyebrow {
  color: #a8c1e6;
}

@keyframes floaty {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}
@keyframes rise {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes pulseDot {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.06); }
}
@keyframes pulseNode {
  0%, 100% { transform: translateY(0); opacity: 1; }
  50% { transform: translateY(-1px); opacity: 0.92; }
}
@keyframes driftGlow {
  0%, 100% { transform: scale(1) translate(0, 0); }
  50% { transform: scale(1.02) translate(-6px, 4px); }
}
@keyframes runLineA {
  0% { transform: translateX(0); opacity: 0; }
  10% { opacity: 1; }
  85% { opacity: 1; }
  100% { transform: translateX(540px); opacity: 0; }
}
@keyframes runLineB {
  0% { transform: translateX(0); opacity: 0; }
  10% { opacity: 1; }
  85% { opacity: 1; }
  100% { transform: translateX(520px); opacity: 0; }
}

@media (min-width: 980px) {
  .hero-shell { grid-template-columns: 1.02fr 1fr; align-items: stretch; }
  .story-grid { grid-template-columns: 1fr 1fr; }
  .cap-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .metrics-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .comparison-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .outcomes-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .faq-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .journey-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .business-flow-grid { grid-template-columns: repeat(5, minmax(0, 1fr)); }
  .voices-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .brand-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .trust-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .lifecycle-track { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .pipeline-track { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}

@media (max-width: 900px) {
  .lane-row {
    grid-template-columns: 1fr;
  }
  .lane-arrow {
    justify-self: center;
    transform: rotate(90deg);
  }
  .lane-right {
    justify-self: start;
  }
}

@media (max-width: 979px) {
  .hero-visual { min-height: 500px; }
  .mc-b { right: 4px; }
  .mc-c { left: 8px; }
}

@media (max-width: 760px) {
  .landing-v2-cinematic {
    padding: 20px 12px 72px;
  }
  .hero-copy {
    padding: 20px;
  }
  .hero-motion {
    min-height: 210px;
  }
  .hero-motion-track {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    margin-top: 34px;
  }
  .motion-node {
    font-size: 12px;
  }
  .hero-motion-caption {
    font-size: 12px;
  }
  .pulse-a,
  .pulse-b {
    display: none;
  }
  .hero-logo {
    width: 24px;
    height: 24px;
    border-radius: 6px;
  }
  .hero-visual {
    min-height: auto;
    display: grid;
    gap: 10px;
    padding: 0;
  }
  .mc-float {
    position: static;
    width: 100%;
    animation: none;
  }
  .lifecycle-canvas {
    position: static;
    transform: none;
    width: 100%;
  }
  .canvas-meta {
    grid-template-columns: 1fr;
  }
  .pipeline-metrics {
    grid-template-columns: 1fr;
  }
  .shot-thumb {
    flex-basis: 120px;
  }
}
</style>
