import { defineComponent, h } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectEnvironmentCenter from "../ProjectEnvironmentCenter.vue";

const routerMocks = vi.hoisted(() => ({
  push: vi.fn(),
  route: { params: { projectId: "proj-1" } as Record<string, any> },
}));

const lifecycleMocks = vi.hoisted(() => ({
  applyProjectEnvironmentTemplate: vi.fn(),
  fetchCapabilityGovernanceCheck: vi.fn(),
  fetchProjectDeploymentReadiness: vi.fn(),
  getProjectEnvironmentCenter: vi.fn(),
  getProjectEnvironmentChecklists: vi.fn(),
  listCapabilities: vi.fn(),
  listCapabilityBindings: vi.fn(),
  listCapabilityIntegrations: vi.fn(),
  listProjectComponentCapabilityContracts: vi.fn(),
  listProjectEnvironmentTemplates: vi.fn(),
  listProjectEnvironmentVariables: vi.fn(),
  syncProjectEnvironment: vi.fn(),
  approveProjectComponentCapabilityContract: vi.fn(),
  upsertCapabilityBinding: vi.fn(),
  upsertProjectComponentCapabilityContract: vi.fn(),
  upsertCapabilityIntegration: vi.fn(),
  upsertProjectEnvironmentVariable: vi.fn(),
  validateProjectEnvironment: vi.fn(),
  writeProjectEnvironmentVariableSecret: vi.fn(),
}));

const messageMocks = vi.hoisted(() => ({
  success: vi.fn(),
}));

vi.mock("vue-router", () => ({
  useRoute: () => routerMocks.route,
  useRouter: () => ({ push: routerMocks.push }),
}));

vi.mock("element-plus", () => ({
  ElMessage: {
    success: messageMocks.success,
  },
}));

vi.mock("../../api/lifecycle", () => ({
  applyProjectEnvironmentTemplate: lifecycleMocks.applyProjectEnvironmentTemplate,
  fetchCapabilityGovernanceCheck: lifecycleMocks.fetchCapabilityGovernanceCheck,
  fetchProjectDeploymentReadiness: lifecycleMocks.fetchProjectDeploymentReadiness,
  getProjectEnvironmentCenter: lifecycleMocks.getProjectEnvironmentCenter,
  getProjectEnvironmentChecklists: lifecycleMocks.getProjectEnvironmentChecklists,
  listCapabilities: lifecycleMocks.listCapabilities,
  listCapabilityBindings: lifecycleMocks.listCapabilityBindings,
  listCapabilityIntegrations: lifecycleMocks.listCapabilityIntegrations,
  listProjectComponentCapabilityContracts: lifecycleMocks.listProjectComponentCapabilityContracts,
  listProjectEnvironmentTemplates: lifecycleMocks.listProjectEnvironmentTemplates,
  listProjectEnvironmentVariables: lifecycleMocks.listProjectEnvironmentVariables,
  syncProjectEnvironment: lifecycleMocks.syncProjectEnvironment,
  approveProjectComponentCapabilityContract: lifecycleMocks.approveProjectComponentCapabilityContract,
  upsertCapabilityBinding: lifecycleMocks.upsertCapabilityBinding,
  upsertProjectComponentCapabilityContract: lifecycleMocks.upsertProjectComponentCapabilityContract,
  upsertCapabilityIntegration: lifecycleMocks.upsertCapabilityIntegration,
  upsertProjectEnvironmentVariable: lifecycleMocks.upsertProjectEnvironmentVariable,
  validateProjectEnvironment: lifecycleMocks.validateProjectEnvironment,
  writeProjectEnvironmentVariableSecret: lifecycleMocks.writeProjectEnvironmentVariableSecret,
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
          onClick: () => {
            if (!props.disabled) emit("click");
          },
        },
        slots.default ? slots.default() : ""
      );
  },
});

const ElInputStub = defineComponent({
  name: "ElInput",
  props: {
    modelValue: { type: String, default: "" },
    placeholder: { type: String, default: "" },
  },
  emits: ["update:modelValue"],
  setup(props, { emit }) {
    return () =>
      h("input", {
        value: props.modelValue,
        placeholder: props.placeholder,
        onInput: (event: Event) => emit("update:modelValue", (event.target as HTMLInputElement).value),
      });
  },
});

function mountView() {
  return mount(ProjectEnvironmentCenter, {
    global: {
      stubs: {
        "el-button": ElButtonStub,
        "el-input": ElInputStub,
        "el-select": true,
        "el-option": true,
        "el-segmented": true,
        "el-switch": true,
        "el-dialog": true,
        AppIcon: true,
        MetricCard: true,
        DeploymentTrustSurfaceCard: true,
      },
    },
  });
}

function primeLoadMocks() {
  lifecycleMocks.getProjectEnvironmentCenter.mockResolvedValue({ project_id: "proj-1", environments: [] });
  lifecycleMocks.getProjectEnvironmentChecklists.mockResolvedValue({ score_pct: 0, environments: [], items: [] });
  lifecycleMocks.listProjectEnvironmentTemplates.mockResolvedValue([]);
  lifecycleMocks.listProjectEnvironmentVariables.mockResolvedValue([]);
  lifecycleMocks.listCapabilities.mockResolvedValue([]);
  lifecycleMocks.listCapabilityIntegrations.mockResolvedValue([]);
  lifecycleMocks.listCapabilityBindings.mockResolvedValue([]);
  lifecycleMocks.fetchCapabilityGovernanceCheck.mockResolvedValue({ unresolved_required_capabilities: [] });
  lifecycleMocks.fetchProjectDeploymentReadiness.mockResolvedValue(null);
  lifecycleMocks.listProjectComponentCapabilityContracts.mockResolvedValue([
    {
      id: "ctr-1",
      tenant_id: "t-1",
      project_id: "proj-1",
      environment: "PREVIEW",
      capability: "HeroSection",
      contract_json: {},
      status: "DRAFT",
      created_at: "2026-05-17T00:00:00Z",
      updated_at: "2026-05-17T00:00:00Z",
    },
  ]);
}

describe("ProjectEnvironmentCenter component capability contracts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    primeLoadMocks();
  });

  it("loads component capability contracts on mount", async () => {
    mountView();
    await flushPromises();
    expect(lifecycleMocks.listProjectComponentCapabilityContracts).toHaveBeenCalledWith("proj-1", "PREVIEW");
  });

  it("upserts component capability contract and shows success", async () => {
    lifecycleMocks.upsertProjectComponentCapabilityContract.mockResolvedValue({
      id: "ctr-2",
      tenant_id: "t-1",
      project_id: "proj-1",
      environment: "PREVIEW",
      capability: "PricingCard",
      contract_json: {},
      status: "DRAFT",
      created_at: "2026-05-17T00:00:00Z",
      updated_at: "2026-05-17T00:00:00Z",
    });
    const wrapper = mountView();
    await flushPromises();

    const capabilityInput = wrapper.find('input[placeholder="Capability (e.g. HeroSection)"]');
    await capabilityInput.setValue("PricingCard");
    const variantInput = wrapper.find('input[placeholder="Variant (e.g. premium_saas)"]');
    await variantInput.setValue("premium_saas");
    const allowedPropsInput = wrapper.find('input[placeholder="Allowed props CSV (headline,subtitle,ctaLabel)"]');
    await allowedPropsInput.setValue("headline, subtitle");
    const slotsInput = wrapper.find('input[placeholder="Slots CSV (title,subtitle,primaryCta)"]');
    await slotsInput.setValue("title, primaryCta");
    const tokensInput = wrapper.find('input[placeholder="Tokens CSV (--color-brand-600,--space-6)"]');
    await tokensInput.setValue("--color-brand-600");
    const variantsInput = wrapper.find('input[placeholder="Variants CSV (premium_saas,enterprise_clean)"]');
    await variantsInput.setValue("premium_saas,enterprise_clean");

    const upsertButton = wrapper.findAll("button").find((btn) => btn.text().includes("Upsert Contract"));
    expect(upsertButton).toBeDefined();
    await upsertButton!.trigger("click");
    await flushPromises();

    expect(lifecycleMocks.upsertProjectComponentCapabilityContract).toHaveBeenCalledWith("proj-1", {
      environment: "PREVIEW",
      capability: "PricingCard",
      contract_json: {
        capability: "PricingCard",
        variant: "premium_saas",
        allowed_props: ["headline", "subtitle"],
        slots: ["title", "primaryCta"],
        tokens: ["--color-brand-600"],
        variants: ["premium_saas", "enterprise_clean"],
      },
    });
    expect(messageMocks.success).toHaveBeenCalledWith("Component capability contract upserted.");
  });

  it("approves capability contract and reports success", async () => {
    lifecycleMocks.approveProjectComponentCapabilityContract.mockResolvedValue({
      id: "ctr-1",
      tenant_id: "t-1",
      project_id: "proj-1",
      environment: "PREVIEW",
      capability: "HeroSection",
      contract_json: {},
      status: "APPROVED",
      approved_at: "2026-05-17T00:00:00Z",
      created_at: "2026-05-17T00:00:00Z",
      updated_at: "2026-05-17T00:00:00Z",
    });
    const wrapper = mountView();
    await flushPromises();

    const approveButton = wrapper.findAll("button").find((btn) => btn.text().includes("Approve Contract"));
    expect(approveButton).toBeDefined();
    await approveButton!.trigger("click");
    await flushPromises();

    expect(lifecycleMocks.approveProjectComponentCapabilityContract).toHaveBeenCalledWith("proj-1", {
      environment: "PREVIEW",
      capability: "HeroSection",
    });
    expect(messageMocks.success).toHaveBeenCalledWith("Component capability contract approved.");
  });

  it("renders API error when contract reload fails", async () => {
    const wrapper = mountView();
    await flushPromises();
    lifecycleMocks.listProjectComponentCapabilityContracts.mockRejectedValueOnce(new Error("contracts load failed"));
    const reloadButton = wrapper.findAll("button").find((btn) => btn.text().includes("Reload Contracts"));
    expect(reloadButton).toBeDefined();
    await reloadButton!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("contracts load failed");
  });
});
