import { expect, test } from '@playwright/test';

/**
 * 2026-09-13 去mock回归(real-data-only 收尾):
 * 1. 会话「LangGraph 决策流」Tab 只渲染 llm_call_logs 真遥测或诚实空态,
 *    编造的 12ms/48ms/95ms、置信度 0.985、运单号 SF10992381029 必须绝迹;
 * 2. 会话列表不再出现整列相同的 850 tokens / $0.0035 假兜底;
 * 3. 侧栏底部状态条来自 /api/health 真实探活,不再有「10 Nodes Active」。
 */

test.describe('Admin 去 mock 回归 (2026-09-13)', () => {
  test('决策流 Tab 只含真遥测,编造标记绝迹', async ({ page }) => {
    await page.goto('/conversations');
    await expect(page.getByText(/共 \d+ 条数据/)).toBeVisible();

    await page.getByRole('button', { name: '查看详情' }).first().click();
    await expect(page.getByText('人工坐席协同通道 (Live Takeover Desk)')).toBeVisible({ timeout: 10_000 });

    await page.getByRole('tab', { name: /LangGraph 决策流/ }).click();
    await expect(page.getByText('LangGraph 节点执行遥测 (llm_call_logs)')).toBeVisible({ timeout: 10_000 });
    // 真数据二选一:有节点遥测行,或诚实空态(快轨/规则路径无 LLM 调用)
    const nodeRows = await page.locator('body').getByText(/tokens \d/).count();
    const honestEmpty = await page.getByText(/暂无已持久化的 LLM 节点遥测/).count();
    expect(nodeRows + honestEmpty).toBeGreaterThan(0);

    const body = await page.locator('body').innerText();
    expect(body).not.toContain('0.985');
    expect(body).not.toContain('SF10992381029');
    expect(body).not.toContain('IntentTriageNode (意图分类与多轮槽位提取)');
  });

  test('会话列表不再整列 850 tokens / $0.0035 假值', async ({ page }) => {
    await page.goto('/conversations');
    await expect(page.getByText(/共 \d+ 条数据/)).toBeVisible();

    const body = await page.locator('main').innerText();
    const fakeTokenCells = (body.match(/850 tokens/g) || []).length;
    const fakeCostCells = (body.match(/\$0\.0035/g) || []).length;
    // 真实数据允许个别相同,但整列清一色编造值(此前每行都是)必须消失
    expect(fakeTokenCells).toBeLessThan(3);
    expect(fakeCostCells).toBeLessThan(3);
  });

  test('侧栏状态条来自真实健康检查', async ({ page }) => {
    await page.goto('/tenants');
    const footer = page.locator('aside').getByText(/服务在线|网关离线|探活中/);
    await expect(footer).toBeVisible({ timeout: 10_000 });
    const aside = await page.locator('aside').innerText();
    expect(aside).not.toContain('10 Nodes Active');
    expect(aside).not.toContain('Engine v2.4');
  });
});
