// 坐席上下文栏五项渲染契约(live-desk-rework P3):五项渲染 + 诚实空态 +
// 备注增删交互 + 折叠行为。spec 验收:弱关联未匹配必须诚实呈现,严禁伪装修配。
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { LiveDeskContext } from '@/lib/api';
import {
  ContextCustomer,
  ContextNotes,
  ContextOrders,
  ContextProfile,
  ContextSection,
  ContextTickets,
} from './live-desk-context-parts';

function ctx(overrides: Partial<LiveDeskContext> = {}): LiveDeskContext {
  return {
    success: true,
    thread: { threadId: 't1', userId: 'u1', status: 'human_takeover', assignedOperatorId: 'a@aurora' },
    customer: { matched: false },
    recentOrders: [],
    afterSaleTickets: [],
    profile: { global: [], tenant: [] },
    notes: [],
    ...overrides,
  };
}

const MATCHED = ctx({
  customer: {
    matched: true,
    customerId: 'CUST-1',
    name: '王小明',
    phoneMasked: '138****8000',
    email: 'w@x.com',
    memberLevel: 'VIP',
    tags: ['高净值客户'],
    totalSpent: 458.5,
    orderCount: 2,
  },
  recentOrders: [
    { orderId: 'ORD-1', status: 'SHIPPED', totalAmount: 299, createdAt: '2026-09-25T10:00:00' },
    { orderId: 'ORD-2', status: 'COMPLETED', totalAmount: 159.5, createdAt: '2026-09-20T10:00:00' },
  ],
  afterSaleTickets: [
    {
      id: 'ast1',
      orderId: 'ORD-1',
      type: 'refund',
      reason: '质量问题',
      status: 'pending_review',
      refundAmount: 99,
      createdAt: null,
    },
  ],
  profile: { global: ['偏好棉质面料'], tenant: ['偏好基础款'] },
  notes: [{ id: 'n1', content: '顾客抱怨物流慢,已安抚', authorEmail: 'a@aurora', createdAt: '2026-09-25T10:00:00' }],
});

describe('ContextCustomer 客户档案', () => {
  it('命中:档案全量 + 手机脱敏 + 聚合', () => {
    render(<ContextCustomer context={MATCHED} />);
    expect(screen.getByTestId('ctx-customer-matched')).toHaveTextContent('王小明');
    expect(screen.getByTestId('ctx-customer-matched')).toHaveTextContent('138****8000');
    expect(screen.getByTestId('ctx-customer-matched')).toHaveTextContent('¥458.50');
    expect(screen.getByTestId('ctx-customer-matched')).toHaveTextContent('2 单');
    expect(screen.getByText('VIP')).toBeInTheDocument();
    expect(screen.getByText('高净值客户')).toBeInTheDocument();
  });

  it('未匹配:诚实空态(聊天身份与商户客户编号暂无关联)', () => {
    render(<ContextCustomer context={ctx()} />);
    expect(screen.getByTestId('ctx-customer-unmatched')).toHaveTextContent(
      '未匹配到商户客户档案(聊天身份与商户客户编号暂无关联)',
    );
  });
});

describe('ContextOrders / ContextTickets / ContextProfile', () => {
  it('订单行渲染 orderId/状态/金额', () => {
    render(<ContextOrders context={MATCHED} />);
    expect(screen.getAllByTestId('ctx-order-row')).toHaveLength(2);
    expect(screen.getByText('ORD-1')).toBeInTheDocument();
    expect(screen.getByText(/SHIPPED · ¥299/)).toBeInTheDocument();
  });

  it('售后中工单渲染类型/原因/状态', () => {
    render(<ContextTickets context={MATCHED} />);
    expect(screen.getByTestId('ctx-ticket-row')).toHaveTextContent('退款');
    expect(screen.getByTestId('ctx-ticket-row')).toHaveTextContent('质量问题');
    expect(screen.getByTestId('ctx-ticket-row')).toHaveTextContent('pending_review');
  });

  it('双层画像 global|tenant 分栏不合并', () => {
    render(<ContextProfile context={MATCHED} />);
    expect(screen.getByTestId('ctx-profile-global')).toHaveTextContent('偏好棉质面料');
    expect(screen.getByTestId('ctx-profile-tenant')).toHaveTextContent('偏好基础款');
    expect(screen.getByText('全局通用')).toBeInTheDocument();
    expect(screen.getByText('本店专属')).toBeInTheDocument();
  });

  it('诚实空态:三区空文案', () => {
    render(
      <>
        <ContextOrders context={ctx()} />
        <ContextTickets context={ctx()} />
        <ContextProfile context={ctx()} />
      </>,
    );
    expect(screen.getByText('暂无订单记录')).toBeInTheDocument();
    expect(screen.getByText('暂无售后中工单')).toBeInTheDocument();
    expect(screen.getByText('暂无画像事实')).toBeInTheDocument();
  });
});

describe('ContextNotes 内部备注', () => {
  it('列表渲染 + 添加回调', () => {
    const onAdd = vi.fn();
    render(<ContextNotes context={MATCHED} onAdd={onAdd} onRemove={vi.fn()} />);
    expect(screen.getByTestId('ctx-note-row')).toHaveTextContent('顾客抱怨物流慢,已安抚');
    fireEvent.change(screen.getByTestId('ctx-note-input'), { target: { value: '补发优惠券' } });
    fireEvent.click(screen.getByTestId('ctx-note-add'));
    expect(onAdd).toHaveBeenCalledWith('补发优惠券');
  });

  it('空态 + 删除回调', () => {
    const onRemove = vi.fn();
    render(<ContextNotes context={ctx()} onAdd={vi.fn()} onRemove={onRemove} />);
    expect(screen.getByText('暂无备注')).toBeInTheDocument();
    render(<ContextNotes context={MATCHED} onAdd={vi.fn()} onRemove={onRemove} />);
    fireEvent.click(screen.getAllByTestId('ctx-note-remove')[0]);
    expect(onRemove).toHaveBeenCalledWith(expect.objectContaining({ id: 'n1' }));
  });

  it('空白草稿不触发添加', () => {
    const onAdd = vi.fn();
    render(<ContextNotes context={ctx()} onAdd={onAdd} onRemove={vi.fn()} />);
    fireEvent.change(screen.getByTestId('ctx-note-input'), { target: { value: '   ' } });
    fireEvent.click(screen.getByTestId('ctx-note-add'));
    expect(onAdd).not.toHaveBeenCalled();
  });
});

describe('ContextSection 折叠', () => {
  it('默认收起,点击展开再收起;defaultOpen 直开', () => {
    render(
      <>
        <ContextSection title="最近订单" testId="ctx-section-orders">
          <div>订单内容</div>
        </ContextSection>
        <ContextSection title="客户档案" testId="ctx-section-customer" defaultOpen>
          <div>档案内容</div>
        </ContextSection>
      </>,
    );
    expect(screen.queryByText('订单内容')).not.toBeInTheDocument();
    expect(screen.getByText('档案内容')).toBeInTheDocument();

    const toggle = screen.getByRole('button', { name: /最近订单/ });
    fireEvent.click(toggle);
    expect(screen.getByText('订单内容')).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.queryByText('订单内容')).not.toBeInTheDocument();
  });
});
