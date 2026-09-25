import { type Customer, type CustomerCoupon, api } from '@/lib/api';
import { getSelection, setSelectionKind } from '@/lib/page-context';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { Button } from 'ui';

interface AddressEntry {
  id?: string;
  recipientName?: string;
  phone?: string;
  fullAddress?: string;
  isDefault?: boolean;
}

interface OrderRowLite {
  order_id: string;
  status: string;
  total_amount: number;
  created_at: string;
}

interface Props {
  customer: Customer;
  onClose: () => void;
}

const STATUS_LABEL: Record<string, string> = {
  PAID: '待发货',
  SHIPPED: '已发货',
  DELIVERED: '已送达',
  REFUNDED: '已退款',
  COMPLETED: '已完成',
};

/** 客户详情抽屉:基本信息 + 只读地址簿 + 关联优惠券 + 关联订单(跳转并勾选)。 */
export function CustomerDetailDrawer({ customer, onClose }: Props) {
  const navigate = useNavigate();
  const [orders, setOrders] = useState<OrderRowLite[]>([]);
  const [coupons, setCouponList] = useState<CustomerCoupon[]>([]);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const res = await fetch('/api/admin/orders');
        if (res.ok) {
          const body = await res.json();
          if (alive) setOrders((body.orders || []).filter((o: any) => o.customer_id === customer.customer_id));
        }
      } catch {
        /* 详情关联数据拉取失败不打断抽屉 */
      }
      try {
        const b = await api.customers.coupons(customer.customer_id);
        if (alive) setCouponList(b.coupons || []);
      } catch {
        /* 同上 */
      }
    })();
    return () => {
      alive = false;
    };
  }, [customer.customer_id]);

  const addresses: AddressEntry[] = (() => {
    try {
      return JSON.parse(customer.addresses || '[]');
    } catch {
      return [];
    }
  })();

  function openOrder(orderId: string) {
    // PageContext 契约(19-D3,T5 翻新):订单写入类型化选择库(order 类),
    // 订单页"已选"横幅与悬浮 agent 实时联动;不再写 localStorage
    setSelectionKind('order', [orderId, ...(getSelection().order || [])]);
    onClose();
    navigate('/orders');
  }

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: 遮罩点击关闭;键盘路径由「关闭」按钮承担
    <div className="fixed inset-0 z-40 flex justify-end bg-zinc-900/30" onClick={onClose} role="presentation">
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: 阻断冒泡到遮罩 */}
      <div className="h-full w-[420px] overflow-y-auto bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <div className="text-base font-semibold">{customer.name}</div>
            <div className="mt-0.5 text-[11px] text-zinc-400">
              {customer.customer_id} · {customer.phone}
              {customer.email ? ` · ${customer.email}` : ''}
            </div>
            <div className="mt-1 flex gap-2 text-[11px]">
              <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-zinc-500">{customer.member_level}</span>
              <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-zinc-500">
                累计 ¥{customer.total_spent.toLocaleString()}
              </span>
              <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-zinc-500">{customer.order_count} 单</span>
            </div>
          </div>
          <Button size="sm" variant="ghost" onClick={onClose}>
            关闭
          </Button>
        </div>

        <Section title={`地址簿(${addresses.length})`}>
          {addresses.length === 0 && <Empty text="暂无地址(随商城收货流程沉淀)" />}
          {addresses.map((a, i) => (
            <div key={a.id || i} className="rounded-lg border border-zinc-100 px-3 py-2 text-xs">
              <div className="font-medium text-zinc-700">
                {a.recipientName || '收件人'} · {a.phone || '-'}
                {a.isDefault && (
                  <span className="ml-2 rounded bg-emerald-50 px-1 text-[10px] text-emerald-600">默认</span>
                )}
              </div>
              <div className="mt-0.5 text-zinc-500">{a.fullAddress || '—'}</div>
            </div>
          ))}
        </Section>

        <Section title={`关联优惠券(${coupons.length})`}>
          {coupons.length === 0 && <Empty text="暂无关联优惠券" />}
          {coupons.map((c) => (
            <div
              key={c.id}
              className="flex items-center justify-between rounded-lg border border-zinc-100 px-3 py-2 text-xs"
            >
              <span>
                {c.name}
                <span className="ml-2 font-semibold text-rose-600">¥{c.value}</span>
              </span>
              <span className={c.status === 'used' ? 'text-zinc-400' : 'text-emerald-600'}>
                {c.status === 'used' ? `已使用(${c.usedOrderId || ''})` : '已领取'}
              </span>
            </div>
          ))}
        </Section>

        <Section title={`关联订单(${orders.length})`}>
          {orders.length === 0 && <Empty text="名下暂无订单" />}
          {orders.map((o) => (
            <div
              key={o.order_id}
              className="flex items-center justify-between rounded-lg border border-zinc-100 px-3 py-2 text-xs"
            >
              <div>
                <span className="font-mono text-zinc-700">{o.order_id}</span>
                <span className="ml-2 text-zinc-500">{STATUS_LABEL[o.status] || o.status}</span>
                <span className="ml-2">¥{o.total_amount}</span>
              </div>
              <Button size="sm" variant="ghost" onClick={() => openOrder(o.order_id)}>
                在订单中查看
              </Button>
            </div>
          ))}
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-5">
      <div className="text-xs font-semibold text-zinc-500">{title}</div>
      <div className="mt-2 space-y-1.5">{children}</div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-dashed border-zinc-200 px-3 py-3 text-center text-[11px] text-zinc-400">
      {text}
    </div>
  );
}
