import '@testing-library/jest-dom/vitest';
import { setSession } from '@/lib/api';
import type { Promotion } from '@/lib/api';
import { gatewayUp, installLiveFetch, login } from '@/test/live-api';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { RedeemPanel } from './redeem-panel';

// 集成测试(真实网关 + 真实库;不 mock 数据):只走「订单不存在」的业务错误
// 路径 —— 不写任何数据;核销成功/幂等写路径由 gateway-py 契约测试覆盖。
const d = gatewayUp ? describe : describe.skip;

const promo: Promotion = {
  id: '00000000-0000-0000-0000-000000000000',
  name: '集成测试',
  promoType: 'coupon',
  threshold: null,
  value: 30,
  scopeType: 'all',
  scopeValue: null,
  status: 'active',
};

beforeAll(async () => {
  installLiveFetch();
  const boss = await login('test@example.com');
  setSession(boss.token, boss.email);
});

beforeEach(() => installLiveFetch());

d('RedeemPanel(真实库,仅错误路径)', () => {
  it('订单不存在 → 服务端错误文案经 onDone 上抛,面板保留', async () => {
    const onDone = vi.fn();
    const onCancel = vi.fn();
    render(<RedeemPanel promo={promo} onCancel={onCancel} onDone={onDone} />);
    fireEvent.change(screen.getByPlaceholderText(/订单号/), { target: { value: 'E2E-不存在的订单' } });
    fireEvent.click(screen.getByRole('button', { name: '确认核销' }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(expect.stringContaining('失败')));
    expect(onCancel).not.toHaveBeenCalled(); // 面板保留,用户可改单号重试
  });

  it('空订单号不触发请求', async () => {
    const onDone = vi.fn();
    render(<RedeemPanel promo={promo} onCancel={() => {}} onDone={onDone} />);
    fireEvent.click(screen.getByRole('button', { name: '确认核销' }));
    expect(onDone).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '确认核销' })).toBeDisabled();
  });
});
