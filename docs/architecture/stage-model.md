# Stage Model — Software Factory Runtime

## Overview

The Stage Model defines the authoritative lifecycle flow of a project within the Software Factory.

Stages are deterministic and enforced by the backend. Agents operate within stages but cannot modify stage state directly.

The stage system prevents invalid execution states and ensures structural integrity.

---

## Stage Flow

INTAKE → PLAN → RUN → EVALUATE

No skipping allowed.

---

## Stage Definitions

### 1. INTAKE

**Purpose**
Define and refine requirements.

**Allowed Actions**
- Create / update documents (PRDs)
- Refine scope
- Clarify constraints

**Agent Role**
- Assist with requirement drafting and refinement.

**Exit Condition**
At least one non-deleted document exists.

---

### 2. PLAN

**Purpose**
Convert requirements into executable task graph.

**Allowed Actions**
- Generate tasks from document
- Refine task structure
- Validate dependency graph

**Agent Role**
- Generate task graph
- Suggest structural improvements

**Exit Condition**
At least one non-deleted task exists.

---

### 3. RUN

**Purpose**
Execute tasks via orchestration runtime.

**Allowed Actions**
- Start run
- Execute tasks
- Log results
- Generate artifacts

**Agent Role**
- Perform task execution
- Produce code/tests/docs
- Log execution outputs

**Exit Condition**
At least one completed run exists.

---

### 4. EVALUATE

**Purpose**
Assess structural integrity and governance health.

**Allowed Actions**
- Compute lifecycle score
- Review traceability
- Review risk indicators
- Decide iteration path

**Agent Role**
- Suggest remediation
- Analyze risk
- Propose improvements

---

## Transition Rules

Transitions are strictly enforced.

Allowed transitions:

| From      | To        |
|-----------|----------|
| INTAKE    | PLAN     |
| PLAN      | RUN      |
| RUN       | EVALUATE |
| EVALUATE  | (none)   |

---

## Guard Conditions

### INTAKE → PLAN
Requires at least one document.

### PLAN → RUN
Requires at least one task.

### RUN → EVALUATE
Requires:
- At least one completed run
- No active run in progress

---

## Backend Enforcement

Transition endpoint:

PATCH /api/v1/store/projects/{project_id}/stage

Payload:

{
  "to_stage": "PLAN"
}

Failure cases return HTTP 409 with descriptive messaging.

Example:

{
  "error": "stage_transition_blocked",
  "reason": "At least one document is required before planning."
}

---

## API Contract (Recommended Extension)

Project response should include:

{
  "current_stage": "PLAN",
  "allowed_transitions": ["RUN"]
}

This allows the frontend to render stage controls without guessing logic.

---

## Design Principle

Stages are:
- Deterministic
- Backend-controlled
- Immutable except through guarded transition endpoint

Agents cannot modify stage directly.

---

## Future Extensions

Possible additions:
- Regression to previous stage (manual override)
- Stage transition audit logging
- Automated transition suggestions (never automatic execution)
- Stage time-in-state metrics

---

## Summary

The Stage Model ensures:
- No execution without planning
- No planning without requirements
- No evaluation without execution
- Clear mental model for users
- Structural integrity for governance

This is the backbone of the Software Factory runtime.