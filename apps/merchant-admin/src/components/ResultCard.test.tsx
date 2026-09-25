import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ResultCard } from './ResultCard';

const tableCard = (rows: Record<string, unknown>[]) => ({
  metric: 'category_gmv_top',
  title: '品类GMV榜 · 元',
  unit: '元',
  chart: null,
  rows,
  cards: [
    {
      type: 'table',
      title: '品类GMV榜 · 元',
      columns: [
        { key: 'productId', label: 'productId' },
        { key: 'metricScore', label: 'metricScore' },
      ],
      rows,
      caliber: '有效订单聚合',
    },
  ],
});

describe('ResultCard(结果卡同形渲染)', () => {
  it('排行形(≥2 行数值)渲染条形图 + 表格 + 口径', () => {
    render(
      <ResultCard
        data={tableCard([
          { productId: '户外机能', metricScore: 14237 },
          { productId: '潮流鞋靴', metricScore: 11487 },
        ])}
      />,
    );
    expect(screen.getByLabelText('排行条形图')).toBeInTheDocument();
    expect(screen.getByText(/口径:/)).toBeInTheDocument();
  });

  it('chart=table 尊重用户指令:不画条形图只出表格', () => {
    render(
      <ResultCard
        data={{
          ...tableCard([
            { productId: 'A', metricScore: 1 },
            { productId: 'B', metricScore: 2 },
          ]),
          chart: 'table',
        }}
      />,
    );
    expect(screen.queryByLabelText('排行条形图')).not.toBeInTheDocument();
  });

  it('逐笔列表(order_overview)不画条形图', () => {
    render(
      <ResultCard
        data={{
          ...tableCard([
            { 订单号: 'O1', 金额: 100 },
            { 订单号: 'O2', 金额: 200 },
          ]),
          metric: 'order_overview',
        }}
      />,
    );
    expect(screen.queryByLabelText('排行条形图')).not.toBeInTheDocument();
  });

  it('chart=line 但数据点 <2:诚实提示后按表格呈现(T2 票面)', () => {
    render(<ResultCard data={{ ...tableCard([{ 日期: '09-01', 销量: 3 }]), chart: 'line' }} />);
    expect(screen.getByText(/折线至少需要 2 个数据点/)).toBeInTheDocument();
    expect(screen.queryByLabelText('趋势折线图')).not.toBeInTheDocument();
  });

  it('chart=line 且 ≥2 点:出折线图', () => {
    render(
      <ResultCard
        data={{
          metric: 'volume_trend',
          title: '销量趋势 · 件',
          unit: '件',
          chart: 'line',
          rows: [
            { 日期: '09-01', 销量: 1 },
            { 日期: '09-02', 销量: 5 },
          ],
          cards: [],
        }}
      />,
    );
    expect(screen.getByLabelText('趋势折线图')).toBeInTheDocument();
  });

  it('chart=line 但第 2 列非数值(历史持久化帧):不出 NaN,诚实降级表格', () => {
    // 实弹:修复前会话持久化帧(spu_compare + 折线指令)重放 —— 值列取到
    // 「品类」文案 → Number()=NaN,LineChart 三格网线全渲染 NaN
    const { container } = render(
      <ResultCard
        data={{
          metric: 'spu_compare',
          title: '极光 120g超轻可收纳防晒皮肤短袖衬衫 等 2 项 · 商品销售对比 · 件',
          unit: '件',
          chart: 'line',
          rows: [
            { 商品: '极光 17.5微米美利奴羊毛天然温控短袖T恤', 品类: '潮流T恤', 销量: 0, GMV: 0, 订单数: 0 },
            { 商品: '极光 120g超轻可收纳防晒皮肤短袖衬衫', 品类: '衬衫', 销量: 0, GMV: 0, 订单数: 0 },
          ],
          cards: [],
        }}
      />,
    );
    expect(container.textContent).not.toContain('NaN');
    expect(screen.queryByLabelText('趋势折线图')).not.toBeInTheDocument();
    expect(screen.getByText(/按表格呈现/)).toBeInTheDocument();
  });

  it('空结果走诚实空文案', () => {
    render(<ResultCard data={{ metric: 'x', unit: '', rows: [], cards: [{ type: 'text', text: '诚实空' }] }} />);
    expect(screen.getByText('诚实空')).toBeInTheDocument();
  });
});
