# Codex Task Pack — GitHub Enterprise Gate (VCS Layer)

Guiding constraints:
- Start with a GitHub App (no PATs); keep scope minimal; no new deps unless required.
- Provide stubs where external secrets are needed; wire env vars, never hard-code keys.
- Build VCS abstraction to allow future GitLab/Bitbucket adapters.

## Phase G1 — GitHub App Foundations

TASK_ID: G1-001  
GOAL: GitHub App auth + installation token service.  
SCOPE:
- Add VCS base interfaces.
- Implement GitHubAdapter with JWT → installation token flow (private key from env/secret).  
FILES_ALLOWED: apps/api/app/services/vcs/base.py, apps/api/app/services/vcs/github_adapter.py, apps/api/app/services/__init__.py, docs/GITHUB_APP.md  
ACCEPTANCE:
- Given APP_ID, INSTALLATION_ID, PRIVATE_KEY envs, service returns an installation token.
- Errors surface clear messages; no secrets logged.

TASK_ID: G1-002  
GOAL: Webhook receiver with signature verification.  
SCOPE:
- Endpoint POST /webhooks/github.
- Verify X-Hub-Signature-256 using webhook secret env.
- Store event minimally in memory/log for now.  
FILES_ALLOWED: apps/api/app/api/v1/routes.py, apps/api/app/services/vcs/github_webhook.py  
ACCEPTANCE:
- Invalid signature → 401; valid events parsed; PR events extracted to structured payload.

TASK_ID: G1-003  
GOAL: Basic repo/PR fetch utilities.  
SCOPE:
- GitHubAdapter methods: get_repo, list_prs, get_pr(pr_number), get_pr_files(pr_number).  
FILES_ALLOWED: apps/api/app/services/vcs/github_adapter.py  
ACCEPTANCE:
- Can fetch repo metadata and PR file list with mocked HTTP tests.

## Phase G2 — Enterprise Gate & Policies

TASK_ID: G2-001  
GOAL: Org model + feature flags scaffold.  
SCOPE:
- In-memory Org store with: org_id, installation_id, plan_type, enabled_features (dict).  
FILES_ALLOWED: apps/api/app/services/enterprise/org_service.py, apps/api/app/services/enterprise/feature_flags.py  
ACCEPTANCE:
- Can upsert org config; feature flag lookup returns bool with default fallback.

TASK_ID: G2-002  
GOAL: Policy engine stub.  
SCOPE:
- PolicyEngine.check(action, org_id, repo) → allow/deny with reason; default allow.  
FILES_ALLOWED: apps/api/app/services/enterprise/policy_engine.py  
ACCEPTANCE:
- Returns structured decision; wired to use feature flags (e.g., pr_doc_guard).

TASK_ID: G2-003  
GOAL: VCS registry wiring.  
SCOPE:
- VCSRegistry that returns adapter by provider ("github").  
FILES_ALLOWED: apps/api/app/services/vcs/registry.py, apps/api/app/services/__init__.py  
ACCEPTANCE:
- Registry returns GitHubAdapter; unknown provider raises clear error.

## Phase G3 — PR Checks & Doc Guard Hook

TASK_ID: G3-001  
GOAL: PR DocGuard skeleton (no AI yet).  
SCOPE:
- Service that takes PR number → uses GitHubAdapter to fetch files → returns diff metadata {added, modified, deleted}.  
FILES_ALLOWED: apps/api/app/services/doc_guard.py  
ACCEPTANCE:
- Returns structured diff with file counts; unit tests with mocked adapter.

TASK_ID: G3-002  
GOAL: PR status check publishing (stub).  
SCOPE:
- GitHubAdapter method create_check(repo, head_sha, summary, conclusion="neutral").  
FILES_ALLOWED: apps/api/app/services/vcs/github_adapter.py  
ACCEPTANCE:
- Payload formatted per GitHub Checks API; mocked HTTP test verifies body.

TASK_ID: G3-003  
GOAL: Wire webhook → policy → doc_guard → check.  
SCOPE:
- On pull_request event: run policy check, run doc_guard diff, publish neutral check with summary.  
FILES_ALLOWED: apps/api/app/api/v1/routes.py, apps/api/app/services/doc_guard.py  
ACCEPTANCE:
- pull_request webhook triggers check creation (mocked); denied policy returns 403/no-op with log.

## Environment / Secrets
- GITHUB_APP_ID, GITHUB_INSTALLATION_ID (or per-org), GITHUB_PRIVATE_KEY (PEM), GITHUB_WEBHOOK_SECRET.
- Do not embed; use env lookups and clear error messages when missing.

## Tests
- Mock GitHub HTTP calls; signature verification unit tests; adapter methods validated without hitting network.

## Deliverables
- VCS abstraction with GitHub App auth + webhook verification.
- Enterprise gate scaffolding (org + feature flags + policy stub).
- PR doc guard skeleton and check publishing hook.
