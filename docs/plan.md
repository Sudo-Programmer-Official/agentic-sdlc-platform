Love the direction — what you’re describing is basically a human-in-the-loop SDLC autopilot: requirements-first, multi-agent execution, and “document-level change control” so code doesn’t get churned.

Here’s a final, buildable system plan that matches your vision and stays semester-realistic.

⸻

1) Product Vision in One Line

A conversational SDLC workspace where a non-tech user can describe an idea, and the system guides them through Requirements → Design → Implementation → Testing → Validation → Deploy, with human approvals at each stage, and an Advanced mode for tech users to override, edit, or plug in custom architecture choices.

⸻

2) Key Design Principle

“Catch changes at the document level, not the code level.”

So the system uses specs as the source of truth and generates/updates code only after approvals.

Artifacts-first pipeline:
	•	Requirements spec ✅
	•	Architecture decision ✅
	•	UML diagrams ✅
	•	Task plan ✅
	•	Implementation ✅
	•	Tests ✅
	•	Deployment ✅

⸻

3) User Experience (2 Modes)

A) Non-Tech Mode (Guided Chat Flow)

A “talking bot” that:
	1.	Asks structured questions (like a PM/BA)
	2.	Produces artifacts (PRD, user stories, acceptance criteria)
	3.	Shows a Review & Approve button at each stage
	4.	Never exposes scary technical controls

B) Advanced Mode (Power User)

A toggle that unlocks:
	•	Edit PRD/user stories directly
	•	Choose architecture template (monolith / modular monolith / microservices)
	•	Pick stack presets (Vue3 + Tailwind + Element Plus + Node/Nest/FastAPI)
	•	Modify repo structure
	•	See full agent traces and logs

⸻

4) Multi-Agent System (Who Does What)

You don’t need 20 agents. You need 5–6 disciplined ones:
	1.	Product/Requirements Agent

	•	Converts chat to PRD + user stories + acceptance criteria
	•	Maintains a “Requirements Change Log”

	2.	Architecture Agent

	•	Proposes architecture options and tradeoffs
	•	Produces: C4-style overview + ADRs (lite)
	•	Generates a repo blueprint (monorepo recommended)

	3.	Planner/Orchestrator Agent

	•	Turns approved artifacts into executable tasks
	•	Creates tickets: “Task Graph” with dependencies

	4.	Implementation Agent

	•	Writes code in the monorepo based on spec + plan

	5.	QA/Test Agent

	•	Generates tests, runs them, reports failures
	•	Works with Implementation agent to fix

	6.	Release/Deploy Agent (optional but nice)

	•	Creates deploy plan and executes (or prepares scripts)
	•	Minimal “one-click deploy” for demo

The Orchestrator is the boss. Others are specialists.

⸻

5) Core Workflow (SDLC as a State Machine)

Your system should behave like a controlled pipeline:

Stage 0 — Intake
	•	User describes idea (chat/voice)
	•	Output: “Project Brief”

Stage 1 — Requirements (Human approval required)
	•	PRD
	•	User stories
	•	Acceptance criteria
	•	Non-functional requirements checklist

✅ Gate: “Approve Requirements”
🔁 If changed: update PRD + regenerate downstream tasks

Stage 2 — Design (Human approval required)
	•	Architecture choice (monorepo default)
	•	Component diagram
	•	API contract draft
	•	DB schema draft (if needed)

✅ Gate: “Approve Design”

Stage 3 — Implementation (Human approval optional)
	•	Scaffolds repo
	•	Implements features per tasks
	•	Logs code changes per requirement ID

Stage 4 — Testing & Validation (Human approval recommended)
	•	Unit tests + basic integration tests
	•	Validation report vs acceptance criteria

✅ Gate: “Approve Release”

Stage 5 — Deploy (Demo scope)
	•	Deploy scripts generated
	•	“One-click deploy” can be simulated OR real (Render/Vercel)

⸻

6) “Document-Level Change Control” (Your Differentiator)

This is your secret sauce for being “more than a chatbot.”

Requirements Traceability Matrix (RTM) lite

Every story gets an ID:
	•	US-01: “User can sign up”
	•	AC-01.1: acceptance criteria

Then code + tests reference it:
	•	commits mention US-01
	•	test file names or comments mention US-01

So if user changes a requirement:
	•	system detects impacted components/tests
	•	regenerates tasks BEFORE touching code

That’s exactly the “avoid costly code-level churn” story.

⸻

7) Monorepo Architecture (Recommended)

Monorepo structure (clean + demo-friendly)
	•	apps/web (Vue 3 + Tailwind + Element Plus)
	•	apps/api (Node/Nest or FastAPI)
	•	packages/shared (types, utils, schemas)
	•	packages/agent-core (orchestrator + tools)
	•	docs/ (PRD, ADRs, UML, diagrams)
	•	infra/ (deploy scripts)

Use docs/ as the source of truth.

⸻

8) Tech Stack (Aligned to Your Existing Stack)

Frontend
	•	Vue 3 + Tailwind + Element Plus

Backend (pick one, don’t overthink)
	•	FastAPI (simple, fast, great for orchestration)
or
	•	NestJS (if you want enterprise style)

Agent Runtime
	•	Orchestrator service with:
	•	tool runner (filesystem, git, test runner)
	•	state machine for SDLC stages
	•	trace logging

Storage
	•	Postgres (project state, artifacts metadata)
	•	S3 (artifacts, logs) — optional, but matches your AWS comfort

Deployment (demo-grade)
	•	Web: Vercel/Netlify
	•	API: Render/Fly.io
	•	Or AWS (if you want, but keep scope sane)

⸻

9) MVP Scope (So You Finish on Time)

MVP = “One vertical slice”

Build one complete SDLC flow for:
✅ “Generate a landing page + contact form + basic backend endpoint”
That’s enough to demo:
	•	requirements
	•	design
	•	implementation
	•	testing
	•	deploy

Then add 1–2 extra tasks for evaluation.

⸻

10) Evaluation Plan (Must-have for Grade A)

Compare:

Baseline (non-agentic)
	•	single LLM prompt: “generate app”
	•	no stage gates
	•	no reflection

Your system
	•	staged pipeline + approvals
	•	multi-agent execution
	•	reflection loop

Metrics:
	•	Task completion rate
	•	Human interventions count
	•	Rework iterations (how many loops)
	•	Requirement change impact accuracy (did it catch impacted tasks?)

⸻

11) What We Lock Today (Decisions)

Here are the decisions to lock now:
	1.	Monorepo: Yes
	2.	Modes: Guided + Advanced toggle
	3.	Human-in-loop gates: Requirements + Design + Release
	4.	MVP app type: Web + API + Deploy
	5.	Backend choice: FastAPI or NestJS (FastAPI is simpler)

⸻

Next: I’ll turn this into a “Project Blueprint”

Tell me these 3 picks and I’ll generate:
	•	final architecture diagram structure
	•	repo skeleton
	•	SDLC state machine spec
	•	agent responsibilities + interfaces
	•	milestone plan (week-by-week)

Q1: Backend: FastAPI or NestJS?
Q2: Deploy target for demo: Vercel+Render or AWS?
Q3: MVP app: Landing+Contact or CRUD dashboard?