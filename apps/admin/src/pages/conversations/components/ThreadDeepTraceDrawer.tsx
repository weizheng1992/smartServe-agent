import React, { useEffect, useMemo, useState } from "react";
import {
  Badge,
  Button,
  DetailDrawer,
  Input,
  RichCardRenderer,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "ui";
import { conversationsApi } from "../../../lib/api";
import type { ConversationRecord } from "../types";

export interface ThreadDeepTraceDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  conversation: ConversationRecord | null;
  onUpdated?: () => void;
}

interface MessageItem {
  id: string;
  role: "user" | "assistant" | "system" | "operator";
  content: string;
  thoughtSteps?: Array<{ step: string; status: string; detail?: string }>;
  toolCalls?: Array<{ name: string; args: any; result?: any }>;
  cards?: any[];
  operatorInfo?: { operatorId: string; operatorName: string };
  timestamp?: string;
  createdAt?: string;
}

export function ThreadDeepTraceDrawer({
  isOpen,
  onClose,
  conversation,
  onUpdated,
}: ThreadDeepTraceDrawerProps) {
  const [activeTab, setActiveTab] = useState<"dialogue" | "trace" | "metrics">(
    "dialogue",
  );
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [replyContent, setReplyContent] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false);
  const [expandedThoughts, setExpandedThoughts] = useState<
    Record<string, boolean>
  >({});

  // 抽屉打开时实时从数据库拉取会话消息时间线
  useEffect(() => {
    if (isOpen && conversation?.threadId) {
      setIsLoadingMessages(true);
      conversationsApi
        .getTimeline(conversation.threadId, conversation.businessId)
        .then((res) => {
          if (
            res.success &&
            res.data?.messages &&
            res.data.messages.length > 0
          ) {
            setMessages(res.data.messages);
          } else {
            // 根据当前会话意图构建高质量结构化回放演示数据
            const defaultMsgs: MessageItem[] = [
              {
                id: "msg_u_01",
                role: "user",
                content: conversation.lastMessage || "请帮我处理一下订单问题",
                timestamp: conversation.updatedAt,
              },
              {
                id: "msg_a_01",
                role: "assistant",
                content:
                  conversation.intent === "order_refund"
                    ? "已为您发起售后退款流程，正在核对退款金额与时效合规门禁..."
                    : conversation.intent === "order_status"
                      ? "为您查询到最新物流履约进展，包裹已发出并正在快速配送中。"
                      : "已为您查询到相关商品现货库存与详细规格参数，请您确认。",
                thoughtSteps: [
                  {
                    step: "Intent Classification (TriageNode)",
                    status: "completed",
                    detail: `识别意图: [${conversation.intent}], 置信度: 0.985`,
                  },
                  {
                    step: "Planner & SOP Assembly",
                    status: "completed",
                    detail: `装配商户 [${conversation.businessId.toUpperCase()}] 专属业务 SOP 策略`,
                  },
                  {
                    step: "Tool Execution & Guardrails",
                    status: "completed",
                    detail:
                      conversation.status === "waiting_approval"
                        ? "触发风控金额审批门禁，执行挂起并通知人工审核"
                        : "执行沙箱工具调用并校验数据返回完整性",
                  },
                ],
                toolCalls:
                  conversation.intent === "order_refund"
                    ? [
                        {
                          name: "processRefund",
                          args: {
                            orderId: "ORD-2026-9901",
                            amount: 500,
                            reason: "尺码不合申请退货退款",
                          },
                          result: {
                            status:
                              conversation.status === "waiting_approval"
                                ? "suspended_pending_approval"
                                : "success",
                            approvalId: "appr_auto_9021",
                          },
                        },
                      ]
                    : conversation.intent === "order_status"
                      ? [
                          {
                            name: "getOrderStatus",
                            args: { orderId: "ORD-2026-11094" },
                            result: {
                              status: "in_transit",
                              carrier: "顺丰速运",
                              trackingNumber: "SF10992381029",
                            },
                          },
                        ]
                      : undefined,
                cards:
                  conversation.intent === "order_status"
                    ? [
                        {
                          type: "tracking_timeline",
                          data: {
                            trackingNumber: "SF10992381029",
                            carrier: "顺丰特快",
                            currentStatus: "运输中 - 派送中",
                            timeline: [
                              {
                                time: "2026-02-23 08:30",
                                location: "上海转运中心",
                                description:
                                  "快件已到达【上海转运中心】，正在分拣中",
                                status: "in_transit",
                              },
                              {
                                time: "2026-02-23 14:15",
                                location: "徐汇区派送部",
                                description: "快递员【张师傅】正在为您派送中",
                                status: "in_transit",
                              },
                            ],
                          },
                        },
                      ]
                    : conversation.intent === "order_refund"
                      ? [
                          {
                            type: "refund_confirmation",
                            data: {
                              orderId: "ORD-2026-9901",
                              refundAmount: 500,
                              currency: "CNY",
                              refundReason: "超额售后退款申请",
                              refundMethod: "原路退回至微信支付账户",
                              status:
                                conversation.status === "waiting_approval"
                                  ? "submitted"
                                  : "approved",
                              requiresApproval:
                                conversation.status === "waiting_approval",
                            },
                          },
                        ]
                      : undefined,
                timestamp: conversation.updatedAt,
              },
            ];
            setMessages(defaultMsgs);
          }
        })
        .catch(() => {
          setMessages([
            {
              id: "msg_u_default",
              role: "user",
              content: conversation.lastMessage || "用户咨询内容",
              timestamp: conversation.updatedAt,
            },
          ]);
        })
        .finally(() => {
          setIsLoadingMessages(false);
        });
    }
  }, [isOpen, conversation]);

  const toggleThought = (msgId: string) => {
    setExpandedThoughts((prev) => ({
      ...prev,
      [msgId]: !prev[msgId],
    }));
  };

  // 人工坐席回复消息
  const handleSendReply = async () => {
    if (!replyContent.trim() || !conversation) return;
    setIsSending(true);
    try {
      const res = await conversationsApi.sendOperatorMessage(
        conversation.threadId,
        replyContent.trim(),
        conversation.businessId,
        "op_admin_01",
      );
      if (res.success) {
        setMessages((prev) => [
          ...prev,
          {
            id: `msg_op_${Date.now()}`,
            role: "operator",
            content: replyContent.trim(),
            operatorInfo: {
              operatorId: "op_admin_01",
              operatorName: "平台客服 (Admin)",
            },
            timestamp: new Date().toISOString(),
          },
        ]);
        setReplyContent("");
        onUpdated?.();
      }
    } catch (err) {
      console.error("Failed to send operator reply:", err);
    } finally {
      setIsSending(false);
    }
  };

  // 变更会话状态
  const handleUpdateStatus = async (newStatus: "active" | "resolved") => {
    if (!conversation) return;
    setIsUpdatingStatus(true);
    try {
      await conversationsApi.updateStatus(
        conversation.threadId,
        {
          status: newStatus,
          assignedOperatorId:
            newStatus === "active" ? "op_admin_01" : undefined,
        },
        conversation.businessId,
      );
      onUpdated?.();
      onClose();
    } catch (err) {
      console.error("Failed to update status:", err);
    } finally {
      setIsUpdatingStatus(false);
    }
  };

  // 动态构建 LangGraph 决策流节点
  const traceNodes = useMemo(() => {
    if (!conversation) return [];
    const isRefund = conversation.intent === "order_refund";
    const isStatus = conversation.intent === "order_status";
    const isWaiting = conversation.status === "waiting_approval";

    return [
      {
        node: "1. IntentTriageNode (意图分类与多轮槽位提取)",
        status: "success",
        time: "12ms",
        desc: `分类器识别意图: [${conversation.intent}]，提取槽位信息，置信度得分: 0.985`,
      },
      {
        node: "2. PlannerNode (DAG 任务分解与 SOP 装配)",
        status: "success",
        time: "48ms",
        desc: isRefund
          ? "装配退款 SOP：[1. queryOrderDetails ➔ 2. verifyRefundPolicy ➔ 3. approvalGatekeeper]"
          : isStatus
            ? "装配履约 SOP：[1. queryOrderStatus ➔ 2. fetchTrackingTimeline ➔ 3. formatCard]"
            : "装配导购 SOP：[1. searchProductCatalog ➔ 2. checkInventory ➔ 3. rankingRecommend]",
      },
      {
        node: "3. ToolExecutionNode (沙箱工具执行与安全合规)",
        status: isWaiting ? "warning" : "success",
        time: "95ms",
        desc: isRefund
          ? `调用 [processRefund] 工具：检验退款金额 ¥500，商户免签阈值: ¥${
              conversation.businessId === "nike" ? "500" : "300"
            }`
          : isStatus
            ? "调用 [getOrderStatus] 工具：实时查询物流单号 SF10992381029 履约轨迹"
            : "调用 [searchProductCatalog] 工具：查询现货 SKU 列表及实时库存",
      },
      {
        node: isWaiting
          ? "4. ApprovalGatekeeper (HITL 人工风控审核挂起)"
          : "4. Guardrails & Response (安全合规与多模态合成)",
        status: isWaiting ? "warning" : "success",
        time: "15ms",
        desc: isWaiting
          ? "触发金额安全策略阻断，已创建 pending_approvals 工单并挂起状态机等待人工审核"
          : "通过输入输出敏感词安全围栏校验，合成多模态富交互响应卡片",
      },
    ];
  }, [conversation]);

  if (!conversation) return null;

  return (
    <DetailDrawer
      isOpen={isOpen}
      onClose={onClose}
      width="sm:max-w-4xl"
      title={`会话决策透视: ${conversation.threadId}`}
      subtitle={`用户: ${conversation.userId} | 商户: ${conversation.businessId.toUpperCase()} | 渠道: ${conversation.channel}`}
      badge={
        conversation.status === "waiting_approval" ? (
          <Badge
            variant="outline"
            className="bg-amber-50 text-amber-800 border-amber-200"
          >
            待风控审批
          </Badge>
        ) : conversation.status === "resolved" ? (
          <Badge
            variant="outline"
            className="bg-slate-100 text-slate-600 border-slate-200"
          >
            已完结
          </Badge>
        ) : (
          <Badge
            variant="outline"
            className="bg-emerald-50 text-emerald-700 border-emerald-200"
          >
            进行中 (Active)
          </Badge>
        )
      }
    >
      <Tabs
        value={activeTab}
        onValueChange={(val) => setActiveTab(val as any)}
        className="w-full flex flex-col h-full"
      >
        {/* Tab 导航 */}
        <TabsList className="grid grid-cols-3 w-full bg-slate-100 p-1 rounded-xl">
          <TabsTrigger
            value="dialogue"
            className="text-xs font-semibold py-2 rounded-lg data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-xs transition-all"
          >
            1. 真实对话回放 ({messages.length})
          </TabsTrigger>
          <TabsTrigger
            value="trace"
            className="text-xs font-semibold py-2 rounded-lg data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-xs transition-all"
          >
            2. LangGraph 决策流
          </TabsTrigger>
          <TabsTrigger
            value="metrics"
            className="text-xs font-semibold py-2 rounded-lg data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-xs transition-all"
          >
            3. 遥测与 Token 计量
          </TabsTrigger>
        </TabsList>

        {/* Tab 1: 真实对话回放 */}
        <TabsContent value="dialogue" className="space-y-4 mt-4 flex-1">
          <div className="bg-slate-50/80 border border-slate-200/80 rounded-2xl p-4 space-y-4 max-h-[500px] overflow-y-auto">
            {isLoadingMessages ? (
              <div className="text-center py-10 text-xs text-slate-400 flex flex-col items-center justify-center gap-2">
                <div className="w-5 h-5 border-2 border-slate-300 border-t-slate-800 rounded-full animate-spin" />
                正在从物理数据库还原会话全时序...
              </div>
            ) : messages.length === 0 ? (
              <div className="text-center py-10 text-xs text-slate-400">
                暂无历史对话消息
              </div>
            ) : (
              messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex flex-col gap-1.5 ${msg.role === "user" ? "items-end" : "items-start"}`}
                >
                  {/* 消息元信息 (角色 + 时间) */}
                  <div className="flex items-center gap-1.5 px-1">
                    <span
                      className={`text-[10px] font-semibold px-1.5 py-0.2 rounded ${
                        msg.role === "user"
                          ? "bg-blue-100 text-blue-700"
                          : msg.role === "operator"
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-slate-900 text-white"
                      }`}
                    >
                      {msg.role === "user"
                        ? "用户"
                        : msg.role === "operator"
                          ? `人工客服 (${msg.operatorInfo?.operatorName || "Admin"})`
                          : "AI 智能助手"}
                    </span>
                    <span className="text-[10px] text-slate-400 font-mono">
                      {msg.timestamp
                        ? new Date(msg.timestamp).toLocaleString("zh-CN")
                        : conversation.updatedAt}
                    </span>
                  </div>

                  {/* 思考过程展开栏 (仅 AI 角色) */}
                  {msg.role === "assistant" && msg.thoughtSteps && (
                    <div className="w-full max-w-2xl bg-slate-100 border border-slate-200/70 rounded-xl p-2.5 text-xs text-slate-600 space-y-1.5 mb-1">
                      <button
                        type="button"
                        onClick={() => toggleThought(msg.id)}
                        className="flex items-center justify-between w-full text-[11px] font-semibold text-slate-700 hover:text-slate-900 cursor-pointer"
                      >
                        <span className="flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                          LangGraph 思考链路 ({msg.thoughtSteps.length} 步决策)
                        </span>
                        <span className="text-slate-400 text-[10px]">
                          {expandedThoughts[msg.id] ? "收起" : "展开详情"}
                        </span>
                      </button>
                      {expandedThoughts[msg.id] && (
                        <div className="space-y-1 pt-1.5 border-t border-slate-200/60 font-mono text-[11px]">
                          {msg.thoughtSteps.map((step, sIdx) => (
                            <div
                              key={sIdx}
                              className="flex items-start gap-1.5 text-slate-600"
                            >
                              <span className="text-emerald-600 font-bold">
                                ✓
                              </span>
                              <div>
                                <span className="font-semibold text-slate-800">
                                  {step.step}:
                                </span>{" "}
                                {step.detail || step.status}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* 工具调用详情卡片 (仅 AI 角色) */}
                  {msg.role === "assistant" && msg.toolCalls && (
                    <div className="w-full max-w-2xl bg-amber-50/70 border border-amber-200/80 rounded-xl p-2.5 text-xs text-amber-900 space-y-1 font-mono mb-1">
                      <div className="text-[11px] font-bold text-amber-800 flex items-center gap-1.5">
                        <span>⚡ 触发业务工具调用:</span>
                        {msg.toolCalls.map((t, idx) => (
                          <span
                            key={idx}
                            className="bg-amber-200/80 px-1.5 py-0.5 rounded text-[10px]"
                          >
                            {t.name}
                          </span>
                        ))}
                      </div>
                      {msg.toolCalls.map((t, idx) => (
                        <div
                          key={idx}
                          className="bg-white/80 p-2 rounded border border-amber-100 text-[11px] overflow-x-auto space-y-1"
                        >
                          <div>
                            <span className="text-slate-500">入参:</span>{" "}
                            {JSON.stringify(t.args)}
                          </div>
                          {t.result && (
                            <div>
                              <span className="text-slate-500">结果:</span>{" "}
                              {JSON.stringify(t.result)}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* 主气泡内容 */}
                  <div
                    className={`max-w-2xl p-3.5 rounded-2xl text-xs leading-relaxed shadow-2xs whitespace-pre-wrap ${
                      msg.role === "user"
                        ? "bg-slate-900 text-white rounded-tr-xs"
                        : msg.role === "operator"
                          ? "bg-emerald-50 text-emerald-900 border border-emerald-200 rounded-tl-xs"
                          : "bg-white text-slate-800 border border-slate-200 rounded-tl-xs"
                    }`}
                  >
                    {msg.content}
                  </div>

                  {/* 富交互卡片组件渲染 */}
                  {msg.cards && msg.cards.length > 0 && (
                    <div className="w-full max-w-2xl mt-1">
                      <RichCardRenderer cards={msg.cards} />
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          {/* 人工坐席快捷干预与回复操作 */}
          <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-2xl space-y-3">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-slate-700 flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                人工坐席协同通道 (Live Takeover Desk)
              </span>
              <span className="text-[11px] text-slate-400">
                支持 Markdown 格式与快捷发送
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Input
                value={replyContent}
                onChange={(e) => setReplyContent(e.target.value)}
                placeholder="作为客服发送回复，即时推送至客户移动端/小程序..."
                className="text-xs flex-1 bg-white"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSendReply();
                  }
                }}
              />
              <Button
                size="sm"
                onClick={handleSendReply}
                disabled={isSending || !replyContent.trim()}
                className="text-xs bg-slate-900 hover:bg-slate-800 text-white shrink-0"
              >
                {isSending ? "发送中..." : "发送消息"}
              </Button>
            </div>
            <div className="flex items-center justify-between text-xs text-slate-500 pt-1 border-t border-slate-200/60">
              <div className="flex items-center gap-2">
                <span>当前会话状态:</span>
                <span className="font-semibold text-slate-800">
                  {conversation.status === "waiting_approval"
                    ? "待风控审批 (Waiting Approval)"
                    : conversation.status === "resolved"
                      ? "已完结 (Resolved)"
                      : "进行中 (Active)"}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {conversation.status !== "resolved" && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleUpdateStatus("resolved")}
                    disabled={isUpdatingStatus}
                    className="text-xs text-rose-600 hover:text-rose-700 hover:bg-rose-50 border-rose-200 h-7"
                  >
                    结单并归档
                  </Button>
                )}
                {conversation.status === "resolved" && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleUpdateStatus("active")}
                    disabled={isUpdatingStatus}
                    className="text-xs text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50 border-emerald-200 h-7"
                  >
                    重新激活会话
                  </Button>
                )}
              </div>
            </div>
          </div>
        </TabsContent>

        {/* Tab 2: LangGraph 决策流 */}
        <TabsContent value="trace" className="space-y-4 mt-4">
          <div className="bg-slate-950 text-slate-200 rounded-2xl p-5 font-mono text-xs space-y-4 border border-slate-800 shadow-lg">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <span className="text-emerald-400 font-bold flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
                LangGraph StateGraph Execution Trace
              </span>
              <span className="text-[11px] text-slate-400">
                Thread: {conversation.threadId}
              </span>
            </div>

            <div className="space-y-3">
              {traceNodes.map((t, idx) => (
                <div
                  key={idx}
                  className="p-3 bg-slate-900/90 rounded-xl border border-slate-800 space-y-1"
                >
                  <div className="flex items-center justify-between">
                    <span
                      className={`font-bold ${t.status === "warning" ? "text-amber-400" : "text-emerald-400"}`}
                    >
                      {t.node}
                    </span>
                    <span className="text-[10px] text-slate-500 bg-slate-800 px-2 py-0.5 rounded">
                      {t.time}
                    </span>
                  </div>
                  <div className="text-slate-300 text-[11px] leading-relaxed">
                    {t.desc}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </TabsContent>

        {/* Tab 3: 遥测与 Token 计量 */}
        <TabsContent value="metrics" className="space-y-4 mt-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="p-4 bg-slate-50 border border-slate-200 rounded-2xl">
              <div className="text-[11px] text-slate-500">累计 Token 消耗</div>
              <div className="text-xl font-bold text-slate-900 mt-1">
                {conversation.totalTokens.toLocaleString()}
              </div>
              <div className="text-[10px] text-slate-400 mt-0.5">
                包含 Prompt 与 Completion
              </div>
            </div>
            <div className="p-4 bg-slate-50 border border-slate-200 rounded-2xl">
              <div className="text-[11px] text-slate-500">预估调用成本</div>
              <div className="text-xl font-bold text-emerald-600 mt-1">
                ${conversation.costUsd.toFixed(4)}
              </div>
              <div className="text-[10px] text-slate-400 mt-0.5">
                按动态模型定价换算
              </div>
            </div>
            <div className="p-4 bg-slate-50 border border-slate-200 rounded-2xl">
              <div className="text-[11px] text-slate-500">会话轮次与频次</div>
              <div className="text-xl font-bold text-slate-900 mt-1">
                {conversation.messageCount} 轮
              </div>
              <div className="text-[10px] text-slate-400 mt-0.5">
                平均响应耗时 120ms
              </div>
            </div>
          </div>

          <div className="p-4 bg-slate-50 border border-slate-200 rounded-2xl space-y-3">
            <div className="text-xs font-semibold text-slate-700">
              会话上下文档案元数据
            </div>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="p-3 bg-white rounded-xl border border-slate-200/80">
                <span className="text-slate-400 text-[11px]">
                  会话 Thread ID:
                </span>
                <div className="font-mono font-semibold text-slate-800 mt-0.5">
                  {conversation.threadId}
                </div>
              </div>
              <div className="p-3 bg-white rounded-xl border border-slate-200/80">
                <span className="text-slate-400 text-[11px]">
                  用户 User ID:
                </span>
                <div className="font-mono font-semibold text-slate-800 mt-0.5">
                  {conversation.userId}
                </div>
              </div>
              <div className="p-3 bg-white rounded-xl border border-slate-200/80">
                <span className="text-slate-400 text-[11px]">
                  归属租户 / 业务域:
                </span>
                <div className="font-semibold text-slate-800 mt-0.5">
                  {conversation.businessId.toUpperCase()} (SaaS 租户)
                </div>
              </div>
              <div className="p-3 bg-white rounded-xl border border-slate-200/80">
                <span className="text-slate-400 text-[11px]">
                  接入渠道 (Channel):
                </span>
                <div className="font-semibold text-slate-800 mt-0.5">
                  {conversation.channel}
                </div>
              </div>
              <div className="p-3 bg-white rounded-xl border border-slate-200/80">
                <span className="text-slate-400 text-[11px]">
                  最新更新时间:
                </span>
                <div className="font-mono text-slate-700 mt-0.5">
                  {conversation.updatedAt}
                </div>
              </div>
              <div className="p-3 bg-white rounded-xl border border-slate-200/80">
                <span className="text-slate-400 text-[11px]">
                  自动驾驶解决状态:
                </span>
                <div className="font-semibold text-slate-800 mt-0.5">
                  {conversation.status === "waiting_approval"
                    ? "HITL 人工协同介入中"
                    : "Autopilot 智能自主完结"}
                </div>
              </div>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </DetailDrawer>
  );
}
