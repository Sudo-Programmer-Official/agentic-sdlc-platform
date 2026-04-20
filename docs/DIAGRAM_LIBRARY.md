# Diagram Library

## Purpose

This document is a reusable diagram pack for the **Agentic SDLC Platform**.

It is designed so the same core system can be explained in different contexts:

- thesis and academic writing
- research papers
- architecture and technical documentation
- investor and business presentations
- sales and design-partner conversations
- product demos

All diagrams are written in **Mermaid** so they can be:

- rendered directly in GitHub-compatible markdown
- copied into Mermaid Live
- redrawn in draw.io, Figma, Lucidchart, or PowerPoint
- adapted for papers and slides

## Recommended Usage by Audience

### Business and investor material

Use these first:

- Diagram 1: System Context
- Diagram 2: Trust Loop and Product Wedge
- Diagram 3: Governed SDLC Flow
- Diagram 9: Mission Control Surface Model
- Diagram 13: Business Value Chain

### Academic thesis or research paper

Use these first:

- Diagram 1: System Context
- Diagram 4: Runtime Component Architecture
- Diagram 5: Execution Graph and Stage Lanes
- Diagram 6: Run Execution Sequence
- Diagram 7: Execution Contract Assembly
- Diagram 10: Failure and Recovery State Model
- Diagram 11: Conceptual Data Model
- Diagram 12: Research Evaluation Framework

### Technical architecture docs

Use these first:

- Diagram 4: Runtime Component Architecture
- Diagram 5: Execution Graph and Stage Lanes
- Diagram 6: Run Execution Sequence
- Diagram 7: Execution Contract Assembly
- Diagram 8: Architecture Profile and Knowledge Loop
- Diagram 10: Failure and Recovery State Model
- Diagram 11: Conceptual Data Model

## Diagram 1: System Context

Best for:

- thesis introduction
- product overview
- architecture summary
- investor deck

```mermaid
flowchart LR
    User[Operator / Founder / Engineer] --> Web[Mission Control UI\napps/web]
    Web <--> API[Control Plane API\napps/api]

    API --> Runtime[Runtime Core\nscheduler + orchestrator + executors]
    Runtime --> Contract[Execution Contract]
    Runtime --> Profile[Architecture Profile]
    Runtime --> Memory[Engineering Memory]
    Runtime --> Workspace[Isolated Run Workspace]
    Workspace --> Repo[(Repository and Branch)]
    Runtime --> Models[AI Executors and Models]
    Runtime --> Store[(Runs / Work Items /\nEvents / Artifacts / Summaries)]
    API --> Store
```

## Diagram 2: Trust Loop and Product Wedge

Best for:

- startup pitch
- website
- customer conversation
- problem framing

```mermaid
flowchart LR
    Goal[User Goal] --> Plan[Visible Plan]
    Plan --> Scope[Bounded Scope]
    Scope --> Execute[Controlled Execution]
    Execute --> Validate[Validation]
    Validate --> Review[Review and Approval]
    Review --> Learn[Memory and Context Reuse]
    Learn --> Goal

    Operator[Mission Control] -. visibility and steering .-> Plan
    Operator -. visibility and steering .-> Execute
    Operator -. visibility and steering .-> Validate
    Operator -. visibility and steering .-> Review
```

## Diagram 3: Governed SDLC Flow

Best for:

- academic explanation
- product deck
- workflow overview

```mermaid
flowchart LR
    Intake[Intake] --> Requirements[Requirements]
    Requirements --> Design[Design]
    Design --> Plan[Plan]
    Plan --> Implement[Implement]
    Implement --> Validate[Validate]
    Validate --> Review[Review]
    Review --> Approve[Approve]
    Approve --> PR[Create PR]
    PR --> Deploy[Deploy]

    Requirements -. source of truth .-> Docs1[(PRD / Stories / Acceptance)]
    Design -. source of truth .-> Docs2[(Architecture / ADR / Contracts)]
    Plan -. source of truth .-> Docs3[(Plan Snapshot / Task Graph)]
    Validate -. evidence .-> Docs4[(Tests / Build / Reports)]
    Review -. evidence .-> Docs5[(Diff / Review Notes / Artifacts)]

    Review -->|changes requested| Plan
    Validate -->|failure| Implement
```

## Diagram 4: Runtime Component Architecture

Best for:

- thesis chapter
- architecture doc
- technical appendix

```mermaid
flowchart TB
    subgraph Experience
        Web[apps/web\nMission Control]
    end

    subgraph Control_Plane
        API[apps/api\nFastAPI API]
        Scheduler[scheduler_service.py]
        Orch[orchestrator.py]
        Graph[execution_graph_spec.py]
    end

    subgraph Policy_and_Context
        AI[ai_policy.py]
        Contract[execution_contract.py]
        Profile[architecture_profile_service.py]
        Knowledge[knowledge_service.py]
    end

    subgraph Execution
        Workspace[workspace_supervisor.py]
        Codex[codex_executor.py]
        Test[test_executor.py]
        RepoTools[repo_tools.py]
    end

    subgraph Persistence
        DB[(Runs / Work Items /\nEvents / Artifacts /\nArchitecture / Knowledge)]
        Repo[(Workspace / Git Repository)]
    end

    Web <--> API
    API --> Scheduler
    Scheduler --> Orch
    Orch --> Graph
    Orch --> AI
    Orch --> Contract
    Orch --> Profile
    Orch --> Knowledge
    Orch --> Workspace
    Workspace --> Repo
    Orch --> Codex
    Orch --> Test
    Codex --> RepoTools
    Test --> RepoTools
    API --> DB
    Orch --> DB
    Profile --> DB
    Knowledge --> DB
```

## Diagram 5: Execution Graph and Stage Lanes

Best for:

- runtime explanation
- paper figure
- operator training

```mermaid
flowchart LR
    subgraph Planning
        PLAN[PLAN]
        VERIFY[PATCH_VERIFY]
        PLAN --> VERIFY
    end

    subgraph Mutating
        PATCH[APPLY_PATCH\nsingle mutating lane]
    end

    subgraph Verification
        LINT[RUN_LINT]
        TESTS[RUN_UNIT_TESTS]
        BUILD_FE[BUILD_FRONTEND]
        BUILD_BE[BUILD_BACKEND]
        VALIDATE[VALIDATE_RESULTS]
    end

    subgraph Provisioning
        PREVIEW_FE[CREATE_FRONTEND_PREVIEW]
        PREVIEW_BE[CREATE_BACKEND_PREVIEW]
        SMOKE[SMOKE_TEST_PREVIEW]
    end

    subgraph Governance
        APPROVAL[APPROVAL]
        PR[CREATE_PR]
    end

    VERIFY --> PATCH
    PATCH --> LINT
    PATCH --> TESTS
    PATCH --> BUILD_FE
    PATCH --> BUILD_BE

    LINT --> VALIDATE
    TESTS --> VALIDATE
    BUILD_FE --> VALIDATE
    BUILD_BE --> VALIDATE

    VALIDATE --> PREVIEW_FE
    VALIDATE --> PREVIEW_BE
    PREVIEW_FE --> SMOKE
    PREVIEW_BE --> SMOKE

    VALIDATE --> APPROVAL
    SMOKE --> APPROVAL
    APPROVAL --> PR
```

## Diagram 6: Run Execution Sequence

Best for:

- thesis methodology
- runtime walkthrough
- live demo narration

```mermaid
sequenceDiagram
    actor User as Operator
    participant Web as Mission Control
    participant API as FastAPI API
    participant Orch as Run Orchestrator
    participant WS as Workspace Supervisor
    participant DAG as DAG Generator
    participant Policy as Policy and Contract Layer
    participant Exec as Executor
    participant Repo as Workspace and Repo
    participant Store as Events and Artifacts

    User->>Web: Start run or run selected task
    Web->>API: POST /projects/{id}/runs
    API->>Orch: bootstrap(run_id)
    Orch->>WS: ensure_run_workspace()
    WS-->>Orch: workspace path and status
    Orch->>DAG: generate_template_dag()
    DAG-->>Orch: work items and edges
    Orch->>Policy: sync execution contract and context
    Policy-->>Orch: scope, budgets, commands, validation

    loop for each runnable work item
        Orch->>Exec: execute(work_item, run_context)
        Exec->>Repo: read, patch, run commands
        Repo-->>Exec: files, diffs, command output
        Exec-->>Orch: result, artifacts, validation state
        Orch->>Store: record event and persist artifacts
    end

    Orch-->>API: run summary and status
    API-->>Web: status, artifacts, current step
    Web-->>User: Mission Control update
```

## Diagram 7: Execution Contract Assembly

Best for:

- core research figure
- thesis contribution chapter
- technical design review

```mermaid
flowchart TD
    Summary[Run Summary and Task Scope] --> Contract[Execution Contract]
    Profile[Architecture Profile] --> Contract
    WorkItems[Planned Work Items] --> Contract
    Settings[Platform Settings] --> Contract
    Budget[Edit Budget and Token Policy] --> Contract
    State[Validation and Retry State] --> Contract

    Contract --> Scope[Allowed Files and Scope Mode]
    Contract --> Paths[Protected Paths and Safe Paths]
    Contract --> Commands[Allowed Command Prefixes]
    Contract --> Validation[Validation Recipes and Validation State]
    Contract --> Retry[Retry State and Recovery Guardrails]
    Contract --> Ledger[Budget Ledger and Model Tier Cap]
    Contract --> Context[Architecture Summary and Assumptions]

    Scope --> RuntimeUse[Executors and Workspace Tools]
    Paths --> RuntimeUse
    Commands --> RuntimeUse
    Validation --> RuntimeUse
    Retry --> OrchUse[Orchestrator and Recovery Policy]
    Ledger --> PolicyUse[AI Policy and Model Routing]
```

## Diagram 8: Architecture Profile and Knowledge Loop

Best for:

- research narrative
- technical docs
- future-work explanation

```mermaid
flowchart LR
    RepoMap[Repository Map and File Inventory] --> ProfileSvc[Architecture Profile Service]
    ProfileSvc --> Profile[Packages / Safe Zones /\nProtected Zones / Commands /\nValidation Recipes]

    Runs[Approved Runs / Review Output / Artifacts] --> KnowledgeSvc[Knowledge Service]
    KnowledgeSvc --> Memory[Architecture Notes / Module Docs /\nRunbooks / API Notes / DB Notes]

    Profile --> ContextPacks[AI Policy Context Packs]
    Memory --> ContextPacks
    ContextPacks --> FutureRuns[Future Runs]
    FutureRuns --> Runs
```

## Diagram 9: Mission Control Surface Model

Best for:

- product documentation
- UI explanation
- operator demo

```mermaid
flowchart TB
    subgraph Runtime_Signals
        Status[Run Status]
        Step[Current Step and Work Items]
        Cmds[Recent Commands and Output]
        Validate[Validation State]
        Artifacts[Artifacts and Diffs]
        Workspace[Workspace and Git State]
        Approvals[Approval State]
        Contract[Contract Summary]
    end

    subgraph Mission_Control
        Overview[Run Overview]
        PlanPanel[Run Plan]
        Reflections[Reflections]
        Context[Working Context]
        Tasks[Agent Tasks]
        Failures[Failed Commands]
        Timeline[Timeline and Events]
    end

    subgraph Operator_Actions
        Inspect[Inspect Diffs and Logs]
        Retry[Retry Step]
        Narrow[Narrow Scope]
        Pause[Pause or Resume]
        Approve[Approve or Reject]
    end

    Runtime_Signals --> Mission_Control
    Mission_Control --> Operator_Actions
```

## Diagram 10: Failure and Recovery State Model

Best for:

- research paper
- runtime appendix
- recovery and reliability section

```mermaid
stateDiagram-v2
    [*] --> QUEUED
    QUEUED --> RUNNING: workspace ready
    QUEUED --> FAILED: workspace error

    RUNNING --> BOOTSTRAP: bootstrap and DAG creation
    BOOTSTRAP --> EXECUTING: work items ready
    BOOTSTRAP --> FAILED: scope or bootstrap error

    EXECUTING --> EXECUTING: work item done
    EXECUTING --> RECOVERY: blocking work item failed
    RECOVERY --> EXECUTING: bounded retry or fix path
    RECOVERY --> FAILED: retries exhausted

    EXECUTING --> REVIEW_WAIT: validation passed and approval required
    REVIEW_WAIT --> COMPLETED: approved and published
    REVIEW_WAIT --> CANCELED: rejected or aborted

    FAILED --> [*]
    CANCELED --> [*]
    COMPLETED --> [*]
```

## Diagram 11: Conceptual Data Model

Best for:

- thesis chapter
- system design appendix
- architecture documentation

```mermaid
erDiagram
    PROJECT ||--o{ RUN : has
    RUN ||--o{ WORK_ITEM : contains
    RUN ||--o{ RUN_EVENT : emits
    RUN ||--o{ ARTIFACT : produces
    WORK_ITEM ||--o{ ARTIFACT : yields
    PROJECT ||--o| ARCHITECTURE_PROFILE : stores
    PROJECT ||--o{ KNOWLEDGE_ARTIFACT : accumulates
    RUN ||--o{ APPROVAL : requests

    PROJECT {
        uuid id
        string name
        string status
    }

    RUN {
        uuid id
        string status
        string executor
        string workspace_status
    }

    WORK_ITEM {
        uuid id
        string type
        string status
        string review_state
    }

    RUN_EVENT {
        uuid id
        string event_type
        datetime created_at
    }

    ARTIFACT {
        uuid id
        string artifact_type
        string uri
    }

    ARCHITECTURE_PROFILE {
        uuid id
        string summary
    }

    KNOWLEDGE_ARTIFACT {
        uuid id
        string artifact_type
        string publication_state
    }

    APPROVAL {
        uuid id
        string status
        string target_type
    }
```

## Diagram 12: Research Evaluation Framework

Best for:

- thesis proposal
- paper methodology section
- experiment design

```mermaid
flowchart LR
    Tasks[Common Task Set] --> A[Unconstrained Prompt Execution]
    Tasks --> B[Scoped Prompt Execution]
    Tasks --> C[Contract-Driven Runtime]

    A --> Metrics[Evaluation Metrics]
    B --> Metrics
    C --> Metrics

    Metrics --> M1[Out-of-Scope Edit Rate]
    Metrics --> M2[Validation Pass Rate]
    Metrics --> M3[Review Rejection Rate]
    Metrics --> M4[Recovery Success Rate]
    Metrics --> M5[Cost per Successful Run]
    Metrics --> M6[Operator Trust and Explainability]
```

## Diagram 13: Business Value Chain

Best for:

- investor deck
- website
- sales deck
- accelerator application

```mermaid
flowchart LR
    Pain[AI Coding Pain\nhidden changes, drift,\nweak validation, low trust] --> Product[Governed Runtime\nfor AI Software Delivery]
    Product --> Controls[Execution Contracts\nArchitecture Awareness\nReview and Validation\nMission Control Visibility]
    Controls --> Outcomes[Faster Delivery\nLess Rework\nHigher Trust\nSafer Adoption]
    Outcomes --> Buyers[Startups\nEngineering Teams\nAgencies\nPlatform Teams]
```

## Suggested Reuse Patterns

### Minimal startup pitch set

Use:

- Diagram 1
- Diagram 2
- Diagram 13

### Product demo set

Use:

- Diagram 3
- Diagram 6
- Diagram 9

### Thesis proposal set

Use:

- Diagram 1
- Diagram 4
- Diagram 7
- Diagram 12

### Full technical appendix set

Use:

- Diagram 4
- Diagram 5
- Diagram 6
- Diagram 7
- Diagram 8
- Diagram 10
- Diagram 11

## Final Note

These diagrams are intentionally written at multiple abstraction levels:

- product level
- workflow level
- runtime level
- data level
- research level
- business level

That is the right approach for this project because the platform needs to be explainable both as:

- a software engineering system
- a research contribution
- a commercial product
