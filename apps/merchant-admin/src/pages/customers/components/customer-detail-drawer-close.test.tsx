import '@testing-library/jest-dom/vitest';
import type { Customer } from '@/lib/api';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CustomerDetailDrawer } from './customer-detail-drawer';

// 「详情页关不掉」回归循环:红 = 点击「关闭」/遮罩后 onClose 未被调(抽屉关不掉)。
// 抽屉挂载会拉订单/券,jsdom 相对路径 fetch 失败走组件内诚实空分支,不影响关闭交互。

const customer: Customer = {
  customer_id: 'CUST-1',
  name: '张三',
  phone: '13800000001',
  email: '',
  member_level: 'VIP',
  addresses: '[]',
  total_spent: 0,
  order_count: 0,
};

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify({ success: true, orders: [], coupons: [] }), {
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  );
});

afterEach(() => vi.unstubAllGlobals());

const renderDrawer = (onClose: () => void) =>
  render(
    <MemoryRouter>
      <CustomerDetailDrawer customer={customer} onClose={onClose} />
    </MemoryRouter>,
  );

describe('CustomerDetailDrawer 关闭交互', () => {
  it('点击「关闭」按钮 → onClose 被调', async () => {
    const onClose = vi.fn();
    renderDrawer(onClose);
    await waitFor(() => expect(screen.getByRole('button', { name: '关闭' })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('点击遮罩 → onClose 被调', async () => {
    const onClose = vi.fn();
    const { container } = renderDrawer(onClose);
    await waitFor(() => expect(screen.getByRole('button', { name: '关闭' })).toBeInTheDocument());
    fireEvent.click(container.firstChild as Element);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('点击抽屉内容区(冒泡阻断)→ onClose 不被调', async () => {
    const onClose = vi.fn();
    renderDrawer(onClose);
    await waitFor(() => expect(screen.getByRole('button', { name: '关闭' })).toBeInTheDocument());
    fireEvent.click(screen.getByText('张三'));
    expect(onClose).not.toHaveBeenCalled();
  });
});
