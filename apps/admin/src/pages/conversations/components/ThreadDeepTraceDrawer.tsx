import React, { useState } from "react";
import { DetailDrawer } from "../../../components/crud";
import { Tabs, TabsList, TabsTrigger, TabsContent, Badge } from "ui";
import type { ConversationRecord } from "../types";

export interface ThreadDeepTraceDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  conversation: ConversationRecord | null;
}

export function ThreadDeepTraceDrawer({
  isOpen,
  onClose,
  conversation,
}: ThreadDeepTraceDrawerProps) {
  const [activeTab, setActiveTab] = useState<"dialogue" | "trace" | "metrics">(
    "dialogue",
  );

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
        ) : (
          <Badge variant="secondary">{conversation.status}</Badge>
        )
      }
    >
      <Tabs
        value={activeTab}
        onValueChange={(val) => setActiveTab(val as any)}
        className="w-full space-y-4"
      >
        {/* Tab 导航 */}
        <TabsList className="grid grid-cols-3 w-full bg-slate-100">
          <TabsTrigger value="dialogue" className="text-xs font-semibold">
            1. 真实对话记录
          </TabsTrigger>
          <TabsTrigger value="trace" className="text-xs font-semibold">
            2. LangGraph 思考/工具决策流
          </TabsTrigger>
          <TabsTrigger value="metrics" className="text-xs font-semibold">
            3. 遥测与 Token 计量
          </TabsTrigger>
        </TabsList>

        {/* Tab 内容区 */}
        <TabsContent value="dialogue" className="space-y-3 mt-4">
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-3">
            <div className="flex items-start gap-2.5">
              <div className="w-6 h-6 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-[10px] font-bold shrink-0">
                U
              </div>
              <div>
                <div className="text-[11px] font-semibold text-slate-700">
                  用户提问
                </div>
                <div className="text-xs text-slate-800 mt-0.5 bg-white p-2.5 rounded-lg border border-slate-200 shadow-2xs">
                  {conversation.lastMessage}
                </div>
              </div>
            </div>

            <div className="flex items-start gap-2.5">
              <div className="w-6 h-6 rounded-full bg-slate-900 text-white flex items-center justify-center text-[10px] font-bold shrink-0">
                AI
              </div>
              <div>
                <div className="text-[11px] font-semibold text-slate-700">
                  Agent 响应
                </div>
                <div className="text-xs text-slate-800 mt-0.5 bg-white p-2.5 rounded-lg border border-slate-200 shadow-2xs">
                  已为您检索到订单状态并触发合规风控策略，正在安全沙箱中处理中...
                </div>
              </div>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="trace" className="space-y-3 mt-4">
          <div className="bg-slate-900 text-slate-200 rounded-xl p-4 font-mono text-xs space-y-2 overflow-x-auto">
            <div className="text-emerald-400 font-bold">
              ▶ [TriageNode] 意图分类: {conversation.intent} (Confidence: 0.98)
            </div>
            <div className="text-blue-300">
              ↳ [PlannerNode] 生成执行计划: [1. queryOrder, 2.
              checkRefundPolicy, 3. approvalGate]
            </div>
            <div className="text-amber-300">
              ↳ [ApprovalPolicyEngine] 检查阈值: 金额超限 (¥500 &gt; 阈值 ¥
              {conversation.businessId === "nike" ? "500" : "300"})
            </div>
            <div className="text-purple-300">
              ↳ [ApprovalGatekeeper] 挂起状态机，向商户 SPI 发送 Webhook 通知
            </div>
          </div>
        </TabsContent>

        <TabsContent value="metrics" className="mt-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl">
              <div className="text-[11px] text-slate-500">累计 Token 消耗</div>
              <div className="text-base font-bold text-slate-900 mt-1">
                {conversation.totalTokens}
              </div>
            </div>
            <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl">
              <div className="text-[11px] text-slate-500">预估费用 (USD)</div>
              <div className="text-base font-bold text-emerald-600 mt-1">
                ${conversation.costUsd.toFixed(4)}
              </div>
            </div>
            <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl">
              <div className="text-[11px] text-slate-500">消息交互轮次</div>
              <div className="text-base font-bold text-slate-900 mt-1">
                {conversation.messageCount} 轮
              </div>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </DetailDrawer>
  );
}
