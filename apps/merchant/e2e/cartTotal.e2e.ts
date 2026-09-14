import { expect, test } from '@playwright/test';

// 购物车金额回归(2026-09-14 用户报告:加购后购物车页显示 ¥NaN)。
//
// 断言的是用户的原始症状,不深究实现:
//   详情页加购 → 购物车页 → ①页面任何位置不得出现 "NaN";
//                          ②合计必须等于 详情页所选 SKU 单价 × 数量。
// 期望单价取自真实在售货架(/api/store/products/:id 的 skus[0],与页面同源)。

test.use({ baseURL: 'http://localhost:3005' });

test.describe('🛒 商户商城购物车金额回归', () => {
  test('商品详情页加购 → 购物车页金额 = 单价×数量,零 NaN', async ({ page, request }) => {
    // 隔离:清掉本机历史毒数据(此前手测写入的旧形状条目),保证从零开始
    await page.goto('/');
    await page.evaluate(() => localStorage.removeItem('aurora_store_cart'));

    // 期望值与页面同源:详情 API 的 skus[0](详情页默认选中第一个 SKU)
    const res = await request.get('http://localhost:4000/api/store/products/SPU-AURORA-001');
    expect(res.ok()).toBeTruthy();
    const data = await res.json();
    expect(data.success && data.product, '货架种子必须含 SPU-AURORA-001').toBeTruthy();
    const unitPrice = Number(data.product.skus[0].price);
    expect(unitPrice).toBeGreaterThan(0);

    // 详情页加购(默认选中 SKU、数量 1)
    await page.goto('/products/SPU-AURORA-001');
    await expect(page.locator("button:has-text('加入购物车')")).toBeVisible();
    await page.locator("button:has-text('加入购物车')").click();
    await expect(page.locator('body')).toContainText('已成功加入购物车');

    // 购物车页:钉用户症状
    await page.goto('/cart');
    const body = await page.locator('body').innerText();
    expect(body, '购物车页不得出现 NaN').not.toContain('NaN');
    expect(body, `单价应展示 ${unitPrice.toFixed(2)}`).toContain(unitPrice.toFixed(2));
    expect(body, `合计应等于 ${unitPrice.toFixed(2)}(单价×1)`).toContain(`¥${unitPrice.toFixed(2)}`);
  });

  test('商城列表弹窗加购 → 购物车页金额 = 单价×数量,零 NaN', async ({ page, request }) => {
    await page.goto('/');
    await page.evaluate(() => localStorage.removeItem('aurora_store_cart'));

    const res = await request.get('http://localhost:4000/api/store/products');
    expect(res.ok()).toBeTruthy();
    const data = await res.json();
    const products = data.products ?? data;
    expect(products.length).toBeGreaterThanOrEqual(1);
    const unitPrice = Number(products[0].price);
    expect(unitPrice).toBeGreaterThan(0);

    // 列表卡片「选规格购买」弹窗 → 加入购物车
    const firstCard = page.locator('main .grid > div').first();
    await firstCard.locator("button:has-text('选规格购买')").click();
    const modal = page.locator("div.fixed:has-text('选择商品规格与数量')");
    await expect(modal).toBeVisible();
    await modal.locator("button:has-text('加入购物车')").click();
    await expect(page.locator('body')).toContainText('加入购物车');

    await page.goto('/cart');
    const body = await page.locator('body').innerText();
    expect(body, '购物车页不得出现 NaN').not.toContain('NaN');
    expect(body, `合计应等于 ${unitPrice.toFixed(2)}(单价×1)`).toContain(`¥${unitPrice.toFixed(2)}`);
  });

  test('历史嵌套形状存档(中毒数据)在读取侧自愈,零 NaN', async ({ page, request }) => {
    const res = await request.get('http://localhost:4000/api/store/products/SPU-AURORA-001');
    const data = await res.json();
    const product = data.product;
    const unitPrice = Number(product.skus[0].price);

    // 预置修复前写入方落下的真实毒数据形状(嵌套 {product, sku}),数量 2
    await page.goto('/');
    await page.evaluate(
      (payload) => {
        localStorage.setItem('aurora_store_cart', JSON.stringify([payload]));
      },
      { product, sku: product.skus[0], quantity: 2, selected: true },
    );

    await page.goto('/cart');
    const body = await page.locator('body').innerText();
    expect(body, '历史毒数据经读取侧归一后不得出现 NaN').not.toContain('NaN');
    expect(body, `合计应为 ${(unitPrice * 2).toFixed(2)}(单价×2)`).toContain(`¥${(unitPrice * 2).toFixed(2)}`);
  });
});
