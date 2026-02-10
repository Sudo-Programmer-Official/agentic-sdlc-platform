Here’s the best “years-long” architecture for your vision: a Modular Monolith with an event-driven execution core.
It gives you: speed now, clean boundaries, and a straight path to microservices later—without rewriting everything.

Below is an ARCHITECTURE.md-ready spec you can drop into /docs/ARCHITECTURE.md so Cortex/Codex stays aligned.

⸻

ARCHITECTURE.md (Draft You Can Use)

1. Architecture Choice

Style: Modular Monolith (Monorepo)
Reason: Fast iteration + strong control + easy future split into services.

Principles
	•	Artifacts-first: /docs is the source of truth.
	•	Stage-gated SDLC: nothing progresses without approvals.
	•	Branch-only execution: agents never touch main directly.
	•	Auditable + stoppable: every tool call is logged; runs can pause/stop/resume.
	•	Least-privilege tools: strict allowlists and budgets.

⸻

2. High-Level System Diagram

Web UI (Vue3) → Orchestrator API (FastAPI) → Execution Runtime → Workspace Repo
Bedrock Agents are used as workers under orchestrator control.

Components
	1.	Web App
	•	Guided Mode: conversational SDLC wizard
	•	Advanced Mode: edit artifacts, view diffs, logs, runs
	2.	Orchestrator API (FastAPI)
	•	SDLC state machine
	•	Approval gates
	•	Run management + budgets
	•	Tool execution coordination
	•	Bedrock agent invocation
	3.	Execution Runtime
	•	Workspace manager (per project/run sandbox)
	•	Git branch manager (feature branch per run)
	•	Tool adapters (fs, git, tests, build, deploy)
	4.	Artifact Store
	•	Primary: repo /docs/*
	•	Secondary: DB metadata for indexing/searching
	5.	Audit Ledger
	•	Immutable action log for every run and tool call

⸻

3. SDLC State Machine

States
	•	INTAKE
	•	REQUIREMENTS_DRAFTED
	•	REQUIREMENTS_APPROVED
	•	DESIGN_DRAFTED
	•	DESIGN_APPROVED
	•	PLAN_READY
	•	IMPLEMENTING
	•	TESTING
	•	READY_FOR_REVIEW
	•	MERGED
	•	DEPLOYED

Gate Rules
	•	Requirements approval required to move forward
	•	Design approval required to move forward
	•	Merge approval required before main changes
	•	Any change to requirements/design invalidates downstream stages and triggers re-plan

⸻

4. Agents (Bedrock) and Responsibilities

Bedrock Agents are specialized and controlled by orchestrator.
	1.	Requirements Agent
	•	outputs: PRD, user stories, acceptance criteria
	2.	Architecture Agent
	•	outputs: architecture doc + ADRs + diagrams (text)
	3.	Planner Agent
	•	outputs: PLAN.json task graph (dependencies + estimates)
	4.	Implementation Agent
	•	executes tasks in branch workspace only
	•	produces diffs + commits + notes
	5.	QA Agent
	•	generates/runs tests
	•	outputs: TEST_REPORT.md + pass/fail vs acceptance criteria

Orchestrator is the governor: agents cannot self-advance stages.

⸻

5. Source of Truth and Change Control

Docs as Source of Truth

Artifacts live in /docs:
	•	PRD.md
	•	USER_STORIES.md
	•	ACCEPTANCE.md
	•	ARCHITECTURE.md
	•	ADRs/
	•	PLAN.json
	•	TEST_REPORT.md
	•	DEPLOY_REPORT.md

Traceability
	•	Requirement IDs: US-01, AC-01.1
	•	Plan tasks reference requirement IDs
	•	Commits reference requirement IDs
	•	Tests reference requirement IDs

Requirement edits trigger impact analysis (tasks/files likely affected) before code changes proceed.

⸻

6. Workspace and Git Strategy

Workspace
	•	Each project has a workspace directory
	•	Each run uses a separate run folder
	•	Each run uses a separate branch: agent/<project-id>/<run-id>

Merge Policy
	•	Only orchestrator can merge after approval
	•	Merge uses PR-style review: diff + test report + run summary

⸻

7. Trust Layer (Core Differentiator)

Action Ledger

Logs every action:
	•	agent
	•	stage
	•	tool
	•	command (if any)
	•	files touched
	•	timestamp
	•	result (success/failure)
	•	cost estimate (optional)

Budgets & Permissions

Per project/run:
	•	max steps
	•	max cost
	•	allowed toolset (fs only / fs+tests / deploy)
	•	network access (off by default)

Stop/Pause/Resume
	•	any run can be paused, resumed, or canceled
	•	cancellation rolls back to last approved stage

⸻

8. Deployment Strategy (Now vs Later)

MVP (recommended)
	•	Web: Vercel
	•	API: Render (or Fly.io)
	•	DB: managed Postgres

Future (optional)
	•	AWS native deployment (ECS/App Runner/Lambda)
	•	Queue-based run execution (SQS/Celery) for scale

Architecture supports both with minimal refactor.

⸻

9. Monorepo Structure

repo-root/
├── apps/
│   ├── web/              # Vue 3 + Tailwind + Element Plus
│   └── api/              # FastAPI orchestrator
├── core/
│   ├── sdlc/             # state machine
│   ├── approvals/        # approvals
│   ├── runs/             # run orchestration
│   ├── ledger/           # audit logs
│   ├── permissions/      # budgets + allowlists
│   └── artifacts/        # artifact IO + indexing
├── agent/
│   ├── bedrock/          # agent configs
│   ├── prompts/          # prompts by role
│   └── tools/            # tool adapters (git, fs, tests)
├── docs/                 # source-of-truth artifacts
└── infra/                # deployment scripts


⸻

10. Why This Will Last for Years
	•	Starts simple (monolith), scales cleanly (service split later)
	•	Strong SDLC governance and trust layer
	•	Vendor-flexible (Bedrock now, swap later if needed)
	•	Document-first reduces churn and supports teams
	•	Great research story + great product story

⸻

The One Recommendation I’d Add

Add ADR documents from day 1:
	•	ADR-001: Modular monolith decision
	•	ADR-002: Stage-gated approvals
	•	ADR-003: Branch-only execution
	•	ADR-004: Bedrock agents as workers, orchestrator as governor

This keeps Cortex aligned and prevents scope drift.

⸻

Quick Naming Note

Your file should be:
	•	/docs/ARCHITECTURE.md (not Azure.md)

⸻

If you say “yes”, I’ll also generate:
	•	ADR-001.md through ADR-004.md (ready to commit)
	•	the API contract (/api/v1/projects, /runs, /approvals)
	•	the DB schema (tables for projects, runs, artifacts, ledger)