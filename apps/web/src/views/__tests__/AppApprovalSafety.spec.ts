import { defineComponent, h, nextTick } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "../../App.vue";
import { projectContext } from "../../state/projectContext";

const pushMock = vi.fn();

const lifecycleMocks = vi.hoisted(() => ({
  getActiveTenantId: vi.fn(),
  getActiveWorkspaceId: vi.fn(),
  getActiveWorkspaceMeta: vi.fn(),
  listApprovals: vi.fn(),
  listRuns: vi.fn(),
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ path: "/" }),
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("../../api/lifecycle", () => ({
  getActiveTenantId: lifecycleMocks.getActiveTenantId,
  getActiveWorkspaceId: lifecycleMocks.getActiveWorkspaceId,
  getActiveWorkspaceMeta: lifecycleMocks.getActiveWorkspaceMeta,
  listApprovals: lifecycleMocks.listApprovals,
  listRuns: lifecycleMocks.listRuns,
}));

vi.mock("../../api/http", () => ({
  isApiErrorStatus: (err: any, status: number) => Number(err?.status) === Number(status),
}));

const ElDialogStub = defineComponent({
  name: "ElDialog",
  props: { modelValue: Boolean },
  emits: ["update:modelValue"],
  setup(props, { slots }) {
    return () =>
      props.modelValue
        ? h("div", { class: "el-dialog-stub" }, [
            slots.header ? h("div", { class: "dialog-header" }, slots.header()) : null,
            slots.default ? h("div", { class: "dialog-body" }, slots.default()) : null,
            slots.footer ? h("div", { class: "dialog-footer" }, slots.footer()) : null,
          ])
        : null;
  },
});

const ElButtonStub = defineComponent({
  name: "ElButton",
  emits: ["click"],
  setup(_, { emit, slots }) {
    return () => h("button", { onClick: () => emit("click") }, slots.default ? slots.default() : "");
  },
});

function mountApp() {
  return mount(App, {
    global: {
      stubs: {
        "router-link": defineComponent({
          props: { to: { type: [String, Object], required: false } },
          setup(_, { slots }) {
            return () => h("a", {}, slots.default ? slots.default() : "");
          },
        }),
        "router-view": defineComponent({ setup: () => () => h("div", "view") }),
        TopBar: defineComponent({ setup: () => () => h("div", "topbar") }),
        AppIcon: defineComponent({ setup: () => () => h("span", "icon") }),
        AiOperatorPanel: defineComponent({ setup: () => () => h("div", "operator") }),
        "el-dialog": ElDialogStub,
        "el-button": ElButtonStub,
      },
    },
  });
}

describe("App approval safety", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    pushMock.mockReset();
    projectContext.projectId = "proj-1";
    projectContext.projectName = "Project One";
    lifecycleMocks.getActiveTenantId.mockReturnValue("tenant-1");
    lifecycleMocks.getActiveWorkspaceId.mockReturnValue("ws-1");
    lifecycleMocks.getActiveWorkspaceMeta.mockReturnValue({ id: "ws-1", name: "Workspace One" });
  });

  it("does not show operator approval dialog when queue is empty and run is not paused for operator confirmation", async () => {
    lifecycleMocks.listApprovals.mockResolvedValue([]);
    lifecycleMocks.listRuns.mockResolvedValue([
      { id: "run-1", status: "RUNNING", summary: {} },
    ]);

    const wrapper = mountApp();
    await flushPromises();
    await nextTick();

    expect(wrapper.text()).not.toContain("Operator Confirmation Required");
    expect(wrapper.text()).not.toContain("Approval Required");
  });

  it("routes Go to Exact Run to debug page for paused operator-confirmation run", async () => {
    lifecycleMocks.listApprovals.mockResolvedValue([]);
    lifecycleMocks.listRuns.mockResolvedValue([
      {
        id: "run-op-123",
        status: "PAUSED",
        summary: {
          operator_confirmation_pause: { reason: "operator_confirmation_required" },
          resume_state: { failed_error: "" },
        },
      },
    ]);

    const wrapper = mountApp();
    await flushPromises();
    await nextTick();

    const goToExactRun = wrapper.findAll("button").find((btn) => btn.text().includes("Go to Exact Run"));
    expect(goToExactRun).toBeDefined();
    await goToExactRun!.trigger("click");

    expect(pushMock).toHaveBeenCalledWith("/projects/proj-1/runs/run-op-123/debug");
  });
});
