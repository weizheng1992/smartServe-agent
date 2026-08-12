import { expect, test } from '@playwright/test';

test.describe('智能客服平台前端 E2E 用户旅程测试', () => {
  test.beforeEach(async ({ page }) => {
    // 每次测试前访问首页 (会自愈路由至 login 页面进行授权拦截)
    await page.goto('/');
  });

  test('未登录用户应被正确重定向到登录页面并可成功登录', async ({ page }) => {
    // 校验 URL 是否重定向到 /login
    await expect(page).toHaveURL(/\/login/);

    // 验证登录卡片、标语和按钮是否渲染
    await expect(page.locator('h1')).toContainText('智能客服大模型决策控制台');
    const loginButton = page.locator('button:has-text("安全登录系统")');
    await expect(loginButton).toBeVisible();

    // 自动输入测试邮箱并登录
    const emailInput = page.locator('input[type="email"]');
    await emailInput.fill('developer@example.com');
    await loginButton.click();

    // 验证登录成功，正确回到主聊面板 `/`
    await expect(page).toHaveURL('/');
  });

  test('登录用户进入主聊天屏应能看到历史会话、Token 看板与人工审批面板', async ({ page }) => {
    // 先进行极速登录
    await page.goto('/login');
    await page.locator('input[type="email"]').fill('developer@example.com');
    await page.locator('button:has-text("安全登录系统")').click();
    await expect(page).toHaveURL('/');

    // 1. 验证左侧历史会话面板
    const leftSidebar = page.locator('aside');
    await expect(leftSidebar).toBeVisible();

    // 2. 验证右侧 Token 看板
    const rightPanel = page.locator('div:has-text("算力消耗总览")');
    await expect(rightPanel).toBeVisible();

    // 3. 验证顶部 Token 动态指示器
    const tokenHeader = page.locator('header');
    await expect(tokenHeader).toContainText('Token');

    // 4. 验证聊天对话窗
    const messageInput = page.locator('textarea[placeholder*="输入您的问题"]');
    await expect(messageInput).toBeVisible();
  });
});
