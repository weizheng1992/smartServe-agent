import { expect, test } from '@playwright/test';

// 站内消息推送 e2e(mall-notifications 06)—— 专属配置 notifications.config.ts
// 运行(baseURL 3007 私有 vite,经 GATEWAY_URL 代理私有网关 4100;不占 dev 的
// 3005/4000,webServer url 已响应即复用跳过)。
// 钉死契约:员工发广播 → 顾客铃铛未读 +1 → 消息中心点开标已读 → 徽标消减;
// 对照组:游客零接入(无铃铛、消息中心诚实空态)。
// 身份注入走 addInitScript 参数字面量(仓库律,严禁引用 Node 闭包常量);
// AI_QUOTA_GATE=0 由 config env 承担(merchant.md 宿主 env 律)。

const BROADCAST_TITLE = 'E2E-e2e-通知-全场包邮';

test.describe('顾客侧消息推送', () => {
  test('广播触达:铃铛未读 +1 → 点开标已读 → 徽标消减', async ({ page, request }) => {
    // 员工侧经同源代理打私有网关(vite proxy /api → 4100),登录 + 发广播
    const login = await request.post('/api/auth/login', {
      data: { email: 'test@example.com', password: 'agent-all-dev' },
    });
    expect(login.ok()).toBeTruthy();
    const token = (await login.json()).data.token as string;
    const send = await request.post('/api/admin/notifications', {
      headers: { Authorization: `Bearer ${token}`, 'x-tenant-id': 'aurora' },
      data: { targetType: 'all', title: BROADCAST_TITLE, body: '全场包邮公告正文(e2e)' },
    });
    expect(send.ok()).toBeTruthy();

    // 顾客身份进消息中心
    await page.addInitScript(() => {
      localStorage.setItem(
        'aurora_merchant_current_user',
        JSON.stringify({
          id: 'CUST-8801',
          name: '张伟',
          phone: '13800138000',
          tier: '黑金SVIP',
          defaultAddress: '北京市海淀区中关村南大街1号院8号楼1201室',
        }),
      );
    });
    await page.goto('/messages');
    await expect(page.getByText(BROADCAST_TITLE)).toBeVisible();
    // 未读行有绿点 + 徽标显示未读 ≥1(行首未读点,铃铛数字徽标)
    const bell = page.getByRole('link', { name: /🔔 消息/ });
    await expect(bell).toBeVisible();
    await expect(bell.getByText(/^\d+$/)).toBeVisible();

    // 点开 = 展开正文 + 标已读;唯一一条 → 「全部标为已读」按钮随之消失
    await page.getByRole('button', { name: new RegExp(BROADCAST_TITLE) }).click();
    await expect(page.getByText('全场包邮公告正文(e2e)')).toBeVisible();
    await expect(page.getByRole('button', { name: '全部标为已读' })).toBeHidden({ timeout: 10_000 });
    // 铃铛徽标消减到无(notify_updated 窗口事件同步)
    await expect(bell.getByText(/^\d+$/)).toBeHidden({ timeout: 10_000 });
  });

  test('游客零接入:无铃铛、消息中心诚实空态(U2 律)', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem(
        'aurora_merchant_current_user',
        JSON.stringify({
          id: 'guest-e2e-notif',
          name: '游客',
          phone: '',
          tier: '游客',
          defaultAddress: '',
        }),
      );
    });
    await page.goto('/');
    await expect(page.getByRole('link', { name: /🔔 消息/ })).toHaveCount(0);
    await page.goto('/messages');
    await expect(page.getByText('暂无消息')).toBeVisible();
  });
});
