import '@testing-library/jest-dom/vitest';
import { type Promotion, type Spu } from '@/lib/api';
import { selectRadixOption } from '@/test/radix-select';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PromoFormDialog } from './promo-dialog';

// 单测(不依赖网关):新建/编辑弹窗的字段渲染、提交映射契约与轻校验。
// 旧「页内平铺新建卡 + 表格展开行编辑」两册的断言在此合并承接。
const mocks = vi.hoisted(() => {
  const create = vi.fn();
  const update = vi.fn();
  create.mockResolvedValue({ success: true, name: 't' });
  update.mockResolvedValue({ success: true });
  return { create, update };
});

// 供「适用商品」Radix Select 选择用的样例 SPU
const MOCK_SPU: Spu = {
  id: 'spu-1',
  spu_code: 'SPU-AURORA-021',
  title: '极光防晒皮肤衣',
  category: '户外机能',
  status: 'ON_SALE',
  price: 329,
  stock: 98,
  ownerId: null,
};

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      products: { ...actual.api.products, list: async () => ({ success: true, spus: [MOCK_SPU] }) },
      promotions: {
        ...actual.api.promotions,
        create: mocks.create,
        update: mocks.update,
      },
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

function renderDialog(opts: { promo?: Promotion | null; open?: boolean } = {}) {
  const onSaved = vi.fn();
  const onClose = vi.fn();
  render(
    <PromoFormDialog
      open={opts.open ?? true}
      promo={opts.promo !== undefined ? opts.promo : null}
      spus={[MOCK_SPU]}
      onClose={onClose}
      onSaved={onSaved}
    />,
  );
  return { onSaved, onClose };
}

describe('PromoFormDialog 新建(时间窗)', () => {
  it('起止 datetime-local 渲染;起缺省当前(非空)、止空 = 长期', () => {
    renderDialog();
    const inputs = document.querySelectorAll('input[type="datetime-local"]');
    expect(inputs).toHaveLength(2);
    const [start, end] = inputs as NodeListOf<HTMLInputElement>;
    expect(start.value).not.toBe('');
    expect(end.value).toBe('');
  });

  it('提交携带 startAt/endAt(止空 → undefined,服务端置 NULL 长期)', async () => {
    mocks.create.mockClear();
    renderDialog();
    fireEvent.change(screen.getByPlaceholderText('如:周年庆满减'), { target: { value: '满减窗' } });
    fireEvent.change(screen.getByPlaceholderText('如 40'), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: '创建' }));
    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    const arg = mocks.create.mock.calls[0][0];
    expect(arg.name).toBe('满减窗');
    expect(arg.startAt).toBeTruthy();
    expect(arg.endAt).toBeUndefined();
    expect(arg.totalQuota).toBeUndefined(); // 非券型不带上限
  });
});

describe('PromoFormDialog 新建(类型卡片)', () => {
  it('三类型卡片渲染;选券型出发放上限,满减/折扣不出', () => {
    renderDialog();
    expect(screen.getByRole('button', { name: /满减/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /折扣/ })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('留空 = 不限')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /券/ }));
    expect(screen.getByPlaceholderText('留空 = 不限')).toBeInTheDocument();
  });

  it('券型提交把上限数值化;留空 → undefined(服务端不限)', async () => {
    mocks.create.mockClear();
    renderDialog();
    fireEvent.click(screen.getByRole('button', { name: /券/ }));
    fireEvent.change(screen.getByPlaceholderText('如:周年庆满减'), { target: { value: '周年券' } });
    fireEvent.change(screen.getByPlaceholderText('如 15'), { target: { value: '15' } });
    fireEvent.change(screen.getByPlaceholderText('留空 = 不限'), { target: { value: '100' } });
    fireEvent.click(screen.getByRole('button', { name: '创建' }));
    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    const arg = mocks.create.mock.calls[0][0];
    expect(arg.promoType).toBe('coupon');
    expect(arg.totalQuota).toBe(100);
  });
});

describe('PromoFormDialog 轻校验', () => {
  it('折扣越界(0-100 外)拦在客户端,不发起创建', async () => {
    mocks.create.mockClear();
    renderDialog();
    fireEvent.click(screen.getByRole('button', { name: /折扣/ }));
    fireEvent.change(screen.getByPlaceholderText('如:周年庆满减'), { target: { value: '骨折' } });
    fireEvent.change(screen.getByPlaceholderText('85 = 8.5 折'), { target: { value: '150' } });
    fireEvent.click(screen.getByRole('button', { name: '创建' }));
    expect(await screen.findByText(/折扣须为 1-99/)).toBeInTheDocument();
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it('结束早于开始拦在客户端', async () => {
    mocks.create.mockClear();
    renderDialog();
    fireEvent.change(screen.getByPlaceholderText('如:周年庆满减'), { target: { value: '倒流' } });
    fireEvent.change(screen.getByPlaceholderText('如 40'), { target: { value: '10' } });
    const inputs = document.querySelectorAll('input[type="datetime-local"]') as NodeListOf<HTMLInputElement>;
    fireEvent.change(inputs[0], { target: { value: '2026-10-02T10:00' } });
    fireEvent.change(inputs[1], { target: { value: '2026-10-01T10:00' } });
    fireEvent.click(screen.getByRole('button', { name: '创建' }));
    expect(await screen.findByText(/结束时间须晚于开始时间/)).toBeInTheDocument();
    expect(mocks.create).not.toHaveBeenCalled();
  });
});

describe('PromoFormDialog 编辑(PATCH 携带即更新)', () => {
  it('预填当前值;类型只读徽标不可改', () => {
    renderDialog({ promo: mkPromo() });
    expect((screen.getByPlaceholderText('如:周年庆满减') as HTMLInputElement).value).toBe('周年庆满减');
    // 类型只读徽标(头部描述句也含「不可改」,此处钉徽标本体)
    expect(screen.getByText('满减(不可改)')).toBeInTheDocument();
    // 无类型卡片可点
    expect(screen.queryByRole('button', { name: /满减/ })).not.toBeInTheDocument();
  });

  it('一次改齐:保存按全字段 PATCH(endAt 预填原样保留、quota 空=清上限、券型门槛=null)', async () => {
    mocks.update.mockClear();
    renderDialog({ promo: mkPromo({ id: 'p1', name: '旧名', promoType: 'coupon', value: 20, totalQuota: 50 }) });
    const nameInput = screen.getByPlaceholderText('如:周年庆满减') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: '新名' } });
    fireEvent.change(screen.getByPlaceholderText('留空 = 不限'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await vi.waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    const [, patch] = mocks.update.mock.calls[0];
    expect(patch.name).toBe('新名');
    expect(patch.value).toBe(20);
    expect(patch.threshold).toBeNull(); // 券型无门槛:空串归一为 null(服务端清除)
    expect(patch.endAt).toBe('2026-09-30T10:00'); // 预填值原样保留
    expect(patch.totalQuota).toBeNull(); // 清空 = 清除上限
  });

  it('取消关闭弹窗,不触发保存;成功后 onClose + onSaved 各一次', async () => {
    const { onClose, onSaved } = renderDialog({ promo: mkPromo() });
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(mocks.update).not.toHaveBeenCalled();

    mocks.update.mockClear();
    mocks.update.mockResolvedValue({ success: true });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await vi.waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

describe('PromoFormDialog 适用范围(Radix Select)', () => {
  it('切「指定商品」→「适用商品」trigger 出现;选 SPU 提交携带 scopeType+scopeValue', async () => {
    mocks.create.mockClear();
    renderDialog();
    await selectRadixOption('适用范围', '指定商品');
    expect(screen.getByLabelText('适用商品')).toBeInTheDocument();

    await selectRadixOption('适用商品', /极光防晒皮肤衣/);
    fireEvent.change(screen.getByPlaceholderText('如:周年庆满减'), { target: { value: '指定品满减' } });
    fireEvent.change(screen.getByPlaceholderText('如 40'), { target: { value: '30' } });
    fireEvent.click(screen.getByRole('button', { name: '创建' }));
    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    const arg = mocks.create.mock.calls[0][0];
    expect(arg.scopeType).toBe('spu');
    expect(arg.scopeValue).toBe('SPU-AURORA-021');
  });

  it('编辑态 scopeType=spu 时商品名回显;范围默认「全部商品」', async () => {
    renderDialog({ promo: mkPromo({ scopeType: 'spu', scopeValue: 'SPU-AURORA-021' }) });
    expect(screen.getByLabelText('适用范围')).toHaveTextContent('指定商品');
    expect(screen.getByLabelText('适用商品')).toHaveTextContent(/极光防晒皮肤衣/);
  });
});
