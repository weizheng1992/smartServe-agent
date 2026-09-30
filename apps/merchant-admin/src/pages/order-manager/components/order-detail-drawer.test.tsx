import '@testing-library/jest-dom/vitest';
import type { OrderDetail } from '@/lib/api';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { type Workbench, WorkbenchProvider } from '../workbench';
import { OrderDetailDrawer } from './order-detail-drawer';

const ORDER: OrderDetail = {
  orderId: 'MA-TEST-001',
  userId: 'CUST-001',
  status: 'PAID',
  totalAmount: 449,
  discountAmount: 50,
  originalAmount: 499,
  currency: 'CNY',
  createdAt: '2026-09-25T08:00:00Z',
  shippingAddress: { recipientName: '张伟', phone: '13800138000', fullAddress: '浙江省杭州市' },
  tracking: null,
  isAddressModifiable: true,
  isReturnable: true,
  items: [
    {
      skuId: 'SKU-001',
      productId: 'SPU-001',
      title: '极光轻量三防连帽冲锋衣',
      quantity: 1,
      price: 499,
      imageUrl: null,
      specSummary: '曜石黑/L',
    },
  ],
};

function withWb(partial: Partial<Workbench>) {
  const wb = {
    detailOrderId: null,
    orderDetail: null,
    detailAuditLogs: [],
    detailLoading: false,
    detailError: null,
    closeOrderDetail: () => {},
    ...partial,
  } as Workbench;
  return ({ children }: { children: React.ReactNode }) => <WorkbenchProvider value={wb}>{children}</WorkbenchProvider>;
}

describe('OrderDetailDrawer(中心态注入,不依赖网关)', () => {
  it('detailOrderId 为空时不渲染(常挂组件诚实静默)', () => {
    const Wrap = withWb({});
    render(
      <Wrap>
        <OrderDetailDrawer />
      </Wrap>,
    );
    expect(screen.queryByText('关闭')).not.toBeInTheDocument();
  });

  it('详情渲染:账本三行/行项目/收货信息/空时间线诚实降级', () => {
    const Wrap = withWb({ detailOrderId: 'MA-TEST-001', orderDetail: ORDER });
    render(
      <Wrap>
        <OrderDetailDrawer />
      </Wrap>,
    );
    expect(screen.getByText('MA-TEST-001')).toBeInTheDocument();
    expect(screen.getByText('¥499.00')).toBeInTheDocument(); // 原价合计
    expect(screen.getByText('¥50.00')).toBeInTheDocument(); // 优惠
    expect(screen.getByText('¥449.00')).toBeInTheDocument(); // 实付
    expect(screen.getByText('极光轻量三防连帽冲锋衣')).toBeInTheDocument();
    expect(screen.getByText('张伟')).toBeInTheDocument();
    expect(screen.getByText('暂无审计记录')).toBeInTheDocument();
    expect(screen.getByText('暂无物流信息(未发货)')).toBeInTheDocument();
  });

  it('失败态:detailError 以错误横幅呈现,不渲染空白抽屉', () => {
    const Wrap = withWb({ detailOrderId: 'MA-GONE-404', detailError: '订单 MA-GONE-404 不存在' });
    render(
      <Wrap>
        <OrderDetailDrawer />
      </Wrap>,
    );
    expect(screen.getByText(/不存在/)).toBeInTheDocument();
  });

  it('审计时间线:action_type/operator 译为人话,失败文本不可读出', () => {
    const Wrap = withWb({
      detailOrderId: 'MA-TEST-001',
      orderDetail: ORDER,
      detailAuditLogs: [
        {
          id: 1,
          action_type: 'MODIFY_ADDRESS',
          order_id: 'MA-TEST-001',
          idempotency_key: 'ik-1',
          operator: 'AGENT_SPI',
          payload: null,
          result: { message: '收货地址修改成功' },
          created_at: '2026-09-25T09:00:00Z',
        },
      ],
    });
    render(
      <Wrap>
        <OrderDetailDrawer />
      </Wrap>,
    );
    expect(screen.getByText('修改收货地址')).toBeInTheDocument();
    expect(screen.getByText(/操作方:AI Agent\(SPI\)/)).toBeInTheDocument();
    expect(screen.getByText('收货地址修改成功')).toBeInTheDocument();
    expect(screen.queryByText('MODIFY_ADDRESS')).not.toBeInTheDocument();
  });

  it('行项目缺价(price=null):单价与小计诚实「—」,严禁假 ¥0.00', () => {
    const Wrap = withWb({
      detailOrderId: 'MA-TEST-001',
      orderDetail: {
        ...ORDER,
        items: [{ ...ORDER.items[0]!, price: null }],
      },
    });
    render(
      <Wrap>
        <OrderDetailDrawer />
      </Wrap>,
    );
    expect(screen.getByText('极光轻量三防连帽冲锋衣')).toBeInTheDocument();
    expect(screen.getByText(/— × 1/)).toBeInTheDocument();
    expect(screen.getByText(/小计 —/)).toBeInTheDocument();
    expect(screen.queryByText(/¥0\.00/)).not.toBeInTheDocument();
  });
});
