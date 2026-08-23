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

  test('1. 商城前台浏览商品、下单与查看我的订单', async ({ page }) => {
    // 1. 访问商户商城前台
    await page.goto('http://localhost:3005/');
    await expect(page).toHaveTitle(/极光潮品/);

    // 2. 校验商城顶部与欢迎 Banner 正常渲染
    await expect(page.locator('header')).toContainText('极光潮品 AURORA LUXE');
    await expect(page.locator('header')).toContainText('张伟 (钻石会员)');
    await expect(page.locator('h1')).toContainText('极简机能 · 极光品质生活');

    // 3. 校验商品列表正常加载并包含现货商品
    const productCards = page.locator('main .grid > div');
    await expect(productCards.first()).toBeVisible({ timeout: 10000 });
    const count = await productCards.count();
    expect(count).toBeGreaterThanOrEqual(4);

    // 4. 点击第一件商品的「立即购买」
    const firstBuyBtn = productCards.first().locator("button:has-text('立即购买')");
    await firstBuyBtn.click();

    // 5. 校验弹出确认购买弹窗
    const modal = page.locator("div.fixed:has-text('确认购买商品')");
    await expect(modal).toBeVisible();

    // 6. 确认下单
    const submitBtn = modal.locator("button:has-text('确认支付并下单')");
    await submitBtn.click();

    // 7. 打开「我的订单」抽屉
    const myOrdersBtn = page.locator("header button:has-text('我的订单')");
    await myOrdersBtn.click();

    const ordersModal = page.locator("div.fixed:has-text('我的订单列表')");
    await expect(ordersModal).toBeVisible();
    await expect(ordersModal).toContainText('张伟 (CUST-8801)');
    await expect(ordersModal).toContainText('待发货');
  });

  test('2. 右下角 AI 智能客服悬浮入口与对话交互', async ({ page }) => {
    await page.goto('http://localhost:3005/');

    // 1. 悬浮客服按钮
    const aiWidgetBtn = page.locator("button:has-text('极光智能客服')");
    await expect(aiWidgetBtn).toBeVisible();
    await aiWidgetBtn.click();

    // 2. 客服对话窗口弹出
    const chatModal = page.locator("div.fixed:has-text('极光潮品 AI 智能客服')");
    await expect(chatModal).toBeVisible();
    await expect(chatModal).toContainText('已连接外部商户 SPI 协议');

    // 3. 点击快捷指令
    const quickBtn = chatModal.locator("button:has-text('🚀 帮我改地址为望京SOHO')");
    await quickBtn.click();

    // 4. 校验输入框填入内容并点击发送
    const sendBtn = chatModal.locator("button:has-text('发送')");
    await sendBtn.click();

    // 5. 校验消息流包含用户提问
    await expect(chatModal).toContainText('帮我把刚才的订单地址改成朝阳区望京SOHO T1 1508室');
  });

  test('3. 商户管理后台 (Admin) 订单中心、发货与 SPI 审计日志流水', async ({ page }) => {
    // 1. 访问商户管理后台
    await page.goto('http://localhost:3005/admin');

    // 2. 校验后台 Header 与数据指标卡
    await expect(page.locator('header')).toContainText('极光潮品商户管理后台');
    await expect(page.locator('body')).toContainText('累计商户订单量');
    await expect(page.locator('body')).toContainText('在售商品款式');
    await expect(page.locator('body')).toContainText('接收 AI SPI 履约调用');

    // 3. 校验订单中心列表
    const orderRows = page.locator('tbody tr');
    await expect(orderRows.first()).toBeVisible({ timeout: 10000 });
    const orderCount = await orderRows.count();
    expect(orderCount).toBeGreaterThanOrEqual(1);

    // 4. 切换到「🔌 AI 客服对接 & SPI 审计流水」Tab
    const auditTab = page.locator("button:has-text('AI 客服对接 & SPI 审计流水')");
    await auditTab.click();

    // 5. 校验审计流水表格展示
    await expect(page.locator('body')).toContainText('来自 Agent 平台的实时 SPI 调度审计流水');

    // 6. 切换到「📦 商品库存管理」Tab
    const inventoryTab = page.locator("button:has-text('商品库存管理')");
    await inventoryTab.click();
    await expect(page.locator('body')).toContainText('极光轻量三防连帽冲锋衣');
    await expect(page.locator('body')).toContainText('正常在售');
  });
});
