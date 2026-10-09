import '@testing-library/jest-dom/vitest';
import type { SkuStockRow } from '@/lib/api';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SkuStockTable } from './sku-stock-table';

// api 只桩 updateSku(改价/库存弹窗提交捕获)
const mocks = vi.hoisted(() => {
  const updateSku = vi.fn();
  updateSku.mockResolvedValue({ success: true });
  return { updateSku };
});

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      products: { ...actual.api.products, updateSku: mocks.updateSku },
    },
  };
});

const skus: SkuStockRow[] = [
  {
    id: 'k1',
    sku_code: 'SKU-A-1',
    sku_title: '红 42',
    spu_id: 's1',
    spu_title: '越野跑鞋',
    price: 99,
    stock: 3,
    spec_attributes: null,
  },
  {
    id: 'k2',
    sku_code: 'SKU-A-2',
    sku_title: '蓝 43',
    spu_id: 's1',
    spu_title: '越野跑鞋',
    price: 99,
    stock: 80,
    spec_attributes: null,
  },
];

describe('SkuStockTable', () => {
  it('渲染库存总表;低库存行标红', () => {
    render(<SkuStockTable skus={skus} onMsg={() => {}} onChanged={() => {}} />);
    expect(screen.getByText('SKU-A-1')).toBeInTheDocument();
    expect(screen.getAllByText('越野跑鞋').length).toBe(2);
    expect(screen.getByText('3')).toHaveClass('text-rose-600');
  });

  it('点「低库存」筛选只留低于阈值的行', () => {
    render(<SkuStockTable skus={skus} onMsg={() => {}} onChanged={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /低库存/ }));
    expect(screen.getByText('SKU-A-1')).toBeInTheDocument();
    expect(screen.queryByText('SKU-A-2')).not.toBeInTheDocument();
  });

  it('搜索命中所属商品;无匹配诚实空', () => {
    render(<SkuStockTable skus={skus} onMsg={() => {}} onChanged={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/搜索 SKU/), { target: { value: '不存在' } });
    expect(screen.getByText('暂无匹配 SKU(诚实空)')).toBeInTheDocument();
  });

  it('改价/库存走弹窗:预填当前值,不点保存不触发回调', () => {
    const onChanged = vi.fn();
    render(<SkuStockTable skus={skus} onMsg={() => {}} onChanged={onChanged} />);
    fireEvent.click(screen.getAllByRole('button', { name: '改价/库存' })[0]);
    // 弹窗预填当前值(旧「行内编辑态」断言的等价改写)
    const priceInput = screen.getByLabelText('价格(¥)') as HTMLInputElement;
    const stockInput = screen.getByLabelText('库存') as HTMLInputElement;
    expect(priceInput.value).toBe('99');
    expect(stockInput.value).toBe('3');
    expect(onChanged).not.toHaveBeenCalled();
  });

  it('弹窗内改价保存 → updateSku 携带数值化 payload,成功后回调刷新', async () => {
    const onChanged = vi.fn();
    render(<SkuStockTable skus={skus} onMsg={() => {}} onChanged={onChanged} />);
    fireEvent.click(screen.getAllByRole('button', { name: '改价/库存' })[0]);
    fireEvent.change(screen.getByLabelText('价格(¥)'), { target: { value: '129' } });
    fireEvent.change(screen.getByLabelText('库存'), { target: { value: '55' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => expect(mocks.updateSku).toHaveBeenCalledWith('k1', { price: 129, stock: 55 }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });
});
