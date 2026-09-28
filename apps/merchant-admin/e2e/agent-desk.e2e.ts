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
import { type Page, expect, test } from '@playwright/test';
import { type Socket, io } from 'socket.io-client';

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

      // ② 认领:状态条切「我接管中」(服务端原子守卫裁决)。认领按钮取
      // 本轮行内部 —— 列表存在历史残留行,全局 first() 会认领到旧行。
      await row.getByTestId('claim-button').click();
      await expect(row.getByText('我接管中')).toBeVisible({ timeout: 15_000 });

      // ③ 坐席回复 → 顾客实时收到
      const reply = '您好,我是人工客服,有什么可以帮您?';
      const got = waitNewMessage(customer, (p) => p.role === 'operator' && p.content === reply, 15_000);
      await page.getByPlaceholder('回复顾客…').fill(reply);
      await page.getByRole('button', { name: '发送', exact: true }).click();
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

/**
 * P4 消息可靠性(live-desk-rework spec §3 P4 验收行)。
 * 台内批驳卡不设浏览器用例:waiting escalation 工单只能由引擎链路产生
 * (gatekeeper 内部创建;socket takeover 产的是 resolved_by_human 终局,
 * 无 HTTP 造法),批驳语义已由 pytest 专册(test_live_desk_p4_decouple)
 * 与 vitest(use-live-desk.test)双层钉死,此处不重复。
 */
test.describe('P4:ack 失败回滚 + typing 指示', () => {
  let token: string;

  test.beforeAll(async ({ request }) => {
    token = await loginViaApi(request);
  });

  /** 建线程 + 摆排队态(human_takeover + 无坐席 = 呼叫中),两条用例共用。 */
  const seedQueuingThread = async (request: any, threadId: string, userId: string) => {
    const res = await request.post(`${GW}/api/chat/threads`, {
      headers: { Authorization: `Bearer ${token}`, 'x-tenant-id': 'aurora' },
      data: { threadId, userId, businessId: 'aurora' },
    });
    expect(res.ok()).toBeTruthy();
    const q = await request.post(`${GW}/api/conversations/${threadId}/status`, {
      headers: { Authorization: `Bearer ${token}`, 'x-tenant-id': 'aurora' },
      data: { status: 'human_takeover' },
    });
    expect(q.ok()).toBeTruthy();
  };

  const presetAuth = async (page: Page) => {
    await page.addInitScript(
      (s: { token: string; email: string }) => {
        localStorage.setItem('merchant-admin.token', s.token);
        localStorage.setItem('merchant-admin.staff', s.email);
        localStorage.setItem('merchant-admin.boss', JSON.stringify(s));
      },
      { token, email: STAFF.email },
    );
  };

  test('socket 掐断后发送:ack 失败如实提示,时间线回真源不残留乐观气泡', async ({ page, request }) => {
    const threadId = `e2e_p4ack_${Date.now()}`;
    const userId = `u_e2e_p4ack_${Date.now()}`;
    await seedQueuingThread(request, threadId, userId);
    await presetAuth(page);
    await page.goto('/agent-desk');
    const row = page.locator('[data-testid="conversation-row"]', { hasText: userId }).first();
    await expect(row).toBeVisible({ timeout: 30_000 });

    // 正常通路认领(socket ack 裁决;行内定位,残留行不吃全局 first())
    await row.getByTestId('claim-button').click();
    await expect(row.getByText('我接管中')).toBeVisible({ timeout: 15_000 });

    // 掐断 socket.io(HTTP /api/* 不受影响)后重载:坐席页 socket 重连
    // 失败 → emitAck 走「未连接实时通道」失败分支,时间线走 HTTP 真源。
    // 坐席页 transports 硬编码 websocket,page.route 拦不到 ws 帧,须
    // routeWebSocket 直接拒握手。
    await page.routeWebSocket('**/socket.io**', (ws) => ws.close());
    await page.reload();
    const rowAfter = page.locator('[data-testid="conversation-row"]', { hasText: userId }).first();
    await expect(rowAfter).toBeVisible({ timeout: 30_000 });
    await rowAfter.click();
    const box = page.getByPlaceholder('回复顾客…');
    await expect(box).toBeVisible({ timeout: 15_000 });

    const ghost = `断连发送_${Date.now()}`;
    await box.fill(ghost);
    await page.getByRole('button', { name: '发送', exact: true }).click();

    // ack 失败 notice 如实呈现
    await expect(page.getByText('未连接实时通道')).toBeVisible({ timeout: 15_000 });
    // 时间线回真源(openThread 重拉):乐观气泡被冲掉,不残留
    await expect(page.getByTestId('desk-timeline')).not.toContainText(ghost, { timeout: 15_000 });
  });

  test('顾客输入中 → 坐席台亮「对方正在输入…」,2.5s 保持窗后熄灭', async ({ page, request }) => {
    const threadId = `e2e_p4typ_${Date.now()}`;
    const userId = `u_e2e_p4typ_${Date.now()}`;
    await seedQueuingThread(request, threadId, userId);
    await presetAuth(page);
    const customer = await connectCustomer(userId);
    try {
      const joined = await new Promise<any>((resolve) => {
        customer.emit('join_thread', { threadId, tenantId: 'aurora', role: 'user' }, (ack: any) => resolve(ack));
        setTimeout(() => resolve({ success: false }), 10_000);
      });
      expect(joined?.success ?? true).toBeTruthy();

      await page.goto('/agent-desk');
      const row = page.locator('[data-testid="conversation-row"]', { hasText: userId }).first();
      await expect(row).toBeVisible({ timeout: 30_000 });
      await row.getByTestId('claim-button').click();
      await expect(row.getByText('我接管中')).toBeVisible({ timeout: 15_000 });

      // 顾客 typing(服务端透传广播,skip_sid 排除发送者)。连发模拟持续
      // 输入:坐席 join_thread 入房与广播存在往返竞态,单发可能落在入房前
      for (let i = 0; i < 4; i++) {
        customer.emit('typing', { threadId, tenantId: 'aurora', role: 'user' });
        await page.waitForTimeout(600);
      }
      await expect(page.getByTestId('desk-typing')).toBeVisible({ timeout: 10_000 });
      // 保持窗(2.5s)过后自动熄灭
      await expect(page.getByTestId('desk-typing')).toBeHidden({ timeout: 6_000 });
    } finally {
      customer.disconnect();
    }
  });
});

/**
 * 坐席上下文栏 P3 浏览器全链路(live-desk-rework spec §3 P3 验收行):
 * 认领后右栏五项出现;弱关联未匹配诚实空态;内部备注添加/删除往返。
 */
test.describe('坐席上下文栏五项(P3)', () => {
  let token: string;
  const threadId = `e2e_ctx_${Date.now()}`;
  const userId = `u_e2e_ctx_${Date.now()}`;

  test.beforeAll(async ({ request }) => {
    token = await loginViaApi(request);
    const res = await request.post(`${GW}/api/chat/threads`, {
      headers: { Authorization: `Bearer ${token}`, 'x-tenant-id': 'aurora' },
      data: { threadId, userId, businessId: 'aurora' },
    });
    expect(res.ok()).toBeTruthy();
    const q = await request.post(`${GW}/api/conversations/${threadId}/status`, {
      headers: { Authorization: `Bearer ${token}`, 'x-tenant-id': 'aurora' },
      data: { status: 'human_takeover' },
    });
    expect(q.ok()).toBeTruthy();
  });

  const presetAuth = async (page: Page) => {
    await page.addInitScript(
      (s: { token: string; email: string }) => {
        localStorage.setItem('merchant-admin.token', s.token);
        localStorage.setItem('merchant-admin.staff', s.email);
        localStorage.setItem('merchant-admin.boss', JSON.stringify(s));
      },
      { token, email: STAFF.email },
    );
  };

  test('认领后右栏出五项,未匹配档案诚实,备注增删往返', async ({ page }) => {
    await presetAuth(page);
    await page.goto('/agent-desk');
    const row = page.locator('[data-testid="conversation-row"]', { hasText: userId }).first();
    await expect(row).toBeVisible({ timeout: 30_000 });

    // 认领 → openThread 拉五项聚合(行内定位,残留行不吃全局 first())
    await row.getByTestId('claim-button').click();
    await expect(row.getByText('我接管中')).toBeVisible({ timeout: 15_000 });

    // 五项 section 出现(客户档案默认展开,其余可折叠)
    for (const sec of ['customer', 'orders', 'tickets', 'profile', 'notes']) {
      await expect(page.getByTestId(`ctx-section-${sec}`)).toBeVisible({ timeout: 15_000 });
    }
    // 弱关联诚实:e2e 造的 userId 无商户档案 → 未匹配空态,严禁伪装修配
    await expect(page.getByTestId('ctx-customer-unmatched')).toContainText(
      '未匹配到商户客户档案(聊天身份与商户客户编号暂无关联)',
    );

    // 内部备注往返:展开 → 添加 → 行出现 → 删除 → 行消失
    await page.getByRole('button', { name: /内部备注/ }).click();
    const marker = `e2e内部备注_${Date.now()}`;
    await page.getByTestId('ctx-note-input').fill(marker);
    await page.getByTestId('ctx-note-add').click();
    await expect(page.getByTestId('ctx-note-row')).toContainText(marker, { timeout: 10_000 });
    await page.getByTestId('ctx-note-remove').click();
    await expect(page.getByTestId('ctx-note-row')).toHaveCount(0, { timeout: 10_000 });
  });
});
