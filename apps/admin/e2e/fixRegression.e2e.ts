import { expect, test } from '@playwright/test';

/**
 * 2026-09-13 admin 十模块 GUI 测试 · 修复回归 spec(真实 Chromium 点击)。
 *
 * 覆盖六项修复,断言全部锚定修复后的真实渲染:
 * P1-1 RAG 新增切片:自拟标题/分类落库(此前 422 静默失败 + 标题被硬编码覆盖)
 * P1-2 RAG 演练台:all 视角真检索(此前 all 硬编码 ecommerce + 0.75 假分数兜底)
 * P1-3 审批状态:resolved_by_human 显示「已接管完结」(此前回落成「待审批」)
 * P2-4 搜索重置页码(此前停留旧页造成「共 N 条 第 2/1 页」假空态)
 * P2-5 画像弹窗归属商户含真实注册租户 aurora(此前硬编码三个演示租户)
 * P2-6 RAG 分类筛选选项与数据 key 对齐(此前中文文案永不匹配)
 * P3  结单并归档二次确认(此前一键直接归档)
 *
 * 自清理:本 spec 新建的切片在用例尾部经 UI 删除;其余用例只读或取消收尾。
 */

const RAG_CREATE_TITLE = `修复回归切片 ${Date.now()}`;

test.describe('Admin 修复回归 (2026-09-13)', () => {
  test('P1-1+P2-6 RAG 新增切片全链路 + 分类筛选对齐', async ({ page }) => {
    await page.goto('/rag-studio');
    await expect(page.getByText('RAG 向量检索在线演练台')).toBeVisible();

    // 新增切片:弹窗打开、归属商户下拉含注册表真实租户 aurora(P2-5 同源验证)
    await page.getByRole('button', { name: '新增知识切片' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    const businessSelect = dialog.locator('select').first();
    const auroraOption = businessSelect.locator('option[value="aurora"]');
    await expect(auroraOption).toHaveText(/极光潮品官方旗舰店/);

    // 分类下拉必须是真实 key(此前是永不匹配的中文文案)
    const categorySelect = dialog.locator('select').nth(1);
    await expect(categorySelect.locator('option[value="product_knowledge"]')).toHaveCount(1);

    await dialog.getByPlaceholder('如 Nike 退换货 SOP').fill(RAG_CREATE_TITLE);
    await businessSelect.selectOption('aurora');
    await categorySelect.selectOption('product_knowledge');
    await dialog
      .getByPlaceholder(/输入该切片涵盖的详细业务事实与规则/)
      .fill('修复回归:极光潮品冲锋衣严禁机洗,需中性洗涤剂 30 度手洗。');
    await dialog.getByRole('button', { name: '保存提交' }).click();
    await expect(dialog).toBeHidden();

    // 自拟标题必须出现在列表(此前被服务端硬编码「官方通用商城知识文档」覆盖)
    await page.getByRole('textbox', { name: /搜索切片/ }).fill(RAG_CREATE_TITLE);
    await expect(page.getByRole('cell', { name: new RegExp(RAG_CREATE_TITLE) })).toBeVisible();
    const row = page.getByRole('row', { name: new RegExp(RAG_CREATE_TITLE) });
    await expect(row).toContainText(/aurora/i);
    await expect(row).toContainText(/product_knowledge/i);

    // 分类筛选按真实 key 生效(此前一筛就空)
    await page.getByRole('button', { name: '重置筛选' }).click();
    await page.locator('main select').first().selectOption('product_knowledge');
    await expect(page.getByText('未检索到符合条件的知识库切片')).toBeHidden();
    await expect(page.getByRole('cell', { name: /product_knowledge/ }).first()).toBeVisible();

    // 自清理:删除本用例创建的切片(走真实确认弹窗)
    await page.getByRole('textbox', { name: /搜索切片/ }).fill(RAG_CREATE_TITLE);
    await row.getByRole('button', { name: '删除' }).click();
    const confirm = page.getByRole('dialog');
    await expect(confirm).toBeVisible();
    await confirm.getByRole('button', { name: '确认删除' }).click();
    await expect(page.getByRole('cell', { name: new RegExp(RAG_CREATE_TITLE) })).toBeHidden();
  });

  test('P1-2 RAG 演练台 all 视角真检索(相关命中或诚实空态,严禁假分数)', async ({ page }) => {
    await page.goto('/rag-studio');
    await page.getByPlaceholder(/输入自然语言测试 Query/).fill('冲锋衣可以机洗吗');
    await page.getByRole('button', { name: '发起检索测试' }).click();

    const playground = page.locator('body');
    await expect(playground.getByText(/召回 Top-|未召回相关切片/)).toBeVisible({
      timeout: 15_000,
    });

    const honestEmpty = await playground.getByText('未召回相关切片').count();
    if (honestEmpty === 0) {
      // 有真命中:冲锋衣知识必须可召回(all 视角此前检不到他租知识),且分数不得再是整齐的 75.0%
      const firstHit = playground.locator('.line-clamp-3').first();
      await expect(firstHit).toContainText(/冲锋衣|机洗|洗涤|面料/);
      const scores = await playground.getByText(/Score:/).allInnerTexts();
      expect(scores.length).toBeGreaterThan(0);
      for (const s of scores) {
        expect(s.replace(/\s+/g, ' ')).not.toBe('Score: 75.0%');
      }
    }
  });

  test('P1-3 审批列表:resolved_by_human 显示已接管完结 + 驳回理由透出', async ({ page }) => {
    await page.goto('/audits');
    await expect(page.getByText('审批工单 ID / 会话')).toBeVisible();

    // 人工接管型工单(此前核准后永远显示「待审批」)
    const escalationRow = page.getByRole('row', { name: /vocab_V5_再形复合/ });
    await expect(escalationRow).toBeVisible();
    await expect(escalationRow).toContainText('已接管完结 (Resolved by Human)');
    await expect(escalationRow).toContainText('人工坐席接管');

    // 被驳回工单的理由从 actionPayload 透出到「审批人 / 驳回理由」列(此前恒为「-」)
    const rejectedRow = page.getByRole('row', { name: /nightly-0913-e1/ }).first();
    await expect(rejectedRow).toContainText('已驳回 (Rejected)');
    await expect(rejectedRow).toContainText('平台管理员依据风控策略驳回');

    // 动作详情列是人读摘要,不再是裸 JSON 糊在动作名后
    await expect(rejectedRow).toContainText(/orderId: AURORA-ORD/);

    // 状态筛选出现新档位
    const statusSelect = page.locator('main select').first();
    await expect(statusSelect.locator('option[value="resolved_by_human"]')).toHaveCount(1);
  });

  test('P2-4 会话列表:第 2 页搜索自动重置回第 1 页(假空态消除)', async ({ page }) => {
    await page.goto('/conversations');
    await expect(page.getByText(/共 \d+ 条数据/)).toBeVisible();

    await page.getByRole('button', { name: '下一页' }).click();
    await expect(page.getByText(/第 2 \/ \d+ 页/)).toBeVisible();

    await page.getByRole('textbox', { name: /搜索会话ID/ }).fill('vocab_V5_再形复合');
    await expect(page.getByText(/第 1 \/ 1 页/)).toBeVisible();
    await expect(page.getByRole('cell', { name: /vocab_V5_再形复合/ }).first()).toBeVisible();
  });

  test('P2-5 画像弹窗归属商户下拉含注册表真实租户', async ({ page }) => {
    await page.goto('/personas');
    await expect(page.getByText(/共 \d+ 条数据/)).toBeVisible();

    await page.getByRole('button', { name: '录入画像事实' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    const businessSelect = dialog.locator('select').first();
    await expect(businessSelect.locator('option[value="aurora"]')).toHaveText(/极光潮品官方旗舰店/);
    await expect(businessSelect.locator('option[value="ecommerce"]')).toHaveCount(1);
    // 取消收尾,不写数据
    await dialog.getByRole('button', { name: '取消' }).click();
    await expect(dialog).toBeHidden();
  });

  test('P3 会话结单并归档必须二次确认(取消不生效)', async ({ page }) => {
    await page.goto('/conversations');
    await expect(page.getByText(/共 \d+ 条数据/)).toBeVisible();

    await page.getByRole('button', { name: '查看详情' }).first().click();
    const drawer = page.getByText('人工坐席协同通道 (Live Takeover Desk)');
    await expect(drawer).toBeVisible({ timeout: 10_000 });

    await page.getByRole('button', { name: '结单并归档' }).click();
    const confirm = page.getByRole('dialog');
    await expect(confirm).toBeVisible();
    await expect(confirm).toContainText('确认结单并归档该会话');
    // 取消:会话状态不变
    await confirm.getByRole('button', { name: '取消' }).click();
    await expect(confirm).toBeHidden();
    await expect(page.getByRole('button', { name: '结单并归档' }).first()).toBeVisible();
  });
});
