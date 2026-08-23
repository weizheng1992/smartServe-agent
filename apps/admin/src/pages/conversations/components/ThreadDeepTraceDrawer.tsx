import React, { useState } from "react";
import { DetailDrawer } from "../../../components/crud";
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
      width="max-w-4xl"
      title={`会话决策透视: ${conversation.threadId}`}
      subtitle={`用户: ${conversation.userId} | 商户: ${conversation.businessId.toUpperCase()} | 渠道: ${conversation.channel}`}
      badge={
        conversation.status === "waiting_approval" ? (
          <span className="px-2 py-0.5 text-xs font-semibold bg-amber-100 text-amber-800 rounded-full">
            待风控审批
          </span>
        ) : (
          <span className="px-2 py-0.5 text-xs font-semibold bg-slate-100 text-slate-700 rounded-full">
            {conversation.status}
          </span>
        )
      }
    >
      <div className="space-y-4">
        {/* Tab 导航 */}
        <div className="flex items-center gap-2 border-b border-slate-200 pb-2">
          <button
            type="button"
            onClick={() => setActiveTab("dialogue")}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer ${
              activeTab === "dialogue"
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            1. 真实对话记录
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("trace")}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer ${
              activeTab === "trace"
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            2. LangGraph 思考/工具决策流
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("metrics")}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer ${
              activeTab === "metrics"
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            3. 遥测与 Token 计量
          </button>
        </div>

        {/* Tab 内容区 */}
        {activeTab === "dialogue" && (
          <div className="space-y-3">
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
          </div>
        )}

        {activeTab === "trace" && (
          <div className="space-y-3">
            <div className="bg-slate-900 text-slate-200 rounded-xl p-4 font-mono text-xs space-y-2 overflow-x-auto">
              <div className="text-emerald-400 font-bold">
                ▶ [TriageNode] 意图分类: {conversation.intent} (Confidence:
                0.98)
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
          </div>
        )}

        {activeTab === "metrics" && (
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
        )}
      </div>
    </DetailDrawer>
  );
}
