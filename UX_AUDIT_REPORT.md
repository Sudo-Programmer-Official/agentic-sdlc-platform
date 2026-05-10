# UX Audit Report (Non-Destructive, End-to-End)

## Scope and Guardrails
- Audit scope: workspace onboarding, project overview, requirements, operator dashboard, and Mission Control execution surfaces.
- Explicit guardrails respected: no core architecture redesign, no runtime orchestration changes, no route changes, no Mission Control behavior changes.
- Evaluation lenses: clarity, consistency, connected lineage, onboarding smoothness, execution visibility, runtime confidence, requirement/task/run relationships, progressive disclosure, actionable next states.

## Executive Summary
The platform already has strong depth and observability, but the user journey has high cognitive load because critical actions are distributed across multiple surfaces without a single, persistent “what next” guide. Most UX risk is not missing capability; it is fragmented sequencing and inconsistent action framing.

## What Works Well
- Rich runtime transparency in Mission Control and Operator Dashboard.
- Strong lineage primitives (requirements, tasks, runs, delivery, graph health) are present.
- Stage model and lifecycle scoring provide governance intent.
- Existing empty/error states are generally present and informative.

## Priority UX Findings
1. Next-action ambiguity across stages
- Users see many controls, but not a canonical order for first run setup.
- Result: onboarding friction and delayed time-to-first-success.

2. Requirement -> Task -> Run chain is visible but not consistently surfaced as one flow
- Evidence appears across Requirements, Overview, and Mission Control but requires manual mental stitching.
- Result: lower confidence in lineage continuity.

3. Progressive disclosure is inconsistent
- Advanced controls appear alongside setup controls, especially in Project Overview and Mission Control.
- Result: new users face expert-level density too early.

4. Terminology and action framing vary by view
- Similar intents use different labels (Execution View, Mission Control, Run Viewer, etc.).
- Result: cognitive switching cost.

5. Recovery and “safe next step” prompts are uneven
- Failure/warning states are surfaced, but recommended next actions are not always dominant.
- Result: slower recovery loops.

## Canonical User Journey (Proposed)
1. Workspace Home
- Create or open project.
- Confirm environment and recent context.

2. Project Overview (Setup)
- Connect repository.
- Confirm architecture contract and foundation readiness.
- Move to requirements preparation.

3. Requirements
- Ingest or edit requirements graph.
- Approve graph when stable.
- Confirm requirement cards/timeline are active.

4. Project Overview (Planning)
- Generate/create tasks.
- Validate task lineage and branch strategy.
- Move project stage to RUN.

5. Mission Control / Operator Dashboard (Execution)
- Start run.
- Monitor run plan, decomposition, and runtime events.
- Inspect artifacts/diffs and delivery status.

6. Iterate
- Compare/replay/fork runs.
- Track requirement health and improvement requests.
- Re-enter planning when refresh flags appear.

## Low-Risk Polish Improvements (Recommended)
- Add persistent journey checklist and primary “next action” CTA in Project Overview.
- Standardize action labels for navigation to execution surfaces.
- Add tighter empty-state guidance that points to exactly one next action.
- Improve lineage language consistency in requirement/task/run summaries.
- Surface warning recovery actions adjacent to warning content.

## High-Value UX Consolidation Opportunities
- Consolidate setup progress into one cross-view “readiness rail” (repo, requirements, tasks, run observed).
- Introduce a unified lineage panel reused across Overview/Requirements/Mission Control.
- Create a shared action vocabulary map for UI labels and button text.
- Add a context-aware “recommended next step” service response used by major views.
- Add compact expert toggles so advanced controls are collapsed until needed.

## Implemented Now (Compatibility-Safe)
- Added an additive Journey Guide panel to Project Overview.
- Includes:
  - Stage-aware headline and hint.
  - Four-step checklist (repo, requirements, tasks, execution observed).
  - Primary CTA that routes to safe existing actions only:
    - connect repo dialog
    - requirements view
    - create task dialog
    - start run
    - move to RUN stage
    - enter Mission Control
- No route changes, runtime logic changes, or orchestration changes.

