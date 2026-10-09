import '@testing-library/jest-dom/vitest';
import { type Promotion } from '@/lib/api';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PromoTable } from './promo-table';

// 单测(不依赖网关):四态/量控展示与行内操作的确定性渲染契约。
// 编辑不再展开行 —— 编辑按钮上报页级 PromoFormDialog 弹窗(表单契约见 promo-dialog.test.tsx)。
// api 只桩 promotions.setStatus / promotions.remove(启停/删除)。
const mocks = vi.hoisted(() => {
  const setStatus = vi.fn();
  const remove = vi.fn();
  setStatus.mockResolvedValue({ success: true });
  remove.mockResolvedValue({ success: true });
  return { setStatus, remove };
});

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      promotions: { ...actual.api.promotions, setStatus: mocks.setStatus, remove: mocks.remove },
    },
  };
});

function mkPromo(overrides: Partial<Promotion> = {}): Promotion {
  return {
    id: 'p1',
    name: '周年庆满减',
    promoType: 'full_reduction',
    threshold: 300,
    value: 40,
    scopeType: 'all',
    scopeValue: null,
    status: 'active',
    startAt: '2026-09-01T10:00:00',
    endAt: '2026-09-30T10:00:00',
    totalQuota: null,
    claimedCount: 0,
    usedCount: 0,
    redemptionCount: 0,
    discountTotal: 0,
    effectiveStatus: 'running',
    ...overrides,
  };
}

function renderTable(promotions: Promotion[]) {
  const onMsg = vi.fn();
  const onChanged = vi.fn();
  const onEdit = vi.fn();
  render(<PromoTable promotions={promotions} spuTitles={{}} onMsg={onMsg} onChanged={onChanged} onEdit={onEdit} />);
  return { onMsg, onChanged, onEdit };
}

describe('PromoTable 生效态四态', () => {
  it('服务端 effectiveStatus 直显:进行中/未开始/已结束/已停用(前端不自算)', () => {
    renderTable([
      mkPromo({ id: 'a', effectiveStatus: 'running' }),
      mkPromo({ id: 'b', effectiveStatus: 'scheduled' }),
      mkPromo({ id: 'c', effectiveStatus: 'ended' }),
      mkPromo({ id: 'd', effectiveStatus: 'disabled' }),
    ]);
    expect(screen.getByText('进行中')).toBeInTheDocument();
    expect(screen.getByText('未开始')).toBeInTheDocument();
    expect(screen.getByText('已结束')).toBeInTheDocument();
    expect(screen.getByText('已停用')).toBeInTheDocument();
  });

  it('仅进行中出核销/发券按钮(与服务端窗口闸同口径)', () => {
    renderTable([
      mkPromo({ id: 'running', promoType: 'coupon', effectiveStatus: 'running' }),
      mkPromo({ id: 'ended', promoType: 'coupon', effectiveStatus: 'ended' }),
    ]);
    // 两行都有「编辑」;核销只有 running 行有 → 全局恰好 1 个
    expect(screen.getAllByRole('button', { name: '编辑' })).toHaveLength(2);
    expect(screen.getByRole('button', { name: '核销' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '发券' })).toBeInTheDocument();
  });
});

describe('PromoTable 有效期与量控展示', () => {
  it('有效期短格式;止空收尾「长期」', () => {
    renderTable([
      mkPromo({ id: 'w1', startAt: '2026-09-01T10:00:00', endAt: '2026-09-30T10:00:00' }),
      mkPromo({ id: 'w2', startAt: '2026-09-01T10:00:00', endAt: null }),
    ]);
    expect(screen.getByText('2026-09-01 10:00 ~ 2026-09-30 10:00')).toBeInTheDocument();
    expect(screen.getByText('2026-09-01 10:00 ~ 长期')).toBeInTheDocument();
  });

  it('券型行显已领 X/上限 Y;无上限只显已领 X', () => {
    renderTable([
      mkPromo({ id: 'q1', promoType: 'coupon', value: 20, totalQuota: 100, claimedCount: 3 }),
      mkPromo({ id: 'q2', promoType: 'coupon', value: 20, totalQuota: null, claimedCount: 5 }),
    ]);
    expect(screen.getByText('已领 3/上限 100')).toBeInTheDocument();
    expect(screen.getByText('已领 5')).toBeInTheDocument();
  });

  it('有核销数据才出效果注记;零数据行不出', () => {
    renderTable([
      mkPromo({ id: 'e1', redemptionCount: 2, discountTotal: 30 }),
      mkPromo({ id: 'e2', redemptionCount: 0, discountTotal: 0 }),
    ]);
    expect(screen.getByText('核销 2 单 · 让利 ¥30')).toBeInTheDocument();
    expect(screen.queryByText(/核销 0 单/)).not.toBeInTheDocument();
  });
});

describe('PromoTable 行内操作', () => {
  it('编辑上报页级弹窗(携带整行活动),本表不自持表单态', () => {
    const { onEdit } = renderTable([mkPromo({ id: 'p1' })]);
    fireEvent.click(screen.getByRole('button', { name: '编辑' }));
    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(onEdit.mock.calls[0][0].id).toBe('p1');
  });

  it('停用/启用按 status 开关,成功回调 onChanged', async () => {
    const { onChanged } = renderTable([mkPromo({ id: 'p1', status: 'active' })]);
    fireEvent.click(screen.getByRole('button', { name: '停用' }));
    await vi.waitFor(() => expect(mocks.setStatus).toHaveBeenCalledWith('p1', 'disabled'));
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });
});
