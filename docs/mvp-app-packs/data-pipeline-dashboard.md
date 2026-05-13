# Data Pipeline Dashboard Pack

## Goal
Build a dashboard for pipeline health, run statuses, failures, and quick operator actions.

## Functional Requirements
- FR-001: Pipeline list with status badges.
- FR-002: Run timeline with start/end/duration.
- FR-003: Failure panel with error summary.
- FR-004: Retry/pause/resume action controls.
- FR-005: Metrics cards (success rate, avg duration, queue depth).
- FR-006: Filters by pipeline/date/status.

## Quality Requirements
- QR-001: Data refresh without full page reload.
- QR-002: Accessible tables and badges.
- QR-003: Clear empty/loading/error states.
- QR-004: Visual consistency on desktop + tablet.

## Task Seeds
- Build dashboard layout and metrics cards.
- Implement run table/timeline components.
- Add operator actions with safe confirmations.
- Add tests for state transitions and filters.
