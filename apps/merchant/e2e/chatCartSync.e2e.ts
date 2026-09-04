import { expect, test } from '@playwright/test';

/**
 * 回归测试:聊天挂件内"把第1件加入购物车"后,商城购物车必须真实收到商品。
 * 背景 bug(2026-09-04):引擎侧 CartManageSkill 旧代码经 self. 访问模块级正则抛
 * AttributeError,fast-track 失败兜底 general_query,finish 节点 LLM 幻觉"已成功
 * 加购"并回填语义缓存;此后相似请求全部命中缓存,回复无 cart_card,商城购物车
 * 始终为空。修复后 fast-track 返回 cart_card,前端 syncCartToLocalStorage 同步落库。
 * 同时钉死次生 bug:SSE 推送与 POST 响应两路同步不得重复累加(quantity 必须为 1)。
 */
test.use({ baseURL: 'http://localhost:3005' });

test('聊天加购后商城购物车应收到 1 件商品(非空、不翻倍)', async ({ page }) => {
  // 每次运行使用独立用户 → 独立线程,保证确定性
  const uid = `CUST-E2E-CART-${Date.now()}`;
  await page.addInitScript((u) => {
    localStorage.setItem(
      'aurora_merchant_current_user',
      JSON.stringify({ id: u, name: '购物车回归', phone: '13800000000', tier: '注册会员', defaultAddress: '回归地址' }),
    );
    // addInitScript 每次导航重放:清空购物车仅首次执行,否则 goto('/cart') 会把
    // 聊天刚同步进去的商品误清掉(sessionStorage 同 tab 导航间持久,可当哨兵)
    if (!sessionStorage.getItem('e2e_cart_cleaned')) {
      localStorage.removeItem('aurora_store_cart');
      sessionStorage.setItem('e2e_cart_cleaned', '1');
    }
  }, uid);

  await page.goto('/');
  // 等待聊天挂件初始化落定(活跃线程 key 写入 = init fetch 已 resolve)
  await page.waitForFunction((u) => !!localStorage.getItem(`aurora_active_thread_${u}`), uid, {
    timeout: 15_000,
  });
  await page.locator("button:has-text('极光智能客服')").click();
  const chatModal = page.locator("div.fixed:has-text('极光潮品 AI 智能助理')");
  await expect(chatModal).toBeVisible();

  // 发送加购指令并等待 POST 响应
  const postDone = page.waitForResponse((r) => r.url().includes('/api/store/chat') && r.request().method() === 'POST', {
    timeout: 90_000,
  });
  await chatModal.locator("input[type='text']").fill('把第1件加入购物车');
  await chatModal.locator("input[type='text']").press('Enter');
  const resp = await postDone;
  const body = await resp.json();
  expect(body.success).toBe(true);

  // 🔴 核心断言 1:响应必须携带带 items 的 cart_card(缺卡片 = 商城购物车收不到商品)
  const cartCards = (body.cards || []).filter((c: any) => c.type === 'cart_card');
  expect(cartCards.length, '响应应包含 cart_card').toBeGreaterThan(0);
  expect((cartCards[0].data?.items || []).length, 'cart_card 应携带 items').toBeGreaterThan(0);

  // 给 SSE 一路 + POST 一路的双同步留出完成窗口,再断言本地购物车
  await page.waitForTimeout(3_000);

  // 🔴 核心断言 2:aurora_store_cart 收到商品,且 quantity 恰为 1(两路同步不得累加)
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('aurora_store_cart') || '[]'));
  expect(stored.length, '商城购物车应有 1 款商品').toBe(1);
  expect(stored[0].quantity, '加购 1 件不得翻倍').toBe(1);
  expect(String(stored[0].title)).toContain('Nike Air Zoom Pegasus 41');

  // 🔴 核心断言 3:购物车页真实渲染该商品
  await page.goto('/cart');
  await expect(page.getByRole('heading', { name: /🛒 购物车/ })).toBeVisible();
  await expect(page.getByText('已选 1 件商品')).toBeVisible();
  await expect(page.getByRole('link', { name: /Nike Air Zoom Pegasus 41/ }).first()).toBeVisible();
});
