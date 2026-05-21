# Fullstack Monorepo Runtime Template

Canonical governed base architecture for Agentic SDLC execution.

## 1) Philosophy

This template is not generic boilerplate. It is a runtime-native architecture baseline for governed software evolution.

Primary principle:

`User Intent -> Architecture Contract -> DAG Execution -> Scoped Mutation -> Validation -> Preview -> PR`

The platform should never guess architecture at run time when architecture can be declared at project creation.

## 2) Monorepo Architecture

```text
apps/
  web/
    src/
      components/
      sections/
      pages/
      layouts/
      styles/
      contracts/
      runtime/
  api/
    app/
      routes/
      services/
      repositories/
      schemas/
      capabilities/
      workers/
      runtime/
packages/
  shared/
  contracts/
  ui/
  runtime-types/
runtime-contracts/
  project_intent.json
  architecture_profile.json
  execution_contract.json
  capability_registry.json
governance/
  defaults.json
```

## 3) Runtime Topology

- Frontend package: `apps/web`
- Backend package: `apps/api`
- Shared domain package: `packages/shared`
- Shared contracts package: `packages/contracts`
- Shared UI primitives: `packages/ui`
- Shared runtime typing: `packages/runtime-types`

This template is executable on day one:

- `pnpm install`
- `npm -C apps/web run dev`
- `python3 apps/api/main.py`

## 4) Execution Lifecycle

1. Project intent contract is set (`runtime-contracts/project_intent.json`).
2. Architecture profile is derived (`runtime-contracts/architecture_profile.json`).
3. DAG plan and backend topology plan are generated.
4. Mutation is scoped by package and layer affinity.
5. Tests and preview validation gates run.
6. Review and integration checks complete.
7. Changes are delivered through PR flow.

## 5) Governance Defaults

Governance lives in `governance/defaults.json` and enforces:

- patch guard constraints
- topology contracts
- drift contracts
- deterministic targeting behavior

## 6) Package Conventions

### Frontend

Component-driven model. Preferred target order:

1. `apps/web/src/sections`
2. `apps/web/src/components`
3. `apps/web/src/pages`

Avoid giant root rewrites.

### Backend

Module-driven model. Layer order:

`routes -> services -> repositories`

Rules:

- route handlers should not contain persistence logic
- repositories should not contain HTTP or transport concerns
- capabilities should be isolated in `app/capabilities`

## 6.1) Boot Profile

Expected runtime classification:

- `MONOREPO_VITE_FASTAPI`

Executable markers:

- root `pnpm-workspace.yaml`
- `apps/web/package.json`
- `apps/web/vite.config.ts`
- `apps/web/index.html`
- `apps/web/src/main.ts`
- `apps/api/requirements.txt`
- `apps/api/main.py`
- `apps/api/app/main.py`

## 7) Feature Development Flow

1. Submit feature intent.
2. Runtime resolves package affinity and layer affinity.
3. DAG seeds bounded work items.
4. Patch guard validates mutation boundaries.
5. Tests and preview validation run.
6. Integration review finalizes handoff.

## 8) Content Strategy Boundary

- Code is architecture.
- Content is data.

Editable content should be declared explicitly in component-owned contracts. The system must render correctly with default in-code text if external content resolution fails.

## 9) Future Extensibility

This template is intentionally monorepo-first. Additional templates can be added after monorepo maturity is stable:

- `runtime-templates/marketing-site`
- `runtime-templates/ai-saas`
- `runtime-templates/internal-admin`

Do not expand template count until this baseline is proven in repeated fresh-project happy flows.
