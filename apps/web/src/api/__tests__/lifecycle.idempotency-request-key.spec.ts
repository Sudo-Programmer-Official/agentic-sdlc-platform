import { beforeEach, describe, expect, it, vi } from "vitest";

import { createRun, createRunPullRequest, forkRun, setActiveTenantId, setActiveWorkspaceId, setAuthToken } from "../lifecycle";

describe("lifecycle request_key transport", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    setAuthToken("token-123");
    setActiveTenantId("tenant-1");
    setActiveWorkspaceId("workspace-1");
  });

  it("sends request_key for createRun when provided", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ id: "run-1" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      })
    );
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    await createRun("project-1", "codex", "task-1", null, { request_key: "run-start-001" });

    const [, init] = fetchMock.mock.calls[0];
    const payload = JSON.parse(String((init as RequestInit).body));
    expect(payload.request_key).toBe("run-start-001");
  });

  it("sends request_key for forkRun when provided", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ id: "run-2" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      })
    );
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    await forkRun("run-1", { start_now: false, request_key: "run-fork-001" });

    const [, init] = fetchMock.mock.calls[0];
    const payload = JSON.parse(String((init as RequestInit).body));
    expect(payload.request_key).toBe("run-fork-001");
  });

  it("sends request_key for createRunPullRequest when provided", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ pull_request_url: "https://github.com/acme/repo/pull/1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    await createRunPullRequest("run-1", { artifact_id: "artifact-1", request_key: "create-pr-001" });

    const [, init] = fetchMock.mock.calls[0];
    const payload = JSON.parse(String((init as RequestInit).body));
    expect(payload.request_key).toBe("create-pr-001");
  });
});
