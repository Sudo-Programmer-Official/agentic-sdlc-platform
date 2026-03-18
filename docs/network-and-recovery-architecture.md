# Network and Recovery Architecture

See also: `docs/agent-runtime-vision-roadmap.md`, `docs/human-in-the-loop-runtime-roadmap.md`, `docs/run-console-product-spec.md`, and `docs/runtime-foundation-spec.md`. This document defines how the SDLC runtime should behave when connectivity, streaming, workers, or external side effects become unreliable.

## Objective

Design the runtime so network interruption never destroys run truth.

Even when work cannot continue, the system should still make it clear:

- what was last confirmed
- what is uncertain
- what is blocked
- what can be retried safely
- what needs reconciliation
- what needs human input

## Core Principle

Checkpoint, reconcile, and resume safely. Never guess.

The platform is a distributed execution system. That means "network" is not one thing. A run can still be healthy while a user is offline, and a UI can still be healthy while a worker has lost GitHub or provider access.

## Connectivity Model

The platform must track three connectivity classes separately.

### 1. User UI connectivity

Can the browser or app talk to the platform?

Examples:

- browser offline
- SSE disconnected
- websocket dropped
- mobile app backgrounded

### 2. Platform service connectivity

Can the control plane talk to its dependencies?

Examples:

- database reachable
- object storage reachable
- queue healthy
- GitHub API reachable
- LLM provider reachable
- CI or deployment API reachable

### 3. Execution environment connectivity

Can the worker or runtime container reach the systems needed for the current step?

Examples:

- repo host reachable
- package registries reachable
- test services reachable
- preview infra reachable
- deployment target reachable

Mission Control should never collapse these into one generic "disconnected" state.

## Failure Classes

### Case 1: User loses internet, worker keeps running

Expected behavior:

- run continues on the backend
- UI reconnects later
- missed events are replayed
- user sees a backfill notice such as:
  - "You were disconnected. Run continued and 14 events were recovered."

### Case 2: Backend loses provider connectivity

Examples:

- GitHub unreachable
- OpenAI timeout
- package registry unavailable

Expected behavior:

- current step becomes `DEGRADED`, `BLOCKED`, or retrying
- exact provider failure is recorded
- retry follows policy
- run remains resumable
- user sees the dependency-specific reason, not only "failed"

### Case 3: Worker dies mid-run

Examples:

- container restart
- process crash
- host eviction
- out-of-memory kill

Expected behavior:

- run state is durable
- step checkpoint persists
- lease expires safely
- another worker may recover from the last safe checkpoint
- duplicate side effects are prevented

### Case 4: Stream breaks but run is alive

Expected behavior:

- UI marks stream as disconnected, not run failed
- polling fallback activates
- missed events are rehydrated after reconnect

### Case 5: Side effect succeeded, acknowledgement was lost

Examples:

- pull request created
- branch pushed
- comment posted
- deployment triggered

Expected behavior:

- external side effects use idempotency keys or reconciliation markers
- the runtime checks external truth before retrying
- duplicate side effects are avoided

## Run Durability Model

Each run should store enough metadata to recover safely.

Suggested fields:

- `run_id`
- `current_state`
- `current_step`
- `worker_id`
- `lease_expiry`
- `last_heartbeat_at`
- `last_event_seq`
- `resume_from_checkpoint`
- `blocking_reason`
- `stream_status`
- `external_operation_keys`

This is the minimum envelope needed for restart safety and truthful UI recovery.

## Step Checkpoint Model

Runs must not exist only in memory. Each step must be resumable.

Example run:

1. parse request
2. inspect repo
3. plan edits
4. patch files
5. run targeted tests
6. build app
7. open preview
8. request approval
9. create pull request

Each step should move through explicit sub-states:

- `STARTED`
- `IN_PROGRESS`
- `COMPLETED`
- `FAILED_RETRYABLE`
- `FAILED_TERMINAL`
- `AWAITING_INPUT`

If connectivity breaks at step 6, the runtime should resume from step 6 or the last safe checkpoint, not from step 1.

## Event Log Rules

The event log must be append-only.

Mission Control should reconstruct truth from persisted events such as:

- `RUN_CREATED`
- `REPO_CLONE_STARTED`
- `REPO_CLONE_FAILED`
- `PATCH_APPLIED`
- `COMMAND_STARTED`
- `COMMAND_FINISHED`
- `STREAM_DISCONNECTED`
- `STREAM_RECONNECTED`
- `WORKER_RECOVERED`
- `RETRY_SCHEDULED`
- `USER_INTERVENED`
- `PULL_REQUEST_CREATED`

This is what allows timeline replay, backfill after reconnect, and honest state restoration.

## Worker Lease Model

The runtime should use explicit worker leasing for active execution.

### Lease rules

- a worker claims a runnable step
- claim writes `worker_id`, `lease_expires_at`, and `last_heartbeat_at`
- worker heartbeats extend the lease
- expired leases are never assumed healthy

### Recovery rules

If heartbeat stops:

1. lease expires
2. scheduler marks the step orphaned or requeueable
3. replacement worker verifies the last checkpoint
4. recovery continues only from a safe point

This prevents two workers from continuing the same run simultaneously.

## Side-Effect Safety

All external mutations must be idempotent or reconciled before retry.

Examples:

- branch push
- pull request creation
- issue comment
- deployment trigger
- Slack or webhook message
- ticket creation

Use:

- operation keys
- external reference IDs
- run markers
- branch plus SHA correlation
- reconciliation-before-retry

Example policy:

Before creating a pull request again, check whether a pull request already exists for:

- the branch
- the head SHA
- the run id marker

## Network Policy per Step

Every step should declare a network policy.

### Local-safe

Can continue without network.

Examples:

- parsing
- local diff generation
- local file edits

### Network-required retryable

Needs network and can safely retry.

Examples:

- fetch issue metadata
- read repo refs
- upload logs
- read external status

### Network-required non-idempotent

Needs network and must reconcile before retrying.

Examples:

- create pull request
- push branch
- comment on issue
- trigger deployment

This classification should drive retry rules, UI messaging, and recovery behavior.

## Recovery Flow

When any actor reconnects or restarts, recovery should follow the same sequence.

### 1. Reload run metadata

Fetch:

- current step
- last checkpoint
- worker lease
- last event sequence
- stream status

### 2. Reconcile external side effects

Check:

- branch already created?
- pull request already opened?
- artifact already uploaded?
- command still running or dead?
- deployment already triggered?

### 3. Decide next state

Choose one:

- continue
- retry step
- mark blocked
- request user input
- recover orphaned state

### 4. Backfill timeline

The UI receives the events it missed and shows what changed during the gap.

## Mission Control UX Requirements

Mission Control should show separate health badges such as:

- `UI connection: connected`
- `Run stream: reconnecting`
- `Worker: active`
- `GitHub: healthy`
- `LLM provider: degraded`
- `Last heartbeat: 12s ago`

If disconnect happens, the UI should be explicit.

Examples:

- "You are offline. The run may still be progressing on the server."
- "Live logs disconnected. Retrying stream connection. Last confirmed step: running targeted tests."
- "GitHub access failed during clone. The run is blocked and safe to retry after auth or network recovery."
- "Your browser disconnected for 45 seconds. 19 missed events were restored."

## Module-Specific Guidance

### Repo operations

Network or auth issues can affect:

- clone
- fetch
- push
- pull request creation

Requirements:

- explicit auth diagnostics
- retry policy
- no anonymous fallback for private repos
- checkpoint after clone success

### LLM operations

Network or provider issues can affect:

- prompt send
- streaming output
- tool call execution

Requirements:

- timeout policy
- safe retry only for idempotent requests
- prompt and response correlation ID
- partial output handling

### Command execution

Network issues can affect:

- package install
- remote API-dependent tests
- browser automation
- image or container pulls

Requirements:

- command classification
- deterministic logs
- retry policy per command class
- visible environment dependencies

### UI live monitoring

Requirements:

- stream reconnect
- polling fallback
- missed-event replay
- stale-stream banner

This is mandatory for trust.

## Architecture Planes

### Control plane

Owns:

- runs
- steps
- events
- leases
- checkpoints
- retry policy

### Worker plane

Owns:

- clone
- edits
- commands
- tool calls
- verification

### Streaming plane

Owns:

- live logs
- event delivery
- reconnect behavior
- replay after disconnect

### Reconciliation plane

Owns:

- restart safety
- deduplication
- external truth sync
- orphan recovery

## Suggested Data Additions

### Run table

Add or standardize:

- `worker_id`
- `lease_expires_at`
- `last_heartbeat_at`
- `last_event_seq`
- `resume_checkpoint`
- `blocking_reason`
- `connectivity_state`

### Step table

Add or standardize:

- `network_policy`
- `checkpoint_payload`
- `external_operation_key`
- `last_confirmed_at`
- `stream_status`

### Event table

Ensure support for:

- ordered sequence number
- actor id
- correlation id
- retry group id
- external reference ids

## Acceptance Criteria

The runtime is network-safe when all of the following are true:

- user disconnect does not terminate a healthy run
- worker restart does not force whole-run restart
- external side effects are not duplicated after uncertain acknowledgement
- Mission Control distinguishes UI connectivity, stream health, worker health, and provider health
- blocked state names the exact failing dependency
- reconnect restores missed events and last confirmed state
- retry policy is guided by step network class, not generic failure handling

## Product Rule

Network interruption must never destroy observability.

The user should always know:

- what was last confirmed
- what is now uncertain
- what is safe to retry
- what is blocked
- what action comes next
