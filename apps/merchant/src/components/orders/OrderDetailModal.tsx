import type React from 'react';
import type { ThirdPartyOrder } from 'types';
import { Badge, Button, Dialog, DialogContent, DialogHeader, DialogTitle } from 'ui';
import { parseShippingAddress } from '../../lib/shippingAddress';

interface OrderDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  order: ThirdPartyOrder | null;
  onOpenLogistics: (order: ThirdPartyOrder) => void;
  onOpenChatWithOrder: (orderId: string, initialPrompt?: string) => void;
}

// 发货面可选的四家承运商编码 → 展示名(ship-dialog 同款),未知编码原样透出
const CARRIER_LABEL: Record<string, string> = {
  SF: '顺丰速运',
  JD: '京东快递',
  ZTO: '中通快递',
  EMS: '邮政 EMS',
};

// 诚实呈现:缺值/坏值一律「—」,严禁 Number(null)===0 冒充 ¥0.00 / Invalid Date
const fmtMoney = (v: unknown): string => {
  const n = Number(v);
  return v != null && v !== '' && Number.isFinite(n) ? n.toFixed(2) : '—';
};
const fmtDate = (v: unknown): string => {
  if (v == null || v === '') return '—';
  const d = new Date(v as string | number);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
};
const toNum = (v: unknown): number | null => {
  const n = Number(v);
  return v != null && v !== '' && Number.isFinite(n) ? n : null;
};

export const OrderDetailModal: React.FC<OrderDetailModalProps> = ({
  isOpen,
  onClose,
  order,
  onOpenLogistics,
  onOpenChatWithOrder,
}) => {
  if (!order) return null;

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'PAID':
        return {
          label: '已付款 / 待发货',
          color: 'bg-blue-100 text-blue-800 border-blue-200',
        };
      case 'PROCESSING':
        return {
          label: '仓库配货中',
          color: 'bg-amber-100 text-amber-800 border-amber-200',
        };
      case 'SHIPPED':
        return {
          label: '已发货 / 运输中',
          color: 'bg-emerald-100 text-emerald-800 border-emerald-200',
        };
      case 'DELIVERED':
        return {
          label: '已签收完成',
          color: 'bg-slate-100 text-slate-800 border-slate-200',
        };
      case 'REFUNDED':
        return {
          label: '已全额退款',
          color: 'bg-purple-100 text-purple-800 border-purple-200',
        };
      case 'CANCELLED':
        return {
          label: '已取消',
          color: 'bg-rose-100 text-rose-800 border-rose-200',
        };
      default:
        return {
          label: status,
          color: 'bg-slate-100 text-slate-800 border-slate-200',
        };
    }
  };

  const statusBadge = getStatusBadge(order.status);
  const items = order.items || [];
  // 账本语义:totalAmount=实付,discountAmount=优惠,originalAmount=原价
  // 优惠缺值按无优惠(0)参与判定;实付缺值保持 null 供「—」呈现,严禁冒充 ¥0.00
  const totalAmount = toNum(order.totalAmount);
  const discountAmount = toNum(order.discountAmount) ?? 0;
  const originalAmount = toNum(order.originalAmount) ?? (totalAmount != null ? totalAmount + discountAmount : null);

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-xl p-6 max-h-[90vh] flex flex-col">
        {/* 顶部 Header */}
        <DialogHeader className="pb-3 border-b border-slate-200">
          <DialogTitle className="flex items-center space-x-2 text-base font-bold text-slate-900">
            <span className="text-xl">📄</span>
            <div>
              <div className="text-base font-bold text-slate-900">订单详情快照</div>
              <p className="text-xs font-normal text-slate-500 font-mono">订单号: {order.orderId}</p>
            </div>
          </DialogTitle>
        </DialogHeader>

        {/* 主体滚动区 */}
        <div className="flex-1 overflow-y-auto py-2 space-y-4 pr-1">
          {/* 状态看板 */}
          <div className="bg-slate-50 rounded-xl p-4 border border-slate-200 flex items-center justify-between">
            <div>
              <div className="text-xs text-slate-500">当前订单状态</div>
              <div className="flex items-center space-x-2 mt-1">
                <Badge variant="outline" className={`text-xs font-bold ${statusBadge.color}`}>
                  {statusBadge.label}
                </Badge>
                {order.status === 'SHIPPED' && (
                  <span className="text-xs text-emerald-600 font-medium">
                    {/* 承运商如实显示(已知编码译名,未知编码原样),不再硬编码顺丰 */}
                    {order.tracking?.carrier
                      ? `${CARRIER_LABEL[order.tracking.carrier] || order.tracking.carrier} 派送中`
                      : '已发货,物流信息待承运商更新'}
                  </span>
                )}
              </div>
            </div>

            <div className="text-right">
              <div className="text-xs text-slate-500">下单时间</div>
              <div className="text-xs font-mono text-slate-700 mt-1">{fmtDate(order.createdAt)}</div>
            </div>
          </div>

          {/* 收货地址卡片 */}
          <div className="bg-white rounded-xl p-4 border border-slate-200 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-900 flex items-center space-x-1">
                <span>📍 收货地址</span>
              </span>
              {order.isAddressModifiable && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    onClose();
                    onOpenChatWithOrder(order.orderId, `我想修改订单 ${order.orderId} 的收货地址`);
                  }}
                  className="text-xs text-emerald-700 hover:text-emerald-900 font-semibold bg-emerald-50 border-emerald-200 h-7"
                >
                  ⚡ AI 极速改地址
                </Button>
              )}
            </div>

            {(() => {
              const addrInfo = parseShippingAddress(order.shippingAddress);
              return (
                <div className="text-xs text-slate-700 space-y-1">
                  <div>
                    <strong className="text-slate-900">{addrInfo.recipientName}</strong>{' '}
                    <span className="text-slate-500 font-mono ml-2">{addrInfo.phone}</span>
                  </div>
                  <p className="text-slate-600 leading-relaxed">{addrInfo.fullAddress}</p>
                </div>
              );
            })()}
          </div>

          {/* 购买商品清单快照 */}
          <div className="bg-white rounded-xl p-4 border border-slate-200 space-y-3">
            <h4 className="text-xs font-bold text-slate-900">商品清单 ({items.length})</h4>

            <div className="divide-y divide-slate-100">
              {items.map((item, idx) => {
                const itemPrice = toNum(item.price);
                const itemQty = toNum(item.quantity);
                return (
                  <div
                    key={item.skuId || item.title || item.imageUrl}
                    className="py-2.5 flex items-start gap-3 first:pt-0 last:pb-0"
                  >
                    {item.imageUrl ? (
                      <img
                        src={item.imageUrl}
                        alt={item.title}
                        className="w-14 h-14 object-cover rounded-lg border border-slate-200 shrink-0 bg-slate-50"
                      />
                    ) : (
                      <div className="w-14 h-14 bg-slate-100 rounded-lg flex items-center justify-center text-xl shrink-0">
                        📦
                      </div>
                    )}

                    <div className="flex-1 min-w-0">
                      <h5 className="text-xs font-bold text-slate-900 truncate">{item.title}</h5>
                      {item.specSummary && <p className="text-[11px] text-slate-500 mt-0.5">{item.specSummary}</p>}
                      <div className="flex items-center justify-between mt-1.5 text-xs">
                        <span className="text-slate-500">
                          ¥{fmtMoney(item.price)} × {itemQty ?? '—'}
                        </span>
                        <span className="font-bold text-slate-900">
                          {itemPrice != null && itemQty != null ? `¥${(itemPrice * itemQty).toFixed(2)}` : '—'}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 费用结算看板 */}
          <div className="bg-slate-50 rounded-xl p-4 border border-slate-200 space-y-2 text-xs">
            <div className="flex justify-between text-slate-600">
              <span>商品总金额</span>
              <span>{originalAmount != null ? `¥${originalAmount.toFixed(2)}` : '—'}</span>
            </div>
            <div className="flex justify-between text-slate-600">
              <span>运费 (极光顺丰包邮)</span>
              <span className="text-emerald-600 font-semibold">¥0.00 (包邮)</span>
            </div>
            {discountAmount > 0 && (
              <div className="flex justify-between font-medium text-rose-600">
                <span>优惠抵扣（活动/优惠券）</span>
                <span>-¥{discountAmount.toFixed(2)}</span>
              </div>
            )}
            <div className="pt-2 border-t border-slate-200 flex justify-between items-center text-sm font-bold">
              <span className="text-slate-900">实付款</span>
              <span className="text-emerald-700 text-base font-extrabold">¥{fmtMoney(order.totalAmount)}</span>
            </div>
          </div>
        </div>

        {/* 底部快捷操作栏 */}
        <div className="pt-3 border-t border-slate-200 flex items-center justify-between gap-3">
          {order.status === 'SHIPPED' ? (
            <Button
              type="button"
              onClick={() => {
                onClose();
                onOpenLogistics(order);
              }}
              className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold"
            >
              <span>🚚 查看物流轨迹</span>
            </Button>
          ) : (
            <div className="text-xs text-slate-400">
              {order.status === 'REFUNDED' ? '已退款至原支付账户' : '订单正在处理中'}
            </div>
          )}

          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              onClose();
              onOpenChatWithOrder(
                order.orderId,
                order.status === 'REFUNDED'
                  ? `查询已退款订单 ${order.orderId} 的退款明细`
                  : `针对订单 ${order.orderId} 咨询售后或规格疑问`,
              );
            }}
            className="flex-1 bg-slate-100 hover:bg-slate-200 text-slate-800 text-xs font-bold"
          >
            <span>💬 咨询专属智能客服</span>
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};
