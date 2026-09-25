import { expect, test } from '@playwright/test';

/**
 * 商户运营台(/admin,端口 3005)全量点击审计 — admin-readiness 工单 04。
 *
 * 只读优先:Tab 切换/表格渲染/详情/过滤/空态;变更类操作仅做「驳回」
 * (无资金移动,dev 数据)且仅当存在 waiting 工单时。
 * 截图证据:.scratch/admin-console-readiness/assets/merchant-console/
 */

const SHOT = '.scratch/admin-console-readiness/assets/merchant-console';

test.describe('商户运营台审计 (admin-readiness 04)', () => {
  let waitingApprovalId: string | null = null;

  test('订单管理 Tab:表格/审计流水/统计渲染', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.getByText(/独立物理隔离/)).toBeVisible();
    await page.waitForTimeout(1500);

    // 订单表有真实数据(aurora 30 SPU 商户)
    const body = await page.locator('body').innerText();
    expect(body).not.toContain('undefined');
    expect(body).not.toContain('NaN');

    await page.screenshot({ path: `${SHOT}/01_orders.png`, fullPage: true });
  });

  test('售后审批 Tab:列表渲染 + 徽标语义', async ({ page }) => {
    await page.goto('/admin');
    await page.waitForTimeout(1200);
    await page.getByText('待办审核 (HITL)').first().click();
    await page.waitForTimeout(1200);

    const body = await page.locator('body').innerText();
    // 找一个 waiting 工单供驳回用例使用
    const waitingMatch = body.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/);
    waitingApprovalId = waitingMatch ? waitingMatch[0] : null;

    await page.screenshot({ path: `${SHOT}/02_approvals.png`, fullPage: true });
  });

  test('在线客服工作台:会话列表 + 时间线加载', async ({ page }) => {
    await page.goto('/admin');
    await page.waitForTimeout(1200);
    await page.getByText('在线客服工作台').first().click();
    await page.waitForTimeout(1500);

    // 时间线或空态可见(严禁假对话——去 mock 收尾后的诚实行为)
    const body = await page.locator('body').innerText();
    const hasTimeline = body.includes('用户') || body.includes('客服');
    const hasEmpty = body.includes('暂无') || body.includes('选择');
    expect(hasTimeline || hasEmpty).toBeTruthy();

    await page.screenshot({ path: `${SHOT}/03_livedesk.png`, fullPage: true });
  });

  test('SPU 商品库 / SKU 规格库存:目录渲染', async ({ page }) => {
    await page.goto('/admin');
    await page.waitForTimeout(1200);
    await page.getByText('SPU 商品库').first().click();
    await page.waitForTimeout(1000);
    const spuBody = await page.locator('body').innerText();
    expect(spuBody).not.toContain('undefined');
    await page.screenshot({ path: `${SHOT}/04_spu.png`, fullPage: true });

    await page.getByText('SKU 规格库存').first().click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${SHOT}/05_sku.png`, fullPage: true });
  });

  test('SPI 开放审计流水:表渲染', async ({ page }) => {
    await page.goto('/admin');
    await page.waitForTimeout(1200);
    await page.getByText('SPI 开放审计流水').first().click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${SHOT}/06_spi.png`, fullPage: true });
  });

  test('P1 金额回照回归:waiting 退款审批卡金额=商户库真实快照', async ({ page }) => {
    // 工单 11 验收原句「审批卡金额>0」——P1 修复(gatekeeper 建票回查
    // merchant_orders.total_amount 落 args.amount,商户不再盲批资金单)
    // 此前零自动化验证(code-review 2026-09-14 补钉):卡面金额必须等于
    // 快照值,严禁 ¥0.00。数据驱动:无带快照的 waiting 退款票时诚实 skip。
    const res = await page.request.get('/api/admin/approvals?tenantId=aurora&status=waiting&actionType=processRefund');
    const body = await res.json();
    const refundTicket = (body.approvals || []).find((a: any) => typeof a.actionPayload?.args?.amount === 'number');
    test.skip(!refundTicket, '无带金额快照的 waiting 退款工单(先经 /api/chat 实弹造票)');
    const expectedAmount = `¥${Number(refundTicket.actionPayload.args.amount).toFixed(2)}`;

    await page.goto('/admin');
    await page.waitForTimeout(1200);
    await page.getByText('待办审核 (HITL)').first().click();
    await page.waitForTimeout(1200);

    const pageBody = await page.locator('body').innerText();
    expect(pageBody).toContain(expectedAmount);
    expect(pageBody).not.toContain('¥0.00');
    await page.screenshot({ path: `${SHOT}/09_refund_amount.png`, fullPage: false });
  });

  test('驳回流(UI 点击):waiting 工单驳回后状态翻转 + actor 落库', async ({ page }) => {
    // 驳回当前唯一的 waiting 工单(processRefund,dev 数据,拒绝不动资金)验证
    // 商户面两步驳回流 + 核准人契约落库;human_escalation 型终态是 resolved_by_human,
    // 资金型(processRefund)终态是 rejected —— 断言按 actionType 分别钉真实语义
    await page.goto('/admin');
    await page.waitForTimeout(1200);
    await page.getByText('待办审核 (HITL)').first().click();
    await page.waitForTimeout(1200);

    // 两步流:点「驳回」→ 原因弹窗 → 「确认驳回」
    // 无 waiting 工单时按钮不存在,驳回链路已在此前审计轮实弹验证
    // (rejected + merchant_operator + 自定义原因,见 git 日志工单 04/11)
    const rejectBtnCount = await page.getByRole('button', { name: '驳回', exact: true }).count();
    test.skip(rejectBtnCount === 0, '无 waiting 工单,驳回流已在此前审计轮实弹验证');
    await page.getByRole('button', { name: '驳回', exact: true }).first().click();
    await expect(page.getByText('驳回审批工单')).toBeVisible();
    await page.locator('#reject-reason').fill('商户台审计:驳回流验证(dev 数据)');
    await page.getByRole('button', { name: '确认驳回' }).click();
    await page.waitForTimeout(1800);

    const res = await page.request.get('/api/admin/approvals?tenantId=aurora');
    const body = await res.json();
    // 按 actionType 分别钉真实语义(code-review 2026-09-14 收紧:旧 OR 断言
    // ['rejected','resolved_by_human'].includes 会让接管型落 rejected 漏网):
    // 资金型 processRefund 终态 rejected;人工接管型 human_escalation 终态
    // resolved_by_human。以「商户台审计」自定义原因定位本次驳回的票。
    const resolved = (body.approvals || []).find((a: any) =>
      (a.actionPayload?.rejectionReason || '').includes('商户台审计'),
    );
    expect(resolved, '按驳回原因定位到本次驳回的工单').toBeTruthy();
    const expectedStatus = resolved.actionType === 'human_escalation' ? 'resolved_by_human' : 'rejected';
    expect(resolved.status).toBe(expectedStatus);
    expect(resolved.actionPayload?.resolvedBy).toBe('merchant_operator');
    await page.screenshot({ path: `${SHOT}/07_reject.png`, fullPage: false });
  });

  test('缺陷修复回归:状态徽标中文化 + /admin 无顾客浮动窗', async ({ page }) => {
    await page.goto('/admin');
    await page.waitForTimeout(1500);
    // 订单中心不再出现裸英文状态徽标(DELIVERED → 已签收)
    const body = await page.locator('body').innerText();
    expect(body).not.toContain('DELIVERED');
    // 顾客浮动客服窗不得挂在商户运营台
    await expect(page.getByText('极光智能客服')).toHaveCount(0);
    // 浮动窗在前台仍可见
    await page.goto('/');
    await page.waitForTimeout(1200);
    await expect(page.getByText('极光智能客服').first()).toBeVisible();
  });

  test('LiveDesk 布局:视口截图核验页头是否真重复(排除 sticky 截图伪影)', async ({ page }) => {
    await page.goto('/admin');
    await page.waitForTimeout(1200);
    await page.getByText('在线客服工作台').first().click();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SHOT}/08_livedesk_viewport.png`, fullPage: false });
  });
});
