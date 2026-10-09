/**
 * 「该找谁」责任人路由 E2E(spec .scratch/owner-routing;真实网关 + 真实库):
 * 1) 责任人维护菜单可见(动态菜单驱动,种子新菜单)
 * 2) 找谁问句端到端(确定性快轨,零 LLM):owner 卡出 姓名部门职级
 * 3) 归因卡附「负责人」列 + 速览尾拼「找:」
 * 4) 责任人维护页:改派 → 表格反映 → 撤销 → 恢复种子态
 * 5) 员工页部门/职级下拉渲染(0019 人事属性)
 */
import { expect, test } from '@playwright/test';

const loginViaApi = async (request: any) => {
  const res = await request.post('http://localhost:4000/api/auth/login', {
    data: { email: 'test@example.com', password: 'agent-all-dev' },
  });
  const body = await res.json();
  return body.data.token as string;
};

test.describe('「该找谁」责任人路由', () => {
  let token: string;
  test.beforeAll(async ({ request }) => {
    token = await loginViaApi(request);
  });
  test.beforeEach(async ({ page }) => {
    await page.addInitScript((t: string) => {
      localStorage.setItem('merchant-admin.token', t);
      localStorage.setItem('merchant-admin.staff', 'test@example.com');
      localStorage.setItem('merchant-admin.boss', JSON.stringify({ token: t, email: 'test@example.com' }));
    }, token);
  });

  test('责任人维护菜单可见且页面渲染映射表(闭集下拉)', async ({ page }) => {
    await page.goto('/analytics');
    const nav = page.locator('aside nav');
    await expect(nav.getByText('责任人维护', { exact: true })).toBeVisible();
    await nav.getByText('责任人维护', { exact: true }).click();
    await expect(page.getByText(/已登记映射\(\d+\)/)).toBeVisible({ timeout: 15_000 });
    // 品类闭集来自语义注册表(下拉含 衬衫 —— 种子未灌品类,枚举照列)
    const valueSelect = page.getByLabel('维度值');
    await expect(valueSelect.locator('option', { hasText: '衬衫' })).toHaveCount(1);
    // 指标闭集切换
    await page.getByLabel('映射类型').selectOption('metric');
    await expect(valueSelect.locator('option', { hasText: '退款率' })).toHaveCount(1);
  });

  test('找谁问句出 owner 卡(确定性快轨,零 LLM)', async ({ page }) => {
    await page.goto('/analytics');
    await page.getByPlaceholder(/问点什么/).fill('户外机能品类该找谁');
    await page.getByRole('button', { name: '发送' }).click();
    await expect(page.getByText(/「户外机能」该找谁/).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/责任人注册表/).first()).toBeVisible();
    // 断言到表格单元格(页面会话累计多卡同文,owner 卡最新 → 取 last)
    await expect(page.getByRole('cell', { name: '李芸', exact: true }).last()).toBeVisible();
    await expect(page.getByRole('cell', { name: '销售部', exact: true }).last()).toBeVisible();
    await expect(page.getByRole('cell', { name: '户外机能', exact: true }).last()).toBeVisible();
  });

  test('归因卡附负责人列(每行「姓名(部门·职级)」)', async ({ page }) => {
    await page.goto('/analytics');
    await page.getByPlaceholder(/问点什么/).fill('净销售额各品类环比');
    await page.getByRole('button', { name: '发送' }).click();
    await expect(page.getByText(/归因 · 净销售额/).first()).toBeVisible({ timeout: 30_000 });
    // 行级负责人列:build_cards 按行键生成中文列头 + 每行带 owner 值
    await expect(page.getByRole('columnheader', { name: '负责人' })).toBeVisible();
    await expect(page.getByRole('cell', { name: /陈锋\(销售部·主管\)/ }).first()).toBeVisible();
    // 速览尾拼「找:」由引擎离线册钉死(test_owner_routing);全屏页不渲染 summary 行
  });

  test('复合问句「为什么退款这么多,什么原因,该找谁」出归因卡(实弹 bug 回钉)', async ({ page }) => {
    // 2026-10-08 实弹:此句曾落 unsupported(裸词「退款」不在词面集 + 复合语感无升格)。
    // 修后:找谁 × 指标 × 原因语感 → 确定性升格退款率×品类×环比归因组合,零 LLM。
    await page.goto('/analytics');
    await page.getByPlaceholder(/问点什么/).fill('为什么退款这么多,什么原因,该找谁');
    await page.getByRole('button', { name: '发送' }).click();
    await expect(page.getByText(/归因 · 退款率/).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole('columnheader', { name: '负责人' })).toBeVisible();
    await expect(page.getByRole('cell', { name: /未登记|销售部|售后部/ }).first()).toBeVisible();
  });

  test('排行问句「哪个品类退货率最高该找谁」出带负责人列的排行卡(第三载体)', async ({ page }) => {
    // 2026-10-09:找谁 × 指标 × 维度泛词 → 主管线语感直通升格排行组合(非归因,
    // 看高低非看变化),owner 列仅在有找谁意图时附(Q10:被动「各品类销售额」不添列)。
    // 「卖得最好」措辞属 gmv/volume 歧义 → L0 泛指反问,不用作本例。
    await page.goto('/analytics');
    await page.getByPlaceholder(/问点什么/).fill('哪个品类退货率最高该找谁');
    await page.getByRole('button', { name: '发送' }).click();
    await expect(page.getByText(/退款率/).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole('columnheader', { name: '负责人' }).last()).toBeVisible();
  });

  test('维护页改派与撤销(改后恢复种子态)', async ({ page }) => {
    await page.goto('/owner-mappings');
    await expect(page.getByText(/已登记映射\(\d+\)/)).toBeVisible({ timeout: 15_000 });
    // 登记衬衫 → 陈锋(种子原为赵磊)
    await page.getByLabel('映射类型').selectOption('category');
    await page.getByLabel('维度值').selectOption('衬衫');
    await page.getByLabel('负责人').selectOption('staff_sales_lead');
    await page.getByRole('button', { name: '登记' }).click();
    await expect(page.getByText('已登记')).toBeVisible({ timeout: 10_000 });
    // 表格行反映改派
    const row = page.locator('tr', { hasText: '衬衫' });
    await expect(row.getByText(/陈锋/)).toBeVisible({ timeout: 10_000 });
    // 撤销后恢复种子映射(衬衫 → staff_sales_2 赵磊)以保种子态
    await page.request.put('http://localhost:4000/api/admin/analytics/owner-mappings', {
      headers: { Authorization: `Bearer ${token}`, 'x-tenant-id': 'aurora', 'Content-Type': 'application/json' },
      data: { mapType: 'category', mapValue: '衬衫', staffId: 'staff_sales_2' },
    });
    await page.reload();
    await expect(page.locator('tr', { hasText: '衬衫' }).getByText(/赵磊/)).toBeVisible({ timeout: 15_000 });
  });

  test('员工页部门/职级下拉渲染(销售部主管在职)', async ({ page }) => {
    await page.goto('/staff');
    await expect(page.getByText('陈锋')).toBeVisible({ timeout: 15_000 });
    const row = page.locator('tr', { hasText: '陈锋' });
    await expect(row.getByLabel('部门:陈锋')).toHaveValue('销售部');
    await expect(row.getByLabel('职级:陈锋')).toHaveValue('主管');
  });
});
