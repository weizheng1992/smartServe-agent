import { expect, test } from '@playwright/test';

/**
 * Admin 控制平面冒烟 E2E(wayfinder 004 对齐修缮):原 spec 钉的是旧版侧栏
 * 文案("SaaS Control Plane" / 原生 select 租户切换),CRUD 套件改版后早已
 * 全量失配 —— 断言全部锚定当前 AdminLayout/Sidebar/Header 真实渲染文案,
 * 租户切换器按 Combobox(role="combobox" + label 选项)交互,种子仅注册
 * aurora(极光潮品官方旗舰店)一个租户。
 */
test.describe('Admin SaaS Control Plane E2E Tests', () => {
  test.beforeEach(async ({ page }) => {
    // 访问 admin 控制平面 (端口 3001)
    await page.goto('http://localhost:3001/tenants');
  });

  test('should render Admin Layout and navigation items properly', async ({ page }) => {
    await expect(page.locator('text=Agent Control Plane')).toBeVisible();
    // 必须锚定侧栏 link 角色:/tenants 页面 h2 标题与导航同名,纯 text= 会 strict mode 撞车
    await expect(page.getByRole('link', { name: '商户租户管理' })).toBeVisible();
    await expect(page.getByRole('link', { name: '全景会话回放' })).toBeVisible();
    await expect(page.getByRole('link', { name: '审批与风控审计' })).toBeVisible();
  });

  test('should switch global tenant via Top Header Selector', async ({ page }) => {
    // 全局租户穿透切换器是自研 Combobox(非原生 select):点开触发器后按租户名选
    const comboboxTrigger = page.locator('header [role="combobox"]');
    await expect(comboboxTrigger).toBeVisible();
    await comboboxTrigger.click();
    // 选项是 cmdk CommandItem(role="option",span 结构,非 <label>),名称含租户名 + ID 行
    await page.getByRole('option', { name: /极光潮品官方旗舰店/ }).click();
    await expect(page.locator('header [role="combobox"]')).toContainText('极光潮品官方旗舰店');
  });

  test('should navigate across main modules and render data tables', async ({ page }) => {
    // 1. 跳转到 全景会话回放(link 角色锚定侧栏,避免与页面标题同名撞车)
    await page.getByRole('link', { name: '全景会话回放' }).click();
    await expect(page).toHaveURL(/.*\/conversations/);
    await expect(page.locator('text=会话 ID / 用户')).toBeVisible();

    // 2. 跳转到 审批与风控审计
    await page.getByRole('link', { name: '审批与风控审计' }).click();
    await expect(page).toHaveURL(/.*\/audits/);
    await expect(page.locator('text=审批工单 ID / 会话')).toBeVisible();

    // 3. 跳转到 知识库与检索演练
    await page.getByRole('link', { name: '知识库与检索演练' }).click();
    await expect(page).toHaveURL(/.*\/rag-studio/);
    await expect(page.locator('text=RAG 向量检索在线演练台')).toBeVisible();

    // 4. 跳转到 计量计费与配额
    await page.getByRole('link', { name: '计量计费与配额' }).click();
    await expect(page).toHaveURL(/.*\/billing/);
    await expect(page.locator('text=本月 Token 消耗 / 水位')).toBeVisible();
  });
});
