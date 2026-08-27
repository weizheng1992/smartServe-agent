'use client';

import React, { useState } from 'react';
import type { OrderCardData, OrderPickerCardData } from 'types';
import { ArrowRight, CheckCircle2, Package, Sparkles, Truck, X } from '../../icons';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '../../ui/dialog';

export interface OrderPickerCardProps {
  data: OrderPickerCardData;
  onAction?: (action: string, payload?: Record<string, unknown>) => void;
}

export const OrderPickerCard: React.FC<OrderPickerCardProps> = ({ data, onAction }) => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const orders = data.orders || [];
  const totalCount = data.totalCount || orders.length;

  const handleSelectOrder = (order: OrderCardData) => {
    setIsModalOpen(false);
    onAction?.('select_order', {
      orderId: order.orderId,
      order,
    });
  };

  return (
    <>
      {/* 订单列表选择入口卡片 */}
      <div className="my-2.5 max-w-md overflow-hidden rounded-xl border border-indigo-500/30 bg-gradient-to-b from-indigo-950/40 to-slate-900/90 p-4 text-slate-100 shadow-xl backdrop-blur-md transition-all hover:border-indigo-400/50">
        <div className="flex items-center justify-between border-b border-indigo-500/20 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/20 text-indigo-300">
              <Package className="h-4 w-4" />
            </div>
            <div>
              <div className="flex items-center gap-1.5 text-xs font-semibold text-indigo-200">
                <Sparkles className="h-3 w-3 text-amber-400" />
                <span>{data.title || `为您查询到 ${totalCount} 笔订单记录`}</span>
              </div>
              <div className="text-[11px] text-slate-400">请点击打开列表选择需要处理的订单</div>
            </div>
          </div>
          <span className="rounded-full bg-indigo-500/20 px-2.5 py-0.5 text-xs font-mono font-medium text-indigo-300">
            {totalCount} 笔
          </span>
        </div>

        {/* 订单简要列表预览 (展示前 2 笔预览) */}
        <div className="my-3 space-y-1.5">
          {orders.slice(0, 2).map((ord, idx) => (
            <div
              key={ord.orderId || idx}
              onClick={() => handleSelectOrder(ord)}
              className="flex items-center justify-between rounded-lg border border-slate-750/70 bg-slate-800/60 p-2.5 text-xs transition-colors hover:border-indigo-500/40 hover:bg-slate-800 cursor-pointer group"
            >
              <div className="flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-700 text-[10px] font-mono text-slate-300">
                  {idx + 1}
                </span>
                <span className="font-mono font-medium text-slate-200 group-hover:text-indigo-300">{ord.orderId}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-emerald-400 font-medium">
                  {ord.currency === 'USD' ? '$' : '¥'}
                  {ord.totalAmount?.toFixed(2) || '0.00'}
                </span>
                <span className="rounded bg-slate-700/60 px-1.5 py-0.5 text-[10px] text-slate-300">{ord.status}</span>
              </div>
            </div>
          ))}
          {orders.length > 2 && (
            <div className="text-center text-[10px] text-slate-400 pt-0.5">... 还有 {orders.length - 2} 笔订单</div>
          )}
        </div>

        {/* 触发弹窗主按钮 */}
        <button
          type="button"
          onClick={() => setIsModalOpen(true)}
          className="w-full mt-2 flex items-center justify-center gap-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 text-xs font-semibold shadow-md transition-all cursor-pointer"
        >
          <span>📋 打开订单列表并选择</span>
          <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* 订单列表选择弹窗 (Order Selection Dialog) */}
      <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
        <DialogContent className="max-w-xl max-h-[85vh] bg-slate-900 border-slate-800 text-slate-100 p-0 flex flex-col">
          <DialogHeader className="p-4 sm:p-5 border-b border-slate-800 flex flex-row items-center justify-between">
            <div>
              <DialogTitle className="text-base font-bold text-slate-100 flex items-center gap-2">
                <Package className="h-5 w-5 text-indigo-400" />
                <span>选择需要办理的订单</span>
                <span className="text-xs font-normal text-slate-400 font-mono">(共 {orders.length} 笔)</span>
              </DialogTitle>
              <DialogDescription className="text-xs text-slate-400 mt-1">
                点击对应订单后的「选择此订单」按钮，即可选中并继续查询物流或申请售后。
              </DialogDescription>
            </div>
            <button
              type="button"
              onClick={() => setIsModalOpen(false)}
              className="p-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition cursor-pointer"
            >
              <X className="h-5 w-5" />
            </button>
          </DialogHeader>

          {/* 订单列表滚动区 */}
          <div className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-3">
            {orders.map((ord, idx) => {
              const isPaid = ord.status === 'PAID' || ord.status === '已付款';
              const isShipped = ord.status === 'SHIPPED' || ord.status === '已发货';

              return (
                <div
                  key={ord.orderId || idx}
                  className="rounded-xl border border-slate-800 bg-slate-850/80 p-4 transition-all hover:border-indigo-500/50 hover:bg-slate-800/90 shadow-md flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                >
                  <div className="space-y-1.5 flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-bold text-indigo-300 truncate">{ord.orderId}</span>
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
                          isShipped
                            ? 'bg-blue-500/10 text-blue-400 ring-1 ring-inset ring-blue-500/20'
                            : isPaid
                              ? 'bg-emerald-500/10 text-emerald-400 ring-1 ring-inset ring-emerald-500/20'
                              : 'bg-slate-700/40 text-slate-300 ring-1 ring-inset ring-slate-700/50'
                        }`}
                      >
                        {ord.status}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-400">
                      <div>
                        <span>订单金额：</span>
                        <span className="font-mono font-bold text-emerald-400">
                          {ord.currency === 'USD' ? '$' : '¥'}
                          {ord.totalAmount?.toFixed(2) || '0.00'}
                        </span>
                      </div>
                      <div>
                        <span>承运商：</span>
                        <span className="text-slate-300">{ord.carrier || '顺丰速运'}</span>
                      </div>
                      {ord.trackingNumber && (
                        <div className="col-span-2 flex items-center gap-1 text-[11px]">
                          <Truck className="h-3 w-3 text-slate-400 shrink-0" />
                          <span className="text-slate-400">运单号：</span>
                          <span className="font-mono text-slate-300">{ord.trackingNumber}</span>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center sm:self-center shrink-0">
                    <button
                      type="button"
                      onClick={() => handleSelectOrder(ord)}
                      className="w-full sm:w-auto flex items-center justify-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white px-3.5 py-2 text-xs font-semibold shadow transition-all cursor-pointer"
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      <span>选择此订单</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
};
