"use client";

import type React from "react";
import { useState } from "react";
import type { ThirdPartyOrder } from "types";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Input,
  Button,
  Badge,
} from "ui";

interface OrdersListModalProps {
  isOpen: boolean;
  onClose: () => void;
  orders: ThirdPartyOrder[];
  loading: boolean;
  onSelectOrder: (order: ThirdPartyOrder) => void;
  onOpenLogistics: (order: ThirdPartyOrder) => void;
  onOpenChatWithOrder: (orderId: string) => void;
  onFilterStatus: (status: string) => void;
  currentStatus: string;
}

export const OrdersListModal: React.FC<OrdersListModalProps> = ({
  isOpen,
  onClose,
  orders,
  loading,
  onSelectOrder,
  onOpenLogistics,
  onOpenChatWithOrder,
  onFilterStatus,
  currentStatus,
}) => {
  const [searchKeyword, setSearchKeyword] = useState("");

  const tabs = [
    { key: "ALL", label: "全部订单" },
    { key: "PAID", label: "待发货" },
    { key: "SHIPPED", label: "已发货" },
    { key: "DELIVERED", label: "已完成" },
    { key: "REFUNDED", label: "已退款" },
  ];

  const filteredOrders = orders.filter((o) => {
    if (!searchKeyword.trim()) return true;
    const kw = searchKeyword.toLowerCase();
    return (
      o.orderId.toLowerCase().includes(kw) ||
      o.items.some(
        (item) =>
          item.title.toLowerCase().includes(kw) ||
          (item.specSummary && item.specSummary.toLowerCase().includes(kw)),
      )
    );
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "PAID":
        return {
          label: "待发货",
          color: "bg-blue-100 text-blue-800 border-blue-200",
        };
      case "SHIPPED":
        return {
          label: "已发货",
          color: "bg-emerald-100 text-emerald-800 border-emerald-200",
        };
      case "DELIVERED":
        return {
          label: "已完成",
          color: "bg-slate-100 text-slate-800 border-slate-200",
        };
      case "REFUNDED":
        return {
          label: "已退款",
          color: "bg-purple-100 text-purple-800 border-purple-200",
        };
      default:
        return {
          label: status,
          color: "bg-slate-100 text-slate-800 border-slate-200",
        };
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl p-6 max-h-[90vh] flex flex-col">
        {/* Header */}
        <DialogHeader className="pb-3 border-b border-slate-200">
          <DialogTitle className="flex items-center space-x-2 text-base font-bold text-slate-900">
            <span className="text-xl">📋</span>
            <div>
              <div className="text-base font-bold text-slate-900">
                我的订单中心
              </div>
              <p className="text-xs font-normal text-slate-500">
                顾客账户: CUST-8801 (张伟)
              </p>
            </div>
          </DialogTitle>
        </DialogHeader>

        {/* 状态分类 Tabs 与 搜索栏 */}
        <div className="pt-2 space-y-3">
          <div className="flex border-b border-slate-200 space-x-2 overflow-x-auto">
            {tabs.map((tab) => {
              const active = currentStatus === tab.key;
              return (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => onFilterStatus(tab.key)}
                  className={`px-3 py-2 text-xs font-semibold whitespace-nowrap border-b-2 transition cursor-pointer ${
                    active
                      ? "border-emerald-600 text-emerald-700"
                      : "border-transparent text-slate-500 hover:text-slate-800"
                  }`}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>

          <div className="relative">
            <Input
              type="text"
              value={searchKeyword}
              onChange={(e) => setSearchKeyword(e.target.value)}
              placeholder="输入订单编号或商品名称快速搜索..."
              className="text-xs pl-8 bg-slate-50 focus:bg-white h-9"
            />
            <span className="absolute left-2.5 top-2.5 text-slate-400 text-xs">
              🔍
            </span>
          </div>
        </div>

        {/* 订单卡片列表 */}
        <div className="flex-1 overflow-y-auto py-2 space-y-3.5 pr-1">
          {loading ? (
            <div className="py-16 text-center text-slate-400 text-xs">
              正在加载订单列表...
            </div>
          ) : filteredOrders.length === 0 ? (
            <div className="py-16 text-center text-slate-400">
              <div className="text-4xl mb-2">📦</div>
              <p className="text-xs font-medium text-slate-600">
                暂无相关订单记录
              </p>
            </div>
          ) : (
            filteredOrders.map((order) => {
              const badge = getStatusBadge(order.status);
              const itemsCount = order.items.reduce(
                (s, i) => s + i.quantity,
                0,
              );

              return (
                <div
                  key={order.orderId}
                  className="bg-white border border-slate-200 rounded-xl p-4 shadow-2xs hover:border-emerald-300 transition space-y-3"
                >
                  {/* 订单 Header */}
                  <div className="flex items-center justify-between text-xs pb-2.5 border-b border-slate-100">
                    <div className="flex items-center space-x-2">
                      <span className="font-mono font-bold text-slate-900">
                        {order.orderId}
                      </span>
                      <span className="text-[11px] text-slate-400">
                        {new Date(order.createdAt).toLocaleDateString()}
                      </span>
                    </div>

                    <Badge
                      variant="outline"
                      className={`text-[11px] font-bold ${badge.color}`}
                    >
                      {badge.label}
                    </Badge>
                  </div>

                  {/* 商品列表 */}
                  <div className="space-y-2">
                    {order.items.map((item, idx) => (
                      <div
                        key={(item.skuId || item.title || "") + idx}
                        className="flex items-center gap-3"
                      >
                        {item.imageUrl ? (
                          <img
                            src={item.imageUrl}
                            alt={item.title}
                            className="w-12 h-12 object-cover rounded-lg border border-slate-200 bg-slate-50 shrink-0"
                          />
                        ) : (
                          <div className="w-12 h-12 bg-slate-100 rounded-lg flex items-center justify-center text-lg shrink-0">
                            👕
                          </div>
                        )}

                        <div className="flex-1 min-w-0">
                          <h4 className="text-xs font-semibold text-slate-900 truncate">
                            {item.title}
                          </h4>
                          {item.specSummary && (
                            <p className="text-[11px] text-slate-500 truncate">
                              {item.specSummary}
                            </p>
                          )}
                        </div>

                        <div className="text-right shrink-0 text-xs">
                          <div className="font-bold text-slate-900">
                            ¥{Number(item.price).toFixed(2)}
                          </div>
                          <div className="text-[11px] text-slate-400">
                            × {item.quantity}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* 底部结算与动作栏 */}
                  <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-xs">
                    <div className="text-slate-500">
                      共{" "}
                      <strong className="text-slate-800">{itemsCount}</strong>{" "}
                      件，实付：
                      <strong className="text-emerald-700 text-sm font-extrabold ml-1">
                        ¥{Number(order.totalAmount).toFixed(2)}
                      </strong>
                    </div>

                    <div className="flex items-center space-x-2">
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() => {
                          onClose();
                          onSelectOrder(order);
                        }}
                        className="text-xs h-7 px-2.5 font-medium text-slate-700 hover:text-slate-900 bg-slate-100 hover:bg-slate-200"
                      >
                        详情
                      </Button>

                      {order.status === "SHIPPED" && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            onClose();
                            onOpenLogistics(order);
                          }}
                          className="text-xs h-7 px-2.5 font-semibold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border-emerald-200"
                        >
                          物流
                        </Button>
                      )}

                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          onClose();
                          onOpenChatWithOrder(order.orderId);
                        }}
                        className="text-xs h-7 px-2.5 font-medium text-slate-600 hover:text-emerald-700 hover:bg-slate-50 border-slate-200"
                      >
                        客服
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};
