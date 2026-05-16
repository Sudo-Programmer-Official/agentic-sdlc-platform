import { expect, test } from "@playwright/test";

test.describe("Tenant auth smoke", () => {
  test("happy path in one shot: task -> run -> approval -> preview -> pr", async ({ page }) => {
    await page.route("**/api/v1/projects/e2e-project-1/tasks", async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "task-1", title: "E2E smoke task" }),
      });
    });
    await page.route("**/api/v1/projects/e2e-project-1/runs", async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "run-1", status: "QUEUED" }),
      });
    });
    await page.route("**/api/v1/projects/e2e-project-1/approvals", async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "approval-1", status: "PENDING" }),
      });
    });
    await page.route("**/api/v1/runs/run-1/preview", async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ run_id: "run-1", status: "READY", preview_url: "http://127.0.0.1:3100" }),
      });
    });
    await page.route("**/api/v1/runs/run-1/create-pr", async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ pull_request_url: "https://github.com/acme/repo/pull/101" }),
      });
    });

    await page.goto("/__e2e__/smoke");
    await page.getByRole("button", { name: "Run Happy Path" }).click();
    await expect(page.getByText("happy-path:success")).toBeVisible();
  });

  test("slow network retry path reuses request_key and avoids duplicates", async ({ page }) => {
    const seen: string[] = [];
    await page.route("**/api/v1/projects/e2e-project-1/runs", async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      const body = route.request().postDataJSON() as { request_key?: string } | null;
      const key = String(body?.request_key || "");
      seen.push(key);
      await page.waitForTimeout(300); // simulate slow network
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "run-retry-1", status: "QUEUED" }),
      });
    });

    await page.goto("/__e2e__/smoke");
    await page.getByRole("button", { name: "Run Retry Path" }).click();
    await expect(page.getByText("retry-path:success")).toBeVisible();
    expect(seen.length).toBe(2);
    expect(seen[0]).toBeTruthy();
    expect(seen[0]).toBe(seen[1]);
  });
});
