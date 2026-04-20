# One-Page Project Summary

## Project Title

**Agentic SDLC Platform: A Contract-Driven, Architecture-Aware Runtime for AI-Assisted Software Delivery**

## Short Summary

The Agentic SDLC Platform is a research-oriented software system that treats AI-assisted engineering as a governed runtime rather than a sequence of disconnected prompts. The project combines architecture-aware planning, bounded code execution, review-aware stages, validation contracts, model-routing policy, engineering memory, and operator-visible run control in a unified workflow.

## Problem

Current AI coding tools are strong at generating code, but weak at safe software delivery. In real projects, engineers still have to manually manage:

- repository context
- architecture boundaries
- scope control
- testing and validation
- review and approval
- failure recovery
- traceability across runs

This limits trust and makes autonomous software execution fragile.

## Core Idea

Instead of letting an AI agent work through unconstrained prompts, the system uses explicit runtime structures such as:

- execution contracts
- architecture profiles
- patch guards
- validation recipes
- review-aware stages
- model-routing and budget policy
- engineering memory and context packs

This makes AI-assisted work more bounded, observable, and operationally defensible.

## What Has Already Been Built

The current repository already includes:

- FastAPI-based orchestration backend
- Vue-based Mission Control frontend
- run bootstrap and isolated workspaces
- work-item DAG execution
- execution contracts with allowed files and protected zones
- patch-guard enforcement
- architecture-profile bootstrap and runtime projection
- model-tier routing and cost control
- review-aware and validation-aware stages
- engineering-memory retrieval through context packs

## Research Direction

The strongest current thesis direction is:

**Contract-Driven Autonomous Software Delivery: A Runtime Architecture for Safe, Architecture-Aware AI Software Execution**

### Core research question

**How can execution contracts improve the safety, traceability, and reliability of autonomous AI-assisted software delivery compared with unconstrained prompt-driven execution?**

## Why This Topic Matters

This work is positioned at the intersection of:

- AI-assisted software engineering
- autonomous agents
- runtime governance
- software architecture
- human-in-the-loop control
- engineering memory

It is attractive as a thesis or publication topic because it focuses on **governable AI software execution**, which is still underexplored compared with raw code-generation benchmarks.

## What I Would Like Feedback On

I would especially value feedback on:

- whether the problem framing is strong enough for thesis or paper work
- whether the proposed topic is appropriately scoped
- what evaluation methodology would be most convincing
- whether the contribution should be framed as a software-engineering systems paper, AI systems paper, or hybrid thesis

## Supporting Documents

- [PROFESSOR_PROJECT_BRIEF.md](./PROFESSOR_PROJECT_BRIEF.md)
- [THESIS_PROPOSAL_FORMAL.md](./THESIS_PROPOSAL_FORMAL.md)
- [POTENTIAL_RESEARCH_TOPICS.md](./POTENTIAL_RESEARCH_TOPICS.md)
- [THESIS_PROJECT_DOCUMENT.md](./THESIS_PROJECT_DOCUMENT.md)
