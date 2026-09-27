import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PromoCreateForm } from './promo-form';

// 单测(不依赖网关):时间窗/发放上限字段的渲染与提交映射契约。
const mocks = vi.hoisted(() => {
  const create = vi.fn();
  create.mockResolvedValue({ success: true, name: 't' });
  return { create };
});

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      products: { ...actual.api.products, list: async () => ({ success: true, spus: [] }) },
      promotions: { ...actual.api.promotions, create: mocks.create },
    },
  };
});

function renderForm() {
  const onMsg = vi.fn();
  const onCreated = vi.fn();
  render(<PromoCreateForm msg="" onMsg={onMsg} onCreated={onCreated} />);
  return { onMsg, onCreated };
}

describe('PromoCreateForm 时间窗', () => {
  it('起止 datetime-local 渲染;起缺省当前(非空)、止空 = 长期', () => {
    renderForm();
    const inputs = document.querySelectorAll('input[type="datetime-local"]');
    expect(inputs).toHaveLength(2);
    const [start, end] = inputs as NodeListOf<HTMLInputElement>;
    expect(start.value).not.toBe('');
    expect(end.value).toBe('');
  });

  it('提交携带 startAt/endAt(止空 → undefined,服务端置 NULL 长期)', async () => {
    mocks.create.mockClear();
    renderForm();
    fireEvent.change(screen.getByPlaceholderText('活动名称'), { target: { value: '满减窗' } });
    fireEvent.change(screen.getByPlaceholderText('优惠 ¥'), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: '创建' }));
    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    const arg = mocks.create.mock.calls[0][0];
    expect(arg.name).toBe('满减窗');
    expect(arg.startAt).toBeTruthy();
    expect(arg.endAt).toBeUndefined();
    expect(arg.totalQuota).toBeUndefined(); // 非券型不带上限
  });
});

describe('PromoCreateForm 发放上限', () => {
  it('仅券型显示发放上限输入;满减/折扣不显示', () => {
    renderForm();
    expect(screen.queryByPlaceholderText('发放上限(空=不限)')).not.toBeInTheDocument();
    // 第一颗 select 是类型(第二颗是适用范围)
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'coupon' } });
    expect(screen.getByPlaceholderText('发放上限(空=不限)')).toBeInTheDocument();
  });

  it('券型提交把上限数值化;留空 → undefined(服务端不限)', async () => {
    mocks.create.mockClear();
    renderForm();
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'coupon' } });
    fireEvent.change(screen.getByPlaceholderText('活动名称'), { target: { value: '周年券' } });
    fireEvent.change(screen.getByPlaceholderText('优惠 ¥'), { target: { value: '15' } });
    fireEvent.change(screen.getByPlaceholderText('发放上限(空=不限)'), { target: { value: '100' } });
    fireEvent.click(screen.getByRole('button', { name: '创建' }));
    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    const arg = mocks.create.mock.calls[0][0];
    expect(arg.promoType).toBe('coupon');
    expect(arg.totalQuota).toBe(100);
  });
});
