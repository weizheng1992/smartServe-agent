import { type OrderAuditLog, type OrderDetail, api, errMsgOf } from '@/lib/api';
import { fmtMoney, orderStatusMeta } from '@/lib/format';
// 坐席台订单弹窗族(客服优化批 2026-10-25):详情 / 一键发货 / 快捷选项推送。
// 全控件 workspace 包 ui(shadcn);弹窗 chrome 统一 rounded-xl border-zinc-200
// p-6 text-zinc-900 shadow-xl(merchant-admin.md §2.5,p-6 由消费方自给)。
// 失败文案一律 errMsgOf 单点;缺值诚实「—」,严禁编造(数据诚实律)。
import { useEffect, useState } from 'react';
import { type RichCardBlock } from 'types';
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from 'ui';
import { CARRIER_OPTIONS, QUICK_REPLY_PRESETS, buildQuickRepliesCard, carrierLabelOf } from './live-desk-cards';

/** 审计动作 → 人话(与 order-manager OrderDetailDrawer 同词表的最小子集)。 */
const AUDIT_ACTION_LABEL: Record<string, string> = {
  SHIP: '发货',
  MODIFY_ADDRESS: '修改收货地址',
  REQUEST_REFUND: '退款申请',
};

function auditOperatorLabel(operator: string): string {
  if (operator === 'AGENT_SPI') return 'AI Agent(SPI)';
  if (operator === 'merchant_operator') return '商户操作员';
  return operator;
}

/** 订单详情弹窗:GET /api/admin/orders/{id}(行项目+账本+收货+物流+审计时间线)。 */
export function DeskOrderDialog({ orderId, onClose }: { orderId: string | null; onClose: () => void }) {
  const [detail, setDetail] = useState<OrderDetail | null>(null);
  const [auditLogs, setAuditLogs] = useState<OrderAuditLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!orderId) return;
    setDetail(null);
    setAuditLogs([]);
    setError('');
    setLoading(true);
    api.orders
      .detail(orderId)
      .then((body) => {
        if (body.success && body.order) {
          setDetail(body.order);
          setAuditLogs(body.auditLogs || []);
        } else {
          setError(errMsgOf(body, '订单详情加载失败'));
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : '订单详情加载失败'))
      .finally(() => setLoading(false));
  }, [orderId]);

  return (
    <Dialog open={Boolean(orderId)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-md overflow-y-auto rounded-xl border-zinc-200 p-6 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3">
          <DialogTitle className="flex items-center gap-2 font-mono text-sm">
            订单详情
            {detail && (
              <Badge variant="outline" className={`${orderStatusMeta(detail.status).cls} text-[10px]`}>
                {orderStatusMeta(detail.status).label}
              </Badge>
            )}
          </DialogTitle>
          {orderId && <p className="mt-1 font-mono text-[11px] text-zinc-500">{orderId}</p>}
        </DialogHeader>

        {loading && <div className="py-8 text-center text-xs text-zinc-400">加载中…</div>}
        {!loading && error && (
          <div className="rounded-lg border border-dashed border-rose-200 bg-rose-50/60 px-3 py-4 text-center text-xs text-rose-600">
            {error}
          </div>
        )}

        {!loading && !error && detail && (
          <div className="space-y-4 text-xs">
            <section>
              <div className="text-[11px] font-semibold text-zinc-500">金额账本</div>
              <div className="mt-1.5 grid grid-cols-3 gap-2 text-center">
                <div className="rounded-lg border border-zinc-100 px-2 py-1.5">
                  <div className="text-[10px] text-zinc-400">原价</div>
                  <div className="mt-0.5 text-zinc-500 line-through">¥{fmtMoney(detail.originalAmount)}</div>
                </div>
                <div className="rounded-lg border border-zinc-100 px-2 py-1.5">
                  <div className="text-[10px] text-zinc-400">优惠</div>
                  <div className="mt-0.5 text-rose-600">¥{fmtMoney(detail.discountAmount)}</div>
                </div>
                <div className="rounded-lg border border-zinc-100 px-2 py-1.5">
                  <div className="text-[10px] text-zinc-400">实付</div>
                  <div className="mt-0.5 font-semibold text-zinc-900">¥{fmtMoney(detail.totalAmount)}</div>
                </div>
              </div>
            </section>

            <section>
              <div className="text-[11px] font-semibold text-zinc-500">商品明细({detail.items.length})</div>
              <div className="mt-1.5 space-y-1.5">
                {detail.items.length === 0 && <div className="text-[11px] text-zinc-400">该订单无行项目记录</div>}
                {detail.items.map((it) => (
                  <div key={it.skuId} className="rounded-lg border border-zinc-100 px-2.5 py-1.5">
                    <div className="font-medium text-zinc-700">{it.title}</div>
                    <div className="mt-0.5 flex items-center justify-between text-zinc-500">
                      <span>{it.specSummary || '—'}</span>
                      <span>
                        {it.price == null ? '—' : `¥${fmtMoney(it.price)}`} × {it.quantity}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="space-y-1">
              <div className="text-[11px] font-semibold text-zinc-500">收货信息</div>
              <div className="flex justify-between">
                <span className="text-zinc-400">收件人</span>
                <span className="text-zinc-700">{detail.shippingAddress?.recipientName || '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400">电话</span>
                <span className="text-zinc-700">{detail.shippingAddress?.phone || '—'}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="shrink-0 text-zinc-400">地址</span>
                <span className="text-right text-zinc-700">{detail.shippingAddress?.fullAddress || '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400">地址可改</span>
                <span className="text-zinc-700">{detail.isAddressModifiable ? '是' : '否(已锁定)'}</span>
              </div>
            </section>

            <section className="space-y-1">
              <div className="text-[11px] font-semibold text-zinc-500">物流信息</div>
              {detail.tracking?.trackingNumber ? (
                <>
                  <div className="flex justify-between">
                    <span className="text-zinc-400">承运商</span>
                    <span className="text-zinc-700">{detail.tracking.carrier || '—'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-400">运单号</span>
                    <span className="font-mono text-zinc-700">{detail.tracking.trackingNumber}</span>
                  </div>
                  {(detail.tracking.timeline || []).map((t, i) => (
                    <div key={t.time || i} className="border-l border-zinc-200 pl-2.5 text-[11px] text-zinc-500">
                      <span className="text-zinc-400">{(t.time || '').slice(5, 16)}</span> {t.status || ''}
                      {t.description ? ` · ${t.description}` : ''}
                    </div>
                  ))}
                </>
              ) : (
                <div className="text-[11px] text-zinc-400">暂无物流信息(未发货)</div>
              )}
            </section>

            <section className="space-y-1.5">
              <div className="text-[11px] font-semibold text-zinc-500">操作时间线({auditLogs.length})</div>
              {auditLogs.length === 0 && <div className="text-[11px] text-zinc-400">暂无审计记录</div>}
              {auditLogs.map((log, i) => (
                <div key={log.id ?? i} className="rounded-lg border border-zinc-100 px-2.5 py-1.5">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-zinc-700">
                      {AUDIT_ACTION_LABEL[log.action_type] || log.action_type}
                    </span>
                    <span className="text-[10px] text-zinc-400">
                      {log.created_at?.replace('T', ' ').slice(0, 16) || '—'}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[10px] text-zinc-400">操作方:{auditOperatorLabel(log.operator)}</div>
                  {log.result && typeof (log.result as Record<string, unknown>).message === 'string' && (
                    <div className="mt-0.5 text-[11px] text-zinc-500">
                      {String((log.result as Record<string, unknown>).message)}
                    </div>
                  )}
                </div>
              ))}
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** 一键发货弹窗:复用 POST /api/admin/orders/ship(RBAC order:ship 服务端闸);
 *  运单号必须实填 —— 随机预填号一旦提交即成真账面假物流(orders-tab 同律)。 */
export function DeskShipDialog({
  orderId,
  onClose,
  onShipped,
}: {
  orderId: string | null;
  onClose: () => void;
  onShipped: (carrierCode: string, carrierLabel: string, trackingNo: string) => void;
}) {
  const [carrier, setCarrier] = useState('SF');
  const [trackingNo, setTrackingNo] = useState('');
  const [err, setErr] = useState('');
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (orderId) {
      setCarrier('SF');
      setTrackingNo('');
      setErr('');
    }
  }, [orderId]);

  const submit = async () => {
    if (!orderId || sending) return;
    const tn = trackingNo.trim();
    if (!tn) {
      setErr('运单号必须实填(不预填随机号,防假物流入账)');
      return;
    }
    setSending(true);
    setErr('');
    try {
      const body = await api.orders.ship({ orderId, carrierCode: carrier, trackingNo: tn });
      if (body.success) {
        onShipped(carrier, carrierLabelOf(carrier), tn);
      } else {
        setErr(errMsgOf(body, '发货失败'));
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : '发货失败');
    } finally {
      setSending(false);
    }
  };

  return (
    <Dialog open={Boolean(orderId)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-sm rounded-xl border-zinc-200 p-6 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3">
          <DialogTitle className="text-sm">订单一键发货</DialogTitle>
          <p className="mt-1 font-mono text-[11px] text-zinc-500">{orderId}</p>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div>
            <Label htmlFor="desk-ship-carrier" className="mb-1 block text-xs font-semibold text-zinc-700">
              承运快递公司
            </Label>
            <Select value={carrier} onValueChange={setCarrier}>
              <SelectTrigger
                id="desk-ship-carrier"
                aria-label="承运快递公司"
                className="w-full rounded-lg border-zinc-300 px-3 py-2 text-xs"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CARRIER_OPTIONS.map((c) => (
                  <SelectItem key={c.code} value={c.code}>
                    {c.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label htmlFor="desk-ship-tracking" className="mb-1 block text-xs font-semibold text-zinc-700">
              快递运单号
            </Label>
            <Input
              id="desk-ship-tracking"
              value={trackingNo}
              onChange={(e) => setTrackingNo(e.target.value)}
              className="h-9 bg-white font-mono text-xs"
              placeholder="请输入真实运单号..."
            />
          </div>
          {err && <div className="rounded-lg bg-red-50 px-2.5 py-1.5 text-[11px] text-red-600">{err}</div>}
        </div>
        <DialogFooter className="gap-2 pt-2">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="cursor-pointer text-xs">
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={sending}
            onClick={() => void submit()}
            className="cursor-pointer text-xs font-semibold"
          >
            {sending ? '发货中…' : '确认发货并锁定地址'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** 快捷选项推送弹窗:预设 quick_replies 卡(顾客点选回流成消息,C 级交互)。 */
export function QuickRepliesDialog({
  open,
  onClose,
  onSend,
}: {
  open: boolean;
  onClose: () => void;
  onSend: (card: RichCardBlock) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm rounded-xl border-zinc-200 p-6 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3">
          <DialogTitle className="text-sm">推送快捷选项</DialogTitle>
          <p className="mt-1 text-[11px] text-zinc-500">顾客在卡片上点选后,选择会作为消息回流到本会话时间线。</p>
        </DialogHeader>
        <div className="space-y-2 py-1">
          {QUICK_REPLY_PRESETS.map((preset) => (
            <div key={preset.id} className="rounded-lg border border-zinc-100 px-3 py-2">
              <div className="text-xs font-medium text-zinc-700">{preset.title}</div>
              <div className="mt-1 flex flex-wrap gap-1">
                {preset.options.map((opt) => (
                  <span key={opt} className="rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] text-zinc-500">
                    {opt}
                  </span>
                ))}
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-testid="quick-reply-push"
                onClick={() => {
                  onSend(buildQuickRepliesCard(preset));
                  onClose();
                }}
                className="mt-2 h-7 cursor-pointer text-[11px]"
              >
                推送该选项卡
              </Button>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
