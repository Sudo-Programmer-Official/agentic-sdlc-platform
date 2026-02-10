# Acceptance Criteria

AC-01 Project Intake
- A project can be created with a name and description.
- The default SDLC stage is INTAKE.
- The project can be retrieved by project_id.

AC-02 Approval Gates
- A requirements approval can be requested for a project.
- Advancing from REQUIREMENTS_DRAFTED to REQUIREMENTS_APPROVED requires approval.
- Approvals can be approved or rejected with a decision record.

AC-03 Run Lifecycle Control
- Runs can be created for the current project stage.
- A run can transition from PENDING to RUNNING.
- A run can transition from RUNNING to PAUSED and back to RUNNING.
- A run can transition from RUNNING to COMPLETED or CANCELED.

AC-04 Auditability
- Each run lifecycle transition creates an audit log entry.
- Audit logs are retrievable by project_id in chronological order.
- Audit logs include timestamp, run_id, stage, agent, tool, and message.

AC-05 Requirements Artifacts
- A requirements run creates /docs/PRD.md, /docs/USER_STORIES.md, /docs/ACCEPTANCE.md.
- Generated artifacts are human-readable and structured.
- Artifact generation stops if the run is paused or canceled.
