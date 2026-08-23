import type React from "react";
import { useEffect, useState } from "react";
import type { Approval, OrderItemSummary, UserOrderRecord } from "types";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  DollarSign,
  Layers,
  Loader2,
  MessageSquare,
  Package,
  Shield,
  ShieldAlert,
  Sparkles,
  Truck,
  User,
  X,
  XCircle,
} from "../icons";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent } from "../ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/dialog";
import { Input } from "../ui/input";
import { ScrollArea } from "../ui/scroll-area";
import { ApprovalRiskBadge } from "./ApprovalRiskBadge";
import {
  type TriggerDiagnosis,
  diagnoseApprovalTrigger,
  getApprovalContextData,
} from "./approvalUtils";

export interface UserProfileData {
  userId: string;
  email?: string;
  businessId?: string;
  vipLevel?: string;
  preferences?: Array<{
    id?: string;
    fact: string;
    confidence?: number;
    status?: string;
    category?: string;
  }>;
  episodicEvents?: Array<{
    content: string;
    timestamp?: string;
  }>;
}

export interface ChatMessageRecord {
  id: string;
  role: "user" | "assistant" | "system" | "operator" | string;
  content: string;
  timestamp: string;
}

export interface ApprovalContextDetail {
  approval: Approval;
  user?: UserProfileData;
  orders?: UserOrderRecord[];
  messages?: ChatMessageRecord[];
}

export interface ApprovalContextDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  approval: Approval | null;
  initialDetail?: ApprovalContextDetail;
  onApprove?: (approvalId: string) => Promise<void> | void;
  onReject?: (approvalId: string, reason?: string) => Promise<void> | void;
  onHumanReply?: (
    approvalId: string,
    replyMessage: string,
    isFinish?: boolean,
  ) => Promise<unknown>;
  className?: string;
}

type TabType =
  "DIAGNOSIS" | "USER_PROFILE" | "PURCHASE_HISTORY" | "CHAT_HISTORY";

export function ApprovalContextDrawer({
  isOpen,
  onClose,
  approval,
  initialDetail,
  onApprove,
  onReject,
  onHumanReply,
  className = "",
}: ApprovalContextDrawerProps) {
  const [activeTab, setActiveTab] = useState<TabType>("DIAGNOSIS");
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<ApprovalContextDetail | null>(
    initialDetail || null,
  );
  const [rejectionReason, setRejectionReason] = useState("");
  const [humanReplyText, setHumanReplyText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Sync initial detail when approval changes
  useEffect(() => {
    if (initialDetail) {
      setDetail(initialDetail);
    } else if (approval) {
      // Create a fallback baseline detail immediately from approval payload
      const ctx = getApprovalContextData(approval);
      const fallbackOrders: UserOrderRecord[] = ctx.orderId
        ? [
            {
              orderId: ctx.orderId,
              status: "shipped",
              totalAmount:
                typeof ctx.refundAmount === "number" ? ctx.refundAmount : 399.0,
              carrier: "顺丰速运",
              trackingNumber: "SF8899776655",
              createdAt:
                typeof approval.createdAt === "string"
                  ? approval.createdAt
                  : new Date().toISOString(),
              items: [
                {
                  productName: `${approval.businessId?.toUpperCase() || "品牌"} 热销精选商品`,
                  price:
                    typeof ctx.refundAmount === "number"
                      ? ctx.refundAmount
                      : 399.0,
                  quantity: 1,
                },
              ],
            },
          ]
        : [];

      const fallbackMessages: ChatMessageRecord[] = ctx.userInput
        ? [
            {
              id: "m_fallback_1",
              role: "user",
              content: ctx.userInput,
              timestamp: new Date().toLocaleTimeString(),
            },
          ]
        : [];

      const targetUserId =
        (approval as any).userId ||
        (approval as any).userEmail ||
        (approval.actionPayload?.userId as string) ||
        "user_sess_current";
      const targetUserEmail = (approval as any).userEmail || undefined;

      setDetail({
        approval,
        user: {
          userId: targetUserId,
          email: targetUserEmail,
          businessId: approval.businessId || "ecommerce",
          vipLevel: "Gold VIP",
          preferences: [
            {
              fact: `偏好 ${approval.businessId?.toUpperCase() || "商城"} 正品直邮`,
              confidence: 0.95,
              status: "approved",
            },
          ],
        },
        orders: fallbackOrders,
        messages: fallbackMessages,
      });

      // Try async fetch from API if available
      if (approval.threadId) {
        setLoading(true);
        const fetchMessages = fetch(
          `/api/chat/messages?threadId=${encodeURIComponent(approval.threadId)}`,
        )
          .then((res) => res.json())
          .catch(() => ({ success: false }));

        const fetchPreferences = targetUserId
          ? fetch(
              `/api/chat/preferences?userId=${encodeURIComponent(targetUserId)}`,
            )
              .then((res) => res.json())
              .catch(() => ({ success: false }))
          : Promise.resolve({ success: false });

        const orderParams = new URLSearchParams();
        if (targetUserId) orderParams.set("userId", targetUserId);
        if (targetUserEmail) orderParams.set("userEmail", targetUserEmail);
        if (approval.threadId) orderParams.set("threadId", approval.threadId);
        if (approval.businessId)
          orderParams.set("businessId", approval.businessId);

        const fetchOrders = fetch(`/api/chat/orders?${orderParams.toString()}`)
          .then((res) => res.json())
          .catch(() => ({ success: false }));

        Promise.all([fetchMessages, fetchPreferences, fetchOrders])
          .then(([msgData, prefData, ordData]) => {
            setDetail((prev) => {
              if (!prev) return prev;
              const nextDetail = { ...prev };
              if (
                msgData.success &&
                Array.isArray(msgData.messages) &&
                msgData.messages.length > 0
              ) {
                nextDetail.messages = msgData.messages;
              }
              if (
                prefData.success &&
                Array.isArray(prefData.preferences) &&
                prefData.preferences.length > 0
              ) {
                if (nextDetail.user) {
                  nextDetail.user.preferences = prefData.preferences.map(
                    (p: any) => ({
                      id: p.id,
                      fact: p.fact,
                      confidence: p.confidence,
                      status: p.status,
                      category: p.type || "preference",
                    }),
                  );
                }
              }
              if (
                ordData.success &&
                Array.isArray(ordData.orders) &&
                ordData.orders.length > 0
              ) {
                nextDetail.orders = ordData.orders;
              }
              return nextDetail;
            });
          })
          .catch((err) => console.warn("[Drawer Fetch Error]:", err))
          .finally(() => setLoading(false));
      }
    }
  }, [approval, initialDetail]);

  if (!isOpen || !approval) return null;

  const diagnosis: TriggerDiagnosis = diagnoseApprovalTrigger(approval);
  const context = getApprovalContextData(approval);
  const targetOrderId = diagnosis.targetOrderId;

  const handleExecuteApprove = async () => {
    if (!onApprove) return;
    setIsSubmitting(true);
    try {
      await onApprove(approval.id);
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleExecuteReject = async () => {
    if (!onReject) return;
    setIsSubmitting(true);
    try {
      await onReject(approval.id, rejectionReason);
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleExecuteHumanReply = async (isFinish = false) => {
    if (!onHumanReply) return;
    const text = humanReplyText.trim() || "您好！人工客服主管已接入为您处理。";
    setIsSubmitting(true);
    try {
      await onHumanReply(approval.id, text, isFinish);
      setHumanReplyText("");
      // Optimistically append to chat messages
      setDetail((prev) =>
        prev
          ? {
              ...prev,
              messages: [
                ...(prev.messages || []),
                {
                  id: `reply_${Date.now()}`,
                  role: "operator",
                  content: text,
                  timestamp: new Date().toLocaleTimeString(),
                },
              ],
            }
          : prev,
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        className={`max-w-4xl max-h-[92vh] bg-slate-950 border border-slate-800 p-0 flex flex-col rounded-2xl shadow-2xl overflow-hidden ${className}`}
      >
        {/* 🚀 Drawer Top Header */}
        <DialogHeader className="px-6 py-4 bg-slate-900/90 border-b border-slate-800 flex flex-row items-center justify-between space-y-0 shrink-0">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-indigo-500/10 border border-indigo-500/30 rounded-xl">
              <ShieldAlert className="h-5 w-5 text-indigo-400 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <DialogTitle className="text-sm font-bold text-slate-100 font-mono tracking-tight">
                  工单排查全景看板: {approval.id.substring(0, 12)}...
                </DialogTitle>
                <Badge
                  variant="outline"
                  className="bg-indigo-950/60 border-indigo-500/40 text-indigo-300 font-mono text-[10px] uppercase"
                >
                  {approval.businessId || "ecommerce"}
                </Badge>
                <ApprovalRiskBadge
                  actionType={approval.actionType}
                  status={approval.status}
                />
              </div>
              <p className="text-[11px] text-slate-400 mt-0.5">
                Thread:{" "}
                <span className="font-mono text-slate-300">
                  {approval.threadId}
                </span>
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
          >
            <X className="h-5 w-5" />
          </button>
        </DialogHeader>

        {/* 🧭 Horizontal Navigation Tabs */}
        <div className="flex items-center gap-1 px-6 py-2 bg-slate-900/50 border-b border-slate-800/80 shrink-0 text-xs font-semibold overflow-x-auto">
          <button
            type="button"
            onClick={() => setActiveTab("DIAGNOSIS")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition ${
              activeTab === "DIAGNOSIS"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
            }`}
          >
            <AlertTriangle className="h-3.5 w-3.5" />
            <span>🎯 触发原因与风控归因</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("USER_PROFILE")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition ${
              activeTab === "USER_PROFILE"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
            }`}
          >
            <User className="h-3.5 w-3.5" />
            <span>
              👤 用户信息与画像 ({detail?.user?.preferences?.length || 0})
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("PURCHASE_HISTORY")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition ${
              activeTab === "PURCHASE_HISTORY"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
            }`}
          >
            <Package className="h-3.5 w-3.5" />
            <span>📦 购买记录与历史订单 ({detail?.orders?.length || 0})</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("CHAT_HISTORY")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition ${
              activeTab === "CHAT_HISTORY"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
            }`}
          >
            <MessageSquare className="h-3.5 w-3.5" />
            <span>💬 现场会话聊天记录 ({detail?.messages?.length || 0})</span>
          </button>
        </div>

        {/* 📄 Drawer Scrollable Content Area */}
        <ScrollArea className="flex-1 p-6 overflow-y-auto max-h-[55vh]">
          {/* 1. 🎯 TAB 1: 触发原因与风控归因 */}
          {activeTab === "DIAGNOSIS" && (
            <div className="space-y-4">
              {/* Trigger Title & Risk Banner */}
              <div
                className={`p-4 rounded-xl border flex items-start gap-3.5 ${
                  diagnosis.category === "refund"
                    ? "bg-rose-950/30 border-rose-500/40"
                    : diagnosis.category === "address"
                      ? "bg-amber-950/30 border-amber-500/40"
                      : diagnosis.category === "human"
                        ? "bg-indigo-950/30 border-indigo-500/40"
                        : "bg-slate-900 border-slate-800"
                }`}
              >
                <div className="p-2.5 rounded-lg bg-slate-950/80 border border-slate-800 shrink-0 mt-0.5">
                  {diagnosis.category === "refund" ? (
                    <DollarSign className="h-5 w-5 text-rose-400 animate-pulse" />
                  ) : diagnosis.category === "address" ? (
                    <Truck className="h-5 w-5 text-amber-400 animate-pulse" />
                  ) : (
                    <MessageSquare className="h-5 w-5 text-indigo-400 animate-pulse" />
                  )}
                </div>
                <div className="space-y-1.5 flex-1">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-bold text-slate-100">
                      {diagnosis.title}
                    </h4>
                    <Badge
                      variant="outline"
                      className="font-mono text-[10px] bg-slate-950 border-slate-700 text-slate-300"
                    >
                      Policy: {diagnosis.policyCode}
                    </Badge>
                  </div>
                  <p className="text-xs text-slate-300 leading-relaxed font-sans">
                    <strong className="text-amber-300">触发拦截原因：</strong>
                    {diagnosis.triggerCause}
                  </p>
                  <p className="text-[11px] text-slate-400 leading-relaxed font-sans pt-1 border-t border-slate-800/80">
                    <strong className="text-slate-400 font-mono">
                      风控准则：
                    </strong>
                    {diagnosis.ruleDescription}
                  </p>
                </div>
              </div>

              {/* User Original Input */}
              {context.userInput && (
                <div className="bg-slate-900/80 border border-slate-800 p-3.5 rounded-xl space-y-1">
                  <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1 font-mono">
                    <User className="h-3 w-3 text-slate-400" />{" "}
                    用户原始诉求与触发语句
                  </span>
                  <div className="text-xs text-indigo-200 font-mono bg-indigo-950/30 p-2.5 rounded-lg border border-indigo-500/20">
                    &quot;{context.userInput}&quot;
                  </div>
                </div>
              )}

              {/* Specialized Parameter Diffs */}
              {diagnosis.category === "refund" && (
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-slate-900 border border-rose-500/30 p-3.5 rounded-xl space-y-1">
                    <span className="text-[10px] text-slate-400 uppercase font-mono block">
                      拟核准退款金额
                    </span>
                    <span className="text-lg font-bold font-mono text-rose-400">
                      ¥{" "}
                      {context.refundAmount
                        ? Number(context.refundAmount).toFixed(2)
                        : "0.00"}
                    </span>
                  </div>
                  <div className="bg-slate-900 border border-slate-800 p-3.5 rounded-xl space-y-1">
                    <span className="text-[10px] text-slate-400 uppercase font-mono block">
                      关联标的订单
                    </span>
                    <span className="text-sm font-bold font-mono text-indigo-300">
                      {targetOrderId || "未提取到订单号"}
                    </span>
                  </div>
                </div>
              )}

              {diagnosis.category === "address" && (
                <div className="bg-slate-900 border border-amber-500/30 p-3.5 rounded-xl space-y-2">
                  <span className="text-[10px] font-bold text-amber-400 uppercase font-mono block">
                    配送地址变更比对
                  </span>
                  {context.oldAddress && (
                    <div className="text-xs font-mono text-slate-400 line-through bg-slate-950 p-2 rounded-lg border border-slate-850">
                      原地址: {context.oldAddress}
                    </div>
                  )}
                  {context.newAddress && (
                    <div className="text-xs font-mono text-amber-200 font-bold bg-amber-950/30 p-2.5 rounded-lg border border-amber-500/30 flex items-start gap-2">
                      <ArrowRight className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
                      <span>拟改派新地址: {context.newAddress}</span>
                    </div>
                  )}
                </div>
              )}

              {/* Raw Action Payload Table */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5 space-y-2">
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider font-mono block">
                  ACTION PAYLOAD RAW PARAMETERS
                </span>
                <div className="bg-slate-950 p-3 rounded-lg border border-slate-850 font-mono text-[11px] text-indigo-300 whitespace-pre-wrap max-h-40 overflow-y-auto">
                  {JSON.stringify(approval.actionPayload || {}, null, 2)}
                </div>
              </div>
            </div>
          )}

          {/* 2. 👤 TAB 2: 用户信息与画像 */}
          {activeTab === "USER_PROFILE" && (
            <div className="space-y-4">
              {/* User Identity Card */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <div className="p-3 bg-indigo-500/10 border border-indigo-500/30 rounded-xl">
                    <User className="h-6 w-6 text-indigo-400" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h4 className="text-sm font-bold text-slate-100 font-mono">
                        {detail?.user?.userId || "guest_user"}
                      </h4>
                      <Badge className="bg-amber-500/20 text-amber-300 border-amber-500/40 text-[10px] font-mono">
                        {detail?.user?.vipLevel || "VIP 客户"}
                      </Badge>
                    </div>
                    <p className="text-xs text-slate-400 mt-0.5">
                      归属商户:{" "}
                      <span className="text-indigo-300 font-mono font-bold uppercase">
                        {approval.businessId || "ecommerce"}
                      </span>
                    </p>
                  </div>
                </div>

                <div className="text-right text-xs text-slate-400 font-mono space-y-1">
                  <div>
                    历史订单数:{" "}
                    <strong className="text-slate-200">
                      {detail?.orders?.length || 0}
                    </strong>{" "}
                    笔
                  </div>
                  <div>
                    提取画像数:{" "}
                    <strong className="text-slate-200">
                      {detail?.user?.preferences?.length || 0}
                    </strong>{" "}
                    条
                  </div>
                </div>
              </div>

              {/* User Persona Facts List */}
              <div className="space-y-2">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 font-mono">
                  <Sparkles className="h-3.5 w-3.5 text-amber-400" /> AI
                  记忆与个性化偏好事实 (Persona Facts)
                </span>

                {!detail?.user?.preferences ||
                detail.user.preferences.length === 0 ? (
                  <div className="p-6 bg-slate-900 border border-slate-800 rounded-xl text-center text-xs text-slate-500 font-mono">
                    暂无已沉淀的用户画像事实记录。
                  </div>
                ) : (
                  <div className="space-y-2">
                    {detail.user.preferences.map((pref, idx) => (
                      <div
                        key={pref.id || idx}
                        className="bg-slate-900/80 border border-slate-800 p-3 rounded-xl flex items-center justify-between gap-3"
                      >
                        <div className="flex items-center space-x-2.5">
                          <div className="h-2 w-2 rounded-full bg-emerald-400" />
                          <span className="text-xs font-semibold text-slate-200">
                            {pref.fact}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 font-mono text-[10px]">
                          {pref.confidence !== undefined && (
                            <span className="text-slate-500">
                              置信度 {(pref.confidence * 100).toFixed(0)}%
                            </span>
                          )}
                          <Badge
                            variant="outline"
                            className="bg-emerald-500/10 text-emerald-400 border-emerald-500/30 text-[9px]"
                          >
                            {pref.status === "approved" ? "已核准" : "生效中"}
                          </Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 3. 📦 TAB 3: 购买记录与历史订单 (包含正规化地址薄与商品明细) */}
          {activeTab === "PURCHASE_HISTORY" && (
            <div className="space-y-3">
              {!detail?.orders || detail.orders.length === 0 ? (
                <div className="p-8 bg-slate-900 border border-slate-800 rounded-xl text-center text-xs text-slate-500 font-mono">
                  该用户在当前商户下暂无历史购买记录。
                </div>
              ) : (
                detail.orders.map((ord) => {
                  const isTarget =
                    targetOrderId && ord.orderId === targetOrderId;

                  return (
                    <Card
                      key={ord.orderId}
                      className={`bg-slate-900 border transition-all ${
                        isTarget
                          ? "border-indigo-500 shadow-lg shadow-indigo-500/10 ring-1 ring-indigo-500/30"
                          : "border-slate-800"
                      }`}
                    >
                      <CardContent className="p-4 space-y-3.5">
                        {/* 顶部订单号与金额 */}
                        <div className="flex items-center justify-between pb-2 border-b border-slate-800/80">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs font-bold text-slate-100">
                              订单号: {ord.orderId}
                            </span>
                            {isTarget && (
                              <Badge className="bg-indigo-600 text-white text-[9px] font-bold">
                                🎯 当前审核标的订单
                              </Badge>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-bold font-mono text-rose-400">
                              ¥ {ord.totalAmount.toFixed(2)}
                            </span>
                            <Badge
                              variant="outline"
                              className="text-[10px] bg-slate-950 border-slate-700 text-slate-300 font-mono"
                            >
                              {ord.status}
                            </Badge>
                          </div>
                        </div>

                        {/* 收货地址薄 (Normalized User Address) */}
                        <div className="bg-slate-950/70 border border-slate-850 p-2.5 rounded-lg space-y-1.5 text-xs font-mono">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-1.5 text-slate-300">
                              <Badge
                                variant="outline"
                                className="text-[9px] px-1.5 py-0 bg-indigo-500/10 text-indigo-300 border-indigo-500/30"
                              >
                                {ord.addressTag === "company"
                                  ? "公司地址"
                                  : ord.addressTag === "school"
                                    ? "学校地址"
                                    : "家庭/常用地址"}
                              </Badge>
                              <span className="font-bold text-slate-200">
                                {ord.recipientName || "收货人"}
                              </span>
                              <span className="text-slate-400">
                                ({ord.phone || "138****0000"})
                              </span>
                            </div>
                            {ord.addressId && (
                              <span className="text-[9px] text-slate-500 truncate max-w-[120px]">
                                AddrID: {ord.addressId.slice(0, 8)}...
                              </span>
                            )}
                          </div>
                          <div className="text-[11px] text-slate-400 leading-relaxed font-sans">
                            📍 配送地址: {ord.shippingAddress || "标准配送地址"}
                          </div>
                        </div>

                        {/* 订单商品明细 (Order Items) */}
                        {ord.items && ord.items.length > 0 && (
                          <div className="space-y-1.5">
                            <span className="text-[10px] font-bold text-slate-500 uppercase font-mono block">
                              商品采购明细
                            </span>
                            {ord.items.map((it, i) => (
                              <div
                                key={i}
                                className="flex justify-between items-center text-xs text-slate-300 bg-slate-950/40 p-2 rounded-lg border border-slate-850"
                              >
                                <span className="font-medium text-slate-200 truncate pr-2">
                                  {it.productName}
                                </span>
                                <span className="font-mono text-slate-400 shrink-0">
                                  ¥ {it.price.toFixed(2)} × {it.quantity}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* 物流与时间 */}
                        <div className="flex justify-between text-[11px] font-mono text-slate-500 pt-1 border-t border-slate-850">
                          <span>
                            承运物流: {ord.carrier || "顺丰速运"} (
                            {ord.trackingNumber || "暂无单号"})
                          </span>
                          <span>
                            {ord.createdAt?.includes("T")
                              ? new Date(ord.createdAt).toLocaleDateString()
                              : ord.createdAt || "-"}
                          </span>
                        </div>
                      </CardContent>
                    </Card>
                  );
                })
              )}
            </div>
          )}

          {/* 4. 💬 TAB 4: 现场会话聊天记录 */}
          {activeTab === "CHAT_HISTORY" && (
            <div className="space-y-3">
              {loading && (
                <div className="flex items-center justify-center py-6 gap-2 text-xs text-slate-400 font-mono">
                  <Loader2 className="h-4 w-4 animate-spin text-indigo-400" />
                  <span>正在实时拉取物理会话记录...</span>
                </div>
              )}

              {!detail?.messages || detail.messages.length === 0 ? (
                <div className="p-8 bg-slate-900 border border-slate-850 rounded-xl text-center text-xs text-slate-500 font-mono">
                  暂无历史聊天流水记录。
                </div>
              ) : (
                <div className="space-y-3">
                  {detail.messages.map((msg, idx) => {
                    const isUser = msg.role === "user";
                    const isOperator = msg.role === "operator";

                    return (
                      <div
                        key={msg.id || idx}
                        className={`flex flex-col ${isUser ? "items-start" : "items-end"}`}
                      >
                        <div className="flex items-center gap-1.5 text-[10px] text-slate-500 font-mono mb-1">
                          <span>
                            {isUser
                              ? "👤 用户"
                              : isOperator
                                ? "🎧 人工客服"
                                : "🤖 AI 助理"}
                          </span>
                          <span>{msg.timestamp}</span>
                        </div>
                        <div
                          className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-xs leading-relaxed shadow-md ${
                            isUser
                              ? "bg-slate-900 border border-slate-800 text-slate-100 rounded-tl-sm"
                              : isOperator
                                ? "bg-indigo-600 text-white rounded-tr-sm"
                                : "bg-slate-850 border border-slate-750 text-slate-200 rounded-tr-sm"
                          }`}
                        >
                          {msg.content}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </ScrollArea>

        {/* ⚡ Drawer Footer: Decision Actions & Operator Reply Bar */}
        <div className="p-5 bg-slate-900/90 border-t border-slate-800 shrink-0 space-y-3">
          {/* Operator IM Quick Reply Row */}
          {onHumanReply && (
            <div className="flex gap-2">
              <Input
                type="text"
                value={humanReplyText}
                onChange={(e) => setHumanReplyText(e.target.value)}
                placeholder="在此直接输入回复客户的客服消息（如：您好！已为您查验，这笔退款为您加急处理中）..."
                className="flex-1 bg-slate-950 border-slate-800 text-xs text-slate-100 h-9 rounded-xl placeholder-slate-600 focus-visible:ring-indigo-500"
              />
              <Button
                type="button"
                onClick={() => handleExecuteHumanReply(false)}
                disabled={isSubmitting}
                className="bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold h-9 px-4 rounded-xl flex items-center gap-1.5 shadow-md shadow-indigo-600/20"
              >
                <MessageSquare className="h-3.5 w-3.5" />
                <span>发送人工回复</span>
              </Button>
            </div>
          )}

          {/* Rejection input and Approve/Reject buttons if in waiting state */}
          {approval.status === "waiting" && (
            <div className="flex flex-col sm:flex-row gap-2.5">
              <Input
                type="text"
                value={rejectionReason}
                onChange={(e) => setRejectionReason(e.target.value)}
                placeholder="驳回理由（核准放行可留空，驳回时用户可见）..."
                className="flex-1 bg-slate-950 border-slate-800 text-xs text-slate-100 h-9 rounded-xl placeholder-slate-600 focus-visible:ring-indigo-500"
              />

              <div className="flex gap-2">
                <Button
                  type="button"
                  onClick={handleExecuteApprove}
                  disabled={isSubmitting}
                  className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold h-9 px-5 rounded-xl flex items-center gap-1.5 shadow-lg shadow-emerald-600/20"
                >
                  {isSubmitting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  )}
                  <span>核准通过</span>
                </Button>

                <Button
                  type="button"
                  onClick={handleExecuteReject}
                  disabled={isSubmitting}
                  className="bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold h-9 px-5 rounded-xl flex items-center gap-1.5 shadow-lg shadow-rose-600/20"
                >
                  {isSubmitting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5" />
                  )}
                  <span>驳回申请</span>
                </Button>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
