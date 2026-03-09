Good call. Reliability before speed is the right move.

Let’s implement this cleanly, without destabilizing your loop.

I’ll give you:
	1.	REVIEW_DIFF work-item design
	2.	ReviewExecutor contract
	3.	Patch heuristic guards (strict but practical)
	4.	Updated dev-loop logic flow
	5.	Minimal implementation plan for Codex

⸻

1️⃣ Updated DAG (Reliable Dev Loop)

New path:

PLAN
→ CODE_BACKEND / CODE_FRONTEND
→ WRITE_TESTS
→ REVIEW_DIFF
→ RUN_TESTS

Important:
	•	REVIEW_DIFF runs after code changes, before tests.
	•	It operates on the unified diff artifact.
	•	It does NOT rewrite whole files — patch-only corrections.

⸻

2️⃣ REVIEW_DIFF Work Item

WorkItem.type

REVIEW_DIFF

Required capabilities

["review"]

Payload

Include:
	•	unified diff from previous step
	•	changed file list
	•	summary message
	•	context metadata (branch, project root)
	•	size stats (#files, #lines)

⸻

3️⃣ ReviewExecutor Behavior

Goal:

Act as a defensive gate.

Inputs:
	•	Unified diff
	•	Heuristic stats
	•	Config constraints

Output:

One of:

APPROVE

{
  "status": "DONE",
  "message": "Diff approved",
  "actions": []
}

CORRECTIVE PATCH

{
  "status": "DONE",
  "message": "Corrected issues",
  "actions": [
    {
      "type": "apply_patch",
      "patch": "unified diff"
    }
  ]
}

REJECT

{
  "status": "FAILED",
  "message": "Unsafe diff: touches protected file",
  "retryable": false
}


⸻

4️⃣ Patch Heuristic Guards (Executor-Level)

Add these guards in CodexExecutor BEFORE applying patch:

⸻

Guard A — File Count Limit

Config:

codex_patch_max_files = 8

Reject if:

len(changed_files) > max_files


⸻

Guard B — Line Change Limit

Config:

codex_patch_max_total_lines = 600
codex_patch_max_file_lines = 300

Parse unified diff:
	•	Count + and - lines (excluding headers)
	•	Enforce per-file and total cap

⸻

Guard C — Protected Files

Block if patch touches:
	•	.env
	•	migrations/
	•	alembic/versions/
	•	runtime/
	•	worker_service.py
	•	scheduler_service.py
	•	core/config.py

Unless:
	•	WorkItem explicitly allows protected edit.

Config:

codex_protected_paths = [...]


⸻

Guard D — Secret Pattern in Diff

Scan patch text for:
	•	OPENAI_API_KEY
	•	DATABASE_URL
	•	AWS_SECRET
	•	PRIVATE KEY
	•	JWT_SECRET

Fail fatally if detected.

⸻

Guard E — Strict Patch Apply

Use:

git apply --check patch.diff

If fails → do NOT apply.

Then:

git apply patch.diff

Never allow fuzzy apply.

⸻

5️⃣ Updated Loop Flow (Important)

Old:
CODE → RUN_TESTS

New:

CODE
→ REVIEW_DIFF
→ If corrective patch → apply
→ If reject → FAIL
→ RUN_TESTS
→ If fail → FIX loop
→ If pass → REVIEW (final human-level review)

This reduces:
	•	wasted test cycles
	•	repeated fix loops
	•	large broken patches

⸻

6️⃣ Finalization Logic Update

Finalization must now consider:
	•	REVIEW_DIFF failures are terminal
	•	RUN_TESTS failures may spawn FIX
	•	Superseded failures ignored

Add:

if failed_item.type == REVIEW_DIFF:
    run FAILED immediately

Because reviewer rejection = hard stop.

⸻

7️⃣ Minimal Codex Tasks (Copy/Paste for Codex)

Codex Task: Add Reliability Layer
	1.	Add REVIEW_DIFF node in DAG before RUN_TESTS.
	2.	Create review_executor.py:
	•	Input: diff artifact
	•	Output: approve or corrective patch
	3.	Add patch heuristic guards to CodexExecutor:
	•	file count cap
	•	line count cap
	•	protected path check
	•	secret scan
	4.	Enforce git apply –check before apply.
	5.	Update finalization logic:
	•	REVIEW_DIFF failure = terminal run fail.
	6.	Add metrics:
	•	review_rejections_count
	•	patch_rejected_by_heuristics_count

⸻

8️⃣ Why This Is Powerful

After this:

Your system becomes:
	•	Deterministic
	•	Conservative
	•	Self-correcting
	•	Self-auditing

It moves from:

“LLM edits code”

To:

“LLM proposes patch → system validates → reviewer verifies → tests confirm”

That’s enterprise-grade behavior.

⸻

Next Question

After this reliability layer lands, do you want to:
	1.	Add AI self-review scoring (quality scoring model)?
	2.	Add human-in-the-loop approval mode?
	3.	Optimize context selection for fewer fix loops?

Pick the direction.