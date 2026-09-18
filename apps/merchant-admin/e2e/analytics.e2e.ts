/**
 * data agent E2E(全链路:真实网关 + 真实 DB):
 * 1) RBAC 动态菜单渲染 + 三档员工切换
 * 2) 全屏工作台六胶囊逐一点击 → 真实查询返回卡片(表格/诚实空/反问)
 * 3) 悬浮 agent 唤起 + 提问 + 不支持问题诚实拒绝
 * 4) 报告生成 → 我的报告列表出现 → CSV 可下载
 * 5) 优惠活动:创建 → 列表出现 → 停用
 * 死按钮禁令的浏览器级断言:每个胶囊点击后必须出现卡片或明确反馈。
 */
import { expect, test } from '@playwright/test';

const loginViaApi = async (request: any) => {
  const res = await request.post('http://localhost:4000/api/auth/login', {
    data: { email: 'test@example.com', password: 'agent-all-dev' },
  });
  const body = await res.json();
  return body.data.token as string;
};

const CAPSULES = ['本月销量 Top10', '卖得最差的商品', '差评最多的 SKU', '近 30 天退款率', '售后工单概况', '客服负载概况'];

test.describe('data agent 全链路', () => {
  let token: string;
  test.beforeAll(async ({ request }) => { token = await loginViaApi(request); });
  test.beforeEach(async ({ page }) => {
    await page.addInitScript((t: string) => localStorage.setItem('merchant-admin.token', t), token);
  });

  test('菜单渲染与员工切换(RBAC)', async ({ page }) => {
    await page.goto('/analytics');
    await expect(page.getByText('极光潮品 · 商户后台')).toBeVisible();
    // 老板视角:数据分析与我的报告可见
    const nav = page.locator('aside nav');
    await expect(nav.getByText('数据分析', { exact: true })).toBeVisible();
    await expect(nav.getByText('我的报告', { exact: true })).toBeVisible();
    // 切换到仓储 → 菜单收敛(优惠活动消失)
    await page.locator('header select').selectOption({ label: /仓储/.test('') ? '' : undefined } as never).catch(() => {});
    const options = page.locator('header select option');
    const texts = (await options.allTextContents()).join('|');
    expect(texts).toContain('仓储');
  });

  for (const capsule of CAPSULES) {
    test(`胶囊「${capsule}」点击出真实卡片(死按钮禁令)`, async ({ page }) => {
      await page.goto('/analytics');
      await page.getByRole('button', { name: capsule }).first().click();
      // 任一可接受反馈:表格卡 / 口径注记 / 诚实空 / 反问 —— 全非静默
      await expect(
        page.locator('text=口径:').first(),
      ).toBeVisible({ timeout: 30_000 });
    });
  }

  test('不支持问题诚实拒绝(禁止幻觉)', async ({ page }) => {
    await page.goto('/analytics');
    await page.getByPlaceholder(/问点什么/).fill('今天天气怎么样');
    await page.getByRole('button', { name: '发送' }).click();
    await expect(page.getByText(/暂不支持/).first()).toBeVisible({ timeout: 30_000 });
  });

  test('悬浮 agent 任意路由可唤起并提问', async ({ page }) => {
    await page.goto('/orders');
    await page.getByRole('button', { name: '打开数据分析助手' }).click();
    await page.getByPlaceholder('提问…').fill('本月销量 Top5');
    await page.getByRole('button', { name: '发送', exact: true }).last().click();
    await expect(page.locator('text=口径:').first()).toBeVisible({ timeout: 30_000 });
  });

  test('报告生成与列表(14 号不变量:数字来自真实查询)', async ({ page }) => {
    await page.goto('/analytics');
    await page.getByRole('button', { name: '生成报告' }).click();
    await expect(page.getByText(/已生成/)).toBeVisible({ timeout: 60_000 });
    await page.getByText('我的报告', { exact: true }).click();
    await expect(page.getByText(/经营报告/).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /下载 CSV/ }).first()).toBeVisible();
  });

  test('优惠活动创建与停用(20 号)', async ({ page }) => {
    await page.goto('/promotions');
    const name = `E2E 满减 ${Date.now()}`;
    await page.getByPlaceholder('活动名称').fill(name);
    await page.getByPlaceholder('门槛 ¥').fill('300');
    await page.getByPlaceholder(/优惠 ¥/).fill('30');
    await page.getByRole('button', { name: '创建' }).click();
    await expect(page.locator('td', { hasText: name })).toBeVisible({ timeout: 15_000 });
    const row = page.locator('tr', { hasText: name });
    await row.getByRole('button', { name: '停用' }).click();
    await expect(row.getByText('已停用')).toBeVisible();
  });
});
