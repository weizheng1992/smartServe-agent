/**
 * 坐席台 P2 浏览器全链路(live-desk-rework spec §3 P2 验收行):
 * 「坐席↔顾客 socket 往返」——
 *   ① 坐席页(/agent-desk)socket.io operator 连接即在线(presence 可查);
 *   ② 排队态会话行点「认领」→ 状态条切「我接管中」(真源 threads 复合语义);
 *   ③ 坐席页发消息(socket send_message)→ 顾客 socket 收 new_message;
 *   ④ 顾客 socket 回一句(role=user)→ 坐席页时间线实时出现顾客行(new_message
 *      刷新)。
 * 顾客侧以 Node socket.io-client 直连 4000 网关;坐席侧走真实 3006 页面。
 */
import { expect, test, type Page } from '@playwright/test';
import { io, type Socket } from 'socket.io-client';

const GW = 'http://localhost:4000';
const STAFF = { email: 'test@example.com', password: 'agent-all-dev' };

const loginViaApi = async (request: any) => {
  const res = await request.post(`${GW}/api/auth/login`, { data: STAFF });
  const body = await res.json();
  return body.data.token as string;
};

/** 顾客 socket(弱身份模型,未认证连接仅能以 user 身份发言)。 */
function connectCustomer(userId: string): Promise<Socket> {
  return new Promise((resolve, reject) => {
    const socket = io(`${GW}/ws/chat`, {
      path: '/socket.io',
      transports: ['websocket'],
      auth: { tenantId: 'aurora', userId, role: 'user' },
      reconnection: false,
    });
    socket.on('connect', () => resolve(socket));
    socket.on('connect_error', reject);
    setTimeout(() => reject(new Error('顾客 socket 连接超时')), 10_000);
  });
}

async function waitNewMessage(socket: Socket, predicate: (payload: any) => boolean, timeoutMs: number) {
  const deadline = Date.now() + timeoutMs;
  return new Promise<any>((resolve, reject) => {
    const handler = (payload: any) => {
      if (predicate(payload)) {
        socket.off('new_message', handler);
        resolve(payload);
      }
    };
    socket.on('new_message', handler);
    setTimeout(() => reject(new Error('等待 new_message 超时')), deadline - Date.now());
  });
}

test.describe('坐席台 认领→回复→顾客收到(P2 socket 往返)', () => {
  let token: string;
  const threadId = `e2e_desk_${Date.now()}`;
  const userId = `u_e2e_desk_${Date.now()}`;

  test.beforeAll(async ({ request }) => {
    token = await loginViaApi(request);
    const res = await request.post(`${GW}/api/chat/threads`, {
      headers: { Authorization: `Bearer ${token}`, 'x-tenant-id': 'aurora' },
      data: { threadId, userId, businessId: 'aurora' },
    });
    expect(res.ok()).toBeTruthy();
    // 摆排队态(human_takeover + 无坐席 = 呼叫中;员工形态 status 路由)
    const q = await request.post(`${GW}/api/conversations/${threadId}/status`, {
      headers: { Authorization: `Bearer ${token}`, 'x-tenant-id': 'aurora' },
      data: { status: 'human_takeover' },
    });
    expect(q.ok()).toBeTruthy();
  });

  const presetAuth = async (page: Page) => {
    // addInitScript 不捕获闭包:Node 侧 STAFF 引用带不进浏览器,字段一律走参数
    await page.addInitScript(
      (s: { token: string; email: string }) => {
        localStorage.setItem('merchant-admin.token', s.token);
        localStorage.setItem('merchant-admin.staff', s.email);
        localStorage.setItem('merchant-admin.boss', JSON.stringify(s));
      },
      { token, email: STAFF.email },
    );
  };

  test('坐席连接在线并认领回复,顾客实时收到', async ({ page, request }) => {
    await presetAuth(page);
    const customer = await connectCustomer(userId);
    const joined = await new Promise<any>((resolve) => {
      customer.emit('join_thread', { threadId, tenantId: 'aurora', role: 'user' }, (ack: any) => resolve(ack));
      setTimeout(() => resolve({ success: false }), 10_000);
    });
    expect(joined?.success ?? true).toBeTruthy();

    try {
      // ① 坐席页开台:列表出现排队行(认领按钮 = 排队态可见口径)
      await page.goto('/agent-desk');
      const row = page.locator('[data-testid="conversation-row"]', { hasText: userId }).first();
      await expect(row).toBeVisible({ timeout: 30_000 });

      // ①' 坐席 socket 连接即在线(presence 真源)
      let online = false;
      for (let i = 0; i < 20 && !online; i++) {
        const pres = await (
          await request.get(`${GW}/api/merchant/live-desk/presence`, {
            headers: { Authorization: `Bearer ${token}`, 'x-tenant-id': 'aurora' },
          })
        ).json();
        online = (pres.agents || []).some((a: any) => a.email === STAFF.email && a.online);
        if (!online) await page.waitForTimeout(500);
      }
      expect(online).toBe(true);

      // ② 认领:状态条切「我接管中」(服务端原子守卫裁决)
      await page.locator('[data-testid="claim-button"]').first().click();
      await expect(page.getByText('我接管中').first()).toBeVisible({ timeout: 15_000 });

      // ③ 坐席回复 → 顾客实时收到
      const reply = '您好,我是人工客服,有什么可以帮您?';
      const got = waitNewMessage(customer, (p) => p.role === 'operator' && p.content === reply, 15_000);
      await page.getByPlaceholder('回复顾客…').fill(reply);
      await page.getByRole('button', { name: '发送' }).click();
      const msg = await got;
      expect(msg.threadId).toBe(threadId);

      // ④ 顾客回一句 → 坐席页时间线实时出现顾客行
      const userLine = '我买的衣服能退吗';
      await page.locator('[data-testid="desk-timeline"]').waitFor();
      const seenOnDesk = (async () => {
        const deadline = Date.now() + 20_000;
        while (Date.now() < deadline) {
          const text = await page.locator('[data-testid="desk-timeline"]').innerText();
          if (text.includes(userLine)) return true;
          await page.waitForTimeout(500);
        }
        return false;
      })();
      await new Promise<any>((resolve) => {
        customer.emit('send_message', { threadId, tenantId: 'aurora', role: 'user', content: userLine }, (ack: any) =>
          resolve(ack),
        );
        setTimeout(() => resolve({ success: false }), 10_000);
      });
      expect(await seenOnDesk).toBe(true);
    } finally {
      customer.disconnect();
    }
  });
});
