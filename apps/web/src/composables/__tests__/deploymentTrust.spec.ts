import { describe, expect, it } from "vitest";

import { buildDeploymentTrustSummary, clampPercent } from "../deploymentTrust";

describe("deploymentTrust", () => {
  it("clamps percentage values", () => {
    expect(clampPercent(-8)).toBe(0);
    expect(clampPercent(48.6)).toBe(49);
    expect(clampPercent(220)).toBe(100);
  });

  it("returns healthy tier for high confidence and no blockers", () => {
    const summary = buildDeploymentTrustSummary({
      confidencePct: 92,
      successPct: 95,
      evidence: "95% success",
    });
    expect(summary.tier).toBe("Healthy");
    expect(summary.tone).toBe("success");
    expect(summary.rollbackConfidencePct).toBeGreaterThanOrEqual(90);
    expect(summary.blockers).toEqual([]);
  });

  it("returns warning tier when blockers are present", () => {
    const summary = buildDeploymentTrustSummary({
      confidencePct: 88,
      successPct: 90,
      blockerSignals: ["manual degrade observed"],
      evidence: "manual degradation detected",
    });
    expect(summary.tier).toBe("Warning");
    expect(summary.tone).toBe("warning");
    expect(summary.blockers).toEqual(["manual degrade observed"]);
  });

  it("returns critical tier for low confidence", () => {
    const summary = buildDeploymentTrustSummary({
      confidencePct: 52,
      successPct: 84,
      evidence: "confidence dropped",
    });
    expect(summary.tier).toBe("Critical");
    expect(summary.tone).toBe("danger");
  });

  it("returns critical tier for low success rate", () => {
    const summary = buildDeploymentTrustSummary({
      confidencePct: 82,
      successPct: 64,
      evidence: "low deployment success",
    });
    expect(summary.tier).toBe("Critical");
    expect(summary.tone).toBe("danger");
  });

  it("caps blockers list at four entries", () => {
    const summary = buildDeploymentTrustSummary({
      confidencePct: 85,
      blockerSignals: ["a", "b", "c", "d", "e", "f"],
      evidence: "many blockers",
    });
    expect(summary.blockers).toEqual(["a", "b", "c", "d"]);
  });
});
