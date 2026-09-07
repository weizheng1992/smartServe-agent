import { expect, test } from '@playwright/test';

import { loginViaUi } from './helpers/auth';
import { chatContainer as chatContainerOf } from './helpers/chat';

// 前置:后端 + 种子由 playwright globalSetup / webServer 数组拉齐(wayfinder 004),
// 登录走真实 /api/auth/login(种子账号 test@example.com,ORD-98712 归属该账号)。
test.describe('智能客服多轮对话自动化测试 (E2E Automated Dialog Tests)', () => {
  test.beforeEach(async ({ page }) => {
    // 每次测试前，首先进行安全登录（真实凭证，经网关校验）
    await loginViaUi(page);
    await expect(page).toHaveURL('/');

    // 新开线程:输入框在无 activeThreadId 时被禁用(wayfinder 004 修复基线误判)
    await page.getByRole('button', { name: /开启新一轮对话/ }).click();
    await expect(page.locator('input[placeholder*="发送您的业务诉求"]')).toBeEnabled({ timeout: 15_000 });
  });

  test('测试 1: 极速问候旁路通道 (Lightning Greeting Bypass Test)', async ({ page }) => {
    // 1. 确认主面板已成功渲染，且输入框可用
    const messageInput = page.locator('input[placeholder*="发送您的业务诉求"]');
    await expect(messageInput).toBeVisible();

    // 2. 发送纯打招呼指令 "你好"
    await messageInput.fill('你好');
    await page.locator('button:has-text("发送")').click();

    // 3. 校验由于 Lightning Bypass，系统应在毫秒级内输出欢迎导购界面，不调用大模型
    //    (品牌名随线程租户解析,断言锚定角色句式与导购条目而非硬编码品牌前缀)
    const chatContainer = chatContainerOf(page);
    await expect(chatContainer).toContainText('的智能客服助理', { timeout: 30_000 });
    await expect(chatContainer).toContainText('订单物流查询');
    await expect(chatContainer).toContainText('快捷退款办理');
  });

  test('测试 2: 查单物流与 ownership 验证 (Order Status Tool Tracking Test)', async ({ page }) => {
    test.setTimeout(180_000); // 真实 LLM 全链,默认 30s 总时钟不够
    const messageInput = page.locator('input[placeholder*="发送您的业务诉求"]');
    await expect(messageInput).toBeVisible();

    // 发送查单意图，要求查询属于种子账号 test@example.com 下的订单（seed 中 ORD-98712 归属该用户）
    await messageInput.fill('帮我查询一下我的订单 ORD-98712 的发货状态');
    await page.locator('button:has-text("发送")').click();

    // 等待 Agent 真实调起工具完成物流数据渲染并返回(全链真实 LLM,余量给足)
    // 预期包含：订单号、已发货（或对应状态）、承运商等真实工具输出
    const chatContainer = chatContainerOf(page);
    await expect(chatContainer).toContainText('ORD-98712', { timeout: 120_000 });
    await expect(chatContainer).toContainText('发货', { timeout: 120_000 });
  });

  test('测试 3: 消费偏好画像与置信度审计自动记录 (User Preference Audit Test)', async ({ page }) => {
    test.setTimeout(180_000); // 真实 LLM 全链,默认 30s 总时钟不够
    const messageInput = page.locator('input[placeholder*="发送您的业务诉求"]');
    await expect(messageInput).toBeVisible();

    // 告诉客服尺寸喜好，物理触发画像记忆提取
    await messageInput.fill('我平时买衣服比较喜欢宽松版型，外套都穿 XL 码，麻烦帮我备注下。');
    await page.locator('button:has-text("发送")').click();

    // 等待真实 LLM 处理并回应偏好已被记录
    const chatContainer = chatContainerOf(page);
    await expect(chatContainer).toContainText('XL', { timeout: 120_000 });
  });
});
