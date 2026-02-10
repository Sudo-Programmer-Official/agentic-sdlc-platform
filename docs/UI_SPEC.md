# UI Component Tree & API Contracts

## Component Tree (Planned)
- AppShell
- TopBar
- ProjectNameBadge
- StageBadge
- RunStatusBadge
- EmergencyStopButton
- SidebarNav
- OverviewPage
- SummaryCards
- AgentActivityPanel
- TaskTable
- AuditTimeline
- ExecutionTimeline
- ChangeRequestPanel
- MetricsPanel
- AdvancedModeToggle
- RequirementsPage
- RequirementsTabs
- DocumentEditor
- ApprovalActions
- PlanPage
- TaskGraph
- ExecutionPage
- AgentStatusPanel
- TaskStream
- ChangesPage
- ChangeList
- ChangeDecisionActions
- MetricsPage
- ProjectMetrics
- RunMetrics

## API Contracts (UI)

### Create Project
- Method: `POST /api/v1/projects`
- Request:
```json
{ "name": "Demo", "description": "Optional" }
```
- Response:
```json
{ "id": "...", "name": "Demo", "description": "Optional", "current_stage": "INTAKE", "created_at": "..." }
```

### Project Summary
- Method: `GET /api/v1/projects/{project_id}/summary`
- Response:
```json
{
  "project_id": "...",
  "name": "Demo",
  "current_stage": "DESIGN_DRAFTED",
  "latest_run": {
    "run_id": "...",
    "status": "RUNNING",
    "stage": "DESIGN_DRAFTED",
    "started_at": "...",
    "finished_at": null
  },
  "task_counts": {
    "pending": 2,
    "running": 1,
    "done": 0,
    "failed": 0,
    "canceled": 0
  }
}
```

### Project Metrics
- Method: `GET /api/v1/projects/{project_id}/metrics`
- Response:
```json
{ "total_runs": 2, "active_runs": 1, "stale_count": 0, "open_changes": 1 }
```

### Run Tasks
- Method: `GET /api/v1/runs/{run_id}/tasks`
- Response:
```json
[
  {
    "task_id": "T-UI-001",
    "run_id": "...",
    "agent": "UI_AGENT",
    "title": "Draft UI wireframe",
    "status": "PENDING",
    "depends_on": [],
    "parallel_group": "A",
    "outputs": ["docs/design/UI_WIREFRAME.md"],
    "created_at": "...",
    "started_at": null,
    "finished_at": null,
    "error": null
  }
]
```

### Run Metrics
- Method: `GET /api/v1/runs/{run_id}/metrics`
- Response:
```json
{
  "run_id": "...",
  "status": "RUNNING",
  "started_at": "...",
  "finished_at": null,
  "duration_seconds": null,
  "tasks_total": 3,
  "tasks_pending": 2,
  "tasks_running": 1,
  "tasks_done": 0,
  "tasks_failed": 0,
  "tasks_canceled": 0,
  "avg_task_duration_seconds": null,
  "retries": 0,
  "agent_distribution": { "UI_AGENT": 1, "BACKEND_AGENT": 1, "TEST_AGENT": 1 }
}
```

### Audit Logs
- Method: `GET /api/v1/projects/{project_id}/audit-logs`
- Response:
```json
[
  {
    "timestamp": "...",
    "run_id": "...",
    "stage": "DESIGN_DRAFTED",
    "agent": "planner_agent",
    "tool": "file_write",
    "message": "Wrote PLAN.json",
    "details": { "path": "docs/PLAN.json" }
  }
]
```

### Change Requests
- Create: `POST /api/v1/projects/{project_id}/changes`
- Request:
```json
{
  "source": "USER",
  "summary": "Update onboarding copy",
  "affected_area": "UI",
  "severity": "LOW",
  "suggested_stage": "DESIGN"
}
```
- List: `GET /api/v1/projects/{project_id}/changes`
- Accept: `POST /api/v1/changes/{change_id}/accept`
- Reject: `POST /api/v1/changes/{change_id}/reject`

### Run Controls
- Start: `POST /api/v1/runs/{run_id}/start`
- Pause: `POST /api/v1/runs/{run_id}/pause`
- Resume: `POST /api/v1/runs/{run_id}/resume`
- Cancel: `POST /api/v1/runs/{run_id}/cancel`
- Execute Tasks: `POST /api/v1/runs/{run_id}/execute?max_parallel_tasks=2`
