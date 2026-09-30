import { expect, test } from '@playwright/test';

/**
 * 商户内嵌运营台(/admin,端口 3005)审计 — admin-readiness 04,c7b26cd 后重写。
 *
 * c7b26cd(2026-09-27)给 /api/admin/* 族上了员工身份闸(_require_staff:
 * 无/坏 Bearer 401,非在职员工 403),而内嵌台无身份源 —— 旧的「点击审计全部
 * Tab」(订单/审批/客服台/SPU/SKU/SPI)是在审计匿名裸奔面,现已整体被 401
 * 引导卡取代。本套件改钉身份闸契约本身:
 *   1. 管理族 API 匿名必 401(闸生效);
 *   2. /admin UI 只出引导卡,不再渲染任何业务数据与 Tab;
 *   3. 前台商城不受累(浮动窗语义照旧)。
 *
 * 审批族 UI 审计(驳回流、退款金额回照)自此无宿主:内嵌台永久 401 无法再
 * 驱动,归宿是 merchant-admin 的 order-manager approvals-tab
 * (apps/merchant-admin/src/pages/order-manager/components/approvals-tab.tsx,
 * 员工登录面),迁移属新功能工作另行排期 —— 历史实弹证据见 git 日志
 * c510d27/faf2782(驳回流 rejected+merchant_operator、卡面金额=快照)。
 * 截图证据:.scratch/admin-console-readiness/assets/merchant-console/
 */

const SHOT = '.scratch/admin-console-readiness/assets/merchant-console';

// 商户门户独立端口(3005):/api/* 相对请求与 /admin、/ 相对 goto 都吃本文件
// 的 baseURL 覆写 —— 主套件默认 baseURL 是 apps/web 的 3000,不覆写必败。
test.use({ baseURL: 'http://localhost:3005' });

test.describe('商户内嵌运营台:身份闸契约 (admin-readiness 04)', () => {
  test('管理族 API 匿名必 401(订单/审批/会话三族抽查)', async ({ page }) => {
    for (const path of [
      '/api/admin/orders',
      '/api/admin/approvals?tenantId=aurora',
      '/api/admin/conversations?tenantId=aurora',
    ]) {
      const res = await page.request.get(path);
      expect(res.status(), `${path} 匿名裸奔未被闸住`).toBe(401);
    }
  });

  test('/admin 只出员工鉴权引导卡,不渲染业务数据与 Tab', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.getByText('商户管理面已启用员工鉴权')).toBeVisible({ timeout: 10_000 });
    // 引导卡诚实指路独立后台(3006)
    await expect(page.getByText('端口 3006')).toBeVisible();

    const body = await page.locator('body').innerText();
    // 旧 Tab 面不再可达
    for (const tabText of ['待办审核 (HITL)', '在线客服工作台', 'SPU 商品库', 'SKU 规格库存', 'SPI 开放审计流水']) {
      expect(body, `内嵌台仍残留 ${tabText} 入口`).not.toContain(tabText);
    }
    // 业务数据不得匿名渲染
    expect(body).not.toContain('累计订单总数');

    await page.screenshot({ path: `${SHOT}/01_staff_auth_gate.png`, fullPage: true });
  });

  test('前台商城不受累:浮动窗前台可见、/admin 不挂', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.getByText('商户管理面已启用员工鉴权')).toBeVisible({ timeout: 10_000 });
    // 顾客浮动客服窗不得挂在商户运营台
    await expect(page.getByText('极光智能客服')).toHaveCount(0);
    // 浮动窗在前台仍可见
    await page.goto('/');
    await expect(page.getByText('极光智能客服').first()).toBeVisible({ timeout: 10_000 });
  });
});
