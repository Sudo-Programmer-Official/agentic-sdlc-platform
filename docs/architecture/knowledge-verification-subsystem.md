# Knowledge Verification Subsystem

See also: `docs/engineering-memory-system-spec.md`. This subsystem is the reviewed publication foundation for engineering memory; the companion spec defines the structured record model, retrieval logic, and runtime integration layer built on top of it.

## Purpose

The knowledge verification subsystem is the platform's engineering memory layer.
It converts repo activity into draft knowledge updates, but official knowledge only changes after a human review action.

## Scope Adaptation

This codebase does not have a standalone `workspace` table.
The subsystem therefore uses:

- `project_id` as the workspace scope
- `project_repositories.id` as the repo scope

That keeps tenancy, auth, and repo integration aligned with the rest of the platform.

## Flow

1. Source activity arrives from one of four paths:
   - GitHub `push`
   - GitHub merged `pull_request`
   - manual `POST /api/v1/knowledge/events/manual-sync`
   - internal agent-run completion hook
2. A `knowledge_events` row is created with raw payload retention and idempotency keys.
3. The analysis layer fetches the relevant diff, changed files, commit metadata, and change context.
4. Heuristics classify the change and persist a `knowledge_changes` row with:
   - summaries
   - impact flags
   - impacted files and modules
   - probable artifact targets
5. Proposal generation creates one or more `knowledge_proposals` rows against `knowledge_artifacts`.
6. The review UI exposes the proposal inbox, proposal detail, artifact history, and event intelligence.
7. Every review/read path is scoped by authenticated tenant plus explicit `project_id`; the subsystem never falls back to cross-project reads.
8. Approval creates `knowledge_reviews` and `knowledge_publications`, increments the artifact version, and updates the canonical artifact.
9. Rejection and defer preserve history without changing official content.
10. Proposal publication is guarded by `base_artifact_version` and `base_artifact_hash`; stale proposals are superseded instead of overwriting newer official knowledge.

## Trust Rules

- Canonical knowledge is never overwritten silently.
- A proposal can publish at most once.
- Re-running manual sync on the same branch head reuses the existing event instead of creating duplicate proposals.
- High-risk changes are still review-gated because no auto-publish policy exists yet.
- Unapproved content remains draft-only in proposals.
- Publication history preserves previous versions for future rollback tooling.

## Validation Snapshot

Verified:

- the hardening schema upgrade reached `20260314_0010` on the shared staging/dev database
- existing project data remained readable after the migration
- local API/service regression coverage and the web build passed after the hardening changes

Not fully verified yet:

- full live Postgres concurrency proof for retry-heavy proposal actions
- full live webhook plus manual-sync lifecycle replay without harness interruption

Known limitations and follow-up:

- the shared staging/dev environment has unrelated schema drift on `tenants.system_reserved`, which blocked part of the live fixture setup
- the retained live validation harness in `scripts/validate_knowledge_hardening_live.py` is a rerun tool, not yet a stable gate
- do not expand subsystem scope again until the shared environment is aligned and the live Postgres validation pass completes cleanly

## Future Extensions

- policy-driven low-risk auto-approval
- semantic embedding and retrieval over official artifacts
- Notion/Confluence publishing adapters
- "docs PR mode" that opens repo documentation pull requests instead of only updating internal canonical artifacts
- rollback API that republishes any previous `knowledge_publications` version
