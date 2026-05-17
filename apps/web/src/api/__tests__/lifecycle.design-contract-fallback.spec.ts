import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchDesignContract, saveDesignContract, setAuthToken } from "../lifecycle";

describe("fetchDesignContract fallback", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    setAuthToken("token-123");
  });

  it("falls back to project-contract when design-contract endpoint returns 404", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response("Not Found", { status: 404 }))
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              contract_json: {
                design_contract: {
                  experience_blueprint: "enterprise_operational",
                  identity: { tone: "governed_structured_stable" },
                },
              },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        ) as unknown as typeof fetch
    );

    const payload = await fetchDesignContract("proj-1");
    expect(payload.experience_blueprint).toBe("enterprise_operational");
    expect(payload.identity?.tone).toBe("governed_structured_stable");
  });

  it("saves through project-contract when design-contract PUT returns 404", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("Not Found", { status: 404 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            status: "ACTIVE",
            source: "DERIVED",
            summary: "existing",
            contract_json: { design_contract: { allowed_components: ["OldCard"] } },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "pc-1",
            status: "ACTIVE",
            source: "DERIVED",
            contract_json: { design_contract: { allowed_components: ["NewCard"] } },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      );
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    const saved = await saveDesignContract("proj-1", { allowed_components: ["NewCard"] });

    expect(saved.status).toBe("ACTIVE");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const finalCall = fetchMock.mock.calls[2];
    expect(finalCall[0]).toContain("/projects/proj-1/project-contract");
    expect((finalCall[1] as RequestInit).method).toBe("POST");
  });
});
