import '@testing-library/jest-dom/vitest';
import { type Promotion } from '@/lib/api';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PromoTable } from './promo-table';

// 单测(不依赖网关):展开行编辑与四态/量控展示的确定性渲染契约。
// api 只桩 products.list(挂载加载)与 promotions.update(编辑保存捕获)。
const mocks = vi.hoisted(() => {
  const update = vi.fn();
  update.mockResolvedValue({ success: true });
  return { update };
});

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      products: { ...actual.api.products, list: async () => ({ success: true, spus: [] }) },
      promotions: { ...actual.api.promotions, update: mocks.update },
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
  render(<PromoTable promotions={promotions} onMsg={onMsg} onChanged={onChanged} />);
  return { onMsg, onChanged };
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

describe('PromoTable 展开行编辑', () => {
  it('一次改齐:保存按「携带即更新」PATCH 全字段(endAt 空=置长期、quota 空=清上限)', async () => {
    mocks.update.mockClear();
    renderTable([mkPromo({ id: 'p1', name: '旧名', promoType: 'coupon', value: 20, totalQuota: 50, claimedCount: 3 })]);
    fireEvent.click(screen.getByRole('button', { name: '编辑' }));
    // 展开行出现,预填当前值
    const nameInput = screen.getByPlaceholderText('活动名称') as HTMLInputElement;
    expect(nameInput.value).toBe('旧名');
    expect(screen.getByPlaceholderText('发放上限(空=不限)')).toBeInTheDocument();

    fireEvent.change(nameInput, { target: { value: '新名' } });
    fireEvent.change(screen.getByPlaceholderText('发放上限(空=不限)'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await vi.waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    const patch = mocks.update.mock.calls[0][1];
    expect(patch.name).toBe('新名');
    expect(patch.value).toBe(20);
    expect(patch.threshold).toBeNull(); // 券型无门槛:空串归一为 null(服务端清除)
    expect(patch.endAt).toBe('2026-09-30T10:00'); // 预填值原样保留
    expect(patch.totalQuota).toBeNull(); // 清空 = 清除上限
  });

  it('取消收起展开行,不触发保存', () => {
    renderTable([mkPromo({ id: 'p1' })]);
    fireEvent.click(screen.getByRole('button', { name: '编辑' }));
    expect(screen.getByPlaceholderText('活动名称')).toBeInTheDocument();
    // 「取消」有两处(行开关 + 展开行内),点展开行内那颗(后者)
    fireEvent.click(screen.getAllByRole('button', { name: '取消' })[1]);
    expect(screen.queryByPlaceholderText('活动名称')).not.toBeInTheDocument();
    expect(mocks.update).not.toHaveBeenCalled();
  });
});
