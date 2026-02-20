# Codex Task Pack — GitHub Integration v1 (Light, Single-Tenant)

Goal  
Integrate GitHub via a single GitHub App installation to receive PR webhooks, fetch PR file changes, run Documentation Guard checks, and post PR comments/check-runs. Architecture should be clean for future multi-tenant expansion, but v1 is single-tenant.

Constraints  
- GitHub App only (no PAT)  
- Single installation/org (v1)  
- Secrets from env: GITHUB_APP_ID, GITHUB_PRIVATE_KEY (PEM), GITHUB_WEBHOOK_SECRET, GITHUB_ALLOWED_ORG  
- No AWS dependency; no auto-merge; no billing; keep deps minimal

Phase G0 — GitHub App Core

TASK_ID: G0.1  
GOAL: GitHub App auth (JWT → installation token) + VCS adapter.  
FILES_ALLOWED: apps/api/app/services/vcs/base.py, apps/api/app/services/vcs/github_app.py, apps/api/app/services/__init__.py  
REQUIREMENTS:
- Define VCSAdapter interface: get_pr_files(...), post_pr_comment(...).
- Implement GitHubAppAdapter: generate_jwt(), get_installation_token(), get_pr_files(repo, pr_number), post_pr_comment(repo, pr_number, body).  
ACCEPTANCE:
- JWT RS256 signed; installation token fetched via GitHub API.
- PR file list retrievable with token.
- No hardcoded tokens.

TASK_ID: G0.2  
GOAL: Webhook endpoint with signature verification.  
FILES_ALLOWED: apps/api/app/api/v1/routes.py, apps/api/app/services/vcs/github_app.py  
REQUIREMENTS:
- POST /webhooks/github
- Validate X-Hub-Signature-256 with secret.
- Handle pull_request opened/synchronize/reopened; log via ledger.  
ACCEPTANCE:
- Valid signature -> 200; invalid -> 401.
- PR event parsed; action/repo/pr_number logged.

Phase G1 — PR Diff Intelligence

TASK_ID: G1.1  
GOAL: PR file extraction.  
FILES_ALLOWED: apps/api/app/services/vcs/github_app.py  
RETURN:
```
{ "added": [], "modified": [], "removed": [], "all_files": [] }
```  
ACCEPTANCE:
- Correct status classification; handles empty PR.

TASK_ID: G1.2  
GOAL: Documentation Guard trigger (deterministic).  
FILES_ALLOWED: apps/api/app/services/documentation_guard.py  
REQUIREMENTS:
- On PR open/update: load REQUIREMENTS_GRAPH.json + PLAN.json.
- Check plan_stale; find impacted requirements (by path match to linked requirements if available).  
OUTPUT:
```
{ "status": "OK" | "WARNING", "impacted_requirements": [], "plan_stale": bool, "message": "..." }
```  
ACCEPTANCE:
- Deterministic, no LLM; logs to ledger.

Phase G2 — PR Commenting

TASK_ID: G2.1  
GOAL: Post structured PR comment via GitHub App token.  
FILES_ALLOWED: apps/api/app/services/vcs/github_app.py, apps/api/app/services/documentation_guard.py  
COMMENT TEMPLATE:
```
## 🧠 Agentic SDLC Documentation Guard
Impacted Requirements:
- FR-003
- QR-SECURITY-01

Plan Status: ❌ Stale

Action Required:
- Regenerate Plan
- Confirm documentation alignment
```
ACCEPTANCE:
- Comment posted on PR; permission errors handled; comment ID logged.

Phase G3 — Minimal Integration Storage

TASK_ID: G3.1  
GOAL: Store single GitHub installation config (in-memory).  
FILES_ALLOWED: apps/api/app/services/vcs/github_store.py  
MODEL:
```
GitHubIntegration:
  installation_id: int
  org_login: str
  allowed_repos: list[str]
  connected_at: datetime
```  
ACCEPTANCE:
- Installation data stored; repo access restricted to allowed_repos.

Ledger Requirements  
- Every webhook event logs: event_type, repo, pr_number, action, guard_status (if run).

Testing  
- Mock JWT generation, installation token response, PR file API response.
- Add tests: tests/test_github_webhook_signature.py, tests/test_github_pr_diff.py.

Out of Scope (v1)  
- Multi-org, auto-merge, commit writing, CI/CD, billing, AWS infra.

End State v1  
PR opened → webhook verified → PR files fetched → Doc Guard executed → PR comment posted → ledger entry recorded.  
System now behaves like a real SDLC governance tool.  
