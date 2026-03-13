# Continuous Repo Understanding v1

Practical architecture for large repositories.

Goal:

Maintain a persistent structural understanding of the repo so each task does not start from zero.

This architecture is the right fit for repositories in the rough range of:

- `100k - 1M LOC`
- `1M+ LOC`

It is intentionally incremental. It improves repo awareness without over-engineering the system into a full graph platform too early.

## Core Idea

Move from:

`task -> full repo scan -> search -> infer structure -> edit`

to:

`persistent repo index -> query relevant slice -> build task context -> edit`

The index becomes the structural memory of the repo.

## Design Constraints

- Keep this in the intelligence plane.
- Do not block runtime hot paths on expensive repo analysis.
- Prefer cheap retrieval first, expensive retrieval last.
- Always verify live files before patching.

The safe retrieval order is:

`symbols -> edges -> grep -> embeddings`

Not:

`embeddings first`

## System Overview

The v1 system has five main modules:

1. Repo Indexer
2. Dependency Builder
3. Incremental Update Engine
4. Context Retriever
5. Hot Context Cache

Architecture:

`repo -> indexer -> repo knowledge store -> context retriever -> task executor`

## 1. Repo Indexer

The repo indexer runs when:

- a repo is cloned for the first time
- a branch is indexed initially
- a refresh is explicitly requested

The indexer extracts:

- files
- symbols
- imports
- exports
- classes
- functions
- tests

Example extraction:

- file: `src/services/ReminderService.ts`
- symbols: `createReminder()`, `deleteReminder()`, `ReminderService`
- imports: `ReminderController.ts -> ReminderService.ts`
- tests: `ReminderService.test.ts -> ReminderService.ts`

This should be lightweight and structural, not semantic-first.

## 2. Knowledge Store

Use a simple persistent structured store first.

Recommended stack:

- Postgres for persistent structure
- Redis or in-memory cache for hot context
- optional vector store later

### Files Table

`repo_files`

- `id`
- `project_id`
- `repo_root`
- `path`
- `language`
- `checksum`
- `last_indexed_at`

### Symbols Table

`repo_symbols`

- `id`
- `project_id`
- `file_id`
- `name`
- `type`
- `line_start`
- `line_end`

Examples:

- `Button` (`component`)
- `createReminder` (`function`)
- `ReminderService` (`class`)

### Dependency Edges

`repo_edges`

- `id`
- `project_id`
- `source_file_id`
- `target_file_id`
- `relation_type`

Examples:

- `WeeklyView.vue -> Button.vue`
- `ReminderController.ts -> ReminderService.ts`

Relation types may begin with:

- `import`
- `call`
- `inherit`
- `dependency`

### Test Linkage

`repo_test_links`

- `id`
- `project_id`
- `test_file_id`
- `target_file_id`
- `relation_type`
- `confidence`

Examples:

- `ReminderService.test.ts -> ReminderService.ts`
- `Button.test.ts -> Button.vue`

## 3. Incremental Update Engine

This is the key scaling mechanism.

Do not rebuild the repo model on every run.

Instead:

`repo update -> detect changed files -> reindex changed files -> update symbols/edges/tests`

Example:

If only `src/components/Button.vue` changes, update:

- its file metadata
- its symbols
- its dependency edges
- any linked test mapping

Do not reindex the whole repo.

## 4. Context Retriever

When a task arrives, the retriever should assemble only the relevant slice.

Example task:

`Increase button size in weekly planner`

Expected retrieval flow:

1. Find symbol `Button`
2. Expand direct dependents:
   - `WeeklyView.vue`
   - `TaskPlannerDialog.vue`
3. Find linked tests:
   - `Button.test.ts`
4. Build context slice

Result:

- `Button.vue`
- `WeeklyView.vue`
- `Button.test.ts`

This slice should then be live-verified before being passed to the agent.

## 5. Hot Context Cache

Developers usually work in bursts around the same subsystem.

The system should keep recent subsystem context warm.

Example cache payload:

- recent files
- recent symbols
- recent failing tests
- recent successful patch clusters
- active subsystem path

Example:

If recent work is around:

- `ReminderService.ts`
- `ReminderController.ts`
- `ReminderService.test.ts`

Then the next reminder-related task should begin there immediately instead of rediscovering the subsystem.

## Subsystem Detection

Large repos should not be treated as flat spaces.

Detect and preserve subsystem boundaries such as:

- `frontend/ui`
- `frontend/planner`
- `backend/reminders`
- `backend/payments`
- `backend/notifications`

Use simple heuristics first:

- directory structure
- import clusters
- test grouping
- recent change patterns

This helps the agent stay inside the correct architectural slice.

## Optional Semantic Layer

Embeddings are useful later, but they should not be the first indexing layer.

Use semantic retrieval only for:

- natural language search
- documentation lookup
- concept similarity

Examples:

`Where is reminder scheduling logic?`

May resolve to:

- `ReminderScheduler.ts`
- `CronReminderService.ts`

Structure should still drive edits. Semantics should support discovery.

## Task Execution Pipeline

Once continuous repo understanding exists, the task flow becomes:

`user request -> intent parser -> context retriever -> plan generator -> patch generator -> verification -> PR creation`

The main improvement is not “more AI.” It is faster and more accurate context retrieval.

## Example Task Walkthrough

User request:

`Increase button text size in weekly planner`

System actions:

1. Retrieve symbol `Button`
2. Find direct dependents:
   - `WeeklyView.vue`
3. Find linked tests:
   - `Button.test.ts`
4. Assemble task context

Context passed to the agent:

- `Button.vue`
- `WeeklyView.vue`
- `Button.test.ts`

No repo-wide rediscovery is needed.

## Performance Targets

For a roughly `1M LOC` repository, v1 should target:

- initial indexing: `2-10 minutes`
- incremental update: `50-500ms`
- context retrieval: `10-50ms`
- task context assembly: `100-300ms`

The system should feel instant even if the underlying repo is large.

## Observability Requirements

Log retrieval behavior so failures are diagnosable.

Minimum metrics:

- `context_retrieval_time`
- `symbols_resolved`
- `files_selected`
- `dependency_depth`
- `cache_hits`

This is required to improve retrieval quality over time.

## Minimal Implementation Plan

### Phase 1

- persistent file index
- persistent symbol index
- `rg` fallback search

### Phase 2

- dependency edges
- test linkage

### Phase 3

- incremental updates
- hot context cache

### Phase 4

- semantic embeddings
- subsystem detection refinement

## Recommended Integration Points In This Repo

This v1 should sit on top of the current repo understanding path, not replace it all at once.

Start from:

- `apps/api/app/services/repo_map.py`
- operator repo-map tools
- read-model style APIs

Keep the current safety pattern:

`cache lookup -> live verify -> read file -> patch`

That avoids stale-index drift while gaining most of the speed and structural benefits.

## What This Unlocks

Once this layer exists, the system becomes much better at:

- bug intake analysis
- impact prediction
- patch planning
- scope detection
- review summaries
- “already implemented” detection
- faster operator responses

This is the transition from useful automation to a real engineering operator.

## Recommended Next Order

For this repo, the safest sequence is:

1. planning layer
2. persistent symbol index
3. dependency / test linkage
4. impact scope detection
5. hot context cache
6. semantic embeddings later

That sequence preserves the current stabilization priorities while moving the platform toward persistent repo intelligence.
