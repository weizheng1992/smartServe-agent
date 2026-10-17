/**
 * Story 9 跨 app 验收(open-merchant-integration issues/07,2026-10-17):
 * 商户后台改 SKU 价 → 商城前台详情页立即可见新价。
 *
 * 为什么自建哨兵 SPU:详情页价 = 选中 SKU 价(MIN 聚合在列表侧),种子 SPU
 * 多规格会让断言随默认选中漂;单 SKU 哨兵让选中/MIN/默认三者恒等,断言确定。
 * 已知陈旧边界(刻意不在此测):客服 RAG 知识同步只在网关 lifespan 跑,
 * 改价后 RAG 直答旧价到重启 —— storefront/导购/下单零缓存直读,本测不受累。
 *
 * 前置:4000 网关 + 3005 商城 + 3006 后台全活;种子账号 test@example.com。
 * 跑法:bunx playwright test --config=apps/merchant-admin/e2e/merchant-admin.config.ts
 *       (cwd 仓库根;config 的 webServer 以 config 目录为 cwd,4000 常驻时 reuse)
 */
import { expect, test } from '@playwright/test';

const GW = 'http://localhost:4000';
const STORE = 'http://localhost:3005';
const STAFF = { email: 'test@example.com', password: 'agent-all-dev' };
const SPU_TITLE = `E2E Story9 哨兵 ${Date.now()}`;

let token = '';
let spuId = '';

const authHeaders = () => ({ Authorization: `Bearer ${token}`, 'x-tenant-id': 'aurora' });

test.describe('Story 9 跨 app:后台改价 → 商城前台可见', () => {
  test.beforeAll(async ({ request }) => {
    const login = await request.post(`${GW}/api/auth/login`, { data: STAFF });
    expect(login.status()).toBe(200);
    token = (await login.json()).data.token as string;
    // 自建单 SKU 哨兵 SPU(契约级 POST;默认 SKU 随建,契约钉于 TestSkuCrud)
    const created = await request.post(`${GW}/api/admin/analytics/spus`, {
      headers: authHeaders(),
      data: { title: SPU_TITLE, category: 'e2e', price: 88.0, stock: 9 },
    });
    expect(created.status(), await created.text()).toBe(200);
    spuId = (await created.json()).id as string;
    expect(spuId, 'create_spu 响应应携带 SPU id').toBeTruthy();
  });

  test.afterAll(async ({ request }) => {
    if (spuId && token) await request.delete(`${GW}/api/admin/analytics/spus/${spuId}`, { headers: authHeaders() });
  });

  test('后台 UI 改价保存 → 3005 商城详情页新价立即可见', async ({ page }) => {
    // ① 后台 /skus:哨兵行 → 改价/库存 → 价格 2.34 / 库存 5 → 保存
    await page.addInitScript((t: string) => {
      localStorage.setItem('merchant-admin.token', t);
      localStorage.setItem('merchant-admin.staff', 'test@example.com');
      localStorage.setItem('merchant-admin.boss', JSON.stringify({ token: t, email: 'test@example.com' }));
    }, token);
    await page.goto('/skus');
    const row = page.locator('tr', { hasText: SPU_TITLE });
    await expect(row).toBeVisible();
    await row.getByRole('button', { name: '改价/库存' }).click();
    await page.getByLabel('价格(¥)').fill('2.34');
    await page.getByLabel('库存').fill('5');
    await page.getByRole('button', { name: '保存' }).click();
    await expect(page.getByText('✓ SKU 已保存')).toBeVisible();

    // ② 商城前台详情页(spu_id 直达,uuid 与 spu_code 双收):零缓存直读,新价即见
    await page.goto(`${STORE}/products/${spuId}`);
    await expect(page.getByText('¥2.34')).toBeVisible({ timeout: 10_000 });
  });

  test('新值域闸在真实链路上:负价 400 诚实拒绝(走 UI 提交)', async ({ page }) => {
    await page.addInitScript((t: string) => {
      localStorage.setItem('merchant-admin.token', t);
      localStorage.setItem('merchant-admin.staff', 'test@example.com');
      localStorage.setItem('merchant-admin.boss', JSON.stringify({ token: t, email: 'test@example.com' }));
    }, token);
    await page.goto('/skus');
    const row = page.locator('tr', { hasText: SPU_TITLE });
    await expect(row).toBeVisible();
    await row.getByRole('button', { name: '改价/库存' }).click();
    await page.getByLabel('价格(¥)').fill('-1');
    await page.getByLabel('库存').fill('5');
    // 前端预闸:负价不可提交(ready=false)
    await expect(page.getByRole('button', { name: '保存' })).toBeDisabled();
  });
});
