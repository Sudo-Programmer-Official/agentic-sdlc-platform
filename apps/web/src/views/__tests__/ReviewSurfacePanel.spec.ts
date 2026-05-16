import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ReviewSurfacePanel from "../../components/workbench/ReviewSurfacePanel.vue";

describe("ReviewSurfacePanel", () => {
  it("renders PR summary from diff metadata", () => {
    const wrapper = mount(ReviewSurfacePanel, {
      props: {
        patchArtifact: { uri: "workspace://patches/auth.patch" },
        files: ["apps/api/app/api/v1/persistence.py", "apps/web/src/views/MissionControl.vue"],
        additions: 42,
        deletions: 9,
        previewStatus: "READY",
        approvalStatus: "APPROVED",
        approvalNote: "Looks safe.",
        pullRequestUrl: null,
      },
    });

    const text = wrapper.text();
    expect(text).toContain("Files changed");
    expect(text).toContain("2");
    expect(text).toContain("+42 / -9");
    expect(text).toContain("READY");
    expect(text).toContain("APPROVED");
  });
});
