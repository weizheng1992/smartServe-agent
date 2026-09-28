/**
 * live-desk 事故回绿钉(live-desk-rework P1,spec §3 验收行):
 * 浏览器全链路「接管 → 释放 → AI 恢复作答」——
 *   ① 工作台点「主动接管会话」→ 真源 threads.human_takeover,按钮切「释放回 AI 托管」;
 *   ② 接管期 AI 暂停闸:顾客轮次不建作业(jobId=""+isHumanActive),诚实文案;
 *   ③ 工作台点「释放回 AI 托管」→ 真源回 active,按钮切回;
 *   ④ 释放后下一条顾客消息恢复建作业,历史出现真引擎 assistant 行(AI 恢复作答)。
 * 钉死的事故:接管/释放曾经只是 socket/工单表皮,释放后 AI 永久哑火 ——
 * 本用例红了即事故回潮。复用运行中的 3006 前端 + 4000 网关,真实 LLM 作答。
 */
import { expect, test } from '@playwright/test';

const GW = 'http://localhost:4000';
const STAFF = { email: 'test@example.com', password: 'agent-all-dev' };

const loginViaApi = async (request: any) => {
  const res = await request.post(`${GW}/api/auth/login`, { data: STAFF });
  const body = await res.json();
  return body.data.token as string;
};

test.describe('客服工作台 接管→释放→AI 恢复(事故回绿钉)', () => {
  let token: string;
  const threadId = `e2e_takeover_${Date.now()}`;
  const userId = `u_e2e_to_${Date.now()}`;

  test.beforeAll(async ({ request }) => {
    token = await loginViaApi(request);
    // 显式建线程(零 LLM 确定性;服务端可能落 welcome/greet 引导行,断言时排除)
    const res = await request.post(`${GW}/api/chat/threads`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { threadId, userId, businessId: 'aurora' },
    });
    expect(res.ok()).toBeTruthy();
  });

  test.beforeEach(async ({ page }) => {
    // 0013:身份 = JWT;预置老板会话
    await page.addInitScript((t: string) => {
      localStorage.setItem('merchant-admin.token', t);
      localStorage.setItem('merchant-admin.staff', STAFF.email);
      localStorage.setItem('merchant-admin.boss', JSON.stringify({ token: t, email: STAFF.email }));
    }, token);
  });

  test('接管→释放→AI 恢复作答', async ({ page, request }) => {
    const auth = { Authorization: `Bearer ${token}` };
    await page.goto('/live-desk');

    // 会话进入队列(首载 + 8s 轮询窗口内),搜索框隔离后选中
    const row = page.locator('p', { hasText: threadId }).first();
    await expect(row).toBeVisible({ timeout: 20_000 });
    await row.click();

    // ① 接管:按钮切「释放回 AI 托管」(操作后立即刷新,不等轮询)
    await page.getByRole('button', { name: /主动接管会话/ }).click();
    const releaseBtn = page.getByRole('button', { name: /释放回 AI 托管/ });
    await expect(releaseBtn).toBeVisible({ timeout: 15_000 });

    // ② 接管期 AI 暂停闸:不建作业(isHumanActive 契约;异步形状无 output
    // 字段,sync 形状的诚实文案由 pytest 契约钉死)
    const paused = await (
      await request.post(`${GW}/api/chat`, {
        headers: auth,
        data: { message: '人工在吗', threadId, userId, businessId: 'aurora' },
      })
    ).json();
    expect(paused.success).toBe(true);
    expect(paused.jobId).toBe('');
    expect(paused.isHumanActive).toBe(true);

    // ③ 释放:按钮切回「主动接管会话」,真源回 active
    await releaseBtn.click();
    await expect(page.getByRole('button', { name: /主动接管会话/ })).toBeVisible({ timeout: 15_000 });

    // ④ 释放后恢复建作业(jobId 非空,无 isHumanActive 标记)
    const resumed = await (
      await request.post(`${GW}/api/chat`, {
        headers: auth,
        data: { message: '请问你们的退货政策是什么', threadId, userId, businessId: 'aurora' },
      })
    ).json();
    expect(resumed.success).toBe(true);
    expect(resumed.jobId).not.toBe('');
    expect(resumed.isHumanActive).toBeFalsy();

    // ⑤ AI 恢复作答:历史出现真引擎 assistant 行(排除 welcome/greet 引导行;
    // 真实 LLM 往返,轮询至多 90s —— 红了即释放后 AI 哑火事故回潮)
    const deadline = Date.now() + 90_000;
    let aiReplied = false;
    while (Date.now() < deadline) {
      const hist = await (
        await request.get(`${GW}/api/chat/messages?threadId=${threadId}&businessId=aurora`, { headers: auth })
      ).json();
      const rows = (hist.messages || []) as Array<{ id?: string; role: string; content?: string }>;
      if (
        rows.some(
          (m) =>
            m.role === 'assistant' &&
            !`${m.id}`.startsWith('welcome_') &&
            !`${m.id}`.startsWith('greet_') &&
            (m.content || '').trim(),
        )
      ) {
        aiReplied = true;
        break;
      }
      await page.waitForTimeout(3000);
    }
    expect(aiReplied).toBe(true);
  });
});
