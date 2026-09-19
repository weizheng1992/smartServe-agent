import '@testing-library/jest-dom/vitest';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { AskTranscript, type AskFrame } from './ask-transcript';

const onAsk = vi.fn();
const renderTranscript = (frames: AskFrame[]) =>
  render(<MemoryRouter><AskTranscript frames={frames} onAsk={onAsk} /></MemoryRouter>);

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
    renderTranscript([{
      event: 'result',
      data: {
        cards: [{
          type: 'table', title: 'gmv · 元', caliber: '已支付订单实付金额',
          columns: [{ key: 'sku', label: 'SKU' }, { key: 'gmv', label: 'GMV' }],
          rows: [{ sku: 'SPU-A', gmv: 99.5 }],
        }],
      },
    }]);
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
    renderTranscript([{
      event: 'clarify',
      data: {
        clarifyKind: 'entity', question: '请选择活动——', originalQuestion: '有个活动卖得怎么样',
        options: [{ label: '开学季满减' }, { label: '618 大促' }],
      },
    }]);
    fireEvent.click(screen.getByRole('button', { name: '开学季满减' }));
    expect(onAsk).toHaveBeenCalledWith('有个活动卖得怎么样(开学季满减)');
  });

  it('customer_orders 结果卡:渲染订单行 + 「在订单中查看」跳转写选中集合', () => {
    renderTranscript([{
      event: 'result',
      data: {
        metric: 'customer_orders', unit: '单', caliber: '客户订单 = 名下全部订单按下单时间倒序',
        rows: [{ order_id: 'AURORA-ORD-1', status: 'PAID', total_amount: 99, created_at: '09-19 10:00' }],
      },
    }]);
    expect(screen.getByText('AURORA-ORD-1')).toBeInTheDocument();
    expect(screen.getByText('待发货')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '在订单中查看' }));
    const selection = JSON.parse(localStorage.getItem('merchant-admin.selection') || '[]');
    expect(selection).toContain('AURORA-ORD-1');
  });
});
