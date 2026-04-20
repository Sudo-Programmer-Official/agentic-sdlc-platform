# Thesis-Level Project Document

## Title

**Agentic SDLC Platform: A Contract-Driven, Architecture-Aware Runtime for AI-Assisted Software Delivery**

## Abstract

Software teams increasingly use large language models to generate code, tests, plans, and technical documentation. Despite strong gains in local productivity, most current usage patterns remain informal, prompt-driven, and difficult to govern at scale. Engineers frequently move between chat tools, code editors, terminal sessions, pull requests, and ad hoc review loops to coordinate work that lacks explicit runtime guarantees. This creates a structural gap between AI assistance and production-grade software delivery.

This project proposes and implements an **Agentic SDLC Platform** that treats AI-assisted software work not as a sequence of isolated prompts, but as a governed execution system. The platform combines document-first planning, structured task decomposition, architecture-aware scope control, bounded repository mutation, model routing, validation contracts, execution replay, and human review gates inside a unified runtime. The system is implemented as a modular monolith with a FastAPI backend, a Vue 3 frontend, and shared core and agent modules. It introduces an execution contract that constrains allowed files, protected zones, safe refactor zones, validation recipes, command prefixes, token budgets, and retry states for each run. It also introduces architecture profiles and engineering memory so future runs can inherit reviewed knowledge instead of starting from zero.

The central thesis of the work is that reliable AI-assisted delivery requires **explicit control planes** around context, scope, validation, and review. Raw code generation alone is insufficient. A usable software execution system must be observable, bounded, auditable, and recovery-safe. This document presents the motivation, architecture, implementation model, capabilities, limitations, and forward roadmap of the Agentic SDLC Platform, and positions it as a foundation for architecture-aware autonomous software operations.

## Keywords

AI-assisted software engineering, autonomous agents, SDLC automation, software runtime orchestration, engineering memory, architecture-aware execution, human-in-the-loop AI, bounded code mutation, task decomposition, validation contracts

## 1. Introduction

### 1.1 Background

The modern software delivery pipeline spans requirements gathering, design, planning, implementation, testing, review, deployment, and operational learning. While AI systems can accelerate individual steps, most engineering organizations still lack a coherent way to integrate them into the full Software Development Life Cycle (SDLC). In practice, AI coding support is often consumed through conversational interfaces that are detached from project history, architectural decisions, execution safety rules, and validation obligations.

This fragmentation creates several recurring problems:

- the system has weak understanding of project-specific architecture
- generated changes are insufficiently scoped
- review and validation rules are loosely enforced
- failure recovery is inconsistent
- knowledge learned from one run is not systematically reused in the next
- delivery decisions remain hidden across multiple disconnected tools

The result is a paradox: AI appears powerful at the point of generation, but brittle at the point of trustworthy software delivery.

### 1.2 Problem Statement

Existing AI coding workflows optimize for generation throughput rather than delivery robustness. They typically do not provide:

- explicit architectural boundaries
- deterministic mutation guardrails
- reusable execution contracts
- run-visible orchestration
- scoped validation plans
- structured review and recovery semantics
- persistent engineering memory

This project addresses the following research problem:

**How can AI-assisted software work be transformed from prompt-level code generation into a governed runtime that is architecture-aware, execution-bounded, validation-backed, and operationally observable?**

### 1.3 Project Goal

The goal of the Agentic SDLC Platform is to build a system that behaves less like a chatbot for coding and more like an **operating environment for AI-assisted software delivery**. The platform should absorb the coordination burden that currently lives in the engineer’s head and expose it as a first-class product and runtime.

### 1.4 Objectives

The project pursues the following objectives:

1. Build a document-first, traceable SDLC model.
2. Introduce a runtime that executes work through structured work items rather than free-form prompts.
3. Constrain AI execution using architecture profiles, scope rules, patch guards, and validation recipes.
4. Route model calls according to task type, ambiguity, risk, cost, and review requirements.
5. Preserve observability through immutable event logs, run context, execution state, and artifact lineage.
6. Support human-in-the-loop review for risky or ambiguous operations.
7. Introduce engineering memory so reviewed knowledge can influence future runs.

### 1.5 Scope of the Work

The current system implements a strong runtime and orchestration foundation for AI-assisted SDLC execution. It includes:

- project and run orchestration
- work-item DAG generation
- execution contracts and patch guard enforcement
- architecture profile bootstrap and runtime projection
- AI routing and cost control
- engineering memory retrieval through context packs
- review-aware and validation-aware runtime stages
- isolated run workspaces and per-run branch management

The current system does **not yet fully formalize** several product-level knowledge domains such as brand kits, design systems, service topology contracts, and infrastructure policy as first-class structured runtime artifacts. These are identified as primary future-work areas.

## 2. Project Context and Motivation

### 2.1 Why Existing AI Coding Workflows Are Not Enough

Current AI usage patterns often assume that better prompts or larger models will solve software delivery problems. This is a weak assumption. Many failures are not fundamentally generation failures; they are failures of control:

- the model is not told what the true scope is
- the model is not given project-specific rules
- the system cannot distinguish planning from mutation
- validation steps are under-specified
- review is reactive rather than structural
- failures are not recovered through stable policies

The Agentic SDLC Platform addresses these issues by separating:

- **what the system is allowed to do**
- **what it is trying to do**
- **what proof it must produce before being trusted**

### 2.2 Core Thesis

The core thesis of this project is:

> AI-assisted software delivery becomes dependable only when generation is embedded inside explicit architectural, operational, and validation contracts.

This leads to six design principles:

1. architecture-first
2. bounded execution
3. truthful runtime visibility
4. validation-backed completion
5. review-aware autonomy
6. memory-guided future runs

## 3. System Overview

### 3.1 High-Level System Shape

The repository is organized as a modular monolith:

- `apps/web`: Vue 3 + Vite operator interface
- `apps/api`: FastAPI orchestration and runtime service
- `core`: domain models, permissions, ledger, and shared SDLC primitives
- `agent`: agent adapters, prompts, and tool integrations
- `infra`: deployment scaffolding and infrastructure support
- `docs`: specifications, roadmaps, architectural references, and planning artifacts

### 3.2 Product Surfaces

The system is organized around four primary product surfaces:

1. **Architecture Profile**  
   Persistent project brain containing repository layout, package boundaries, commands, validation recipes, safe zones, and protected zones.

2. **Task Router and Runtime Policy Layer**  
   Classifies work by role, task type, ambiguity, risk, model tier, budget, retry strategy, and human review requirements.

3. **Run Console / Mission Control**  
   Exposes current step, work-item state, failed commands, artifacts, validation state, and run-level execution context.

4. **Approval and Verification Plane**  
   Governs risky execution, validation obligations, review stages, and completion claims.

### 3.3 Core Runtime Flow

At a high level, the system executes as follows:

1. A project run is created.
2. The orchestrator bootstraps a run workspace.
3. A work-item DAG is generated.
4. A run plan snapshot and execution contract are persisted.
5. Executors claim work items and execute them through a bounded runtime.
6. Outputs are validated through stage-aware rules and patch guards.
7. Reviews and validation items determine whether the run completes, fails, or blocks.
8. Knowledge artifacts and runtime lineage may be promoted for future retrieval.

## 4. Architectural Design

### 4.1 Runtime and Orchestration Layer

The runtime converts manually initiated work into governed execution. It is built around:

- `RunOrchestrator`
- `TaskExecutor`
- run workspaces
- work-item DAGs
- state guards
- event log emission
- execution contract synchronization

This design prevents agents from mutating the system’s core state directly. Agents act only through the runtime, and status transitions are system-owned rather than model-owned.

### 4.2 Execution Contract

The execution contract is one of the most important contributions of the system. It captures a run-scoped operational envelope including:

- goal
- target files
- allowed files
- related files
- protected paths
- safe paths
- validation steps
- validation recipes
- command index
- build, test, and lint commands
- allowed command prefixes
- file budgets
- risk level
- assumptions used
- validation state
- retry state
- token and cost budget

This contract makes AI execution **explicitly bounded**. Instead of asking the model to “be careful,” the runtime defines what careful means in operational terms.

### 4.3 Patch Guard and Scope Enforcement

The patch guard evaluates planned actions against:

- file-budget limits
- hard file caps
- allowed-file scope
- protected architecture zones
- safe refactor zones

Stage-specific restrictions further refine what work is legal. For example:

- planning stages may only produce note actions
- review stages may only produce note actions
- test-writing stages may only mutate Python test files

This is a major robustness feature because it separates model output from permission to apply that output.

### 4.4 Architecture Profile

The architecture profile provides persistent, reusable project structure. It derives and exposes:

- package inventory
- repository layout
- service and package boundaries
- command coverage
- validation recipes
- safe refactor zones
- protected zones
- environment assumptions
- release-flow assumptions

The runtime consumes a summarized version of this profile to guide execution. This reduces dependence on transient prompt context and increases consistency across runs.

### 4.5 Engineering Memory and Context Packs

The platform uses reviewed engineering knowledge as a runtime input rather than treating every run as isolated. Context packs can include:

- repository summary
- architecture summary
- conventions summary
- changed module map
- file ownership hints

This is a strong foundation for long-lived project intelligence. It is especially important because it shifts the system from “guess again every run” toward “retrieve what the project already knows.”

### 4.6 AI Routing and Cost Control

The AI policy layer routes jobs by:

- role
- task type
- ambiguity level
- risk level
- selected model tier
- max model tier
- retry count
- context cap
- budget cap
- human review requirement

This design recognizes that not all AI work deserves the same model quality or cost profile. Planning, coding, review, testing, and deterministic formatting are treated as different computational classes.

## 5. Implementation Details

### 5.1 Backend Implementation

The backend is implemented using FastAPI and organizes runtime behavior across orchestration, policy, context, safety, and state-management services. Key implementation areas include:

- runtime orchestration
- patch and scope guard logic
- architecture profile derivation
- engineering memory retrieval
- AI job preparation and accounting
- work-item lifecycle management
- workspace preparation and branch handling

The backend is responsible for maintaining execution truth.

### 5.2 Frontend Implementation

The frontend provides an operator-facing Mission Control interface. It exposes:

- run-plan visualization
- current step and next best step
- review and validation state
- agent activity
- artifact access
- AI ops and routing metrics
- project overview and architecture surfaces

This is important because transparency is a product requirement. Hidden AI work reduces trust; visible execution increases operator control.

### 5.3 Workspace Isolation

Each run executes in its own workspace. The workspace layer handles:

- workspace directory creation
- repository seeding
- branch allocation
- context and artifact directory creation
- manifest persistence
- command audit path exposure

This structure reduces cross-run interference and supports future replay, debugging, and recovery.

### 5.4 Structured Output Discipline

The executor requires model outputs to conform to a JSON schema. The system contains structured-output recovery rules including:

- parser-failure detection
- bounded parser retry
- stage-aware prompt repair
- model-tier escalation on selected failure modes
- patch-repair regeneration when a diff does not apply

These mechanisms are essential because many practical failures are not semantic reasoning failures; they are output-shape failures. Treating them explicitly improves reliability.

## 6. Functional Capabilities of the Current System

The current platform can already support several non-trivial software-delivery capabilities.

### 6.1 Capabilities That Are Operational Today

- document-first project and run management
- run bootstrapping with workspace preparation
- task and work-item generation
- bounded frontend and backend implementation stages
- test-writing and validation stages
- review-diff and integration-review stages
- AI policy-based routing, retry, and budget accounting
- architecture-aware safe-zone and protected-zone enforcement
- cached context-pack retrieval
- event logging and artifact lineage
- recovery-aware execution state tracking

### 6.2 Why These Capabilities Matter

Together, these capabilities establish the project as more than a code generator. The platform already functions as a **controlled execution environment** with:

- explicit state transitions
- execution boundaries
- traceable failures
- recoverable runtime context
- staged validation
- project-aware execution hints

This is a meaningful step toward operational AI software engineering.

## 7. Current Weaknesses and Research Gaps

Although the system is robust in runtime terms, several knowledge domains are still under-modeled.

### 7.1 Brand Kit Is Not Yet First-Class

The system does not yet have a structured `brand_kit` artifact with fields such as:

- primary and secondary colors
- typography hierarchy
- spacing scale
- iconography rules
- copy tone
- forbidden visual patterns

As a result, UI generation can still be visually inconsistent across runs.

### 7.2 Design System Is Not Yet First-Class

The system lacks a structured design-system contract such as:

- approved components
- design tokens
- layout primitives
- accessibility thresholds
- component usage constraints
- visual acceptance references

Without this, the runtime can protect code scope but cannot yet strongly protect design consistency.

### 7.3 System Architecture Is Path-Aware More Than Contract-Aware

The architecture profile is currently strong at:

- repository structure
- safe zones
- protected zones
- commands
- validation recipes

It is weaker at fully structured system design concerns such as:

- service contracts
- API ownership boundaries
- event schemas
- database ownership
- rollout sequencing
- SLO-aware operational boundaries

### 7.4 Infrastructure Knowledge Is Not Yet Formalized Enough

The system knows how to classify risk in infra-sensitive paths, but it does not yet expose a full structured infrastructure contract including:

- environment topology
- secret handling policy
- deployment sequencing
- rollback strategy
- migration ordering rules
- environment-specific command contracts

### 7.5 Semantic Validation Is Still Limited

Validation is currently strong for bounded execution and command-backed checks. It is still weaker for:

- design-token validation
- screenshot or visual regression review
- API compatibility validation
- schema drift detection
- cross-service contract validation
- operator-defined domain invariants

## 8. How the System Would Handle More Complete Software Context

### 8.1 Brand Kit

To support product-grade UI work, the system should store a brand kit as structured project memory. This would allow the runtime to:

- load brand rules into context packs
- constrain UI prompts with canonical style rules
- validate generated output against token usage or class patterns
- require screenshot review for visual changes

### 8.2 Design System

A design system should be modeled as an execution contract input, not just a document. The platform should know:

- which components are canonical
- which raw HTML/CSS patterns are forbidden
- which token names are legal
- which accessibility checks are mandatory

That would let the runtime reject visually inconsistent but syntactically valid changes.

### 8.3 Backend and System Design

For large backend systems, the architecture profile should expand into a full system contract including:

- service topology
- ownership map
- synchronous and asynchronous interfaces
- schema and migration rules
- trust boundaries
- rate-limiting or auth assumptions
- rollback-safe mutation rules

### 8.4 Infrastructure and Deployment

For production infrastructure, the platform should introduce an `infra_contract` with:

- environment matrix
- deployment tiers
- protected infra zones
- required approval thresholds
- rollback procedures
- command allowlists by environment

This is necessary before autonomous infrastructure work can be considered safe.

## 9. Evaluation Framework

### 9.1 Evaluation Criteria

A thesis-level system of this nature should be evaluated across the following axes:

1. **Correctness**  
   Did the system produce bounded, valid, stage-appropriate outputs?

2. **Safety**  
   Did the system avoid illegal mutations, protected zones, or out-of-scope edits?

3. **Observability**  
   Could an operator understand what happened, why it happened, and what should happen next?

4. **Recovery Quality**  
   Could the system recover from parser failures, invalid diffs, blocked runs, and review-stage issues without destructive behavior?

5. **Cost Efficiency**  
   Did the policy layer route work through appropriate model tiers and context sizes?

6. **Knowledge Reuse**  
   Did reviewed architectural and operational knowledge meaningfully improve later runs?

### 9.2 Practical Prototype Evidence

The current prototype already demonstrates several promising properties:

- stage-aware mutation control
- parser-retry handling
- review-aware execution separation
- token and cost budget control
- architecture-profile-driven scope guidance
- engineering-memory retrieval through cached context packs

These are not cosmetic features. They directly contribute to reliability, operator trust, and reproducibility.

### 9.3 Recommended Future Evaluation

The next evaluation phase should measure:

- success rate by work-item type
- blocked-run rate by cause
- patch-guard violation frequency
- average retries by role and tier
- context-pack reuse rate
- cost per successful run
- false-positive and false-negative review outcomes
- time saved versus manual orchestration

## 10. Contributions of the Project

This project contributes the following:

1. A practical argument that AI-assisted SDLC needs a runtime, not just prompts.
2. A contract-driven execution model for bounded repository mutation.
3. An architecture-profile system that converts repository structure into runtime guidance.
4. An engineering-memory integration strategy for reviewed knowledge reuse.
5. A model-routing and cost-control layer that treats AI work as policy-governed computation.
6. A stage-aware execution model that distinguishes planning, implementation, testing, and review.
7. A product blueprint for turning software delivery into a visible execution cockpit.

## 11. Limitations

This work also has clear limitations:

- it is currently implemented as a modular monolith rather than a distributed execution plane
- brand and design-system knowledge are not yet first-class runtime artifacts
- semantic validation remains weaker than syntactic validation
- infrastructure automation is not yet formalized enough for safe autonomy
- human review remains important for high-risk or high-ambiguity changes
- large-scale empirical evaluation is still pending

These limitations do not weaken the project thesis. Rather, they define the next research and engineering steps.

## 12. Future Work

The most important future directions are:

### 12.1 Project Contract Expansion

Extend the architecture profile into a broader `project_contract` containing:

- `brand_kit`
- `design_system`
- `system_architecture`
- `backend_contract`
- `infra_contract`
- `delivery_contract`

### 12.2 Stronger Validation

Add first-class semantic validators such as:

- design-token checks
- screenshot or preview review
- API contract validation
- migration safety checks
- environment-aware infra verification

### 12.3 Recovery Intelligence

Expand recovery policy into a more explicit fault-classification engine that can distinguish:

- parser failures
- policy failures
- validation failures
- environment failures
- architecture-boundary violations

### 12.4 Multi-Agent Execution Maturity

Continue moving toward explicitly separated agent roles:

- planner
- explorer
- implementer
- critic
- verifier
- recovery agent
- narrator

### 12.5 Measured Human Trust

Study how run visibility, approval gates, and recovery explanations affect operator trust and willingness to delegate more software work to the platform.

## 13. Conclusion

The Agentic SDLC Platform demonstrates that reliable AI-assisted software engineering requires much more than strong language models. It requires a runtime with explicit boundaries, structured context, architectural awareness, validation obligations, review semantics, and reusable memory.

The project’s significance lies in shifting the conversation from:

- “How do we generate better code?”

to:

- “How do we build a trustworthy system that can own parts of software delivery responsibly?”

This platform answers that question with a concrete design: a document-first, architecture-aware, contract-driven execution environment for AI-assisted SDLC work. The current implementation already establishes strong foundations in orchestration, execution control, architecture profiling, memory retrieval, and runtime safety. Its next evolution is clear: convert deeper product, design, system, and infrastructure knowledge into first-class project contracts that can shape planning, mutation, validation, and review with the same rigor that the runtime already applies to file scope and execution state.

In that sense, the system is not merely an AI coding assistant. It is an early operating model for **autonomous but governable software delivery**.

## 14. Suggested References Section

For academic submission, the following reference categories should be added in your preferred citation style:

- literature on AI-assisted software engineering
- research on human-in-the-loop autonomy
- work on software traceability and provenance
- papers on program synthesis and code repair
- literature on runtime verification and safe autonomy
- industry material on platform engineering, DevOps, and software delivery governance

## 15. Appendix: Suggested Figures for a Final Submitted Thesis

If you want to convert this document into a final academic thesis, add these diagrams:

1. Overall platform architecture diagram  
2. Run lifecycle and work-item state machine  
3. Execution contract model  
4. Architecture profile derivation pipeline  
5. Context-pack retrieval flow  
6. AI routing and model-tier policy flow  
7. Review and validation workflow  
8. Recovery and blocked-run handling flow  
9. Knowledge publication and memory reuse pipeline  
10. Future-state project contract with brand, design, backend, and infra layers
