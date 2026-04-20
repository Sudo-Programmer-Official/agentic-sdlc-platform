# Formal Thesis Proposal

## Title

**Contract-Driven Autonomous Software Delivery: A Runtime Architecture for Safe, Architecture-Aware AI Software Execution**

## 1. Abstract

Recent progress in large language models has significantly improved code generation, bug fixing, and developer assistance. However, most AI-assisted software engineering workflows remain prompt-centric and operationally weak. They typically lack explicit architectural boundaries, bounded mutation control, validation obligations, review separation, and persistent project memory. As a result, they often perform well at local generation tasks while remaining fragile at actual software delivery.

This thesis proposes a **contract-driven runtime for autonomous software delivery**. The system under study, called the **Agentic SDLC Platform**, models AI-assisted software work as a governed execution workflow rather than a sequence of isolated model interactions. It introduces execution contracts, architecture profiles, patch guards, validation recipes, model-routing policy, review-aware work-item stages, and engineering-memory context packs to constrain and guide autonomous execution. The central hypothesis is that contract-driven execution can improve safety, traceability, recovery quality, and operator trust compared with unconstrained prompt-based execution.

The proposed work will implement and evaluate a prototype system that supports document-first planning, structured work-item execution, bounded repository mutation, validation-aware completion, and architecture-aware retrieval. The thesis will compare contract-driven execution against weaker baselines using measures such as out-of-scope edit rate, review rejection rate, validation success rate, recovery behavior, and cost per successful run. The expected contribution is a systems-oriented framework for governable AI-assisted software delivery.

## 2. Background and Motivation

AI-assisted software development has rapidly progressed from code completion to multi-step agent workflows. Despite this progress, many systems remain weak in practical software-engineering discipline. They often assume that a model can safely plan, modify, test, and judge its own work with limited structure. In real repositories, this assumption breaks down because software delivery depends on:

- architectural boundaries
- validation obligations
- ownership constraints
- deployment and environment assumptions
- review and approval protocols
- failure recovery discipline

Without these controls, AI software agents may:

- edit unrelated files
- generate malformed or unreviewable patches
- pass through incomplete validation
- collapse planning, execution, and critique into one unstable loop
- repeat the same failure patterns across runs

This motivates a different research direction: rather than optimizing only model capability, build a runtime that explicitly governs what AI execution is allowed to do and what proof it must produce before being trusted.

## 3. Problem Statement

Existing AI software engineering workflows under-model the control structures required for reliable software delivery. In particular, they often lack:

- explicit execution contracts
- architecture-aware scope control
- stage-aware separation between planning, mutation, validation, and review
- recovery-safe policies for parser, patch, validation, and review failures
- persistent project memory that can guide future runs

This thesis addresses the following problem:

**How can a contract-driven runtime improve the safety, traceability, and reliability of autonomous AI-assisted software delivery in comparison with less constrained prompt-based workflows?**

## 4. Research Questions

The proposed thesis will focus on the following research questions:

### Primary Research Question

**RQ1. How does contract-driven execution affect the safety and reliability of autonomous AI-assisted software delivery?**

### Secondary Research Questions

**RQ2. Can architecture-aware scope control reduce unintended repository mutations in multi-module projects?**

**RQ3. Does stage-aware separation of planning, implementation, validation, and review improve overall run quality?**

**RQ4. Can execution contracts improve recovery quality after structured-output, patch-application, and review-stage failures?**

**RQ5. How does contract-driven execution affect operator trust and willingness to delegate work?**

## 5. Hypothesis

The main hypothesis is:

> If AI-assisted software execution is constrained by an explicit execution contract containing file scope, architecture boundaries, validation obligations, command restrictions, review state, and retry budget, then autonomous software runs will be safer, more traceable, and more recoverable than unconstrained prompt-based execution.

This hypothesis implies measurable expectations:

- lower out-of-scope edit rate
- lower invalid patch rate
- lower review rejection rate
- better recovery after structured failures
- more consistent validation-backed completion
- better operator understanding of what the system did and why

## 6. Proposed System

The thesis will be grounded in a working prototype called the **Agentic SDLC Platform**. The system is implemented as a modular monolith with:

- FastAPI backend
- Vue 3 frontend
- shared core SDLC modules
- agent and tool integration layers

The system includes the following technical foundations:

### 6.1 Execution Contract

A run-scoped contract that captures:

- goal
- target and allowed files
- related files
- protected and safe paths
- validation steps and validation recipes
- build, test, and lint commands
- allowed command prefixes
- file budgets
- risk level
- retry state and validation state
- token and cost budget

### 6.2 Architecture Profile

A persistent project model that derives:

- repository layout
- package slices
- command coverage
- validation recipes
- safe refactor zones
- do-not-touch zones
- release-flow assumptions

### 6.3 Patch Guard and Stage Guards

A runtime guard layer that checks:

- touched files
- scope violations
- protected-zone violations
- stage-specific mutation legality

### 6.4 AI Policy Layer

A routing layer that decides:

- role
- task type
- ambiguity level
- risk level
- selected model tier
- max model tier
- retries
- context cap
- budget cap
- human review requirements

### 6.5 Engineering Memory

A retrieval layer that provides scoped context packs containing:

- repository summary
- architecture summary
- conventions
- changed module map
- ownership hints

## 7. Methodology

The research will follow a **design, implementation, and evaluation** methodology.

### 7.1 System Design

The first part of the work formalizes the architecture of a contract-driven runtime for AI software execution.

### 7.2 Prototype Implementation

The second part implements the runtime in the Agentic SDLC Platform and ensures the following are operational:

- bounded planning and execution
- architecture-aware run context
- review-aware stage handling
- policy-driven model routing
- run and work-item observability
- failure and retry accounting

### 7.3 Comparative Evaluation

The third part evaluates the system against simpler baselines.

## 8. Experimental Design

### 8.1 Compared Conditions

The evaluation will compare three execution settings:

1. **Unconstrained Prompt Execution**  
   The model is given the task and local context with minimal structural governance.

2. **Scoped Prompt Execution**  
   The model is given explicit target files and limited context, but without a full contract-driven runtime.

3. **Contract-Driven Execution**  
   The model operates inside the full execution contract with architecture profile, patch guard, validation state, routing policy, and stage-aware controls.

### 8.2 Task Categories

Evaluation tasks should be selected across multiple software-delivery classes such as:

- small frontend feature changes
- bounded backend feature changes
- test-writing tasks
- review and validation tasks
- failure recovery scenarios
- architecture-sensitive changes

### 8.3 Metrics

The proposed evaluation metrics are:

- task success rate
- out-of-scope edit rate
- patch guard violation rate
- validation pass rate
- review rejection rate
- retries per successful run
- recovery success rate
- average token and cost usage
- operator-rated explanation or trust score

### 8.4 Qualitative Analysis

In addition to quantitative results, the thesis should analyze:

- common failure classes
- types of scope violations prevented
- cases where architecture-aware context materially changed behavior
- cases where contracts were too strict or not strict enough

## 9. Expected Contributions

The expected contributions of the thesis are:

1. A runtime architecture for contract-driven autonomous software delivery.
2. A concrete implementation of execution contracts for AI-assisted software runs.
3. An architecture-aware scope-control model using safe and protected zones.
4. A stage-aware execution framework separating planning, mutation, validation, and review.
5. An evaluation of whether contract-driven execution improves software-delivery robustness.

## 10. Significance

This work is significant because it shifts the research focus from:

- whether an AI system can generate code

to:

- whether an AI system can participate in software delivery responsibly

That distinction matters in both academia and industry. From an academic standpoint, it creates a systems-oriented contribution at the intersection of AI, software engineering, and runtime governance. From an industry standpoint, it addresses the growing need for AI tools that can be trusted inside real engineering workflows.

## 11. Limitations

The thesis will also explicitly acknowledge limitations, including:

- current prototype scale
- limited semantic validation beyond command-backed checks
- incomplete first-class modeling of brand, design system, and infra contracts
- dependence on selected task classes rather than all software tasks
- continued need for human review in high-risk conditions

These limitations are acceptable because the goal is not full autonomy, but a stronger architecture for governable autonomy.

## 12. Proposed Timeline

### Phase 1: Research Framing and Scope Lock

- finalize thesis topic
- define research questions
- define baseline conditions and evaluation metrics

### Phase 2: Prototype Stabilization

- refine runtime behavior
- strengthen architecture profile and execution contract integration
- stabilize recovery and review logic

### Phase 3: Experiment Setup

- define benchmark tasks
- capture baseline results
- instrument evaluation metrics

### Phase 4: Evaluation and Analysis

- run comparative experiments
- collect quantitative and qualitative findings
- analyze failure classes and recovery behavior

### Phase 5: Writing and Defense Preparation

- write thesis chapters
- prepare diagrams and results
- refine the problem statement and contributions

## 13. Resources Needed

The proposed work mainly requires:

- access to the repository and local development environment
- compute access for AI-backed runs
- representative evaluation tasks
- supervision on research framing and methodology

No unusually large infrastructure is required for the initial thesis scope.

## 14. Conclusion

This thesis proposes that the next important step in AI-assisted software engineering is not only stronger generation, but stronger runtime governance. The Agentic SDLC Platform provides a concrete foundation for studying that claim. By combining execution contracts, architecture-aware scope control, validation and review stages, policy-based routing, and engineering memory, the system offers a practical framework for safer and more trustworthy autonomous software delivery.

The proposed work is therefore positioned as a systems-oriented contribution to the emerging field of agentic software engineering.

## 15. Placeholder Reference Categories

The final written thesis should include literature from:

- AI-assisted software engineering
- autonomous software agents
- repository-level software repair
- human-in-the-loop autonomy
- runtime verification and safe execution
- software traceability and engineering governance
