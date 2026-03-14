# AI Routing And Cost Control

This platform routes every AI-backed job through a policy layer before execution. The goal is to keep expensive calls rare, short, and justified.

## Core Contract

Every routed job carries:

- `task_type`
- `ambiguity_level`
- `risk_level`
- `max_model_tier`
- `max_retries`
- `max_context_tokens`
- `budget_cents`
- `requires_human_review`

The policy layer also records the selected tier, estimated cost, actual cost, retries, context size, approval state, and stop reason in `ai_job_runs`.

## Model Tiers

- `tier_premium`: planning, architecture, high-ambiguity reasoning
- `tier_standard`: scoped coding, bug fixes, test work
- `tier_economy`: docs, summaries, lightweight classification
- `tier_none`: deterministic formatting, templating, and rule-based tasks

Model names live in config as tier mappings. Callers resolve a tier, not a hardcoded model id.

## Routing Rules

- `planner` routes to `tier_premium`
- `coder` routes to `tier_standard`
- `reviewer` routes to `tier_premium` only when risk is high, otherwise `tier_standard`
- `documenter` and `classifier` cap at `tier_economy`
- `formatter` routes to `tier_none`

Webhook and background jobs default to economy-or-below unless sensitive paths, failing tests, or high-risk signals escalate them.

## Budget And Retry Policy

Default hard caps:

- premium: `25c`
- standard: `8c`
- economy: `2c`
- background: `0.5c`

Retry caps:

- premium: `1`
- standard: `2`
- economy: `1`
- none: `0`

Retries are allowed only for:

- timeout
- rate limit
- transient network failure
- one structured parser failure

Retries are not allowed for low-confidence reasoning or repeated “try again” loops with the same scope.

## Context Policy

The policy layer blocks oversized prompts and expects narrowed inputs:

- changed files
- exact failing tests
- exact error traces
- relevant interfaces
- compressed architecture summary
- prior run summary

It avoids full-repo dumps, repeated unchanged context, raw PR threads, and long log blobs by default.

Current default caps:

- interactive planning: `20k`
- repo implementation: `10k`
- docs verification: `4k`

## Deterministic Filters And Cache

Before model calls, callers should narrow input using deterministic logic such as:

- diff narrowing
- stack trace extraction
- explicit file hint lookup
- repo graph lookup
- docs target lookup

Stable artifacts are cached in `ai_artifact_cache`, including:

- repo summary
- conventions
- architecture summary
- module map
- file ownership hints

## Stop Conditions

Jobs stop when:

- budget is exceeded
- context cap is exceeded
- retries are exhausted
- output contract is still invalid after the capped parser retry
- confidence falls below the configured low threshold for autonomous patching
- human review is required for a blocked mutating workflow

Blocked or stopped jobs persist their partial state with a `stop_reason` and `next_action`.

## Dashboard

`/api/v1/ai/ops/dashboard` and the `AI Ops` frontend page surface:

- spend by workflow type
- spend by model tier
- spend by project
- spend by repository
- average cost per successful PR
- average cost per docs proposal
- retry offenders
- context offenders
- success, escalation, and approval rates

## Adding A New Workflow Safely

1. Define the workflow’s `AIJobRequest` with the correct role, ambiguity, risk, budget, and context scope.
2. Run deterministic narrowing before building the prompt.
3. Call `AIJobManager.prepare_job(...)` before any model invocation.
4. Respect `stop_reason` and `next_action`; do not bypass blocked jobs.
5. Record attempts, retries, completion, or failure on the same `ai_job_runs` record.
6. Prefer `tier_none` for deterministic work, then `tier_economy`, and escalate only when policy justifies it.
