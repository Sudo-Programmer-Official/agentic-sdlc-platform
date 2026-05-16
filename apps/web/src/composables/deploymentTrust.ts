export type TrustTier = "Healthy" | "Warning" | "Critical";

export type TrustTone = "success" | "warning" | "danger";

export type DeploymentTrustSummary = {
  tier: TrustTier;
  tone: TrustTone;
  confidencePct: number;
  rollbackConfidencePct: number;
  evidence: string;
  blockers: string[];
};

type BuildTrustInput = {
  confidencePct: number;
  successPct?: number;
  blockerSignals?: Array<string | null | undefined>;
  evidence: string;
};

export function buildDeploymentTrustSummary(input: BuildTrustInput): DeploymentTrustSummary {
  const confidencePct = clampPercent(input.confidencePct);
  const successPct = clampPercent(input.successPct ?? confidencePct);
  const blockers = (input.blockerSignals || [])
    .map((item) => String(item || "").trim())
    .filter(Boolean)
    .slice(0, 4);
  const rollbackConfidencePct = clampPercent(Math.round((confidencePct * 0.6) + (successPct * 0.4)));
  let tier: TrustTier = "Healthy";
  if (confidencePct < 60 || successPct < 70) tier = "Critical";
  else if (confidencePct < 80 || successPct < 85 || blockers.length > 0) tier = "Warning";
  return {
    tier,
    tone: tier === "Critical" ? "danger" : tier === "Warning" ? "warning" : "success",
    confidencePct,
    rollbackConfidencePct,
    evidence: input.evidence,
    blockers,
  };
}

export function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}
