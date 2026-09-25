import { setSelectionKind } from '@/lib/page-context';
import React from 'react';
import {
  ApprovalContextDrawer,
  ApprovalRiskBadge,
  Badge,
  Button,
  CheckCircle2,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  RichCardRenderer,
  ShieldAlert,
  Textarea,
} from 'ui';
import { useWorkbench } from '../workbench';

export function OrdersTab() {
  const {
    filteredOrders,
    orderSearchQuery,
    orderStatusFilter,
    orders,
    paidOrdersCount,
    refundedOrdersCount,
    selectedOrderIds,
    setOrderSearchQuery,
    setOrderStatusFilter,
    setSelectedOrderIds,
    setShippingOrderId,
    setTrackingNumberInput,
    shippedOrdersCount,
    toggleOrderSelection,
  } = useWorkbench();
  return (
    <>
      <div className="bg-white rounded-b-xl border border-slate-200 shadow-2xs overflow-hidden space-y-0">
        {/* 订单筛选与搜索工具条 */}
        <div className="p-4 border-b border-slate-100 bg-slate-50/70 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex bg-slate-200/80 p-0.5 rounded-lg text-xs font-semibold">
              {[
                { key: 'ALL', label: '全部订单', count: orders.length },
                { key: 'PAID', label: '待发货', count: paidOrdersCount },
                {
                  key: 'SHIPPED',
                  label: '已发货',
                  count: shippedOrdersCount,
                },
                {
                  key: 'REFUNDED',
                  label: '已退款',
                  count: refundedOrdersCount,
                },
              ].map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setOrderStatusFilter(tab.key)}
                  className={`px-3 py-1 rounded-md transition cursor-pointer flex items-center gap-1.5 ${
                    orderStatusFilter === tab.key
                      ? 'bg-white text-slate-900 shadow-xs font-bold'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  <span>{tab.label}</span>
                  <span className="text-[10px] text-slate-400">({tab.count})</span>
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Input
              type="text"
              placeholder="搜索订单号 / 顾客 / 收货人 / 手机..."
              value={orderSearchQuery}
              onChange={(e) => setOrderSearchQuery(e.target.value)}
              className="text-xs h-8 w-64 bg-white"
            />
          </div>
        </div>

        {selectedOrderIds.length > 0 && (
          <div className="sticky bottom-3 z-10 mx-auto w-fit flex items-center gap-3 rounded-full bg-slate-900 px-4 py-2 text-xs text-white shadow-lg">
            <span>已选 {selectedOrderIds.length} 笔订单</span>
            <button
              type="button"
              className="rounded-full bg-white px-3 py-1 font-semibold text-slate-900"
              // 就地唤起悬浮助手并自动提问(勾选经 PageContext 上行,不跳页)
              onClick={() =>
                window.dispatchEvent(
                  new CustomEvent('merchant-admin:open-agent', {
                    detail: { question: '两个订单对比' },
                  }),
                )
              }
            >
              向 AI 提问 →
            </button>
          </div>
        )}
        {filteredOrders.length === 0 ? (
          <div className="p-12 text-center space-y-2">
            <div className="text-3xl">📦</div>
            <h4 className="text-sm font-bold text-slate-800">暂无符合条件的订单记录</h4>
            <p className="text-xs text-slate-400">可调整筛选状态或清空搜索关键词后重试。</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 uppercase font-semibold">
                <tr>
                  <th className="p-3.5 w-8">
                    <input
                      type="checkbox"
                      aria-label="全选本页订单"
                      checked={selectedOrderIds.length > 0 && selectedOrderIds.length === filteredOrders.length}
                      onChange={(e) => {
                        const next = e.target.checked ? filteredOrders.map((o) => o.order_id) : [];
                        setSelectedOrderIds(next);
                        // PageContext 内存广播(§1.3 严禁 localStorage:残留勾选静默污染查询)
                        setSelectionKind('order', next);
                      }}
                    />
                  </th>
                  <th className="p-3.5">订单流水号</th>
                  <th className="p-3.5">顾客 ID</th>
                  <th className="p-3.5">订单状态</th>
                  <th className="p-3.5">实付金额</th>
                  <th className="p-3.5">收货人 & 联系方式</th>
                  <th className="p-3.5">配送收货地址</th>
                  <th className="p-3.5">物流单号</th>
                  <th className="p-3.5 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {filteredOrders.map((o) => (
                  <tr
                    key={o.order_id}
                    className={`hover:bg-slate-50/80 transition ${selectedOrderIds.includes(o.order_id) ? 'bg-blue-50/60' : ''}`}
                  >
                    <td className="p-3.5">
                      <input
                        type="checkbox"
                        aria-label={`选择订单 ${o.order_id}`}
                        checked={selectedOrderIds.includes(o.order_id)}
                        onChange={() => toggleOrderSelection(o.order_id)}
                      />
                    </td>
                    <td className="p-3.5 font-semibold text-slate-900 font-mono">{o.order_id}</td>
                    <td className="p-3.5 text-slate-500">{o.customer_id}</td>
                    <td className="p-3.5">
                      <Badge
                        variant="outline"
                        className={
                          o.status === 'PAID'
                            ? 'bg-amber-100 text-amber-800 border-amber-200 font-bold'
                            : o.status === 'SHIPPED'
                              ? 'bg-blue-100 text-blue-800 border-blue-200 font-bold'
                              : o.status === 'REFUNDED'
                                ? 'bg-purple-100 text-purple-800 border-purple-200 font-bold'
                                : o.status === 'DELIVERED'
                                  ? 'bg-emerald-100 text-emerald-800 border-emerald-200 font-bold'
                                  : 'bg-slate-100 text-slate-800 border-slate-200 font-bold'
                        }
                      >
                        {o.status === 'PAID' && '待发货'}
                        {o.status === 'SHIPPED' && '已发货'}
                        {o.status === 'REFUNDED' && '已退款'}
                        {o.status === 'DELIVERED' && '已签收'}
                        {!['PAID', 'SHIPPED', 'REFUNDED', 'DELIVERED'].includes(o.status) && o.status}
                      </Badge>
                    </td>
                    <td className="p-3.5 font-bold text-slate-900">¥{Number(o.total_amount).toFixed(2)}</td>
                    <td className="p-3.5">
                      <div className="font-medium text-slate-800">{o.shipping_address?.recipientName || '张伟'}</div>
                      <div className="text-[11px] text-slate-400">{o.shipping_address?.phone || '13800138000'}</div>
                    </td>
                    <td className="p-3.5 max-w-xs">
                      <span className="text-slate-800 line-clamp-2" title={o.shipping_address?.fullAddress}>
                        {o.shipping_address?.fullAddress}
                      </span>
                    </td>
                    <td className="p-3.5">
                      {o.tracking_info ? (
                        <span className="text-blue-600 font-mono text-[11px]">
                          {o.tracking_info.carrier} {o.tracking_info.trackingNumber}
                        </span>
                      ) : (
                        <span className="text-slate-400 italic">未发货</span>
                      )}
                    </td>
                    <td className="p-3.5 text-right">
                      {o.status === 'PAID' ? (
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => {
                            setShippingOrderId(o.order_id);
                            setTrackingNumberInput(`SF${Math.floor(10000000000 + Math.random() * 90000000000)}`);
                          }}
                          className="bg-blue-600 text-white hover:bg-blue-500 h-7 text-xs font-semibold cursor-pointer"
                        >
                          一键发货
                        </Button>
                      ) : (
                        <span className="text-slate-400 text-[11px]">
                          {o.status === 'SHIPPED' ? '运输中' : '已归档'}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
