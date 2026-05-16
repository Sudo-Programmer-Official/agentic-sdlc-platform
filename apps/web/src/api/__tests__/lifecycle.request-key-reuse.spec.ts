import { beforeEach, describe, expect, it, vi } from "vitest";

import { getOrCreateActionRequestKey } from "../lifecycle";

describe("getOrCreateActionRequestKey", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("reuses request key for same action scope within ttl", () => {
    const first = getOrCreateActionRequestKey("start_run", "mission_control:intake:project-1:item-1", 60_000);
    const second = getOrCreateActionRequestKey("start_run", "mission_control:intake:project-1:item-1", 60_000);
    expect(second).toBe(first);
  });

  it("rotates request key after ttl expires", () => {
    const nowSpy = vi.spyOn(Date, "now");
    nowSpy.mockReturnValue(1_000);
    const first = getOrCreateActionRequestKey("fork_run", "operator_dashboard:fork:run-1", 1_000);
    nowSpy.mockReturnValue(2_500);
    const second = getOrCreateActionRequestKey("fork_run", "operator_dashboard:fork:run-1", 1_000);
    expect(second).not.toBe(first);
  });
});
