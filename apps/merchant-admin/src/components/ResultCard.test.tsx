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

  it('单元格缺值诚实「—」,不出 "null"/"undefined" 字面量(夜审 2026-09-29)', () => {
    // 实弹:宽表某行缺列(null/undefined)时 String() 直出 "null" 字面量
    const { container } = render(
      <ResultCard
        data={tableCard([
          { productId: 'SKU-1', metricScore: 100 },
          { productId: null, metricScore: undefined },
        ])}
      />,
    );
    expect(container.textContent).not.toContain('null');
    expect(container.textContent).not.toContain('undefined');
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('宽表可横向滚动:三处表格(主表/诚实降级/折线降级)均包 overflow-x-auto', () => {
    // 实弹(2026-09-29):宽表(UUID 列/多列对比卡)被卡片根 overflow-hidden
    // 直接裁剪,无左右滚动。jsdom 无布局,断言滚动容器结构存在。
    const wide = [
      {
        productId: '4439213e-51a5-4c24-ba12-8dfa40dc68a9',
        name: '极光三合一全天候户外硬壳冲锋衣',
        category: '户外机能',
        stock: 205,
        metricScore: 9093,
      },
      {
        productId: 'ccf8e1f1-c25e-4fe4-82a6-22dd6ec952eb',
        name: '极光 Vibram黄金大底 复古解构运动老爹鞋',
        category: '潮流鞋靴',
        stock: 63,
        metricScore: 7192,
      },
    ];
    // 主表路径(排行卡)
    const main = render(<ResultCard data={tableCard(wide)} />);
    expect(main.container.querySelector('div.overflow-x-auto table')).not.toBeNull();
    main.unmount();
    // 用户点名条形但形状不符的诚实降级表
    const barDegrade = render(<ResultCard data={{ ...tableCard(wide), chart: 'bar', metric: 'order_overview' }} />);
    expect(barDegrade.container.querySelector('div.overflow-x-auto table')).not.toBeNull();
    barDegrade.unmount();
    // 折线降级表(linePoints 非数值路径)
    const lineDegrade = render(
      <ResultCard
        data={{
          metric: 'spu_compare',
          unit: '件',
          chart: 'line',
          rows: [
            { 商品: '极光羊毛短袖T恤', 品类: '潮流T恤', 销量: 0, GMV: 0, 订单数: 0 },
            { 商品: '极光轻量防晒衬衫', 品类: '衬衫', 销量: 0, GMV: 0, 订单数: 0 },
          ],
          cards: [],
        }}
      />,
    );
    expect(lineDegrade.container.querySelector('div.overflow-x-auto table')).not.toBeNull();
  });
});
