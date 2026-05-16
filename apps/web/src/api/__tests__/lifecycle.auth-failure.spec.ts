import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, setActiveTenantId, setActiveWorkspaceId, setAuthToken } from "../lifecycle";

describe("apiFetch auth failure handling", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    setAuthToken("token-123");
    setActiveTenantId("tenant-1");
    setActiveWorkspaceId("workspace-1");
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        ...originalLocation,
        pathname: "/projects/abc/run",
        search: "?tab=overview",
        assign: vi.fn(),
      },
    });
  });

  it("redirects to signin with actionable session_expired reason on 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("unauthorized", { status: 401 })) as unknown as typeof fetch
    );

    await apiFetch("/api/v1/projects");

    expect(window.location.assign).toHaveBeenCalledTimes(1);
    const redirectUrl = (window.location.assign as any).mock.calls[0][0] as string;
    expect(redirectUrl).toContain("/signin?");
    expect(redirectUrl).toContain("reason=session_expired");
    expect(redirectUrl).toContain("redirect=");
    expect(localStorage.getItem("agentic.authToken")).toBeNull();
    expect(localStorage.getItem("agentic.activeTenantId")).toBeNull();
    expect(localStorage.getItem("agentic.activeWorkspaceId")).toBeNull();
  });
});
