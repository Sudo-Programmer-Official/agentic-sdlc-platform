You’re describing the exact gap between “manual daily dev loop” and “real agentic SDLC”: who does what, how code changes are controlled, and how we keep a single source of truth so the agent doesn’t go rogue.

Here’s the clean architecture that replaces your current workflow end-to-end.

⸻

0) The Big Idea

Your current loop is:

You: prompt → modify code → run tests → review → iterate → update docs.

The agentic replacement is:

System: capture requirements → generate plan → execute in sandbox → run tests → produce diff + report → ask human approval → merge → deploy.

✅ The key: the agent never commits to “main”. It works in a branch / sandbox, and humans approve.

⸻

1) The Core Components (Platform Architecture)

A) UI (Vue3 + Tailwind + Element Plus)

Two modes:
	•	Guided Mode: chat-based SDLC wizard
	•	Advanced Mode: shows artifacts, diffs, agent logs, repo tree, pipeline buttons

UI actions:
	•	“Approve Requirements”
	•	“Approve Design”
	•	“Run Implementation”
	•	“Run Tests”
	•	“Review Diff”
	•	“Approve Merge”
	•	“Deploy”

B) Orchestrator API (FastAPI recommended)

This is the “brain” that:
	•	Controls the SDLC state machine
	•	Spawns agents
	•	Manages tools (git, tests, build)
	•	Saves artifacts
	•	Enforces guardrails

C) Agent Runtime (Multi-agent, controlled)

Agents do only their assigned role, all coordinated by orchestrator.

D) Workspace / Repo Sandbox
	•	Each project has a workspace folder
	•	Each run happens in a git branch (or ephemeral workspace)
	•	Only after approval, changes are merged

E) Artifact Store (source of truth)
	•	docs/ in repo + DB metadata
	•	PRD, user stories, ADRs, diagrams, task plan, evaluation report
	•	Every stage writes artifacts before code

⸻

2) Agents You’ll Have (Minimal but Powerful)

You do 5 agents (enough to look serious, not enough to become chaos).
	1.	Requirements Agent

	•	Converts conversation → PRD + user stories + acceptance criteria
	•	Outputs: docs/PRD.md, docs/USER_STORIES.md

	2.	Architect Agent

	•	Proposes architecture templates (monorepo by default)
	•	Outputs: docs/ARCHITECTURE.md, docs/ADR-001.md

	3.	Planner Agent

	•	Converts artifacts → task graph (tickets)
	•	Outputs: docs/PLAN.json (tasks with dependencies)

	4.	Implementation Agent

	•	Executes tasks by editing files + running commands
	•	Outputs code changes + notes per task

	5.	QA Agent

	•	Generates tests, runs tests, summarizes failures
	•	Outputs: docs/TEST_REPORT.md

Orchestrator (not an agent): enforces stages + approvals + safety.

⸻

3) How Code Is Managed (This is the “No-Rogue-Agent” policy)

Golden Rules
	•	✅ Agent works only on a feature branch: agent/<run-id>
	•	✅ Agent must produce a Change Proposal (diff + report)
	•	✅ Human must approve before merge to main
	•	✅ Every code change must link to a requirement/task ID
	•	✅ If requirements change, code changes pause and plan regenerates

Concrete flow
	1.	Orchestrator creates branch agent/run-2026-02-03-001
	2.	Agent edits files + runs tests
	3.	Orchestrator generates:
	•	git diff
	•	tests output
	•	“What changed / why”
	4.	UI shows Diff Viewer + Report
	5.	User clicks:
	•	✅ “Approve & Merge”
	•	🔁 “Request Changes”
	•	❌ “Reject Run”

This mimics how a real team works (PR review).

⸻

4) “Source of Truth” (Your “sticking with the source of truth”)

Your source of truth = artifacts in docs/.

Required artifacts per stage
	•	Requirements: PRD + Stories + Acceptance Criteria
	•	Design: Architecture doc + ADRs
	•	Plan: Task graph JSON
	•	Implementation: Change log + mapping tasks → files
	•	QA: Test report + coverage (optional)
	•	Deploy: Deploy report

The agent is not allowed to “invent requirements.”
If something is unclear → it must ask questions or pause.

⸻

5) The SDLC State Machine (How we finish end-to-end)

Define project state:
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

Each transition requires either:
	•	agent output + checks, or
	•	human approval

This guarantees you can finish, because it prevents endless wandering.

⸻

6) Tool Execution (Replacing what you do manually)

The agent will have controlled tools:
	•	read_file(path)
	•	write_file(path, content)
	•	run_cmd(command) (allowed list only)
	•	search_repo(query)
	•	git_status, git_diff, git_commit (in branch only)
	•	run_tests (e.g., npm test, pytest)
	•	build (e.g., npm run build)

Tool restriction matters for safety + reproducibility.

⸻

7) “One-Click Deploy” (Demo-Realistic)

For the capstone, keep deploy simple:

Best demo deploy
	•	Web: Vercel
	•	API: Render (or Fly.io)
	•	DB: managed (optional)

Flow:
	•	Orchestrator generates deploy config + instructions
	•	User clicks “Deploy” → triggers CI script or shows copy/paste commands
	•	Store docs/DEPLOY_REPORT.md

If you insist on AWS later, you can swap it in, but for semester success: keep it simple.

⸻

8) How You Finish This in a Semester (No Scope Explosion)

MVP (must deliver)
	•	Guided intake → PRD → approve
	•	Architecture doc → approve
	•	Task plan JSON
	•	Agent implements a small web+api app
	•	Tests run + report
	•	Diff review + merge
	•	Deploy to Vercel/Render

That’s a complete SDLC loop.

Stretch (if time)
	•	Advanced mode editing
	•	Requirement change impact: update plan without breaking code
	•	Better diagrams

⸻

9) What We Build First (Week 1–2 Engineering Plan)
	1.	Project State Machine + DB schema
	2.	Artifact folder structure (docs/)
	3.	Branch-based workspace execution
	4.	One agent: Requirements Agent
	5.	UI: stage approvals

Once this is solid, adding more agents is easy.

⸻

Now pick 2 decisions so I can lock the architecture doc
	1.	Backend orchestrator: FastAPI or NestJS?
	2.	Deploy target: Vercel+Render (recommended) or AWS?

If you don’t answer, I’ll assume FastAPI + Vercel/Render because it’s the fastest path to an end-to-end demo.