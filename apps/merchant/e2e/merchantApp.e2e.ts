import { expect, test } from '@playwright/test';

test.describe('🛍️ 极光潮品商户商城与管理后台端到端测试 (Merchant E2E Browser Test)', () => {
  test.use({ baseURL: 'http://localhost:3005' });

  test.beforeEach(async ({ page }) => {
    page.on('console', (msg) => console.log(`[Browser Console] ${msg.type()}: ${msg.text()}`));
    page.on('pageerror', (err) => console.error('[Browser PageError]', err));
    page.on('response', (resp) => {
      if (resp.status() >= 400) {
        console.log(`[HTTP ERROR] ${resp.status()} ${resp.url()}`);
      }
    });
  });

  test('1. 商城前台浏览商品、选规格加购与查看我的订单', async ({ page }) => {
    // U2(2026-10-05):默认身份已是游客;本用例验「已选预设顾客」视图,
    // 显式注入张伟身份(注入值走参数字面量,严禁引用 Node 闭包常量)
    await page.addInitScript(() => {
      localStorage.setItem(
        'aurora_merchant_current_user',
        JSON.stringify({
          id: 'CUST-8801',
          name: '张伟',
          phone: '13800138000',
          tier: '黑金SVIP',
          defaultAddress: '北京市海淀区中关村南大街1号院8号楼1201室',
        }),
      );
    });

    // 1. 访问商户商城前台
    await page.goto('http://localhost:3005/');
    await expect(page).toHaveTitle(/极光潮品/);

    // 2. 校验商城顶部与欢迎 Banner 正常渲染
    await expect(page.locator('header')).toContainText('极光潮品 AURORA LUXE');
    await expect(page.locator('header')).toContainText('张伟');
    await expect(page.locator('header')).toContainText('黑金SVIP');
    await expect(page.locator('h1')).toContainText('极简机能 · 严选面料与多维规格');

    // 3. 校验商品列表正常加载
    const productCards = page.locator('main .grid > div');
    await expect(productCards.first()).toBeVisible({ timeout: 10000 });
    const count = await productCards.count();
    expect(count).toBeGreaterThanOrEqual(4);

    // 4. 点击第一件商品的「选规格购买」
    const firstBuyBtn = productCards.first().locator("button:has-text('选规格购买')");
    await firstBuyBtn.click();

    // 5. 校验 SPU/SKU 选规格弹窗弹出
    const modal = page.locator("div.fixed:has-text('选择商品规格与数量')");
    await expect(modal).toBeVisible();

    // 6. 加入购物车
    const addCartBtn = modal.locator("button:has-text('加入购物车')");
    await addCartBtn.click();

    // 7. 校验加购成功通知条与「去购物车结算」入口
    await expect(page.locator('body')).toContainText('加入购物车');
    const goCartLink = page.locator("a:has-text('去购物车结算')");
    await expect(goCartLink).toBeVisible();
    await goCartLink.click();

    // 8. 校验购物车页展示刚加入的商品(非空状态)
    await expect(page).toHaveURL(/\/cart/);
    await expect(page.locator('body')).not.toContainText('购物车空空如也');

    // 9. 通过顶部导航进入「我的订单」页
    const myOrdersLink = page.locator("header a:has-text('我的订单')");
    await myOrdersLink.click();
    await expect(page).toHaveURL(/\/orders/);
    await expect(page.locator('body')).toContainText('我的订单中心');
    await expect(page.locator('body')).toContainText('待发货');
  });

  test('2. 右下角 AI 智能客服悬浮入口与对话交互', async ({ page }) => {
    await page.goto('http://localhost:3005/');

    // 1. 悬浮客服按钮
    const aiWidgetBtn = page.locator("button:has-text('极光智能客服')");
    await expect(aiWidgetBtn).toBeVisible();
    await aiWidgetBtn.click();

    // 2. 客服对话窗口弹出
    const chatModal = page.locator("div.fixed:has-text('极光潮品 AI 智能助理')");
    await expect(chatModal).toBeVisible();

    // 3. 点击快捷指令「改收货地址」
    const quickBtn = chatModal.locator("button:has-text('改收货地址')");
    await quickBtn.click();

    // 4. 校验消息流包含快捷指令发出的用户提问
    await expect(chatModal).toContainText('修改未发货订单地址');
  });

  test('3. 商户管理后台 (Admin):员工身份闸生效,匿名只见引导卡', async ({ page }) => {
    // c7b26cd(2026-09-27)后 /api/admin/* 族要求员工 Bearer JWT,内嵌台无
    // 身份源 —— 旧用例(订单中心/SKU 库存/SPI 审计 Tab 点击)审计的是匿名
    // 裸奔面,已不可能通过;现钉身份闸契约:引导卡 + 指路 3006 + 无业务数据。
    await page.goto('http://localhost:3005/admin');

    await expect(page.getByText('商户管理面已启用员工鉴权')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('端口 3006')).toBeVisible();

    const body = await page.locator('body').innerText();
    expect(body).not.toContain('累计订单总数');
    expect(body).not.toContain('SPI 开放审计流水');
    expect(body).not.toContain('SKU 规格库存');
  });
});
