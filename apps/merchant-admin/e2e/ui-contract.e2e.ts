/**
 * UI 视觉契约(2026-10-18 用户实弹报障「弹窗贴边 + 表格乱折行」):
 * ① 弹窗家族:FormDialogShell 渲染的 [role=dialog] 必须自带内边距(p-6=24px)。
 *    ui 包 DialogContent 本体不带 padding(消费方自给,apps/admin ConfirmDialog
 *    先例);32ea113 CRUD 收口重构抄 chrome 时把旧弹窗的 p-6 抄丢,13 个弹窗
 *    全家族内容贴边(标题顶到圆角、X 按钮坠到标题下一行)。
 * ② 数据表:表头/单元格 whitespace-nowrap(禁中文竖排折行),容器横向可滚
 *    (ui Table 自带 overflow-auto 包裹,nowrap 后自然出横向滚动)。
 * 跑法:bunx playwright test --config=apps/merchant-admin/e2e/merchant-admin.config.ts ui-contract
 * 前置:3006 + 4000(config webServer reuse);种子老板 test@example.com。
 */
import { expect, test } from '@playwright/test';

const GW = 'http://localhost:4000';
const STAFF = { email: 'test@example.com', password: 'agent-all-dev' };

let token = '';

test.beforeAll(async ({ request }) => {
  const login = await request.post(`${GW}/api/auth/login`, { data: STAFF });
  expect(login.status()).toBe(200);
  token = (await login.json()).data.token as string;
  expect(token).toBeTruthy();
});

test.beforeEach(async ({ page }) => {
  await page.addInitScript((t: string) => {
    localStorage.setItem('merchant-admin.token', t);
    localStorage.setItem('merchant-admin.staff', 'test@example.com');
    localStorage.setItem('merchant-admin.boss', JSON.stringify({ token: t, email: 'test@example.com' }));
  }, token);
});

test.describe('弹窗家族:DialogContent 必须有内边距', () => {
  const PAD_MIN = 20; // p-6 = 24px;0px(贴边事故)与 24px 之间的粗闸

  async function openDialogPadding(page: import('@playwright/test').Page, route: string, open: () => Promise<void>) {
    await page.goto(route);
    await open();
    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible();
    return dialog.evaluate((el) => {
      const cs = getComputedStyle(el);
      return {
        top: Number.parseFloat(cs.paddingTop),
        right: Number.parseFloat(cs.paddingRight),
        bottom: Number.parseFloat(cs.paddingBottom),
        left: Number.parseFloat(cs.paddingLeft),
      };
    });
  }

  test('SKU 库存页:改价/库存弹窗四向内边距 ≥ 20px', async ({ page }) => {
    const pad = await openDialogPadding(page, '/skus', async () => {
      await page.getByRole('button', { name: '改价/库存' }).first().click();
    });
    expect(pad, `弹窗内边距贴边: ${JSON.stringify(pad)}(32ea113 丢 p-6 回归)`).toEqual({
      top: expect.any(Number),
      right: expect.any(Number),
      bottom: expect.any(Number),
      left: expect.any(Number),
    });
    expect(pad.top).toBeGreaterThanOrEqual(PAD_MIN);
    expect(pad.right).toBeGreaterThanOrEqual(PAD_MIN);
    expect(pad.bottom).toBeGreaterThanOrEqual(PAD_MIN);
    expect(pad.left).toBeGreaterThanOrEqual(PAD_MIN);
  });

  test('商品列表页:新增商品弹窗四向内边距 ≥ 20px', async ({ page }) => {
    const pad = await openDialogPadding(page, '/products', async () => {
      await page.getByRole('button', { name: '新增商品' }).click();
    });
    expect(pad.top).toBeGreaterThanOrEqual(PAD_MIN);
    expect(pad.right).toBeGreaterThanOrEqual(PAD_MIN);
    expect(pad.bottom).toBeGreaterThanOrEqual(PAD_MIN);
    expect(pad.left).toBeGreaterThanOrEqual(PAD_MIN);
  });
});

test.describe('数据表:不折行 + 横向可滚', () => {
  test('订单履约表:表头单元格 nowrap 单行,容器横向可滚', async ({ page }) => {
    await page.goto('/orders');
    await expect(page.getByText('订单流水号')).toBeVisible();
    const sig = await page.evaluate(() => {
      const table = document.querySelector('table');
      if (!table) return null;
      const heads = [...table.querySelectorAll('th')];
      const firstHead = heads[1] ?? heads[0]; // [0] 是勾选列
      const wrap = heads.map((th) => getComputedStyle(th).whiteSpace);
      const orderIdCell = table.querySelector('tbody tr td:nth-child(2)');
      // 行盒计数:td 盒高=行高(会被合法两行的地址豁免列撑高),症状本体是
      // 订单号文本自己的 line box 数(折三行=3,单行=1)
      const range = document.createRange();
      if (orderIdCell) range.selectNodeContents(orderIdCell);
      const orderCellLineBoxes = orderIdCell ? [...range.getClientRects()].filter((r) => r.width > 2).length : 0;
      const scroller = table.parentElement!;
      return {
        headWhiteSpaces: [...new Set(wrap)],
        firstHeadH: firstHead.getBoundingClientRect().height,
        orderCellWhiteSpace: orderIdCell ? getComputedStyle(orderIdCell).whiteSpace : null,
        orderCellLineBoxes,
        scrollable:
          scroller.scrollWidth > scroller.clientWidth ||
          ['auto', 'scroll'].includes(getComputedStyle(scroller).overflowX),
      };
    });
    expect(sig, '页面应渲染出数据表').not.toBeNull();
    // nowrap:表头与单元格全部收口(dense-table 单点预设)
    expect(sig!.headWhiteSpaces, '表头应 whitespace-nowrap').toEqual(['nowrap']);
    expect(sig!.orderCellWhiteSpace, '单元格应 whitespace-nowrap').toBe('nowrap');
    // 单行:表头 < 50px(p-3.5*2 + 一行 ≈ 44;双行折行 ≈ 60+)
    expect(sig!.firstHeadH, '表头应单行(未折行)').toBeLessThan(50);
    expect(sig!.orderCellLineBoxes, '订单号文本应单行(1 个行盒,此前折三行)').toBe(1);
    // 横向可滚:容器 overflow-auto 且(超宽可滚或天然不超宽)
    expect(sig!.scrollable, '表容器应横向可滚(ui Table overflow-auto)').toBe(true);
  });
});
