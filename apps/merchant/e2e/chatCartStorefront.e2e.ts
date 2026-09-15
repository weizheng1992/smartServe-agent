import { expect, test } from '@playwright/test';

// 商城购物车页可见性回归(2026-09-15 用户实报:聊天点名加购「曜石黑 M码」
// 成功,商城购物车页刷新却没有;点名「曜石黑 L码」被 SPU 粒度去重误拦)。
//
// 收口:①商城页挂载时拉 /api/store/cart 引擎车行合流展示(引擎账本权威);
// ②点名直配行以 SKU 码为主键,同款不同规格两行共存;③聊天请求携带
// storeCart 水合引擎车。
//
// 断言策略:消息经 /api/store/chat 真实链路直发(「加入购物车」命中 triage
// 快轨 CartManageSkill,零 LLM,确定性),页面只验购物车页渲染。不驱动画布
// 上的聊天悬浮窗 —— 其历史恢复/卡片同步属于 UX 层,时序脆弱且非本 spec 被测
// 对象。两用例共享 CUST-8801 引擎车,serial 串行防互踩。

const GATEWAY = 'http://localhost:4000';

test.use({ baseURL: 'http://localhost:3005' });

test.describe.configure({ mode: 'serial' });

const chatSend = async (request: any, message: string) => {
  const r = await request.post(`${GATEWAY}/api/store/chat`, {
    data: {
      message,
      threadId: `merchant_thread_e2e_cart_${Date.now()}`,
      userId: 'CUST-8801',
      businessId: 'aurora',
      storeCart: [],
    },
  });
  return r.json();
};

const engineItems = async (request: any) => {
  const r = await request.get(`${GATEWAY}/api/store/cart?customerId=CUST-8801`);
  return (await r.json()).items ?? [];
};

test.describe('🛒 聊天加购 × 商城购物车页 全链路', () => {
  test('聊天点名加购 曜石黑M → 刷新购物车页可见,同款 L 码两行共存', async ({ page, request }) => {
    test.setTimeout(150_000);

    // 引擎车起点确定性:经真实聊天链路清空,轮询账本归零
    await chatSend(request, '清空购物车');
    await expect
      .poll(async () => (await engineItems(request)).length, { timeout: 60_000, intervals: [500, 1000, 2000] })
      .toBe(0);

    // 聊天点名加购 曜石黑 M:轮询引擎账本出现确切 SKU 行(直配行以 SKU 码为主键)
    await chatSend(request, '极光三合一冲锋衣 曜石黑 M码 加入购物车');
    await expect
      .poll(
        async () =>
          (await engineItems(request)).some((i: any) => i.skuId === 'AURORA-SKU-001-BLK-M')
            ? 'added'
            : 'pending',
        { timeout: 60_000, intervals: [500, 1000, 2000] },
      )
      .toBe('added');

    // 同款不同规格:再点名 极夜绿 M → 新增一行,严禁被「已在购物车」拦掉
    // (2026-09-15 用户实报:曜石黑 M 在车时点名 L 码被去重误拦)
    await chatSend(request, '极光三合一冲锋衣 极夜绿 M码 加入购物车');
    await expect
      .poll(
        async () => {
          const rows = await engineItems(request);
          const has = (code: string) => rows.some((i: any) => i.skuId === code);
          return has('AURORA-SKU-001-BLK-M') && has('AURORA-SKU-001-GRN-M') ? 'both' : 'pending';
        },
        { timeout: 60_000, intervals: [500, 1000, 2000] },
      )
      .toBe('both');

    // 浏览器打开商城购物车页:全新挂载,走 /api/store/cart 合流路径,两行规格均可见
    await page.goto('/cart');
    const body = page.locator('body');
    await expect(body).toContainText('极光三合一全天候户外硬壳冲锋衣', { timeout: 15_000 });
    await expect(body).toContainText('曜石黑');
    await expect(body).toContainText('极夜绿');
    await expect(body).toContainText('1299');
    await expect(body).not.toContainText('购物车空空如也');
  });

  test('聊天删除 → 引擎车与商城购物车页同步清空', async ({ page, request }) => {
    test.setTimeout(150_000);

    // 引擎车起点确定性:清空(上一用例遗留)
    await chatSend(request, '清空购物车');
    await expect
      .poll(async () => (await engineItems(request)).length, { timeout: 60_000, intervals: [500, 1000, 2000] })
      .toBe(0);

    // 聊天点名加购 → 引擎车出现冲锋衣
    await chatSend(request, '极光三合一冲锋衣 曜石黑 M码 加入购物车');
    await expect
      .poll(
        async () => ((await engineItems(request)).some((i: any) => i.skuId === 'AURORA-SKU-001-BLK-M') ? 'added' : 'pending'),
        { timeout: 60_000, intervals: [500, 1000, 2000] },
      )
      .toBe('added');

    // 聊天删除:引擎车归零
    await chatSend(request, '删除购物车的商品');
    await expect
      .poll(
        async () =>
          (await engineItems(request)).some((i: any) => i.skuId === 'AURORA-SKU-001-BLK-M') ? 'present' : 'removed',
        { timeout: 60_000, intervals: [500, 1000, 2000] },
      )
      .toBe('removed');

    // 商城购物车页:本地存档清空后,合流路径下应显示空车(引擎权威)
    await page.goto('/');
    await page.evaluate(() => localStorage.removeItem('aurora_store_cart'));
    await page.goto('/cart');
    const body = page.locator('body');
    await expect(body).toContainText('购物车空空如也', { timeout: 15_000 });
    await expect(body).not.toContainText('极光三合一全天候户外硬壳冲锋衣');
  });
});
