'use client';

import type React from 'react';
import type { ThirdPartyOrder } from 'types';

interface OrderDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  order: ThirdPartyOrder | null;
  onOpenLogistics: (order: ThirdPartyOrder) => void;
  onOpenChatWithOrder: (orderId: string, initialPrompt?: string) => void;
}

export const OrderDetailModal: React.FC<OrderDetailModalProps> = ({
  isOpen,
  onClose,
  order,
  onOpenLogistics,
  onOpenChatWithOrder,
}) => {
  if (!isOpen || !order) return null;

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
  const totalAmount = Number(order.totalAmount || 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* 遮罩 */}
      <div
        className="fixed inset-0 bg-slate-900/60 backdrop-blur-xs transition-opacity cursor-pointer"
        onClick={onClose}
      />

      <div className="relative bg-white rounded-2xl max-w-xl w-full p-6 shadow-2xl z-10 max-h-[90vh] flex flex-col">
        {/* 顶部 Header */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-200">
          <div className="flex items-center space-x-2">
            <span className="text-xl">📄</span>
            <div>
              <h3 className="text-base font-bold text-slate-900">订单详情快照</h3>
              <p className="text-xs text-slate-500 font-mono">订单号: {order.orderId}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* 主体滚动区 */}
        <div className="flex-1 overflow-y-auto py-4 space-y-4 pr-1">
          {/* 状态看板 */}
          <div className="bg-slate-50 rounded-xl p-4 border border-slate-200 flex items-center justify-between">
            <div>
              <div className="text-xs text-slate-500">当前订单状态</div>
              <div className="flex items-center space-x-2 mt-1">
                <span className={`text-xs font-bold px-2.5 py-0.5 rounded-full border ${statusBadge.color}`}>
                  {statusBadge.label}
                </span>
                {order.status === 'SHIPPED' && (
                  <span className="text-xs text-emerald-600 font-medium">顺丰速运派送中</span>
                )}
              </div>
            </div>

            <div className="text-right">
              <div className="text-xs text-slate-500">下单时间</div>
              <div className="text-xs font-mono text-slate-700 mt-1">{new Date(order.createdAt).toLocaleString()}</div>
            </div>
          </div>

          {/* 收货地址卡片 */}
          <div className="bg-white rounded-xl p-4 border border-slate-200 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-900 flex items-center space-x-1">
                <span>📍 收货地址</span>
              </span>
              {order.isAddressModifiable && (
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    onOpenChatWithOrder(order.orderId, `我想修改订单 ${order.orderId} 的收货地址`);
                  }}
                  className="text-xs text-emerald-700 hover:text-emerald-900 font-semibold bg-emerald-50 px-2.5 py-1 rounded-md border border-emerald-200"
                >
                  ⚡ AI 极速改地址
                </button>
              )}
            </div>

            <div className="text-xs text-slate-700 space-y-1">
              <div>
                <strong className="text-slate-900">{order.shippingAddress.recipientName}</strong>{' '}
                <span className="text-slate-500 font-mono ml-2">{order.shippingAddress.phone}</span>
              </div>
              <p className="text-slate-600 leading-relaxed">{order.shippingAddress.fullAddress}</p>
            </div>
          </div>

          {/* 购买商品清单快照 */}
          <div className="bg-white rounded-xl p-4 border border-slate-200 space-y-3">
            <h4 className="text-xs font-bold text-slate-900">商品清单 ({items.length})</h4>

            <div className="divide-y divide-slate-100">
              {items.map((item, idx) => (
                <div key={item.skuId + idx} className="py-2.5 flex items-start gap-3 first:pt-0 last:pb-0">
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
                    <p className="text-[11px] text-slate-500 mt-0.5">{item.specSummary || item.skuTitle}</p>
                    <div className="flex items-center justify-between mt-1.5 text-xs">
                      <span className="text-slate-500">
                        ¥{Number(item.price).toFixed(2)} × {item.quantity}
                      </span>
                      <span className="font-bold text-slate-900">
                        ¥{(Number(item.price) * item.quantity).toFixed(2)}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 费用结算看板 */}
          <div className="bg-slate-50 rounded-xl p-4 border border-slate-200 space-y-2 text-xs">
            <div className="flex justify-between text-slate-600">
              <span>商品总金额</span>
              <span>¥{totalAmount.toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-slate-600">
              <span>运费 (极光顺丰包邮)</span>
              <span className="text-emerald-600 font-semibold">¥0.00 (包邮)</span>
            </div>
            <div className="flex justify-between text-slate-600">
              <span>SVIP 会员立减</span>
              <span className="text-emerald-600">-¥0.00</span>
            </div>
            <div className="pt-2 border-t border-slate-200 flex justify-between items-center text-sm font-bold">
              <span className="text-slate-900">实付款</span>
              <span className="text-emerald-700 text-base font-extrabold">¥{totalAmount.toFixed(2)}</span>
            </div>
          </div>
        </div>

        {/* 底部快捷操作栏 */}
        <div className="pt-4 border-t border-slate-200 flex items-center justify-between gap-3">
          {order.status === 'SHIPPED' ? (
            <button
              type="button"
              onClick={() => {
                onClose();
                onOpenLogistics(order);
              }}
              className="flex-1 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-xl shadow-xs transition flex items-center justify-center space-x-1.5 cursor-pointer"
            >
              <span>🚚 查看物流轨迹</span>
            </button>
          ) : (
            <div className="text-xs text-slate-400">
              {order.status === 'REFUNDED' ? '已退款至原支付账户' : '订单正在处理中'}
            </div>
          )}

          <button
            type="button"
            onClick={() => {
              onClose();
              onOpenChatWithOrder(
                order.orderId,
                order.status === 'REFUNDED'
                  ? `查询已退款订单 ${order.orderId} 的退款明细`
                  : `针对订单 ${order.orderId} 咨询售后或规格疑问`,
              );
            }}
            className="flex-1 py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-800 text-xs font-bold rounded-xl transition flex items-center justify-center space-x-1.5 cursor-pointer"
          >
            <span>💬 咨询专属智能客服</span>
          </button>
        </div>
      </div>
    </div>
  );
};
