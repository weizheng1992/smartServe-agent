import type { OrderAuditLog } from '@/lib/api';
import { Badge, Button } from 'ui';
import { useWorkbench } from '../workbench';

/** 行内操作审计 → 人话标签(真实写入面:MODIFY_ADDRESS/REQUEST_REFUND 走 AGENT_SPI)。 */
const ACTION_LABEL: Record<string, string> = {
  MODIFY_ADDRESS: '修改收货地址',
  REQUEST_REFUND: '退款申请',
  SHIP: '发货',
  ship: '发货',
};

const OPERATOR_LABEL: Record<string, string> = {
  AGENT_SPI: 'AI Agent(SPI)',
  merchant_operator: '商户操作员',
};

/** 订单详情抽屉:与 storefront /spi/v1/orders/detail 同形(camelCase 行项目 +
 *  实付/优惠/原价账本三行)+ 该订单审计时间线;数据经 workbench 中心态拉取。 */
export function OrderDetailDrawer() {
  const { detailOrderId, orderDetail, detailAuditLogs, detailLoading, detailError, closeOrderDetail } = useWorkbench();

  if (!detailOrderId) return null;

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: 遮罩点击关闭;键盘路径由「关闭」按钮承担
    <div className="fixed inset-0 z-40 flex justify-end bg-zinc-900/30" onClick={closeOrderDetail} role="presentation">
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: 阻断冒泡到遮罩 */}
      <div className="h-full w-[480px] overflow-y-auto bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <div className="font-mono text-base font-semibold">{detailOrderId}</div>
            {orderDetail && (
              <div className="mt-1.5">
                <StatusBadge status={orderDetail.status} />
              </div>
            )}
          </div>
          <Button size="sm" variant="ghost" onClick={closeOrderDetail}>
            关闭
          </Button>
        </div>

        {detailLoading && <div className="mt-8 text-center text-xs text-zinc-400">加载中…</div>}
        {!detailLoading && detailError && (
          <div className="mt-8 rounded-lg border border-dashed border-rose-200 bg-rose-50/60 px-3 py-4 text-center text-xs text-rose-600">
            {detailError}
          </div>
        )}

        {!detailLoading && !detailError && orderDetail && (
          <>
            <Section title="金额账本">
              <div className="grid grid-cols-3 gap-2">
                <AmountCell label="原价合计" value={orderDetail.originalAmount} muted />
                <AmountCell label="优惠" value={orderDetail.discountAmount} accent />
                <AmountCell label="实付" value={orderDetail.totalAmount} strong />
              </div>
              <div className="text-[11px] text-zinc-400">币种:{orderDetail.currency}</div>
            </Section>

            <Section title={`商品明细(${orderDetail.items.length})`}>
              {orderDetail.items.length === 0 && <Empty text="该订单无行项目记录" />}
              {orderDetail.items.map((it) => (
                <div key={it.skuId} className="rounded-lg border border-zinc-100 px-3 py-2 text-xs">
                  <div className="font-medium text-zinc-700">{it.title}</div>
                  <div className="mt-0.5 flex items-center justify-between text-zinc-500">
                    <span>{it.specSummary || '—'}</span>
                    <span>
                      ¥{(it.price ?? 0).toFixed(2)} × {it.quantity}
                      <span className="ml-2 font-semibold text-zinc-700">
                        小计 ¥{((it.price ?? 0) * it.quantity).toFixed(2)}
                      </span>
                    </span>
                  </div>
                </div>
              ))}
            </Section>

            <Section title="收货信息">
              <Row label="收件人">{orderDetail.shippingAddress?.recipientName || '—'}</Row>
              <Row label="联系电话">{orderDetail.shippingAddress?.phone || '—'}</Row>
              <Row label="收货地址">{orderDetail.shippingAddress?.fullAddress || '—'}</Row>
              <Row label="地址可修改">{orderDetail.isAddressModifiable ? '是' : '否(已锁定)'}</Row>
              <Row label="可退货">{orderDetail.isReturnable ? '是' : '否'}</Row>
            </Section>

            <Section title="物流信息">
              {orderDetail.tracking?.trackingNumber ? (
                <>
                  <Row label="承运商">{orderDetail.tracking.carrier || '—'}</Row>
                  <Row label="运单号">
                    <span className="font-mono">{orderDetail.tracking.trackingNumber}</span>
                  </Row>
                  {(orderDetail.tracking.timeline || []).length > 0 && (
                    <div className="mt-1 space-y-1 border-l border-zinc-200 pl-3">
                      {orderDetail.tracking.timeline!.map((t, i) => (
                        <div key={t.time || i} className="text-[11px] text-zinc-500">
                          <span className="text-zinc-400">{t.time || ''}</span> {t.status || ''}
                          {t.description ? ` · ${t.description}` : ''}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <Empty text="暂无物流信息(未发货)" />
              )}
            </Section>

            <Section title={`操作时间线(${detailAuditLogs.length})`}>
              {detailAuditLogs.length === 0 && <Empty text="暂无审计记录" />}
              {detailAuditLogs.map((log, i) => (
                <AuditRow key={log.id ?? i} log={log} />
              ))}
            </Section>

            <div className="mt-5 text-[11px] text-zinc-400">下单时间:{formatTime(orderDetail.createdAt)}</div>
          </>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    PAID: { label: '待发货', cls: 'bg-amber-100 text-amber-800 border-amber-200' },
    SHIPPED: { label: '已发货', cls: 'bg-blue-100 text-blue-800 border-blue-200' },
    DELIVERED: { label: '已签收', cls: 'bg-emerald-100 text-emerald-800 border-emerald-200' },
    REFUNDED: { label: '已退款', cls: 'bg-purple-100 text-purple-800 border-purple-200' },
  };
  const s = map[status] || { label: status, cls: 'bg-slate-100 text-slate-800 border-slate-200' };
  return (
    <Badge variant="outline" className={`${s.cls} font-bold`}>
      {s.label}
    </Badge>
  );
}

function AmountCell({
  label,
  value,
  strong,
  muted,
  accent,
}: {
  label: string;
  value: number;
  strong?: boolean;
  muted?: boolean;
  accent?: boolean;
}) {
  return (
    <div className="rounded-lg border border-zinc-100 px-3 py-2 text-center">
      <div className="text-[10px] text-zinc-400">{label}</div>
      <div
        className={`mt-0.5 text-sm font-semibold ${
          strong ? 'text-zinc-900' : muted ? 'text-zinc-500 line-through' : accent ? 'text-rose-600' : 'text-zinc-700'
        }`}
      >
        ¥{value.toFixed(2)}
      </div>
    </div>
  );
}

function AuditRow({ log }: { log: OrderAuditLog }) {
  return (
    <div className="rounded-lg border border-zinc-100 px-3 py-2 text-xs">
      <div className="flex items-center justify-between">
        <span className="font-medium text-zinc-700">{ACTION_LABEL[log.action_type] || log.action_type}</span>
        <span className="text-[11px] text-zinc-400">{formatTime(log.created_at)}</span>
      </div>
      <div className="mt-0.5 text-[11px] text-zinc-400">操作方:{OPERATOR_LABEL[log.operator] || log.operator}</div>
      {log.result && typeof log.result.message === 'string' && (
        <div className="mt-0.5 text-zinc-500">{log.result.message}</div>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 text-xs">
      <span className="shrink-0 text-zinc-400">{label}</span>
      <span className="text-right text-zinc-700">{children}</span>
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

function formatTime(iso?: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-CN', { hour12: false });
}
