import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';

import { loginViaUi } from './helpers/auth';
import { chatContainer as chatContainerOf } from './helpers/chat';

// 多模态图片客服全链路验收(wayfinder multimodal 005):
// 选图上传 → 发破损图 → 真实 vision LLM 定责 → damage_assessment 卡片渲染 → 刷新还原(004)。
// 前置:后端 + 种子由 globalSetup / webServer 数组拉齐;真实凭证登录(test@example.com)。
const FIXTURE = fileURLToPath(new URL('./fixtures/damaged-shoe.png', import.meta.url));

test.describe('多模态破损定责全链路 (Multimodal Damage Assessment)', () => {
  test.beforeEach(async ({ page }) => {
    await loginViaUi(page);
    await expect(page).toHaveURL('/');

    // 新开线程:输入框在无 activeThreadId 时被禁用
    await page.getByRole('button', { name: /开启新一轮对话/ }).click();
    await expect(page.locator('input[placeholder*="发送您的业务诉求"]')).toBeEnabled({ timeout: 15_000 });
  });

  test('选图上传 → 破损图定责卡片 → 刷新后图与卡俱在', async ({ page }) => {
    test.setTimeout(360_000); // 真实 vision LLM + 决策主链,默认 30s 总时钟不够

    // 1. 选图上传:夹具为鞋底开胶示意图(含 OCR 文本「破损投诉 ORD-77777」)
    await page.setInputFiles('input[type="file"]', FIXTURE);
    await expect(page.getByText('图片 1')).toBeVisible({ timeout: 15_000 });

    // 2. 发破损投诉,捕获 dispatch 返回的 threadId(刷新后按 id 点回线程)
    const messageInput = page.locator('input[placeholder*="发送您的业务诉求"]');
    await messageInput.fill('收到的运动鞋鞋底开胶断裂了，请看照片定责，申请退款 ORD-77777');
    const dispatchResponse = page.waitForResponse(
      (r) => r.request().method() === 'POST' && r.url().endsWith('/api/chat'),
    );
    await page.locator('button:has-text("发送")').click();
    const dispatch = await (await dispatchResponse).json();
    expect(dispatch.success).toBe(true);
    const threadId: string = dispatch.threadId;

    const chat = chatContainerOf(page);

    // 3. 用户消息缩略图落在聊天流(/api/uploads 引用)
    await expect(chat.locator('img[src*="/api/uploads/"]').first()).toBeVisible({ timeout: 30_000 });

    // 4. damage_assessment 卡片:定责对象任何级别(negligible/minor/severe)都渲染,
    //    锚定卡头与诊断概述(不锚定具体定责级别,避免 LLM 判级波动致脆断)
    await expect(chat).toContainText('AI 视觉成色与定责智能评定', { timeout: 300_000 });
    await expect(chat).toContainText('AI 诊断概述');

    // 5. 刷新还原(004 验收):SPA 以 ?threadId= 自愈恢复当前线程,历史消息/图/卡经接口还原。
    //    (侧栏历史列表依赖 GET /api/chat/threads,网关仅实现 POST/DELETE 返 405 —— 存量缺口,
    //    不在本图验收面;内容级还原即 004 契约)
    await page.reload();
    await expect(page).toHaveURL(new RegExp(`threadId=${threadId}`), { timeout: 15_000 });
    await expect(chat.locator('img[src*="/api/uploads/"]').first()).toBeVisible({ timeout: 30_000 });
    await expect(chat).toContainText('AI 视觉成色与定责智能评定', { timeout: 30_000 });
    await expect(chat).toContainText('AI 诊断概述');
  });
});
