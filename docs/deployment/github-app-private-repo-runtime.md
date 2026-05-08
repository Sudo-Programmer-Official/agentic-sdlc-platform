# GitHub App Private Repo Runtime Setup

This platform supports multi-user GitHub repository connection through one platform-owned GitHub App and per-project repository metadata.

The production-ready private-repo runtime strategy is:

- GitHub App installation-token HTTPS for clone, fetch, and push
- optional SSH mode if you explicitly operate runtime SSH keys in ECS

Recommended mode:

- `RUNTIME_GIT_AUTH_MODE=github_app_https`

This keeps runtime credentials short-lived and scoped to the installation attached to each project repository record.

## Required Backend Env Vars

Set these for every repo-executing runtime service:

- API service
- worker service, only if you actually deploy one

The scheduler does not need GitHub App secrets because it does not clone or push repositories.

If your production shape is only `web + api`, the API service is the runtime container that must have the GitHub App env vars.

Shared repo-backed runtime env:

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `ENV=production`
- `RUNTIME_MODE=external`
- `WORKSPACE_BASE_DIR`
- `GIT_AUTHOR_NAME`
- `GIT_AUTHOR_EMAIL`
- `RUNTIME_GIT_AUTH_MODE=github_app_https`
- `GITHUB_APP_ID`
- `GITHUB_PRIVATE_KEY`
- `GITHUB_WEBHOOK_SECRET`
- `GITHUB_APP_SLUG`
- `GITHUB_ALLOWED_ORG` optional

For scheduler-only containers:

- `DATABASE_URL`
- `ENV=production`
- `RUNTIME_MODE=external`
- `RUN_MIGRATIONS_ON_STARTUP=0`

Useful optional settings:

- `TEST_COMMAND`
- `PREVIEW_HOST`
- `PREVIEW_DEFAULT_TTL_HOURS`
- `PREVIEW_MAX_PER_PROJECT`
- `PREVIEW_MAX_GLOBAL`

## Current Production GitHub App

Current platform-owned GitHub App:

- `GITHUB_APP_ID=2904464`
- `GITHUB_APP_SLUG=prompt-to-pr`

Recommended production values:

- `RUNTIME_GIT_AUTH_MODE=github_app_https`
- `GITHUB_ALLOWED_ORG=Sudo-Programmer-Official` if you want org restriction enabled

## Required ECS Secrets / Runtime Inputs

Inject these into the API task securely, and into the worker task as well if you deploy a separate worker service:

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `GITHUB_APP_ID`
- `GITHUB_PRIVATE_KEY`
- `GITHUB_WEBHOOK_SECRET`
- `GITHUB_APP_SLUG`

Recommended ECS task-definition mapping:

- `GITHUB_APP_ID=2904464`
- `GITHUB_APP_SLUG=prompt-to-pr`
- `GITHUB_PRIVATE_KEY` from AWS Secrets Manager or SSM Parameter Store
- `GITHUB_WEBHOOK_SECRET` from AWS Secrets Manager or SSM Parameter Store

Use [ecs-runtime-container-env.example.json](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/infra/deploy/ecs-runtime-container-env.example.json) as the source-controlled template for the ECS container `environment` and `secrets` arrays.

Notes:

- `GITHUB_PRIVATE_KEY` and `GITHUB_WEBHOOK_SECRET` are true secrets.
- `GITHUB_APP_ID` and `GITHUB_APP_SLUG` are not sensitive, but you can still inject them through ECS secrets or SSM for consistency.
- These values belong on the API task, not the static web task.
- These values also belong on the worker task when you deploy one. Repo-backed runs can prepare workspaces in the API bootstrap path and later execute repo mutations in the worker path, but API-only deployment is also supported through embedded fallback when no worker heartbeats exist.

## Repo Auth Strategy Contract

Repository identity and repository auth are separate concerns.

Project repository rows should persist the canonical repo plus an explicit `auth_strategy`:

- `public_https`: public GitHub HTTPS clone. Uses `auth_mode=plain`.
- `github_app`: GitHub App installation token over HTTPS. Uses `auth_mode=github_app_https`.
- `ssh`: runtime SSH credentials. Uses `auth_mode=ssh`.
- `runtime_default`: legacy fallback to `RUNTIME_GIT_AUTH_MODE`.

Do not rely on the saved `repo_url` alone to infer runtime auth. A GitHub repo can have both SSH and HTTPS URLs, and a global env var can drift from the project-level intent.

Before starting repo-backed runs, verify the project with the preflight endpoint:

```bash
curl -sS -X POST \
  http://127.0.0.1:8000/api/v1/projects/<project_id>/repo/preflight \
  -H 'Content-Type: application/json' \
  -d '{"clone":true}'
```

Healthy public HTTPS output includes:

```json
{
  "ok": true,
  "auth_strategy": "public_https",
  "auth_mode": "plain",
  "credential_strategy": "anonymous_https"
}
```

Healthy GitHub App output should include:

```json
{
  "ok": true,
  "auth_strategy": "github_app",
  "auth_mode": "github_app_https",
  "credential_strategy": "http.extraheader",
  "token_generated": true
}
```

## Private Key Format

`GITHUB_PRIVATE_KEY` must be the raw GitHub App PEM with the header/footer intact:

```pem
-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----
```

Rules:

- preserve real newlines
- do not strip the header/footer
- do not store the value with literal `\n` unless your secret-injection layer converts them back to actual newlines before the process reads the env var
- prefer Secrets Manager or SSM over plaintext task-definition values

If you run SSH mode instead of GitHub App HTTPS, you also need:

- SSH private key material available to the runtime
- known_hosts / host verification setup
- `RUNTIME_GIT_AUTH_MODE=ssh`

Do not combine SSH runtime auth with GitHub App HTTPS unless you have a specific migration reason.

## Worker Freshness Guard

Repo-backed execution can happen in the worker, not only the API.

If a run fails with SSH clone errors even though API health and repo preflight show `public_https/plain`, check worker rows:

```sql
select id, name, status, last_heartbeat_at, executors, capabilities
from agents
where kind = 'worker'
order by last_heartbeat_at desc
limit 20;
```

Expected state:

- one or more intentionally deployed current workers are `ACTIVE`
- old local workers are `INACTIVE`
- no stale worker with old code/config has `codex` or `test` in `executors`

Local dev safety:

- `worker_service.py` deactivates existing local active workers before registering a new local worker.
- Still restart the full dev stack after changing runtime auth or repo connector code.
- Do not rely on API hot reload for worker changes. The worker process does not hot reload.

Production safety:

- deploy API and worker from the same image/build revision
- restart worker services after repo auth changes
- expose API runtime auth and worker runtime auth separately in logs/health dashboards
- alert if old worker revisions keep heartbeating after deploy

## GitHub App Settings

Create one platform-owned GitHub App and let each customer org/user install it.

### Setup URL

Set the GitHub App Setup URL to your workspace root:

- `https://www.prompt2pr.com/`

Reason:

- the UI passes a `state` payload when starting installation
- the workspace page reads `state` and redirects the user back to the correct `/projects/:projectId`
- GitHub App settings should also enable `Redirect on update`

### Webhook URL

Set:

- `https://api.prompt2pr.com/api/v1/webhooks/github`

### Required permissions

Minimum recommended permissions:

- Repository contents: `Read and write`
- Pull requests: `Read and write`
- Metadata: `Read-only`

If you later automate issues/comments/checks more deeply, expand explicitly.

### Required events

Enable:

- `Installation`
- `Installation repositories`
- `Pull request`
- `Push`

Current webhook automation is centered on pull requests, but enabling the broader install/repository events is correct for production onboarding and future repo-sync handling.

### Installation target

Confirm the app is installed on:

- `Sudo-Programmer-Official`

## Runtime Git Auth Modes

### `github_app_https`

Recommended.

Behavior:

- UI or API stores clean GitHub repo metadata per project
- runtime resolves the installation ID from the connected project repository
- clone/fetch/push use a short-lived installation token via `git -c http.https://github.com/.extraheader=...`
- token is not written into the remote URL

### `ssh`

Supported when you intentionally manage SSH credentials in ECS.

Behavior:

- GitHub-selected repos normalize to `git@github.com:owner/repo.git`
- runtime relies on SSH agent/key availability

### `auto`

Best-effort mode.

Behavior:

- GitHub App HTTPS is used when installation metadata is present
- otherwise clone/push falls back to the saved repo URL

For production private-repo operation, prefer `github_app_https` over `auto`.

## Repo Connection Rules

When a repository is selected from the GitHub App installation:

- `repo_full_name` is preserved
- `installation_id` is preserved
- `default_branch` is preserved
- repo URL is normalized by backend policy:
  - SSH mode -> `git@github.com:owner/repo.git`
  - GitHub App HTTPS mode -> `https://github.com/owner/repo.git`

That keeps UI selection, stored project metadata, runtime clone transport, and PR creation aligned.

## Verification Checklist For Private Repo Success

Use this exact checklist after deployment.

1. Open a project in the UI.
2. Click `Connect Repo`.
3. Click `Continue with GitHub`.
4. Install or authorize the GitHub App for the target account/org.
5. Confirm the browser returns to the correct project page and preloads the installation repository list.
6. Select a private repository and save the connection.
7. Confirm `repo_full_name`, `default_branch`, and `installation_id` are stored on the project.
8. Start a repo-backed `codex` run.
9. Confirm workspace seeding succeeds and the repo is cloned into the run workspace.
10. Make or simulate a file change.
11. Create/approve a patch artifact.
12. Trigger PR creation.
13. Confirm runtime performs:
    - clone/fetch
    - commit
    - push branch
    - GitHub PR creation
14. Confirm the PR opens against the expected base branch in the connected private repo.

## Deployment Verification

After updating ECS task definitions:

1. Deploy the new API task revision.
2. If you run a separate worker service, deploy the new worker task revision.
3. Wait for the old tasks to drain.
4. Confirm API startup logs:
   - `Starting API build=... sha=...`
   - `Runtime tool availability git=/usr/bin/git`
   - `GitHub integration env app_id_present=True private_key_present=True webhook_secret_present=...`
5. Confirm worker startup logs, if a worker service exists:
   - `Starting worker build=... sha=...`
   - `Worker runtime tool availability git=/usr/bin/git`
   - `Worker GitHub integration env app_id_present=True private_key_present=True webhook_secret_present=...`
6. Start a smoke run and confirm workspace prep logs:
   - `adapter=GitHubAppAdapter`
   - `auth_mode=github_app_https`
   - `token_generated=True`

If `app_id_present=True` and `private_key_present=True` but clone still fails, the next likely causes are:

- malformed PEM private key
- wrong GitHub App ID or private key pair
- app installation missing access to the target repo
- wrong installation id attached to the project
- GitHub API/network failure while minting the installation token

## Final Production Checklist

1. GitHub App slug is `prompt-to-pr`.
2. GitHub App ID is `2904464`.
3. Webhook URL is `https://api.prompt2pr.com/api/v1/webhooks/github`.
4. Setup URL is `https://www.prompt2pr.com/`.
5. `Redirect on update` is enabled in GitHub App settings.
6. Permissions are:
   - Contents `Read and write`
   - Pull requests `Read and write`
   - Metadata `Read-only`
7. Events are:
   - Installation
   - Installation repositories
   - Pull request
   - Push
8. The app is installed on `Sudo-Programmer-Official`.
9. ECS API task has:
   - `GITHUB_APP_ID=2904464`
   - `GITHUB_APP_SLUG=prompt-to-pr`
   - `GITHUB_PRIVATE_KEY`
   - `GITHUB_WEBHOOK_SECRET`
10. If a worker service exists, it has the same GitHub App env vars as the API task.
11. API runtime mode is `RUNTIME_GIT_AUTH_MODE=github_app_https`.

## Runtime Verification Commands

After deploying the API, verify the control-plane surface first:

```bash
curl -s https://api.prompt2pr.com/api/v1/integrations/github/connect | jq
```

Expected:

- `enabled: true`
- correct `app_slug`
- `runtime_git_auth_mode: "github_app_https"` for the recommended setup

Then verify the webhook surface:

```bash
curl -i https://api.prompt2pr.com/api/v1/webhooks/github
```

Expected:

- route exists
- non-POST or unsigned requests should not be treated as healthy webhook deliveries

## Multi-User Model

This setup is intentionally multi-user capable:

- one platform-owned GitHub App
- many installations across future users/orgs
- per-project repository records store:
  - `provider`
  - `repo_url`
  - `repo_full_name`
  - `default_branch`
  - `installation_id`

Do not hardcode a personal GitHub username, personal installation ID, or one-repo assumption into runtime or deploy config.
