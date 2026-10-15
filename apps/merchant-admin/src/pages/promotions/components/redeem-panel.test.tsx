import '@testing-library/jest-dom/vitest';
import { setSession } from '@/lib/api';
import type { Promotion } from '@/lib/api';
import { gatewayUp, installLiveFetch, login } from '@/test/live-api';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { RedeemDialog } from './redeem-panel';

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
  startAt: null,
  endAt: null,
  totalQuota: null,
  claimedCount: 0,
  usedCount: 0,
  redemptionCount: 0,
  discountTotal: 0,
  effectiveStatus: 'running',
};

beforeAll(async () => {
  installLiveFetch();
  const boss = await login('test@example.com');
  setSession(boss.token, boss.email);
});

beforeEach(() => installLiveFetch());

d('RedeemDialog(真实库,仅错误路径)', () => {
  it('订单不存在 → 服务端错误文案留窗内(FormDialogShell 契约),弹窗保留可改单号重试', async () => {
    const onMsg = vi.fn();
    const onCancel = vi.fn();
    render(<RedeemDialog promo={promo} onClose={onCancel} onMsg={onMsg} />);
    fireEvent.change(screen.getByPlaceholderText(/订单号/), { target: { value: 'E2E-不存在的订单' } });
    fireEvent.click(screen.getByRole('button', { name: '确认核销' }));
    // 失败文案留窗内(壳 err),不假成功、不关窗
    await waitFor(() => {
      const err = document.querySelector('.text-red-600');
      expect(err).not.toBeNull();
      expect(String(err!.textContent).length).toBeGreaterThan(0);
    });
    expect(onMsg).not.toHaveBeenCalled(); // 失败严禁走成功横幅
    expect(onCancel).not.toHaveBeenCalled(); // 弹窗保留,用户可改单号重试
  });

  it('空订单号不触发请求', async () => {
    const onMsg = vi.fn();
    render(<RedeemDialog promo={promo} onClose={() => {}} onMsg={onMsg} />);
    fireEvent.click(screen.getByRole('button', { name: '确认核销' }));
    expect(onMsg).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '确认核销' })).toBeDisabled();
  });
});
