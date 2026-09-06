import { expect, test } from '@playwright/test';

import { E2E_ACCOUNT_EMAIL, E2E_ACCOUNT_PASSWORD, loginViaUi } from './helpers/auth';

// 前置:后端 + 种子就绪(docker:up / db:push / db:seed / dev:server),
// playwright webServer 只负责前端(3000)。
// 注:真正的 HITL 审批挂起→核签流程 E2E 由 wayfinder ticket 004 补齐,
// 本文件先钉死真实登录链路(auth 真实化)与主屏布局渲染。
test.describe('智能客服平台前端 E2E 用户旅程测试', () => {
  test('未登录用户应被重定向到登录页,凭种子账号真实登录成功', async ({ page }) => {
    // 未登录访问首页 → 授权拦截重定向 /login
    await page.goto('/');
    await expect(page).toHaveURL(/\/login/);

    // 登录卡片渲染(标题 + 邮箱/密码双输入 + 提交按钮)
    await expect(page.getByText('分布式智能客服控制中心')).toBeVisible();
    await expect(page.locator('input[type="email"]')).toBeVisible();
    await expect(page.locator('input[type="password"]')).toBeVisible();

    // 走真实 /api/auth/login(密码来自 engine seed)
    await page.locator('input[type="email"]').fill(E2E_ACCOUNT_EMAIL);
    await page.locator('input[type="password"]').fill(E2E_ACCOUNT_PASSWORD);
    await page.locator('button[type="submit"]').click();

    // 登录成功,回到主聊面板 `/`
    await expect(page).toHaveURL('/');
  });

  test('错误密码登录被拒绝并提示统一文案', async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="email"]').fill(E2E_ACCOUNT_EMAIL);
    await page.locator('input[type="password"]').fill('wrong-password');
    await page.locator('button[type="submit"]').click();

    // 网关统一 401 文案(防账号枚举),且不发生跳转
    await expect(page.getByText('邮箱或密码错误')).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test('登录用户进入主聊天屏应能看到历史会话面板与对话输入框', async ({ page }) => {
    await loginViaUi(page);

    // 1. 左侧历史会话面板
    const leftSidebar = page.locator('aside');
    await expect(leftSidebar).toBeVisible();

    // 2. 聊天输入框(极速问候旁路同款入口)
    const messageInput = page.locator('input[placeholder*="发送您的业务诉求"]');
    await expect(messageInput).toBeVisible();

    // 3. 顶部人工接管入口(header 稳定品牌与 IM 呼叫按钮)
    const tokenHeader = page.locator('header');
    await expect(tokenHeader).toContainText('E-COMMERCE CORE');
    await expect(tokenHeader).toContainText('呼叫人工客服');
  });
});
