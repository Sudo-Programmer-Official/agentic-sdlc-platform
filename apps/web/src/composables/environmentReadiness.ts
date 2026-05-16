export type EnvironmentType = "PREVIEW" | "STAGING" | "PRODUCTION";
export type ReadinessOwner = "platform" | "user";
export type ReadinessStatus = "done" | "pending";

export type EnvironmentChecklistItem = {
  id: string;
  label: string;
  owner: ReadinessOwner;
  status: ReadinessStatus;
  note?: string;
};

export type EnvironmentChecklistSummary = {
  environment: EnvironmentType;
  scorePct: number;
  total: number;
  completed: number;
  platformCompleted: number;
  platformTotal: number;
  userPending: number;
  items: EnvironmentChecklistItem[];
};

export type EnvironmentReadinessInput = {
  hasRepo: boolean;
  hasDeploymentConnector: boolean;
  deploymentProviders?: string[];
  foundationMissing?: string[];
  previewReady?: boolean;
  deploymentPreflightOk?: boolean | null;
};

export function buildEnvironmentReadiness(input: EnvironmentReadinessInput) {
  const providers = (input.deploymentProviders || []).map((value) => String(value || "").toLowerCase()).filter(Boolean);
  const hasVercel = providers.includes("vercel");
  const hasRender = providers.includes("render");
  const missing = new Set((input.foundationMissing || []).map((value) => String(value || "").toLowerCase()));
  const hasAuthMissing = [...missing].some((row) => row.includes("auth"));
  const hasPreviewMissing = [...missing].some((row) => row.includes("preview"));
  const hasRepoMissing = [...missing].some((row) => row.includes("repo"));
  const hasArchMissing = [...missing].some((row) => row.includes("arch"));
  const previewVerified = Boolean(input.previewReady || input.deploymentPreflightOk);

  const preview = summarize("PREVIEW", [
    platform("preview_runtime", "Preview runtime orchestration", true),
    platform("preview_domain", "Temporary preview URL provisioning", true),
    platform("preview_recovery", "Preview restart and recovery handling", true),
    platform("preview_health", "Preview health verification", previewVerified, previewVerified ? "" : "No active healthy preview verified yet."),
    user("preview_connector", "Connect deployment provider (Vercel/Render)", input.hasDeploymentConnector),
    user("preview_repo", "Connect repository for deployment bootstrap", input.hasRepo && !hasRepoMissing),
  ]);

  const staging = summarize("STAGING", [
    platform("staging_deploy_flow", "Staging deployment orchestration", true),
    platform("staging_retry", "Retry/rollback workflow availability", true),
    user("staging_secrets", "Provide staging environment secrets", !hasArchMissing, hasArchMissing ? "Architecture/foundation prerequisites still missing." : ""),
    user("staging_connectors", "Connect at least one deployment provider", input.hasDeploymentConnector),
    user("staging_auth", "Configure staging auth callbacks/domains", !hasAuthMissing, hasAuthMissing ? "Auth-related prerequisite is still missing." : ""),
    user("staging_checks", "Run staging integration checks", !hasPreviewMissing, hasPreviewMissing ? "Preview prerequisites suggest staging checks are incomplete." : ""),
  ]);

  const production = summarize("PRODUCTION", [
    platform("prod_governance", "Deployment governance and promotion controls", true),
    platform("prod_recovery", "Rollback + recovery orchestration", true),
    user("prod_domain", "Configure production domain and DNS", hasVercel || hasRender, "Custom domain and DNS are user-owned."),
    user("prod_secrets", "Set production secrets (DB/auth/payments)", !hasArchMissing && input.hasRepo, "Credentials and rotation remain user-owned."),
    user("prod_monitoring", "Enable production monitoring and alerting", false, "Monitoring ownership remains with workspace operators."),
    user("prod_backup", "Define backup and restore policy", false, "Backup/compliance policy is required before production trust is high."),
  ]);

  const all = [preview, staging, production];
  const total = all.reduce((acc, env) => acc + env.total, 0);
  const completed = all.reduce((acc, env) => acc + env.completed, 0);
  const scorePct = total ? Math.round((completed / total) * 100) : 0;

  return {
    scorePct,
    environments: all,
    nextUserActions: all.flatMap((env) => env.items.filter((item) => item.owner === "user" && item.status === "pending")).slice(0, 6),
  };
}

function summarize(environment: EnvironmentType, items: EnvironmentChecklistItem[]): EnvironmentChecklistSummary {
  const total = items.length;
  const completed = items.filter((item) => item.status === "done").length;
  const platformItems = items.filter((item) => item.owner === "platform");
  const platformCompleted = platformItems.filter((item) => item.status === "done").length;
  const userPending = items.filter((item) => item.owner === "user" && item.status === "pending").length;
  return {
    environment,
    total,
    completed,
    platformCompleted,
    platformTotal: platformItems.length,
    userPending,
    scorePct: total ? Math.round((completed / total) * 100) : 0,
    items,
  };
}

function platform(id: string, label: string, done: boolean, note = ""): EnvironmentChecklistItem {
  return { id, label, owner: "platform", status: done ? "done" : "pending", note: note || undefined };
}

function user(id: string, label: string, done: boolean, note = ""): EnvironmentChecklistItem {
  return { id, label, owner: "user", status: done ? "done" : "pending", note: note || undefined };
}
