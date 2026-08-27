"use client";

import type React from "react";
import type { OrderCardData } from "types";
import {
  ArrowRight,
  CheckCircle2,
  Package,
  ShieldCheck,
  Truck,
} from "../../icons";

export interface OrderCardProps {
  data: OrderCardData;
  onAction?: (action: string, payload?: Record<string, unknown>) => void;
}

export const OrderCard: React.FC<OrderCardProps> = ({ data, onAction }) => {
  return (
    <div className="my-2 max-w-md overflow-hidden rounded-xl border border-slate-700/60 bg-gradient-to-b from-slate-850 to-slate-900/90 p-4 text-slate-100 shadow-xl backdrop-blur-md transition-all hover:border-slate-600">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-750/70 pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400">
            <Package className="h-4 w-4" />
          </div>
          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              订单编号
            </span>
            <div className="font-mono text-sm font-bold text-indigo-300">
              {data.orderId}
            </div>
          </div>
        </div>
        <span className="inline-flex items-center rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-400 ring-1 ring-inset ring-emerald-500/20">
          {data.status}
        </span>
      </div>

      {/* Details */}
      <div className="my-3 space-y-2 text-xs">
        <div className="flex justify-between text-slate-300">
          <span className="text-slate-400">承运商 & 运单:</span>
          <span className="font-mono text-slate-200">
            {data.carrier || "SF Express"} ({data.trackingNumber || "N/A"})
          </span>
        </div>
        <div className="flex justify-between text-slate-300">
          <span className="text-slate-400">订单总金额:</span>
          <span className="font-mono text-sm font-semibold text-emerald-300">
            {data.currency === "USD" ? "$" : "¥"}
            {data.totalAmount.toFixed(2)}
          </span>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="mt-3.5 flex flex-wrap gap-2 border-t border-slate-750/70 pt-3">
        <button
          type="button"
          onClick={() => onAction?.("select_order", { orderId: data.orderId })}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-600/20 px-2.5 py-1.5 text-xs font-medium text-emerald-300 transition-colors hover:bg-emerald-600/30 hover:text-emerald-200 cursor-pointer"
        >
          <CheckCircle2 className="h-3.5 w-3.5" />
          选择此订单
        </button>
        <button
          type="button"
          onClick={() => onAction?.("track_order", { orderId: data.orderId })}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-indigo-600/20 px-2.5 py-1.5 text-xs font-medium text-indigo-300 transition-colors hover:bg-indigo-600/30 hover:text-indigo-200 cursor-pointer"
        >
          <Truck className="h-3.5 w-3.5" />
          查看物流
        </button>
        <button
          type="button"
          onClick={() =>
            onAction?.("request_refund", { orderId: data.orderId })
          }
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-rose-500/10 px-2.5 py-1.5 text-xs font-medium text-rose-300 transition-colors hover:bg-rose-500/20 hover:text-rose-200 cursor-pointer"
        >
          <ShieldCheck className="h-3.5 w-3.5" />
          申请售后
        </button>
      </div>
    </div>
  );
};
