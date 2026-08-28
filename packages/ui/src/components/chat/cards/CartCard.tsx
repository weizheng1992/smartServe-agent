"use client";

import type React from "react";
import type { CartCardData } from "types";
import { ArrowRight, CheckCircle2, ShoppingCart, Trash2 } from "../../icons";

export interface CartCardProps {
  data: CartCardData;
  onAction?: (action: string, payload?: Record<string, unknown>) => void;
}

function formatAmount(val: unknown): string {
  if (typeof val === "number") return val.toFixed(2);
  if (typeof val === "string") {
    const num = Number.parseFloat(val.replace(/[^0-9.-]/g, ""));
    return Number.isNaN(num) ? "0.00" : num.toFixed(2);
  }
  return "0.00";
}

export const CartCard: React.FC<CartCardProps> = ({ data, onAction }) => {
  const items = data.items || [];
  const currencySymbol = data.currency === "USD" ? "$" : "¥";

  const defaultActions = [
    {
      label: "去结算",
      action: "checkout_cart",
      icon: "arrow",
      variant: "primary" as const,
    },
    {
      label: "查看购物车",
      action: "view_cart",
      icon: "cart",
      variant: "secondary" as const,
    },
  ];

  const effectiveActions =
    data.actions && data.actions.length > 0 ? data.actions : defaultActions;

  return (
    <div className="my-2 max-w-md overflow-hidden rounded-xl border border-emerald-800/40 bg-gradient-to-b from-slate-900 via-slate-850 to-slate-900 p-4 text-slate-100 shadow-xl backdrop-blur-md transition-all hover:border-emerald-600/60">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-750/70 pb-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400">
            <ShoppingCart className="h-4 w-4" />
          </div>
          <div>
            <span className="text-xs font-semibold tracking-wider text-slate-400">
              {data.actionType === "added"
                ? "已成功加入购物车"
                : "购物车商品清单"}
            </span>
            <div className="text-sm font-bold text-emerald-300">
              {data.title ||
                `共 ${data.totalQuantity || items.reduce((s, i) => s + (i.quantity || 1), 0)} 件商品`}
            </div>
          </div>
        </div>
        <span className="inline-flex items-center rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-400 ring-1 ring-inset ring-emerald-500/20">
          {data.actionType === "checkout" ? "待结算" : "购物车"}
        </span>
      </div>

      {/* Items List */}
      <div className="my-3 space-y-2.5">
        {items.map((item, idx) => (
          <div
            key={item.skuId || item.skuCode || `cart_it_${idx}`}
            className="flex items-center justify-between rounded-lg bg-slate-800/50 p-2.5 border border-slate-700/40"
          >
            <div className="flex items-center gap-2.5 min-w-0 flex-1">
              {item.imageUrl && (
                <img
                  src={item.imageUrl}
                  alt={item.title}
                  className="h-10 w-10 rounded-md object-cover border border-slate-700 shrink-0"
                />
              )}
              <div className="min-w-0 flex-1">
                <div className="text-xs font-semibold text-slate-200 truncate">
                  {item.title}
                </div>
                {item.specSummary && (
                  <div className="text-[11px] text-slate-400 truncate">
                    规格: {item.specSummary}
                  </div>
                )}
                <div className="text-[11px] text-slate-400">
                  数量:{" "}
                  <span className="text-slate-200 font-semibold">
                    {item.quantity}
                  </span>
                </div>
              </div>
            </div>
            <div className="font-mono text-xs font-bold text-emerald-400 ml-3 shrink-0">
              {currencySymbol}
              {formatAmount(item.price * item.quantity)}
            </div>
          </div>
        ))}
      </div>

      {/* Details & Total */}
      <div className="my-3 flex items-center justify-between border-t border-slate-800/70 pt-2 text-xs text-slate-300">
        <span className="text-slate-400">
          商品总计 (
          {data.totalQuantity ||
            items.reduce((s, i) => s + (i.quantity || 1), 0)}{" "}
          件):
        </span>
        <span className="font-mono text-base font-extrabold text-emerald-300">
          {currencySymbol}
          {formatAmount(data.totalAmount)}
        </span>
      </div>

      {/* Action Buttons */}
      <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-750/70 pt-3">
        {effectiveActions.map((btn, idx) => {
          const isPrimary =
            btn.action === "checkout_cart" ||
            btn.action === "go_to_checkout" ||
            idx === 0;
          return (
            <button
              key={idx}
              type="button"
              onClick={() =>
                onAction?.(
                  btn.action,
                  ("payload" in btn ? (btn as any).payload : undefined) || {
                    cartData: data,
                  },
                )
              }
              className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                isPrimary
                  ? "bg-emerald-600 text-white hover:bg-emerald-500 shadow-sm"
                  : "bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-700"
              }`}
            >
              {isPrimary ? (
                <ArrowRight className="h-3.5 w-3.5" />
              ) : (
                <ShoppingCart className="h-3.5 w-3.5" />
              )}
              {btn.label}
            </button>
          );
        })}
      </div>
    </div>
  );
};
