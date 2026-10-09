import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import { setSelectionKind } from '@/lib/page-context';
import React from 'react';
import {
  ApprovalContextDrawer,
  ApprovalRiskBadge,
  Badge,
  Button,
  CheckCircle2,
  Checkbox,
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
    openOrderDetail,
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
                <Button
                  key={tab.key}
                  type="button"
                  variant="ghost"
                  onClick={() => setOrderStatusFilter(tab.key)}
                  className={`h-auto cursor-pointer items-center gap-1.5 rounded-md px-3 py-1 text-xs transition ${
                    orderStatusFilter === tab.key
                      ? 'bg-white text-slate-900 font-bold shadow-xs hover:bg-white hover:text-slate-900'
                      : 'font-semibold text-slate-600 hover:bg-transparent hover:text-slate-900'
                  }`}
                >
                  <span>{tab.label}</span>
                  <span className="text-[10px] text-slate-400">({tab.count})</span>
                </Button>
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
            <Button
              type="button"
              className="h-auto rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-900 shadow-none hover:bg-white/90"
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
            </Button>
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
            <DenseTable className="text-left text-xs">
              <DenseTableHeader>
                <DenseTableRow className="bg-slate-50 border-b border-slate-200 text-slate-500 uppercase font-semibold hover:bg-slate-50">
                  <DenseTableHead className="w-8 p-3.5 text-xs">
                    <Checkbox
                      aria-label="全选本页订单"
                      checked={selectedOrderIds.length > 0 && selectedOrderIds.length === filteredOrders.length}
                      onCheckedChange={(v) => {
                        const next = v === true ? filteredOrders.map((o) => o.order_id) : [];
                        setSelectedOrderIds(next);
                        // PageContext 内存广播(§1.3 严禁 localStorage:残留勾选静默污染查询)
                        setSelectionKind('order', next);
                      }}
                    />
                  </DenseTableHead>
                  <DenseTableHead className="p-3.5 text-xs">订单流水号</DenseTableHead>
                  <DenseTableHead className="p-3.5 text-xs">顾客 ID</DenseTableHead>
                  <DenseTableHead className="p-3.5 text-xs">订单状态</DenseTableHead>
                  <DenseTableHead className="p-3.5 text-xs">实付金额</DenseTableHead>
                  <DenseTableHead className="p-3.5 text-xs">收货人 & 联系方式</DenseTableHead>
                  <DenseTableHead className="p-3.5 text-xs">配送收货地址</DenseTableHead>
                  <DenseTableHead className="p-3.5 text-xs">物流单号</DenseTableHead>
                  <DenseTableHead className="p-3.5 text-right text-xs">操作</DenseTableHead>
                </DenseTableRow>
              </DenseTableHeader>
              <DenseTableBody>
                {filteredOrders.map((o) => (
                  <DenseTableRow
                    key={o.order_id}
                    className={`hover:bg-slate-50/80 transition ${selectedOrderIds.includes(o.order_id) ? 'bg-blue-50/60' : ''}`}
                  >
                    <DenseTableCell className="p-3.5">
                      <Checkbox
                        aria-label={`选择订单 ${o.order_id}`}
                        checked={selectedOrderIds.includes(o.order_id)}
                        onCheckedChange={() => toggleOrderSelection(o.order_id)}
                      />
                    </DenseTableCell>
                    <DenseTableCell className="p-3.5 font-semibold text-slate-900 font-mono">
                      {o.order_id}
                    </DenseTableCell>
                    <DenseTableCell className="p-3.5 text-slate-500">{o.customer_id}</DenseTableCell>
                    <DenseTableCell className="p-3.5">
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
                    </DenseTableCell>
                    <DenseTableCell className="p-3.5 font-bold text-slate-900">
                      ¥{Number(o.total_amount).toFixed(2)}
                    </DenseTableCell>
                    <DenseTableCell className="p-3.5">
                      <div className="font-medium text-slate-800">{o.shipping_address?.recipientName || '张伟'}</div>
                      <div className="text-[11px] text-slate-400">{o.shipping_address?.phone || '13800138000'}</div>
                    </DenseTableCell>
                    <DenseTableCell className="p-3.5 max-w-xs">
                      <span className="text-slate-800 line-clamp-2" title={o.shipping_address?.fullAddress}>
                        {o.shipping_address?.fullAddress}
                      </span>
                    </DenseTableCell>
                    <DenseTableCell className="p-3.5">
                      {o.tracking_info ? (
                        <span className="text-blue-600 font-mono text-[11px]">
                          {o.tracking_info.carrier} {o.tracking_info.trackingNumber}
                        </span>
                      ) : (
                        <span className="text-slate-400 italic">未发货</span>
                      )}
                    </DenseTableCell>
                    <DenseTableCell className="p-3.5 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => openOrderDetail(o.order_id)}
                          className="h-7 cursor-pointer text-xs font-semibold"
                        >
                          详情
                        </Button>
                        {o.status === 'PAID' && (
                          <Button
                            type="button"
                            size="sm"
                            onClick={() => {
                              setShippingOrderId(o.order_id);
                              // 运单号必须商户实填:随机预填号一旦提交即成真账面
                              // 假物流(顾客按假单查件永远查无),弹窗侧空值已闸
                              setTrackingNumberInput('');
                            }}
                            className="bg-blue-600 text-white hover:bg-blue-500 h-7 text-xs font-semibold cursor-pointer"
                          >
                            一键发货
                          </Button>
                        )}
                      </div>
                    </DenseTableCell>
                  </DenseTableRow>
                ))}
              </DenseTableBody>
            </DenseTable>
          </div>
        )}
      </div>
    </>
  );
}
