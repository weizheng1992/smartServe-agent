import { expect, test } from '@playwright/test';

import { loginViaUi } from './helpers/auth';
import { chatContainer as chatContainerOf } from './helpers/chat';

/**
 * LLM 上游熔断降级 E2E(wayfinder 004):独立网关(4001)注入死 LLM
 * (AI_BASE_URL 指向不存在端口 + 失败阈值 1)→ 首次真实模型调用即熔断,
 * run_agent 以 CircuitBreakerOpenError 兜底道歉回复 —— 前端必须看到道歉文案,
 * 而不是白屏 / 永久 loading / 崩溃。
 * 本 spec 由 playwright.breaker.config.ts 独占运行(主配置 testIgnore)。
 */
test.describe('LLM 上游熔断降级 E2E', () => {
  test('上游模型不可达时熔断道歉,不白屏不挂死', async ({ page }) => {
    test.setTimeout(90_000);
    await loginViaUi(page);
    await expect(page).toHaveURL('/');

    // 新开线程(输入框在无 activeThreadId 时禁用)
    await page.getByRole('button', { name: /开启新一轮对话/ }).click();
    const messageInput = page.locator('input[placeholder*="发送您的业务诉求"]');
    await expect(messageInput).toBeEnabled({ timeout: 15_000 });

    // 输入必须真正抵达至少一次 LLM 调用:问候/订单查询/退款查询都有规则或
    // embedding 锚点直达旁路(判定 1/2/3),零 LLM 调用则熔断永不触发(实测
    // 「查订单发货状态」全程确定性履约)。价保咨询无订单/退款关键词,RAG
    // top_score 0.52 < 0.55 拒绝 consult 快轨 → 整轮唯一 LLM 调用就是 finish
    // 终稿 —— 它穷尽重试后恰好把熔断推至 OPEN,韧性层改抛
    // CircuitBreakerOpenError(2026-09-30 _trip_or_original;此前原始
    // ConnectionError 被 finish 兜底吃成罐头,道歉永不触达),经 finish 穿透
    // 闸接 run_agent 的 job 级降级道歉。
    await messageInput.fill('我想了解一下你们平台的价保规则是怎么样的，可以详细说明一下吗');
    await page.locator('button:has-text("发送")').click();

    // 熔断降级道歉文案(SSE result 事件流式渲染)
    const chatContainer = chatContainerOf(page);
    await expect(chatContainer).toContainText('上游模型波动', { timeout: 60_000 });
  });
});
