import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SignIn from "../SignIn.vue";

const routerMocks = vi.hoisted(() => ({
  replace: vi.fn(),
  route: { query: { redirect: "/projects/p1/run" } as Record<string, any> },
}));

const authMocks = vi.hoisted(() => ({
  loginWithEmailPassword: vi.fn(),
  signupWithEmailPassword: vi.fn(),
}));

const lifecycleMocks = vi.hoisted(() => ({
  getAuthToken: vi.fn(),
}));

vi.mock("vue-router", () => ({
  useRoute: () => routerMocks.route,
  useRouter: () => ({ replace: routerMocks.replace }),
}));

vi.mock("../../auth/firebaseAuth", () => ({
  loginWithEmailPassword: authMocks.loginWithEmailPassword,
  signupWithEmailPassword: authMocks.signupWithEmailPassword,
}));

vi.mock("../../api/lifecycle", () => ({
  getAuthToken: lifecycleMocks.getAuthToken,
}));

describe("SignIn", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routerMocks.route.query = { redirect: "/projects/p1/run" };
  });

  it("redirects after successful login when token is available immediately", async () => {
    authMocks.loginWithEmailPassword.mockResolvedValue(undefined);
    lifecycleMocks.getAuthToken.mockReturnValue("token-abc");

    const wrapper = mount(SignIn);
    const inputs = wrapper.findAll("input");
    await inputs[0].setValue("dev@example.com");
    await inputs[1].setValue("secret123");
    await wrapper.find("form").trigger("submit.prevent");
    await flushPromises();

    expect(authMocks.loginWithEmailPassword).toHaveBeenCalledWith("dev@example.com", "secret123");
    expect(routerMocks.replace).toHaveBeenCalledWith("/projects/p1/run");
    expect(wrapper.text()).not.toContain("Session not established yet");
  });

  it("shows session message when login succeeds but token is still missing", async () => {
    authMocks.loginWithEmailPassword.mockResolvedValue(undefined);
    lifecycleMocks.getAuthToken.mockReturnValue(null);

    const wrapper = mount(SignIn);
    const inputs = wrapper.findAll("input");
    await inputs[0].setValue("dev@example.com");
    await inputs[1].setValue("secret123");
    await wrapper.find("form").trigger("submit.prevent");
    await flushPromises();

    expect(routerMocks.replace).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("Session not established yet. Try again.");
  });
});
