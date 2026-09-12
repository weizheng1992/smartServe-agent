import { describe, expect, it } from 'bun:test';
import React from 'react';
import { renderToString } from 'react-dom/server';
import type { ProductRankingCardData, RankedProductItem } from 'types';
import { ProductRankingCard } from '../src/components/chat/cards/ProductRankingCard';

// 真实事故载荷(2026-09-12):engine 卡合成器把 searchProducts 工具结果误装为
// 排行卡,条目是商户货架检索形 {id,name,price,stock,...} —— 无
// totalGmv/grossProfit/metricDisplay/rank。前端此前在此载荷上抛
// "Cannot read properties of undefined (reading 'toLocaleString')"
// (ProductRankingCard.tsx:74),整个聊天控制台白屏。
const SEARCH_SHAPED_PRODUCTS = [
  {
    id: 'BAG-001',
    name: '户外徒步背包 45L',
    price: 829,
    stock: 12,
    description: '大容量防泼水',
    category: '背包收纳',
    specs: { 容量: '45L' },
    imageUrl: null,
  },
] as unknown as RankedProductItem[];

const WELL_FORMED_RANKING: ProductRankingCardData = {
  rankingMetric: 'gmv',
  metricLabel: '总销售额 (GMV)',
  metricUnit: '元',
  itemCount: 1,
  products: [
    {
      rank: 1,
      productId: 'prod-1',
      name: 'Nike Air Zoom Pegasus 41',
      category: 'running_shoes',
      price: 899,
      costPrice: 539.4,
      stock: 58,
      totalVolume: 10,
      totalGmv: 8990,
      grossProfit: 3596,
      marginRate: '40.0%',
      metricScore: 8990,
      metricDisplay: '8,990 元',
    },
  ],
};

describe('ProductRankingCard', () => {
  it('检索形条目(缺排行字段)诚实降级渲染,不抛 toLocaleString 崩溃', () => {
    const html = renderToString(
      React.createElement(ProductRankingCard, {
        data: {
          rankingMetric: 'gmv',
          metricLabel: '总销售额 (GMV)',
          metricUnit: '元',
          itemCount: 1,
          products: SEARCH_SHAPED_PRODUCTS,
        },
      }),
    );
    expect(html).toContain('户外徒步背包 45L');
    expect(html).toContain('单价');
    expect(html).toContain('829');
    expect(html).toContain('—');
    expect(html).not.toContain('销量');
    expect(html).not.toContain('毛利率');
    expect(html).not.toContain('毛利');
  });

  it('合规排行数据仍渲染 GMV/毛利/销量(防过度防御丢了合法展示)', () => {
    const html = renderToString(React.createElement(ProductRankingCard, { data: WELL_FORMED_RANKING }));
    expect(html).toContain('8,990 元');
    expect(html).toContain('毛利');
    expect(html).toContain('3,596');
    expect(html).toContain('销量');
    expect(html).toContain('10');
    expect(html).toContain('毛利率');
    expect(html).toContain('40.0%');
  });
});
