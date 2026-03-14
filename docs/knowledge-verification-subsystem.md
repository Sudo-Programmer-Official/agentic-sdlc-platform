# Knowledge Verification Developer Guide

## What Was Added

The subsystem spans database, backend workflow, and frontend review surfaces.

Backend:

- schema and migration for:
  - `knowledge_events`
  - `knowledge_changes`
  - `knowledge_artifacts`
  - `knowledge_proposals`
  - `knowledge_reviews`
  - `knowledge_publications`
  - `knowledge_file_mappings`
- repo-backed analysis helpers in `app/services/knowledge_git.py`
- ingestion, analysis, proposal, review, publication, and query orchestration in `app/services/knowledge_service.py`
- REST surface in `app/api/v1/knowledge.py`
- GitHub webhook integration for `push` and merged PRs
- agent-run completion hooks in run finalization paths

Frontend:

- knowledge inbox
- proposal review page
- artifact history page
- event intelligence page

## API Surface

- `POST /api/v1/knowledge/events/manual-sync`
- `GET /api/v1/knowledge/inbox`
- `GET /api/v1/knowledge/proposals`
- `GET /api/v1/knowledge/proposals/:id`
- `POST /api/v1/knowledge/proposals/:id/approve`
- `POST /api/v1/knowledge/proposals/:id/reject`
- `POST /api/v1/knowledge/proposals/:id/defer`
- `POST /api/v1/knowledge/proposals/:id/edit-and-approve`
- `GET /api/v1/knowledge/artifacts`
- `GET /api/v1/knowledge/artifacts/:id`
- `GET /api/v1/knowledge/events/:id`
- `GET /api/v1/knowledge/search-hooks`

All read and mutation routes are project-scoped.

- `project_id` is required on list and detail requests.
- every knowledge read/write is constrained by the authenticated tenant plus the requested `project_id`
- reviewer identity is derived from the authenticated user context only and is no longer client-controlled

## Heuristics

The first pass is deterministic and intentionally lightweight.

- docs-only changes usually generate changelog and sometimes onboarding notes
- small test-only changes do not generate proposals
- migration and schema paths generate `db_note` suggestions
- infra and deployment paths generate `runbook` suggestions
- API-shaped changes generate `api_note` suggestions
- cross-cutting or multi-module changes generate `architecture_note` suggestions
- module path prefixes generate `module_doc` suggestions

Add repo-specific overrides through `knowledge_file_mappings` when the default path heuristics are too noisy.

## Lifecycle Hardening

Proposal states now follow an explicit lifecycle:

- `pending`
- `deferred`
- `rejected`
- `superseded`
- `published`

Rules:

- approval is an internal `pending -> approved -> published` transition in one transaction
- repeated approve on an already published proposal is idempotent and reuses the existing publication
- rejected and superseded proposals are terminal
- deferred proposals are held until a future reopen/regenerate path exists
- each proposal stores `base_artifact_version` and `base_artifact_hash`
- approval compares that base against the live artifact before publication
- stale proposals are blocked from publishing and are marked `superseded`
- only one `knowledge_publications` row can exist per proposal
- manual sync dedupes on project, repository, branch, commit, and source type so the same commit does not create duplicate events

## Local Testing

1. Run the stack.
2. Seed demo data if needed:

```bash
PYTHONPATH=apps/api python3 scripts/seed_knowledge_demo.py
```

3. Open the web app and navigate to the Knowledge section for the seeded project.
4. Trigger manual sync from the inbox for a connected repo, or send a GitHub webhook to `/api/v1/webhooks/github`.

## Verification Notes

- `python3 -m pytest apps/api/tests/test_knowledge_service.py` passes locally.
- `python3 -m pytest apps/api/tests/test_knowledge_api.py` covers scoping, reviewer identity, lifecycle validation, stale-publish blocking, manual-sync idempotency, and event status behavior, but local execution requires `aiosqlite`.
- `python3 -m pytest apps/api/tests/test_github_webhook_signature.py` still passes after the webhook changes.
- `npm run build` passes for the web app.
