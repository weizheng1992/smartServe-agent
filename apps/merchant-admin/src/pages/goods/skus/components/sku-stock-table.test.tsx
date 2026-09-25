import '@testing-library/jest-dom/vitest';
import type { SkuStockRow } from '@/lib/api';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SkuStockTable } from './sku-stock-table';

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

  it('改价/库存进入行内编辑态(不点保存不触发回调)', () => {
    const onChanged = vi.fn();
    render(<SkuStockTable skus={skus} onMsg={() => {}} onChanged={onChanged} />);
    fireEvent.click(screen.getAllByRole('button', { name: '改价/库存' })[0]);
    expect(screen.getByPlaceholderText('库存')).toBeInTheDocument();
    expect(onChanged).not.toHaveBeenCalled();
  });
});
