import '@testing-library/jest-dom/vitest';
import { clearSelection, getSelection } from '@/lib/page-context';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type AskFrame, AskTranscript } from './ask-transcript';

const onAsk = vi.fn();
const renderTranscript = (frames: AskFrame[]) =>
  render(
    <MemoryRouter>
      <AskTranscript frames={frames} onAsk={onAsk} />
    </MemoryRouter>,
  );

beforeEach(() => {
  onAsk.mockClear();
  clearSelection();
});

describe('AskTranscript', () => {
  it('start 帧不渲染;用户问题渲染为气泡', () => {
    renderTranscript([
      { event: 'start', data: { staff: '老板' } },
      { event: 'user', data: { message: '本月销量 Top10' } },
    ]);
    expect(screen.getByText('本月销量 Top10')).toBeInTheDocument();
    expect(screen.queryByText('老板')).not.toBeInTheDocument();
  });

  it('result 表格卡:标题/列头/行与口径注记齐全', () => {
    renderTranscript([
      {
        event: 'result',
        data: {
          cards: [
            {
              type: 'table',
              title: 'gmv · 元',
              caliber: '已支付订单实付金额',
              columns: [
                { key: 'sku', label: 'SKU' },
                { key: 'gmv', label: 'GMV' },
              ],
              rows: [{ sku: 'SPU-A', gmv: 99.5 }],
            },
          ],
        },
      },
    ]);
    expect(screen.getByText('gmv · 元')).toBeInTheDocument();
    expect(screen.getByText('SKU')).toBeInTheDocument();
    expect(screen.getByText('SPU-A')).toBeInTheDocument();
    expect(screen.getByText('口径:已支付订单实付金额')).toBeInTheDocument();
  });

  it('unsupported 诚实展示拒绝文案', () => {
    renderTranscript([{ event: 'unsupported', data: { message: '该问题暂不支持。' } }]);
    expect(screen.getByText('该问题暂不支持。')).toBeInTheDocument();
  });

  it('clarify(指标歧义)选项点击 → 按「按{label}的商品排行」模板追问', () => {
    renderTranscript([{ event: 'clarify', data: { options: [{ label: '销量' }, { label: 'GMV' }] } }]);
    fireEvent.click(screen.getByRole('button', { name: '销量' }));
    expect(onAsk).toHaveBeenCalledWith('按销量的商品排行');
  });

  it('clarify(实体反问)点击 → 原问题 + 选项名组合回问(保留查询上下文)', () => {
    renderTranscript([
      {
        event: 'clarify',
        data: {
          clarifyKind: 'entity',
          question: '请选择活动——',
          originalQuestion: '有个活动卖得怎么样',
          options: [{ label: '开学季满减' }, { label: '618 大促' }],
        },
      },
    ]);
    fireEvent.click(screen.getByRole('button', { name: '开学季满减' }));
    expect(onAsk).toHaveBeenCalledWith('有个活动卖得怎么样(开学季满减)');
  });

  it('customer_orders 结果卡:渲染订单行 + 「在订单中查看」跳转写入内存选中集合(严禁 localStorage)', () => {
    renderTranscript([
      {
        event: 'result',
        data: {
          metric: 'customer_orders',
          unit: '单',
          caliber: '客户订单 = 名下全部订单按下单时间倒序',
          rows: [{ order_id: 'AURORA-ORD-1', status: 'PAID', total_amount: 99, created_at: '09-19 10:00' }],
        },
      },
    ]);
    expect(screen.getByText('AURORA-ORD-1')).toBeInTheDocument();
    expect(screen.getByText('待发货')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '在订单中查看' }));
    expect(getSelection().order).toContain('AURORA-ORD-1');
    // 违禁键不得复活(残留勾选曾两次静默污染查询,merchant-admin.md §1.3)
    expect(localStorage.getItem('merchant-admin.selection')).toBeNull();
  });

  it('折线走 ResultCard 唯一渲染缝:值列非数值 → 诚实降级表格,不画 NaN 网线', () => {
    renderTranscript([
      {
        event: 'result',
        data: {
          chart: 'line',
          metric: 'spu_compare',
          unit: '件',
          caliber: '有效订单聚合',
          rows: [
            { name: '潮流T恤', qty: '品类文案' },
            { name: '防晒衬衫', qty: 3 },
          ],
        },
      },
    ]);
    expect(screen.getByText(/不是数值数列/)).toBeInTheDocument();
    expect(screen.getByText('潮流T恤')).toBeInTheDocument();
    expect(document.querySelector('svg')).toBeNull();
  });
});
