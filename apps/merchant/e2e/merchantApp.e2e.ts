import { expect, test } from '@playwright/test';

test.describe('🛍️ 极光潮品商户商城与管理后台端到端测试 (Merchant E2E Browser Test)', () => {
  test.use({ baseURL: 'http://localhost:3005' });

  test.beforeEach(async ({ page }) => {
    page.on('console', (msg) => console.log(`[Browser Console] ${msg.type()}: ${msg.text()}`));
    page.on('pageerror', (err) => console.error(`[Browser PageError]`, err));
    page.on('response', (resp) => {
      if (resp.status() >= 400) {
        console.log(`[HTTP ERROR] ${resp.status()} ${resp.url()}`);
      }
    });
  });

  test('1. 商城前台浏览商品、选规格加购与查看我的订单', async ({ page }) => {
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

  test('3. 商户管理后台 (Admin) 订单中心、SKU 库存与 SPI 审计日志流水', async ({ page }) => {
    // 1. 访问商户管理后台
    await page.goto('http://localhost:3005/admin');

    // 2. 校验后台 Header 与数据指标卡
    await expect(page.locator('header')).toContainText('极光潮品商户后台管理系统');
    await expect(page.locator('body')).toContainText('累计订单总数');
    await expect(page.locator('body')).toContainText('SPU 库');

    // 3. 校验订单中心列表
    const orderRows = page.locator('tbody tr');
    await expect(orderRows.first()).toBeVisible({ timeout: 10000 });
    const orderCount = await orderRows.count();
    expect(orderCount).toBeGreaterThanOrEqual(1);

    // 4. 切换到「🔌 SPI 开放审计流水」Tab
    const auditTab = page.locator("button:has-text('SPI 开放审计流水')");
    await auditTab.click();

    // 5. 校验审计流水表格展示
    await expect(page.locator('body')).toContainText('来自 Agent 平台的实时 SPI 调度审计流水');

    // 6. 切换到「📦 SKU 规格库存」Tab
    const inventoryTab = page.locator("button:has-text('SKU 规格库存')");
    await inventoryTab.click();
    await expect(page.locator('body')).toContainText('SKU 编码');
    await expect(page.locator('body')).toContainText('当前可用库存');
  });
});
