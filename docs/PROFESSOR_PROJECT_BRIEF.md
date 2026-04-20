# Professor Project Brief

## Project Title

**Agentic SDLC Platform: A Contract-Driven, Architecture-Aware Runtime for AI-Assisted Software Delivery**

## Purpose of This Document

This brief is intended for sharing the project with a professor, research mentor, or academic collaborator. It explains:

- what the project is
- why it matters
- what has already been implemented
- what makes it research-worthy
- which thesis direction is currently the strongest
- what type of feedback or supervision would be valuable

The goal is to present the work as a serious systems and software-engineering project rather than as a generic AI coding demo.

## 1. Project Summary

The **Agentic SDLC Platform** is an architecture-aware software delivery runtime that treats AI-assisted engineering as a governed execution workflow rather than a sequence of isolated prompts.

Instead of simply asking a model to generate code, the system attempts to manage the entire software-delivery loop through:

- document-first planning
- structured work-item decomposition
- architecture-aware scope control
- bounded repository mutation
- validation-aware execution
- review-aware runtime stages
- execution visibility and auditability
- engineering memory for future runs

In simple terms, the project is trying to answer this question:

> How can we make AI-assisted software development reliable, visible, and safe enough to operate inside a real SDLC rather than just inside a chat session?

## 2. Motivation

Current AI software tools are impressive at code generation, but they are still weak at controlled delivery. In many real workflows, engineers still need to manually coordinate:

- requirements and design interpretation
- planning and task decomposition
- repository context gathering
- code generation
- validation and testing
- review and approval
- recovery after failure

Most existing tools do not give strong guarantees around:

- architectural boundaries
- change scope
- validation obligations
- review gates
- failure recovery
- persistent project memory

This project is motivated by the belief that the next meaningful step in AI-assisted software engineering is not just “better code generation,” but **better control over software execution**.

## 3. Central Idea

The central idea is to build a runtime where AI execution is governed by explicit operational structures such as:

- **execution contracts**
- **architecture profiles**
- **patch guards**
- **validation recipes**
- **model-routing policy**
- **review-aware work-item stages**
- **run-level observability**
- **memory-backed context retrieval**

The project therefore moves from:

- prompt-driven AI coding

to:

- contract-driven AI software delivery

## 4. System Overview

The repository is organized as a modular monolith:

- `apps/web`: Vue 3 + Vite operator interface
- `apps/api`: FastAPI orchestration and runtime backend
- `core`: shared SDLC and domain primitives
- `agent`: agent adapters, prompts, and tools
- `infra`: deployment scaffolding
- `docs`: specifications, architecture, roadmap, and research material

The system is designed around several major surfaces:

1. **Architecture Profile**  
   Stores project structure, package boundaries, commands, validation recipes, safe zones, and protected zones.

2. **Execution Contract**  
   Captures the bounded scope of a run, including allowed files, protected paths, validation expectations, command prefixes, budgets, and retry state.

3. **Mission Control / Run Console**  
   Exposes run progress, current step, failure surfaces, recent commands, artifacts, and review state.

4. **AI Policy Layer**  
   Routes work by role, risk, ambiguity, budget, model tier, and review requirement.

5. **Engineering Memory Layer**  
   Reuses reviewed knowledge through cached context packs and runtime guidance.

## 5. What Is Already Implemented

The project is not only conceptual. A meaningful prototype foundation has already been implemented.

### 5.1 Runtime and Orchestration

- run bootstrap and workspace preparation
- work-item DAG generation
- run plan snapshot persistence
- orchestrator-owned status transitions
- work-item execution through structured executor interfaces

### 5.2 Execution Control

- execution contracts with bounded file scope
- patch guard enforcement
- protected-zone and safe-zone awareness
- stage-specific mutation rules
- bounded retries and run budgets

### 5.3 Architecture and Context

- architecture profile bootstrap and derivation
- command coverage and validation recipes
- context-pack caching for:
  - repository summary
  - architecture summary
  - conventions summary
  - changed module map
  - file ownership hints

### 5.4 Review and Validation

- planning, implementation, testing, review, and integration stages
- review-aware runtime behavior
- validation state and retry state tracking
- parser failure handling and repair loops

### 5.5 Observability and Runtime Truth

- event logging
- run-level execution context
- artifact lineage
- failed-command visibility
- operator-facing Mission Control surfaces

## 6. What Makes This Different from Typical AI Coding Projects

The most important distinction is that this is **not just a code-generation assistant**.

Its novelty lies in the fact that it treats AI work as a governed runtime problem.

### Key differences from typical AI coding tools

- It is **architecture-aware**, not only prompt-aware.
- It is **contract-driven**, not only instruction-driven.
- It is **stage-aware**, separating planning, mutation, validation, and review.
- It is **review-aware**, not merely generation-oriented.
- It is **observable**, exposing run context and execution state.
- It is **memory-backed**, reusing reviewed project knowledge.
- It is **bounded**, using file scope, path constraints, and budgets.

This gives the project a stronger software-engineering identity than many AI coding demos that focus only on task completion.

## 7. Current Research Direction

Among several candidate directions, the strongest current research topic is:

### **Contract-Driven Autonomous Software Delivery: A Runtime Architecture for Safe, Architecture-Aware AI Software Execution**

This is the strongest direction because it aligns directly with the implementation already present in the repository:

- execution contracts
- architecture profiles
- bounded mutation rules
- validation-aware execution
- review-aware workflow separation
- recovery-aware behavior
- context and policy control

### Core research question

**How can execution contracts improve the safety, traceability, and reliability of autonomous AI-assisted software delivery compared with unconstrained prompt-driven execution?**

### Working hypothesis

If AI execution is constrained by explicit contracts that define:

- scope
- architecture boundaries
- validation obligations
- command restrictions
- review state
- retry and budget constraints

then the system should show:

- fewer out-of-scope edits
- stronger review-stage correctness
- better recovery after failure
- improved operator trust
- more stable software-delivery behavior

## 8. Why This Could Be a Strong Thesis or Publication Topic

This project has a strong academic angle because it sits at the intersection of:

- AI-assisted software engineering
- autonomous agent systems
- runtime governance
- software architecture
- engineering memory
- human-in-the-loop AI systems

Many current papers and tools focus on whether AI can write code or solve benchmark tasks. Fewer systems focus on:

- how AI work should be governed in real software delivery
- how architecture and scope should shape agent behavior
- how review, validation, and recovery should be made first-class
- how reviewed memory should guide future runs

That gap creates a meaningful opportunity for a systems-oriented research contribution.

## 9. Current Weak Spots and Open Research Problems

Although the system has a strong runtime foundation, several important areas are still incomplete and therefore open for deeper research.

### 9.1 Brand Kit and Design System Are Not Yet First-Class

The system does not yet model:

- visual identity
- design tokens
- typography systems
- component contracts
- UI consistency rules

This means frontend delivery is currently bounded by execution control, but not yet strongly governed by design knowledge.

### 9.2 Architecture Is More Repository-Aware Than System-Design-Aware

The current architecture profile is good at:

- package structure
- safe and protected zones
- command inference
- validation recipe inference

It is weaker at:

- explicit service contracts
- data ownership boundaries
- event-flow modeling
- deployment architecture constraints
- environment topology

### 9.3 Validation Is Stronger Syntactically Than Semantically

The runtime currently enforces scope and output correctness well, but richer semantic checks are still needed for:

- visual correctness
- API compatibility
- migration safety
- infrastructure rollout safety
- deeper architecture conformance

These weaknesses are important because they naturally define future thesis work and evaluation opportunities.

## 10. What I Would Like Feedback On

If shared with a professor, the most useful feedback would be around the following:

### Research framing

- Is the topic best framed as software engineering research, AI systems research, or a hybrid?
- Is the current primary topic sufficiently novel for thesis or publication work?

### Methodology

- What would be the right baseline systems for comparison?
- What evaluation design would make the results defensible?
- Which metrics would be most meaningful for a systems paper?

### Scope control

- Should the thesis focus on the full runtime, or narrow to one contribution such as execution contracts, architecture-aware execution, or engineering memory?

### Publication potential

- Would this be stronger as:
  - a thesis project
  - a capstone plus paper
  - a systems prototype paper
  - a software engineering evaluation study

## 11. Suggested Next Technical Milestones

The next milestones that would strengthen both the project and the research story are:

1. Formalize a broader `project_contract` that extends the architecture profile with:
   - brand kit
   - design system
   - backend contract
   - infrastructure contract
   - delivery contract

2. Introduce richer semantic validators such as:
   - design-token checks
   - visual review or screenshot comparison
   - API and schema contract checks
   - rollout and migration rules

3. Define a rigorous experimental protocol comparing:
   - unconstrained prompt execution
   - scoped prompt execution
   - contract-driven execution

4. Measure:
   - out-of-scope edit rate
   - validation pass rate
   - review rejection rate
   - recovery success rate
   - cost per successful run
   - operator trust and explainability

## 12. Suggested Summary to Say Verbally

If explaining the project briefly in conversation:

> I have been building an Agentic SDLC Platform that treats AI-assisted software engineering as a governed runtime rather than just prompt-based code generation. The system uses execution contracts, architecture profiles, patch guards, model routing, validation stages, review stages, and engineering memory to make AI software work more bounded, observable, and reliable. I think the strongest research angle is contract-driven autonomous software delivery, and I would really value your feedback on whether the framing and evaluation direction are strong enough for a thesis or paper.

## 13. Suggested Message for Sending to the Professor

You can adapt the following note when you send the document:

---

**Subject:** Project Brief and Research Direction for Feedback

Dear Professor,

I hope you are doing well. I wanted to share a project I have been working on that builds on my interest in AI-assisted software engineering and autonomous systems.

The project is called **Agentic SDLC Platform**. Its main idea is to move beyond prompt-based coding assistants and instead build a runtime for AI-assisted software delivery that is architecture-aware, bounded by execution contracts, validation-aware, review-aware, and observable through a run console.

I have attached a short project brief describing:

- the motivation and problem statement
- the system architecture
- what has already been implemented
- the most promising thesis direction I currently see

At the moment, I believe the strongest research topic is:

**Contract-Driven Autonomous Software Delivery: A Runtime Architecture for Safe, Architecture-Aware AI Software Execution**

I would be very grateful for your feedback on:

- whether the research framing is strong
- whether the topic looks thesis-worthy or publication-worthy
- what evaluation methodology or narrowing strategy you would recommend

Thank you for your time. I would really appreciate any guidance you may have.

Best regards,  
[Your Name]

---

## 14. Final Note

This project is strongest when presented not as “an AI tool that writes code,” but as:

**a governed runtime for autonomous software delivery**

That framing is more serious, more defensible academically, and more aligned with the actual engineering work already present in the repository.
