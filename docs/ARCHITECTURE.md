# Architecture

## Overview
Modular monolith with clear boundaries across frontend, backend, core domain, and agent layer.

## Components
- FastAPI orchestrator
- Vue 3 frontend
- Core SDLC state machine and approvals
- Bedrock agent adapter stubs

## Run Lifecycle

```mermaid
stateDiagram-v2
    [*] --> PENDING : create_run()

    PENDING --> RUNNING : start_run()
    RUNNING --> PAUSED : pause_run()
    PAUSED --> RUNNING : resume_run()

    RUNNING --> COMPLETED : complete_run()
    RUNNING --> FAILED : fail_run()
    RUNNING --> CANCELED : cancel_run()

    COMPLETED --> [*]
    FAILED --> [*]
    CANCELED --> [*]

    note right of PENDING
        Run created for a specific
        project and SDLC stage
    end note

    note right of RUNNING
        Execution in progress
        (agents plug in here)
    end note

    note bottom of PAUSED
        Human or system can
        pause/resume execution
    end note
```

Each autonomous execution is modeled as a Run with a deterministic lifecycle. Runs are
explicitly created for a given project and SDLC stage and progress through well-defined
states (Pending, Running, Paused, Completed, Failed, or Canceled). All state transitions
are governed by the orchestrator and logged in the audit ledger, ensuring execution
remains controllable, auditable, and interruptible before agents are added.

## Change Intake & Continuous Evolution

ChangeRequests provide a lightweight, human-governed intake mechanism for ongoing work.
Each request captures the source, affected area, severity, and suggested SDLC stage.
When a change is accepted, the orchestrator routes the project back to the suggested
stage and marks downstream stages as stale. This reuses the existing staleness mechanism
so that no agent runs on outdated specifications. ChangeRequests never auto-run agents
or advance stages; they make the re-planning path explicit and auditable.

## Observability & Metrics

Metrics are derived directly from existing state (runs, tasks, change requests, and the
audit ledger). This keeps observability read-only and avoids new background jobs or
external dependencies. The API exposes lightweight JSON summaries per project and run,
including counts of active runs, open changes, stale stages, task status totals, and
execution duration. The ledger remains the source of truth for audits, while metrics
provide an operational view for demos and future dashboards.
