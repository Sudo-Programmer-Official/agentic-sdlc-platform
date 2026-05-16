import { defineComponent, h } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi, beforeEach } from "vitest";

import AdminConsole from "../AdminConsole.vue";

const lifecycleMocks = vi.hoisted(() => ({
  listAdminWorkspaces: vi.fn(),
  listAdminAuditLogs: vi.fn(),
  startAdminImpersonation: vi.fn(),
  endAdminImpersonation: vi.fn(),
  getAdminWorkspaceEntitlements: vi.fn(),
  patchAdminWorkspaceEntitlements: vi.fn(),
  getAdminWorkspaceUsage: vi.fn(),
  materializeAdminWorkspaceUsage: vi.fn(),
  listAdminAnomalies: vi.fn(),
  materializeAdminAnomalies: vi.fn(),
  getAdminDaemonHealth: vi.fn(),
}));

vi.mock("../../api/lifecycle", () => ({
  listAdminWorkspaces: lifecycleMocks.listAdminWorkspaces,
  listAdminAuditLogs: lifecycleMocks.listAdminAuditLogs,
  startAdminImpersonation: lifecycleMocks.startAdminImpersonation,
  endAdminImpersonation: lifecycleMocks.endAdminImpersonation,
  getAdminWorkspaceEntitlements: lifecycleMocks.getAdminWorkspaceEntitlements,
  patchAdminWorkspaceEntitlements: lifecycleMocks.patchAdminWorkspaceEntitlements,
  getAdminWorkspaceUsage: lifecycleMocks.getAdminWorkspaceUsage,
  materializeAdminWorkspaceUsage: lifecycleMocks.materializeAdminWorkspaceUsage,
  listAdminAnomalies: lifecycleMocks.listAdminAnomalies,
  materializeAdminAnomalies: lifecycleMocks.materializeAdminAnomalies,
  getAdminDaemonHealth: lifecycleMocks.getAdminDaemonHealth,
}));

vi.mock("../../api/http", () => ({
  isApiErrorStatus: (err: any, status: number) => Number(err?.status) === Number(status),
}));

const ElButtonStub = defineComponent({
  name: "ElButton",
  props: {
    disabled: Boolean,
  },
  emits: ["click"],
  setup(props, { emit, slots }) {
    return () =>
      h(
        "button",
        {
          disabled: props.disabled,
          onClick: () => emit("click"),
        },
        slots.default ? slots.default() : ""
      );
  },
});

const ElInputStub = defineComponent({
  name: "ElInput",
  props: {
    modelValue: { type: String, default: "" },
    type: { type: String, default: "text" },
  },
  emits: ["update:modelValue"],
  setup(props, { emit }) {
    return () => {
      if (props.type === "textarea") {
        return h("textarea", {
          value: props.modelValue,
          onInput: (event: Event) => emit("update:modelValue", (event.target as HTMLTextAreaElement).value),
        });
      }
      return h("input", {
        value: props.modelValue,
        onInput: (event: Event) => emit("update:modelValue", (event.target as HTMLInputElement).value),
      });
    };
  },
});

function mountAdminConsole() {
  return mount(AdminConsole, {
    global: {
      stubs: {
        "el-button": ElButtonStub,
        "el-input": ElInputStub,
      },
    },
  });
}

describe("AdminConsole", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows super-admin required message when bootstrap API returns 403", async () => {
    lifecycleMocks.listAdminWorkspaces.mockRejectedValueOnce({ status: 403, message: "forbidden" });
    lifecycleMocks.listAdminAuditLogs.mockResolvedValueOnce([]);
    lifecycleMocks.getAdminWorkspaceUsage.mockResolvedValue({ totals: {} });
    lifecycleMocks.getAdminWorkspaceEntitlements.mockResolvedValue({ plan: "starter", limits: {}, features: {} });
    lifecycleMocks.listAdminAnomalies.mockResolvedValue([]);
    lifecycleMocks.getAdminDaemonHealth.mockResolvedValue({
      last_cycle_workspaces_processed: 0,
      last_cycle_workspace_failures: 0,
    });

    const wrapper = mountAdminConsole();
    await flushPromises();

    expect(wrapper.text()).toContain("Super admin access required.");
  });

  it("starts and ends impersonation for selected workspace", async () => {
    lifecycleMocks.listAdminWorkspaces.mockResolvedValue([{ id: "ws-1", name: "Workspace One" }]);
    lifecycleMocks.listAdminAuditLogs.mockResolvedValue([]);
    lifecycleMocks.getAdminWorkspaceEntitlements.mockResolvedValue({ plan: "starter", limits: {}, features: {} });
    lifecycleMocks.getAdminWorkspaceUsage.mockResolvedValue({
      totals: {
        usage_date: "total",
        runs_count: 0,
        deployments_count: 0,
        recoveries_count: 0,
        input_tokens: 0,
        output_tokens: 0,
        total_cost_cents: 0,
      },
    });
    lifecycleMocks.listAdminAnomalies.mockResolvedValue([]);
    lifecycleMocks.getAdminDaemonHealth.mockResolvedValue({
      last_cycle_workspaces_processed: 1,
      last_cycle_workspace_failures: 0,
    });
    lifecycleMocks.startAdminImpersonation.mockResolvedValue({ id: "session-12345678" });
    lifecycleMocks.endAdminImpersonation.mockResolvedValue({ id: "session-12345678", is_active: false });

    const wrapper = mountAdminConsole();
    await flushPromises();

    const workspaceButton = wrapper.findAll("button").find((btn) => btn.text().includes("Workspace One"));
    expect(workspaceButton).toBeDefined();
    await workspaceButton!.trigger("click");

    const reasonBox = wrapper.find("textarea");
    await reasonBox.setValue("Incident triage");

    const startButton = wrapper.findAll("button").find((btn) => btn.text().trim() === "Start");
    expect(startButton).toBeDefined();
    await startButton!.trigger("click");
    await flushPromises();

    expect(lifecycleMocks.startAdminImpersonation).toHaveBeenCalledWith({
      workspace_id: "ws-1",
      reason: "Incident triage",
      duration_minutes: 60,
    });

    const endButton = wrapper.findAll("button").find((btn) => btn.text().trim() === "End");
    expect(endButton).toBeDefined();
    await endButton!.trigger("click");
    await flushPromises();

    expect(lifecycleMocks.endAdminImpersonation).toHaveBeenCalledWith("session-12345678");
  });
});
