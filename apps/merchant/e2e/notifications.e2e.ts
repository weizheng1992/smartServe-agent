import { expect, test } from '@playwright/test';

// 站内消息推送 e2e(mall-notifications 06)—— 专属配置 notifications.config.ts
// 运行(baseURL 3007 私有 vite,经 GATEWAY_URL 代理私有网关 4100;不占 dev 的
// 3005/4000,webServer url 已响应即复用跳过)。
// 钉死契约:员工发广播 → 顾客铃铛未读 +1 → 消息中心点开标已读 → 徽标消减;
// 对照组:游客零接入(无铃铛、消息中心诚实空态)。
// 身份注入走 addInitScript 参数字面量(仓库律,严禁引用 Node 闭包常量);
// AI_QUOTA_GATE=0 由 config env 承担(merchant.md 宿主 env 律)。

// 标题带时间戳:本册无删除端点(spec D7 撤回不进 MVP),残留行不可清 ——
// 固定标题会让第二次运行 strict mode 撞双行(实测 11-02),唯一化是唯一解。

test.describe('顾客侧消息推送', () => {
  test('广播触达:铃铛未读 +1 → 点开标已读 → 徽标消减', async ({ page, request }) => {
    const BROADCAST_TITLE = `E2E-e2e-通知-全场包邮-${Date.now()}`;
    // 员工侧经同源代理打私有网关(vite proxy /api → 4100),登录 + 发广播
    const login = await request.post('/api/auth/login', {
      data: { email: 'test@example.com', password: 'agent-all-dev' },
    });
    expect(login.ok()).toBeTruthy();
    const token = (await login.json()).data.token as string;
    // 跑前把 CUST-8801 未读清零(自家 store 端点,幂等):徽标断言才可钉精确值
    // —— 历史运行残留的未读行不构成本册零态假设的破坏源
    await request.post('/api/store/notifications/read', {
      data: { userId: 'CUST-8801', businessId: 'aurora', all: true },
    });
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

    // 点开 = 展开正文 + 标已读;已读态信号 = 行内绿点消失 + 页头「本页未读」
    // 计数消隐(复审 P6 后「全部标为已读」恒驻,按钮可见性不再是已读信号)
    await page.getByRole('button', { name: new RegExp(BROADCAST_TITLE) }).click();
    await expect(page.getByText('全场包邮公告正文(e2e)')).toBeVisible();
    await expect(page.getByText(/本页未读/)).toBeHidden({ timeout: 10_000 });
    await expect(
      page.getByRole('button', { name: new RegExp(BROADCAST_TITLE) }).locator('span.bg-emerald-500'),
    ).toHaveCount(0);
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
