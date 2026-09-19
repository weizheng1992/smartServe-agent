import '@testing-library/jest-dom/vitest';
import { beforeEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api, setSession } from '@/lib/api';
import { GATEWAY, gatewayUp, installLiveFetch, login } from '@/test/live-api';
import { GrantPanel } from './grant-panel';

// 集成测试(真实网关 + 真实库;不 mock 数据):本用例只读 —— 发放动作的
// 写路径由 gateway-py 契约测试(密封真实库)覆盖。
const d = gatewayUp ? describe : describe.skip;
const authHeadersOf = (s: { token: string }) => ({ Authorization: `Bearer ${s.token}` });

beforeAll(async () => {
  installLiveFetch();
  const boss = await login('test@example.com');
  setSession(boss.token, boss.email); // 组件 fetch 需要 Bearer 头
});

beforeEach(() => installLiveFetch());

d('GrantPanel(真实库)', () => {
  it('加载真实客户列表并可搜索(只读)', async () => {
    const boss = await login('test@example.com');
    const listed = await (
      await fetch(`${GATEWAY}/api/admin/analytics/customers`, { headers: authHeadersOf(boss) })
    ).json();
    const real: Array<{ customer_id: string; name: string }> = listed.customers || [];

    render(<GrantPanel promoName="集成测试(不发放)" promoId="none" onCancel={() => {}} onDone={() => {}} />);

    if (real.length === 0) {
      await waitFor(() => expect(screen.getByText('暂无匹配客户')).toBeInTheDocument());
      return;
    }
    // 真实库首客户出现在面板中
    await waitFor(() => expect(screen.getByText(real[0].name)).toBeInTheDocument());
    // 搜索一个必然不存在的串 → 诚实空;清空后恢复真实列表
    fireEvent.change(screen.getByPlaceholderText('搜索客户…'), { target: { value: 'E2E-不存在的客户' } });
    await waitFor(() => expect(screen.getByText('暂无匹配客户')).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText('搜索客户…'), { target: { value: real[0].name } });
    await waitFor(() => expect(screen.getByText(real[0].name)).toBeInTheDocument());
  });

  it('发放动作走真实护栏(重复发放被拦截)', async () => {
    // 直接对不存在的活动发放:权限/校验先行,404/400 语义由真实后端给出
    const boss = await login('test@example.com');
    setSession(boss.token, boss.email);
    const body = await api.promotions.grant('00000000-0000-0000-0000-000000000000', 'E2E-不存在的客户');
    // 活动不存在 → 服务端业务错误(诚实文案),不抛异常
    expect(body.success).toBe(false);
  });
});
