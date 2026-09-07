import { expect, test } from '@playwright/test';

import { loginViaUi } from './helpers/auth';
import { chatContainer as chatContainerOf } from './helpers/chat';

/**
 * HITL 审批全链路 E2E(wayfinder 004):超阈值退款挂起 → web 审批卡 → 人工核签 →
 * 恢复执行真实退款 → 会话落定。
 *
 * 场景锚点:ORD-ECO-LARGE($199.96)> ecommerce 免签阈值($100)→ 引擎挂起;
 * 种子把送达日期锚在 NOW()-3d(7 天时效窗口内),核签通过后退款可真实执行,
 * 且 globalSetup 每次重播种子重置 refunded 状态,用例可重复。
 * 前端链路:useApprovals 2s 轮询 /api/chat/approvals(按 activeThreadId 过滤
 * waiting 卡)→ APMPanel 渲染核签按钮 → POST 后 triggerStream(job_resume_*)
 * 重开 SSE 流式渲染恢复输出。
 */
test.skip(
  ({ browserName }) => browserName !== 'chromium',
  'HITL 链路含两次真实 LLM 运行(挂起+恢复),单浏览器钉契约即可;三浏览器并行重复消耗且共享种子订单状态',
);

test.describe('HITL 审批流 E2E(超阈值退款 → 人工核签 → 恢复执行)', () => {
  test('超阈值退款核签通过后恢复执行并物理退款成功', async ({ page }) => {
    test.setTimeout(300_000); // 挂起+恢复两次真实 LLM 运行,默认 30s 总时钟必爆
    await loginViaUi(page);
    await expect(page).toHaveURL('/');

    // 新开线程(输入框在无 activeThreadId 时禁用)
    await page.getByRole('button', { name: /开启新一轮对话/ }).click();
    const messageInput = page.locator('input[placeholder*="发送您的业务诉求"]');
    await expect(messageInput).toBeEnabled({ timeout: 15_000 });

    // 发起超阈值退款 → 引擎挂起等待人工(真实 LLM:triage→planner→HITL 门禁)
    await messageInput.fill('帮我申请订单 ORD-ECO-LARGE 的退款，商品质量问题');
    await page.locator('button:has-text("发送")').click();

    const chatContainer = chatContainerOf(page);
    await expect(chatContainer).toContainText('ORD-ECO-LARGE', { timeout: 60_000 });

    // 审批卡经 2s 轮询出现(APMPanel 安全红线卡)
    await expect(page.getByText('待人工核准放行')).toBeVisible({ timeout: 60_000 });

    // 核签放行 → Fast-Path 派发 job_resume_* → SSE 恢复流
    await page.getByRole('button', { name: /核准放行/ }).click();

    // 卡片随 waiting 状态消失而落定(轮询驱动)
    await expect(page.getByText('待人工核准放行')).toBeHidden({ timeout: 30_000 });
    // 恢复输出:退款真实执行成功。断言锚定确定性卡片字段(退款核签与赔付凭证卡,
    // CardSynthesizer 渲染)而非 LLM 措辞 —— 实测同一链路措辞会在
    // "执行成功"/"已成功执行"间漂移(wayfinder 004)。
    await expect(chatContainer).toContainText('核定退款金额', { timeout: 120_000 });
    await expect(chatContainer).toContainText('$199.96', { timeout: 15_000 });
  });
});
