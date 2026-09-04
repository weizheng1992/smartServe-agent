import { expect, test } from '@playwright/test';

/**
 * 回归测试:商户端重复询问同一问题(快捷胶囊"推荐热销"),
 * 第二条 AI 回复必须实时出现。
 * 背景 bug:前端曾按"文本相同"去重,SSE 与 POST 响应两路都会吞掉与历史消息
 * 同文本的新回复(推荐类 skill 输出为模板化文本,逐字节相同),导致"没有
 * chat 返回,刷新之后才有"。修复后去重仅按 messageId 幂等。
 */
test.use({ baseURL: 'http://localhost:3005' });

test('重复询问推荐热销,第二条 AI 回复应实时出现', async ({ page }) => {
  // 每次运行使用独立用户 → 独立线程,保证确定性
  const uid = `CUST-E2E-${Date.now()}`;
  await page.addInitScript((u) => {
    localStorage.setItem(
      'aurora_merchant_current_user',
      JSON.stringify({ id: u, name: '回归用户', phone: '13800000000', tier: '注册会员', defaultAddress: '回归地址' }),
    );
  }, uid);

  const consoleErrors: string[] = [];
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });

  await page.goto('/');
  // 等待聊天挂件初始化完全落定(localStorage 写入活跃线程 key 即代表 init fetch 已 resolve),
  // 避免慢速 init 在点击后返回并整体替换消息列表,引入与被测行为无关的竞态。
  await page.waitForFunction((u) => !!localStorage.getItem(`aurora_active_thread_${u}`), uid, {
    timeout: 15_000,
  });
  await page.locator("button:has-text('极光智能客服')").click();
  const chatModal = page.locator("div.fixed:has-text('极光潮品 AI 智能助理')");
  await expect(chatModal).toBeVisible();

  // AI 推荐回复的稳定模板前缀(服务端模板化输出,逐字节稳定)。
  // 仅匹配消息气泡 div(whitespace-pre-wrap 为气泡独有 class),避免 getByText 命中祖先容器。
  const replyBubbles = page.locator('div.whitespace-pre-wrap', { hasText: '为您精选了以下推荐商品' });
  const userBubbles = page.locator('div.whitespace-pre-wrap', { hasText: '推荐当季热销机能外套' });
  const pill = chatModal.locator("button:has-text('推荐热销')");

  // ── 第 1 次询问 ──────────────────────────────────────────────
  let postDone = page.waitForResponse((r) => r.url().includes('/api/store/chat') && r.request().method() === 'POST', {
    timeout: 90_000,
  });
  await pill.click();
  const resp1 = await postDone;
  const body1 = await resp1.json();
  expect(body1.success).toBe(true);

  await expect.poll(() => replyBubbles.count(), { timeout: 30_000 }).toBeGreaterThanOrEqual(1);
  expect(await replyBubbles.count()).toBe(1);

  // ── 第 2 次询问同一问题 ──────────────────────────────────────
  postDone = page.waitForResponse((r) => r.url().includes('/api/store/chat') && r.request().method() === 'POST', {
    timeout: 90_000,
  });
  await pill.click();
  const resp2 = await postDone;
  const body2 = await resp2.json();
  expect(body2.success).toBe(true); // 服务端确实成功返回了第二条回复
  expect(body2.output).toContain('为您精选了以下推荐商品');

  // 等待 UI 静置(spinner 消失),再给去重/渲染逻辑 3s 完成窗口
  await page.waitForTimeout(3_000);

  // 🔴 核心断言:第二条 AI 回复应实时渲染(bug 时为 1)
  expect(await replyBubbles.count()).toBe(2);
  // 用户消息两条都在(bug 时用户消息正常、仅 AI 回复被吞)
  expect(await userBubbles.count()).toBe(2);

  // ── reload 后历史拉取应仍能拿到全部回复(不重复、不丢失)──
  await page.reload();
  await page.locator("button:has-text('极光智能客服')").click();
  await expect(chatModal).toBeVisible();
  await expect.poll(() => replyBubbles.count(), { timeout: 30_000 }).toBeGreaterThanOrEqual(2);

  expect(consoleErrors, `console errors: ${consoleErrors.join(' | ')}`).toEqual([]);
});
