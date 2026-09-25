import type { SkuStockRow } from '@/lib/api';
import { describe, expect, it } from 'vitest';
import { filterSkuStock } from './filters';

const row = (over: Partial<SkuStockRow>): SkuStockRow => ({
  id: over.id || 'k1',
  sku_code: 'SKU-A-1',
  sku_title: '红色 42 码',
  spu_id: 's1',
  spu_title: '越野跑鞋',
  price: 99,
  stock: 30,
  spec_attributes: null,
  ...over,
});

const skus = [
  row({ id: 'k1', sku_code: 'SKU-A-1', spu_title: '越野跑鞋', stock: 3 }),
  row({ id: 'k2', sku_code: 'SKU-A-2', spu_title: '越野跑鞋', stock: 80 }),
  row({ id: 'k3', sku_code: 'SKU-B-1', sku_title: '防风帽', spu_title: '防风连帽衫', stock: 49 }),
];

describe('filterSkuStock', () => {
  it('ALL 返回全量;low 只留低于阈值;normal 只留达标', () => {
    expect(filterSkuStock(skus, 'ALL', '')).toHaveLength(3);
    expect(filterSkuStock(skus, 'low', '').map((s) => s.id)).toEqual(['k1', 'k3']);
    expect(filterSkuStock(skus, 'normal', '').map((s) => s.id)).toEqual(['k2']);
  });

  it('关键词命中 SKU 编码 / 名称 / 所属商品(不区分大小写)', () => {
    expect(filterSkuStock(skus, 'ALL', 'sku-b').map((s) => s.id)).toEqual(['k3']);
    expect(filterSkuStock(skus, 'ALL', '防风帽').map((s) => s.id)).toEqual(['k3']);
    expect(filterSkuStock(skus, 'ALL', '跑鞋').map((s) => s.id)).toEqual(['k1', 'k2']);
  });

  it('筛选与关键词叠加', () => {
    expect(filterSkuStock(skus, 'low', '跑鞋').map((s) => s.id)).toEqual(['k1']);
    expect(filterSkuStock(skus, 'normal', '跑鞋').map((s) => s.id)).toEqual(['k2']);
  });

  it('无匹配返回空数组(诚实空)', () => {
    expect(filterSkuStock(skus, 'ALL', '不存在')).toEqual([]);
  });
});
