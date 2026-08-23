"use client";

import React, { useState } from "react";
import {
  Badge,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Clock,
  Code2,
  Coins,
  Copy,
  Layers,
  MessageSquare,
  RichCardRenderer,
  Search,
  Sparkles,
  User,
  Wrench,
  X,
} from "ui";
import type { ConversationTimeline } from "./ConversationsExplorer";

interface ThreadDeepTraceDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  timeline: ConversationTimeline | null;
  selectedMerchant: string;
}

export function ThreadDeepTraceDrawer({
  isOpen,
  onClose,
  timeline,
  selectedMerchant,
}: ThreadDeepTraceDrawerProps) {
  const [activeRightTab, setActiveRightTab] = useState<
    "decision_flow" | "tools_trace" | "rag_facts" | "billing"
  >("decision_flow");
  const [copiedJson, setCopiedJson] = useState(false);

  if (!isOpen || !timeline) return null;

  const { thread, messages } = timeline;

  // 模拟/提取 LangGraph 节点时序数据
  const mockDecisionNodes = [
    {
      node: "triage",
      name: "意图识别分流",
      status: "completed",
      duration: "120ms",
      summary: "识别为订单查询与售后诉求",
    },
    {
      node: "planner",
      name: "任务规划与编排",
      status: "completed",
      duration: "340ms",
      summary: "生成 2 步执行子任务计划",
    },
    {
      node: "executor",
      name: "工具执行与数据装配",
      status: "completed",
      duration: "610ms",
      summary: "调用 getOrderStatus 成功获取物流",
    },
    {
      node: "validator",
      name: "安全策略与红线核验",
      status: "completed",
      duration: "85ms",
      summary: "通过防重复退款与商户SOP校验",
    },
    {
      node: "finish",
      name: "卡片合成与最终响应",
      status: "completed",
      duration: "210ms",
      summary: "合成 TrackingTimeline 卡片",
    },
  ];

  const mockToolTraces = [
    {
      tool: "getOrderStatus",
      category: "E-Commerce SPI",
      status: "success",
      duration: "420ms",
      input: { orderId: "ORD-2026-001", threadId: thread.threadId },
      output: {
        orderId: "ORD-2026-001",
        status: "SHIPPED",
        carrier: "顺丰速运",
        trackingNumber: "SF1092837461",
        timeline: [{ status: "在途中", location: "上海转运中心" }],
      },
    },
  ];

  const mockRagFacts = [
    {
      title: "Nike 售后退换货保障条例.pdf",
      chunkId: "chk_nike_0912",
      score: 0.942,
      category: "Policy",
      snippet: "自签收之日起 30 天内支持无理由退换货；需保持商品原样吊牌齐全。",
    },
    {
      title: "物流时效与延迟赔付标准.md",
      chunkId: "chk_logistics_33",
      score: 0.816,
      category: "FAQ",
      snippet: "顺丰特快默认 48 小时达，超出时效可申请 10 元无门槛优惠券补偿。",
    },
  ];

  const handleCopyRawJson = () => {
    navigator.clipboard.writeText(JSON.stringify(timeline, null, 2));
    setCopiedJson(true);
    setTimeout(() => setCopiedJson(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-slate-950/80 backdrop-blur-md flex justify-end animate-in fade-in duration-200">
      <div className="w-full max-w-6xl bg-slate-900 border-l border-slate-800 h-full flex flex-col shadow-2xl">
        {/* 🚀 Header */}
        <div className="px-6 py-4 border-b border-slate-800 bg-slate-950/60 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-xl bg-indigo-600/20 text-indigo-400 border border-indigo-500/30 flex items-center justify-center font-bold">
              <BrainCircuit className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold text-slate-100">
                  会话全景决策与认知深度透视 (Cognitive Trace)
                </h2>
                <Badge className="bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 text-[10px]">
                  商户: {thread.businessId || selectedMerchant}
                </Badge>
                <span className="text-xs font-mono text-slate-400">
                  ID: {thread.threadId}
                </span>
              </div>
              <p className="text-[11px] text-slate-500">
                还原终端用户视角对话并穿透 LangGraph 节点时序、Tool
                入参出参、RAG 向量召回及 Token 计费
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleCopyRawJson}
              className="px-3 py-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg flex items-center gap-1.5 transition-colors border border-slate-700"
            >
              {copiedJson ? (
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
              ) : (
                <Copy className="w-3.5 h-3.5" />
              )}
              {copiedJson ? "已复制 JSON" : "复制原始 JSON"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-slate-100 rounded-lg hover:bg-slate-800 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* 📊 Split Two-Column Body */}
        <div className="flex-1 grid grid-cols-12 overflow-hidden">
          {/* 💬 Left Column: 1:1 Dialogue Experience */}
          <div className="col-span-12 lg:col-span-5 border-r border-slate-800 flex flex-col bg-slate-950/40">
            <div className="px-4 py-3 border-b border-slate-800/80 bg-slate-900/40 flex items-center justify-between">
              <span className="text-xs font-bold text-slate-300 flex items-center gap-1.5">
                <MessageSquare className="w-3.5 h-3.5 text-indigo-400" />{" "}
                用户原貌对话回放
              </span>
              <span className="text-[10px] text-slate-500">
                共 {messages.length} 条消息
              </span>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.map((msg, idx) => {
                const isUser = msg.role === "user";
                const isOperator = msg.role === "operator";
                return (
                  <div
                    key={msg.id || idx}
                    className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}
                  >
                    <div className="text-[10px] text-slate-500 mb-1 px-1 flex items-center gap-1">
                      <span className="font-semibold">
                        {isUser
                          ? "买家"
                          : isOperator
                            ? "人工坐席"
                            : "智能 Agent"}
                      </span>
                      <span>
                        {new Date(msg.timestamp).toLocaleTimeString("zh-CN")}
                      </span>
                    </div>

                    <div
                      className={`max-w-[90%] p-3.5 rounded-2xl text-xs ${
                        isUser
                          ? "bg-indigo-600 text-white rounded-tr-sm"
                          : isOperator
                            ? "bg-amber-600/30 text-amber-100 border border-amber-500/30 rounded-tl-sm"
                            : "bg-slate-800 text-slate-200 border border-slate-700 rounded-tl-sm"
                      }`}
                    >
                      <div className="whitespace-pre-wrap leading-relaxed">
                        {msg.content}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 🧠 Right Column: Cognitive Inspector (Graph Nodes / Tools / RAG / Billing) */}
          <div className="col-span-12 lg:col-span-7 flex flex-col bg-slate-900/30">
            {/* Sub-tabs */}
            <div className="px-4 py-2.5 border-b border-slate-800 bg-slate-900/80 flex items-center gap-2">
              {[
                {
                  id: "decision_flow",
                  label: "LangGraph 节点决策流",
                  icon: BrainCircuit,
                },
                { id: "tools_trace", label: "Tool 调用明细", icon: Wrench },
                { id: "rag_facts", label: "RAG 向量召回切片", icon: Sparkles },
                { id: "billing", label: "Token 计费与成本", icon: Coins },
              ].map((tab) => {
                const Icon = tab.icon;
                const isActive = activeRightTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveRightTab(tab.id as any)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all ${
                      isActive
                        ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/20"
                        : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {tab.label}
                  </button>
                );
              })}
            </div>

            {/* Sub-tab Content */}
            <div className="flex-1 overflow-y-auto p-5">
              {/* 1. LangGraph Decision Flow */}
              {activeRightTab === "decision_flow" && (
                <div className="space-y-4">
                  <div className="text-xs text-slate-400">
                    智能体状态图经历以下节点完成状态流转并合成最终响应：
                  </div>
                  <div className="relative pl-6 space-y-4 before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-800">
                    {mockDecisionNodes.map((node, index) => (
                      <div key={node.node} className="relative">
                        <div className="absolute -left-6 top-1.5 w-5 h-5 rounded-full bg-slate-900 border-2 border-emerald-500 flex items-center justify-center text-[10px] text-emerald-400 font-bold">
                          {index + 1}
                        </div>
                        <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800 space-y-1.5">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-slate-200 font-mono">
                              node::{node.node} ({node.name})
                            </span>
                            <div className="flex items-center gap-2">
                              <Badge className="bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 text-[9px]">
                                {node.status}
                              </Badge>
                              <span className="text-[10px] font-mono text-slate-500">
                                {node.duration}
                              </span>
                            </div>
                          </div>
                          <p className="text-xs text-slate-400">
                            {node.summary}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 2. Tool Traces */}
              {activeRightTab === "tools_trace" && (
                <div className="space-y-4">
                  <div className="text-xs text-slate-400">
                    本会话中 Agent 调用的标准化工具入参与出参审计：
                  </div>
                  {mockToolTraces.map((t) => (
                    <div
                      key={t.tool}
                      className="p-4 rounded-xl bg-slate-950/80 border border-slate-800 space-y-3"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Wrench className="w-4 h-4 text-amber-400" />
                          <span className="text-xs font-bold text-slate-200 font-mono">
                            {t.tool}
                          </span>
                          <span className="text-[10px] text-slate-500">
                            [{t.category}]
                          </span>
                        </div>
                        <Badge className="bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 text-[9px]">
                          {t.status} ({t.duration})
                        </Badge>
                      </div>

                      <div className="space-y-2">
                        <div>
                          <span className="text-[10px] font-bold text-slate-500 uppercase">
                            Input Payload:
                          </span>
                          <pre className="mt-1 p-2.5 rounded-lg bg-slate-900 border border-slate-800 text-[11px] font-mono text-indigo-300 overflow-x-auto">
                            {JSON.stringify(t.input, null, 2)}
                          </pre>
                        </div>
                        <div>
                          <span className="text-[10px] font-bold text-slate-500 uppercase">
                            Execution Output:
                          </span>
                          <pre className="mt-1 p-2.5 rounded-lg bg-slate-900 border border-slate-800 text-[11px] font-mono text-emerald-300 overflow-x-auto">
                            {JSON.stringify(t.output, null, 2)}
                          </pre>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* 3. RAG Facts */}
              {activeRightTab === "rag_facts" && (
                <div className="space-y-4">
                  <div className="text-xs text-slate-400">
                    基于 pgvector 混合检索 (BM25 + RRF)
                    命中的租户私有知识库切片：
                  </div>
                  {mockRagFacts.map((fact) => (
                    <div
                      key={fact.chunkId}
                      className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-indigo-300">
                          {fact.title}
                        </span>
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] font-mono text-emerald-400">
                            Score: {fact.score}
                          </span>
                          <Badge className="bg-slate-800 text-slate-400 text-[9px]">
                            {fact.category}
                          </Badge>
                        </div>
                      </div>
                      <p className="text-xs text-slate-300 bg-slate-900/60 p-2.5 rounded-lg border border-slate-800/80 leading-relaxed">
                        “{fact.snippet}”
                      </p>
                    </div>
                  ))}
                </div>
              )}

              {/* 4. Billing & Tokens */}
              {activeRightTab === "billing" && (
                <div className="space-y-4">
                  <div className="grid grid-cols-3 gap-3">
                    <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800">
                      <div className="text-[10px] text-slate-500 uppercase font-bold">
                        Input Tokens
                      </div>
                      <div className="text-base font-bold text-slate-200 font-mono mt-1">
                        1,420
                      </div>
                    </div>
                    <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800">
                      <div className="text-[10px] text-slate-500 uppercase font-bold">
                        Output Tokens
                      </div>
                      <div className="text-base font-bold text-slate-200 font-mono mt-1">
                        388
                      </div>
                    </div>
                    <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800">
                      <div className="text-[10px] text-slate-500 uppercase font-bold">
                        Total Cost (USD)
                      </div>
                      <div className="text-base font-bold text-emerald-400 font-mono mt-1">
                        $0.0054
                      </div>
                    </div>
                  </div>

                  <div className="p-4 rounded-xl bg-slate-950/40 border border-slate-800 text-xs text-slate-400 space-y-2">
                    <div className="font-bold text-slate-300">
                      SaaS 计费规则说明：
                    </div>
                    <p>• 基础模型采用按 Token 调用量阶梯结算。</p>
                    <p>• 商户专属 SPI 工具调用计入基础服务 SLA 配额。</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
