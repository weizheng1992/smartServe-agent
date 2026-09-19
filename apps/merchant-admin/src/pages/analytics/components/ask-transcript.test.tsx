import '@testing-library/jest-dom/vitest';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { AskTranscript, type AskFrame } from './ask-transcript';

const base = { onAsk: () => {} };

describe('AskTranscript', () => {
  it('start 帧不渲染;用户问题渲染为右对齐气泡', () => {
    const frames: AskFrame[] = [
      { event: 'start', data: { staff: '老板' } },
      { event: 'user', data: { message: '本月销量 Top10' } },
    ];
    render(<AskTranscript frames={frames} onAsk={base.onAsk} />);
    expect(screen.getByText('本月销量 Top10')).toBeInTheDocument();
    expect(screen.queryByText('老板')).not.toBeInTheDocument();
  });

  it('result 表格卡:标题/列头/行与口径注记齐全', () => {
    const frames: AskFrame[] = [{
      event: 'result',
      data: {
        cards: [{
          type: 'table', title: 'gmv · 元', caliber: '已支付订单实付金额',
          columns: [{ key: 'sku', label: 'SKU' }, { key: 'gmv', label: 'GMV' }],
          rows: [{ sku: 'SPU-A', gmv: 99.5 }],
        }],
      },
    }];
    render(<AskTranscript frames={frames} onAsk={base.onAsk} />);
    expect(screen.getByText('gmv · 元')).toBeInTheDocument();
    expect(screen.getByText('SKU')).toBeInTheDocument();
    expect(screen.getByText('SPU-A')).toBeInTheDocument();
    expect(screen.getByText('口径:已支付订单实付金额')).toBeInTheDocument();
  });

  it('unsupported 诚实展示拒绝文案', () => {
    const frames: AskFrame[] = [{ event: 'unsupported', data: { message: '该问题暂不支持。' } }];
    render(<AskTranscript frames={frames} onAsk={base.onAsk} />);
    expect(screen.getByText('该问题暂不支持。')).toBeInTheDocument();
  });

  it('clarify 反问选项点击 → 按模板发起追问', () => {
    const onAsk = vi.fn();
    const frames: AskFrame[] = [{
      event: 'clarify',
      data: { options: [{ label: '销量' }, { label: 'GMV' }] },
    }];
    render(<AskTranscript frames={frames} onAsk={onAsk} />);
    fireEvent.click(screen.getByRole('button', { name: '销量' }));
    expect(onAsk).toHaveBeenCalledWith('按销量的商品排行');
  });
});
