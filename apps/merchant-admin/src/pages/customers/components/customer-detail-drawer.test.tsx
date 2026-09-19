import '@testing-library/jest-dom/vitest';
import { beforeEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { setSession } from '@/lib/api';
import { GATEWAY, gatewayUp, installLiveFetch, login } from '@/test/live-api';
import { CustomerDetailDrawer } from './customer-detail-drawer';

// 集成测试(真实网关 + 真实库;不 mock 数据):全只读 —— 抽屉仅拉取展示。
const d = gatewayUp ? describe : describe.skip;

beforeAll(async () => {
  installLiveFetch();
  const boss = await login('test@example.com');
  setSession(boss.token, boss.email);
});

beforeEach(() => installLiveFetch());

async function firstRealCustomer() {
  const boss = await login('test@example.com');
  const body = await (
    await fetch(`${GATEWAY}/api/admin/analytics/customers`, {
      headers: { Authorization: `Bearer ${boss.token}`, 'x-tenant-id': 'aurora' },
    })
  ).json();
  return (body.customers || [])[0] as { customer_id: string; name: string; member_level: string } | undefined;
}

d('CustomerDetailDrawer(真实库)', () => {
  it('用真实客户渲染:基本信息/地址簿/关联优惠券/关联订单各分区', async () => {
    const c = await firstRealCustomer();
    if (!c) return; // 库里暂无客户则无可断言(诚实空)

    render(
      <MemoryRouter>
        <CustomerDetailDrawer customer={c as any} onClose={() => {}} />
      </MemoryRouter>,
    );

    expect(screen.getByText(c.name)).toBeInTheDocument();
    expect(screen.getByText(c.member_level)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/地址簿\(/)).toBeInTheDocument();
      expect(screen.getByText(/关联优惠券\(/)).toBeInTheDocument();
      expect(screen.getByText(/关联订单\(/)).toBeInTheDocument();
    });
  });

  it('「在订单中查看」把订单写入 PageContext 选中集合并关闭抽屉', async () => {
    const c = await firstRealCustomer();
    if (!c) return;

    // 该客户在真实库中名下订单数(与抽屉同一数据源)
    const boss = await login('test@example.com');
    const ordersBody = await (
      await fetch(`${GATEWAY}/api/admin/orders`, { headers: { Authorization: `Bearer ${boss.token}` } })
    ).json();
    const his = (ordersBody.orders || []).filter((o: any) => o.customer_id === c.customer_id);
    if (his.length === 0) return; // 无订单客户没有可跳转的行

    const onClose = vi.fn();
    render(
      <MemoryRouter>
        <CustomerDetailDrawer customer={c as any} onClose={onClose} />
      </MemoryRouter>,
    );
    const buttons = await screen.findAllByRole('button', { name: '在订单中查看' }, { timeout: 8000 });
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const selection = JSON.parse(localStorage.getItem('merchant-admin.selection') || '[]');
    expect(selection).toContain(his[0].order_id);
  });
});
