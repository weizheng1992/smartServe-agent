import { expect, test } from '@playwright/test';

test.describe('智能客服多轮对话自动化测试 (E2E Automated Dialog Tests)', () => {
  test.beforeEach(async ({ page }) => {
    // 每次测试前，首先进行安全登录
    await page.goto('/login');
    await page.locator('input[type="email"]').fill('tester_dialog@example.com');
    await page.locator('button:has-text("安全登录系统")').click();
    await expect(page).toHaveURL('/');
  });

  test('测试 1: 极速问候旁路通道 (Lightning Greeting Bypass Test)', async ({ page }) => {
    // 1. 确认主面板已成功渲染，且输入框可用
    const messageInput = page.locator('input[placeholder*="发送您的业务诉求"]');
    await expect(messageInput).toBeVisible();

    // 2. 发送纯打招呼指令 "你好"
    await messageInput.fill('你好');
    await page.locator('button:has-text("发送")').click();

    // 3. 校验由于 Lightning Bypass，系统应在毫秒级内输出欢迎导购界面，不调用大模型
    const chatContainer = page.locator('div.overflow-y-auto');
    await expect(chatContainer).toContainText('您好！我是您的智能电商客服助理');
    await expect(chatContainer).toContainText('订单物流查询');
    await expect(chatContainer).toContainText('快捷退款办理');
  });

  test('测试 2: 查单物流与 ownership 验证 (Order Status Tool Tracking Test)', async ({ page }) => {
    const messageInput = page.locator('input[placeholder*="发送您的业务诉求"]');
    await expect(messageInput).toBeVisible();

    // 发送查单意图，要求查询属于 tester_dialog@example.com (对应 default_user) 下的订单
    await messageInput.fill('帮我查询一下我的订单 ORD-98712 的发货状态');
    await page.locator('button:has-text("发送")').click();

    // 等待 Agent 真实调起工具，解析 Drizzle SQL 完成物流数据渲染并返回
    // 预期包含：订单号、已发货（或对应状态）、承运商等真实工具输出
    const chatContainer = page.locator('div.overflow-y-auto');
    await expect(chatContainer).toContainText('ORD-98712', { timeout: 15000 });
    await expect(chatContainer).toContainText('发货', { timeout: 15000 });
  });

  test('测试 3: 消费偏好画像与置信度审计自动记录 (User Preference Audit Test)', async ({ page }) => {
    const messageInput = page.locator('input[placeholder*="发送您的业务诉求"]');
    await expect(messageInput).toBeVisible();

    // 告诉客服尺寸喜好，物理触发 recordUserPreference 工具
    await messageInput.fill('我平时买衣服比较喜欢宽松版型，外套都穿 XL 码，麻烦帮我备注下。');
    await page.locator('button:has-text("发送")').click();

    // 等待工具调用并提示偏好已被成功存储
    const chatContainer = page.locator('div.overflow-y-auto');
    await expect(chatContainer).toContainText('偏好', { timeout: 15000 });
    await expect(chatContainer).toContainText('XL', { timeout: 15000 });
  });
});
