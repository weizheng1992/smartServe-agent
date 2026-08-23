import { test, expect } from "@playwright/test";

test.describe("Admin SaaS Control Plane E2E Tests", () => {
  test.beforeEach(async ({ page }) => {
    // 访问 admin 控制平面 (端口 3001)
    await page.goto("http://localhost:3001/tenants");
  });

  test("should render Admin Layout and navigation items properly", async ({
    page,
  }) => {
    await expect(page.locator("text=SaaS Control Plane")).toBeVisible();
    await expect(page.locator("text=商户管理 (Tenants)")).toBeVisible();
    await expect(page.locator("text=会话与决策回放")).toBeVisible();
    await expect(page.locator("text=风控审批审计")).toBeVisible();
  });

  test("should switch global tenant via Top Header Selector", async ({
    page,
  }) => {
    const tenantSelect = page.locator("header select");
    await expect(tenantSelect).toBeVisible();

    // 切换到 Nike 官方旗舰店
    await tenantSelect.selectOption("nike");
    await expect(page.locator("text=NIKE")).toBeVisible();
  });

  test("should navigate across main modules and render data tables", async ({
    page,
  }) => {
    // 1. 跳转到 会话与决策回放
    await page.click("text=会话与决策回放");
    await expect(page).toHaveURL(/.*\/conversations/);
    await expect(page.locator("text=会话 ID / Trace ID")).toBeVisible();

    // 2. 跳转到 风控审批审计
    await page.click("text=风控审批审计");
    await expect(page).toHaveURL(/.*\/audits/);
    await expect(page.locator("text=审批工单 ID / 会话")).toBeVisible();

    // 3. 跳转到 知识库 RAG Studio
    await page.click("text=知识库 RAG Studio");
    await expect(page).toHaveURL(/.*\/rag-studio/);
    await expect(page.locator("text=检索演练台 (Playground)")).toBeVisible();

    // 4. 跳转到 计量计费 (Billing)
    await page.click("text=计量计费 (Billing)");
    await expect(page).toHaveURL(/.*\/billing/);
    await expect(page.locator("text=平台累计消耗 Token")).toBeVisible();
  });
});
