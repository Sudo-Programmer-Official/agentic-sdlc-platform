# AI Automation Console Pack

## Goal
Build an AI automation console showing workflows, execution logs, retries, and outcomes.

## Functional Requirements
- FR-001: Workflow catalog with trigger type.
- FR-002: Execution queue with in-progress/blocked/completed states.
- FR-003: Step-level logs with timestamps.
- FR-004: Retry failed step and resume workflow.
- FR-005: Policy panel for max retries/timeouts.
- FR-006: Notification area for run completion/failure.

## Quality Requirements
- QR-001: Real-time status updates for running workflows.
- QR-002: Strong visibility of blocked reason and recovery action.
- QR-003: Idempotent retry behavior for failed steps.
- QR-004: Operator can diagnose issue within 30 seconds from UI.

## Task Seeds
- Build queue + step log views.
- Implement retry/resume controls.
- Add policy editor and guardrails.
- Add tests for workflow state progression and recovery.
