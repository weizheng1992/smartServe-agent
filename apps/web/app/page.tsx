'use client';

import {
  Activity,
  ArrowRight,
  Avatar,
  AvatarFallback,
  AvatarImage,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  CheckCircle2,
  Clock,
  Cpu,
  ImageIcon,
  Input,
  Laptop,
  Layout,
  Loader2,
  LogOut,
  Maximize2,
  MessageSquare,
  Plus,
  RefreshCw,
  Send,
  Shield,
  Sparkles,
  Trash2,
  User,
  X,
  XCircle,
} from 'ui';
import type React from 'react';
import { useEffect, useRef } from 'react';
import { useAuth } from "../hooks/useAuth";
import { useChatThreads } from "../hooks/useChatThreads";
import { useChatMessages } from "../hooks/useChatMessages";
import { useApprovals } from "../hooks/useApprovals";
import { ChatThread, Message, TaskPlan } from "../hooks/types";



// Safely format timestamps into MM-DD HH:mm format without hydration mismatches or invalid parsing
const formatFriendlyDate = (dateStr: any) => {
  if (!dateStr) return '未知时间';
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return '未知时间';

  const pad = (n: number) => String(n).padStart(2, '0');
  const month = pad(d.getMonth() + 1);
  const date = pad(d.getDate());
  const hours = pad(d.getHours());
  const minutes = pad(d.getMinutes());

  return `${month}-${date} ${hours}:${minutes}`;
};

export default function Home() {
  const { currentUser, isPageHydrated, handleLogout } = useAuth();

  const {
    threads,
    setThreads,
    activeThreadId,
    setActiveThreadId,
    selectedNewThreadMerchant,
    setSelectedNewThreadMerchant,
    isThreadsLoading,
    fetchThreads,
    handleCreateNewThread,
    handleMerchantSwitch,
    handleDeleteThread,
  } = useChatThreads({
    currentUser,
    onThreadCreated: () => {
      setRunningDetails([]);
      setActivePlan(null);
      setCurrentStepText("");
    },
  });

  const {
    messages,
    setMessages,
    input,
    setInput,
    isSubmitting,
    setIsSubmitting,
    activePlan,
    setActivePlan,
    currentStepText,
    setCurrentStepText,
    selectedScreenshot,
    setSelectedScreenshot,
    tokensConsumed,
    setTokensConsumed,
    runningDetails,
    setRunningDetails,
    syncPollCountRef,
    loadHistory,
    triggerStream,
    handleSend,
  } = useChatMessages({
    currentUser,
    activeThreadId,
    fetchThreads,
  });

  const {
    allApprovals,
    pendingApprovalsList,
    rejectionInput,
    setRejectionReason,
    activeTab,
    setActiveTab,
    selectedApprovalId,
    setSelectedApprovalId,
    auditFilter,
    setAuditFilter,
    handleApprovalAction,
  } = useApprovals({
    currentUser,
    activeThreadId,
    loadHistory,
    fetchThreads,
    syncPollCountRef,
    setMessages,
    setIsSubmitting,
    triggerStream,
  });

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 🌟 Auto Scroll to Bottom effect
  useEffect(() => {
    if (messages.length > 0) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  // 首屏渲染占位符，防止重定向闪烁
  if (!isPageHydrated || !currentUser) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-slate-950 text-slate-100 font-sans">
        <div className="flex flex-col items-center gap-3.5">
          <Loader2 className="h-9 w-9 animate-spin text-indigo-500" />
          <span className="text-xs font-mono text-slate-500 tracking-wider uppercase">
            Loading Workspace Session...
          </span>
        </div>
      </div>
    );
  }

  // ================= 2. 主会话大屏控制台 =================
  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 font-sans overflow-hidden">
      {/* 🚀 左侧：全新的历史对话与会话管理面板 */}
      <aside className="flex flex-col w-72 bg-slate-900 border-r border-slate-800 justify-between shrink-0">
        {/* 会话顶部账户卡片 */}
        <div className="p-4 border-b border-slate-800 bg-slate-950/20">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center space-x-2.5 min-w-0">
              <Avatar className="h-8.5 w-8.5 border border-indigo-500/30">
                <AvatarFallback className="bg-indigo-600 text-white text-xs font-mono">
                  {currentUser.email.charAt(0).toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0">
                <p className="text-xs font-bold text-slate-200 truncate">{currentUser.email}</p>
                <div className="flex items-center gap-1 mt-0.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse shrink-0" />
                  <span className="text-[9px] text-slate-500 font-mono uppercase tracking-wider">Online</span>
                </div>
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={handleLogout}
              className="h-7 w-7 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 shrink-0"
              title="登出账户"
            >
              <LogOut className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {/* 新增会话选择与操作按钮 */}
        <div className="px-4 pt-4 pb-2 space-y-2.5">
          <div className="flex flex-col gap-1.5">
            <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider font-mono px-1">
              选择对话商户
            </span>
            <div className="grid grid-cols-3 gap-1 bg-slate-950/60 border border-slate-850/80 p-1 rounded-xl">
              {[
                { id: 'ecommerce', label: '主站' },
                { id: 'nike', label: 'Nike' },
                { id: 'adidas', label: 'Adidas' },
              ].map((m) => (
                <button
                  type="button"
                  key={m.id}
                  onClick={() => handleMerchantSwitch(m.id)}
                  className={`py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wider transition ${
                    selectedNewThreadMerchant === m.id
                      ? 'bg-indigo-600 text-white shadow-md'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/20'
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          <Button
            onClick={() => handleCreateNewThread(selectedNewThreadMerchant)}
            className="w-full bg-slate-950/40 hover:bg-slate-950/80 text-indigo-400 border border-indigo-500/20 hover:border-indigo-500/40 rounded-xl h-10 text-xs font-semibold flex items-center justify-center gap-2 transition"
          >
            <Plus className="h-4 w-4" />
            <span>开启新一轮对话</span>
          </Button>
        </div>

        {/* Tab Switcher */}
        <div className="px-4 py-2 flex gap-2">
          <Button
            variant={activeTab === 'CHAT_DESK' ? 'default' : 'outline'}
            onClick={() => setActiveTab('CHAT_DESK')}
            className={`flex-1 text-[11px] h-8 rounded-lg font-semibold transition ${
              activeTab === 'CHAT_DESK'
                ? 'bg-indigo-600 hover:bg-indigo-500 text-white border-transparent'
                : 'border-slate-800 text-slate-400 hover:bg-slate-850 hover:text-slate-200 bg-transparent'
            }`}
          >
            💬 智能工作台
          </Button>
          <Button
            variant={activeTab === 'AUDIT_DESK' ? 'default' : 'outline'}
            onClick={() => setActiveTab('AUDIT_DESK')}
            className={`flex-1 text-[11px] h-8 rounded-lg font-semibold transition relative ${
              activeTab === 'AUDIT_DESK'
                ? 'bg-indigo-600 hover:bg-indigo-500 text-white border-transparent'
                : 'border-slate-800 text-slate-400 hover:bg-slate-850 hover:text-slate-200 bg-transparent'
            }`}
          >
            <span>🛡️ 审核中心</span>
            {allApprovals.filter((a) => a.status === 'waiting').length > 0 && (
              <span className="absolute -top-1 -right-1 h-4.5 w-4.5 bg-rose-500 text-white text-[9px] rounded-full flex items-center justify-center font-bold animate-pulse">
                {allApprovals.filter((a) => a.status === 'waiting').length}
              </span>
            )}
          </Button>
        </div>

        {/* 历史对话会话列表 */}
        <div className="flex-1 overflow-y-auto px-2 space-y-1.5 pt-2">
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider px-3 mb-1.5 font-mono">
            历史对话列表 ({threads.length})
          </p>

          {isThreadsLoading && threads.length === 0 ? (
            <div className="py-12 text-center flex flex-col items-center gap-2">
              <Loader2 className="h-5 w-5 animate-spin text-slate-600" />
              <span className="text-[10px] text-slate-500 font-mono">加载会话中...</span>
            </div>
          ) : threads.length === 0 ? (
            <div className="py-12 text-center px-4">
              <MessageSquare className="h-6 w-6 text-slate-700 mx-auto mb-2" />
              <p className="text-[11px] text-slate-500">无任何历史对话记录，点击上方按钮开辟一个吧！</p>
            </div>
          ) : (
            threads.map((t) => {
              const isActive = t.id === activeThreadId;

              return (
                // biome-ignore lint/a11y/useKeyWithClickEvents: Thread card is clickable for chat switching
                <div
                  key={t.id}
                  onClick={() => {
                    if (isSubmitting) return;
                    setActiveThreadId(t.id);
                  }}
                  className={`w-full text-left p-3 rounded-xl flex items-center justify-between gap-2.5 transition group border cursor-pointer ${
                    isActive
                      ? 'bg-indigo-600/10 border-indigo-500/30 text-indigo-200 font-medium'
                      : 'bg-transparent border-transparent text-slate-400 hover:bg-slate-950/30 hover:border-slate-800 hover:text-slate-200'
                  }`}
                >
                  <div className="flex items-center gap-2.5 min-w-0 flex-1">
                    <MessageSquare
                      className={`h-4.5 w-4.5 shrink-0 ${isActive ? 'text-indigo-400' : 'text-slate-600 group-hover:text-slate-400'}`}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs truncate font-mono tracking-tight">{t.id}</p>
                      <div className="flex items-center justify-between mt-1 text-[10px] text-slate-500">
                        <span className="font-mono">{formatFriendlyDate(t.createdAt)}</span>
                        <span
                          className={`px-1.5 py-0.2 rounded text-[8px] font-bold uppercase tracking-wider ${
                            t.businessId === 'nike'
                              ? 'bg-amber-500/10 text-amber-400 border border-amber-500/10'
                              : t.businessId === 'adidas'
                                ? 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/10'
                                : 'bg-slate-500/10 text-slate-400 border border-slate-800'
                          }`}
                        >
                          {t.businessId === 'nike' ? 'Nike' : t.businessId === 'adidas' ? 'Adidas' : '主站'}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Delete button, shows up on hover */}
                  <button
                    type="button"
                    onClick={(e) => handleDeleteThread(e, t.id)}
                    className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition shrink-0"
                    title="删除会话"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })
          )}
        </div>

        {/* 底部探针参数 */}
        <div className="p-4 border-t border-slate-800/80 bg-slate-950/20">
          <div className="rounded-xl border border-slate-800/80 bg-slate-950/50 p-2.5 space-y-1">
            <span className="text-[8px] text-slate-500 font-mono tracking-widest uppercase block">
              PERSISTENT CACHE
            </span>
            <div className="flex items-center gap-1.5 text-[10px] text-slate-300 font-mono">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse shrink-0" />
              <span className="truncate">Local Storage Hydrated</span>
            </div>
          </div>
        </div>
      </aside>

      {/* 中右侧大屏 */}
      <div className="flex-1 flex flex-col md:flex-row h-full overflow-hidden">
        {activeTab === 'CHAT_DESK' ? (
          <>
            {/* Chatting window */}
            <main className="flex-1 flex flex-col h-full bg-slate-950 relative border-r border-slate-900">
              {/* Header */}
              <header className="px-6 py-4 border-b border-slate-800 bg-slate-900/60 backdrop-blur-md flex justify-between items-center z-10">
                <div className="flex items-center space-x-3 min-w-0">
                  <div className="h-2.5 w-2.5 rounded-full bg-indigo-500 shadow-lg shadow-indigo-500/50 shrink-0" />
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 font-mono truncate">
                    会话: {activeThreadId || '未选择任何对话'}
                  </span>
                </div>
                <div className="flex items-center space-x-3 shrink-0">
                  <Badge
                    variant="outline"
                    className="border-indigo-500/30 text-indigo-400 bg-indigo-950/10 gap-1.5 hidden sm:flex font-mono text-[10px]"
                  >
                    <Laptop className="h-3 w-3" /> E-COMMERCE CORE
                  </Badge>
                  <Button
                    variant="outline"
                    size="icon"
                    className="h-8 w-8 rounded-lg border-slate-800 hover:bg-slate-800 text-slate-400 hover:text-slate-200"
                    onClick={() => {
                      if (activeThreadId) {
                        loadHistory(activeThreadId);
                      }
                      setActivePlan(null);
                      setCurrentStepText('');
                      setRunningDetails([]);
                    }}
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </header>

              {/* Messaging Area */}
              <div className="flex-1 overflow-y-auto p-6 min-h-0">
                <div className="max-w-3xl mx-auto space-y-6 pb-28">
                  {messages.map((m, idx) => (
                    <div key={idx} className={`flex gap-4 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      {m.role === 'assistant' && (
                        <Avatar className="h-9 w-9 border border-slate-800 shadow-md shrink-0">
                          <AvatarFallback className="bg-indigo-600/10 text-indigo-400 text-xs">AI</AvatarFallback>
                        </Avatar>
                      )}

                      <div className="space-y-3.5 max-w-[85%] shrink-0">
                        {/* Chat Message Box */}
                        <div
                          className={`rounded-2xl px-5 py-4 text-sm leading-relaxed shadow-xl border ${
                            m.role === 'user'
                              ? 'bg-gradient-to-br from-indigo-600 to-indigo-700 text-white border-indigo-500/30'
                              : 'bg-slate-900/90 text-slate-200 border-slate-800'
                          }`}
                        >
                          {m.isLoading ? (
                            <div className="flex items-center space-x-3 py-1">
                              <Loader2 className="h-4.5 w-4.5 animate-spin text-indigo-400" />
                              <span className="text-slate-400 font-medium animate-pulse">
                                正在全速运行本地有向有环图节点，智能调用工具链中...
                              </span>
                            </div>
                          ) : (
                            <p className="whitespace-pre-wrap">{m.content}</p>
                          )}
                        </div>

                        {/* Task Plan steps visualization */}
                        {m.plan && (
                          <Card className="bg-slate-900/40 border-slate-800/80 shadow-2xl backdrop-blur-sm">
                            <CardHeader className="p-4 pb-3 border-b border-slate-800/60 flex flex-row items-center justify-between gap-4">
                              <div className="flex items-center space-x-2.5 min-w-0">
                                <span className="h-2 w-2 rounded-full bg-indigo-500 animate-pulse shrink-0" />
                                <CardTitle className="text-xs font-semibold text-slate-300 uppercase tracking-wider truncate">
                                  已完成的分布式执行步骤规划
                                </CardTitle>
                              </div>
                              <Badge
                                variant="outline"
                                className="border-slate-800 text-[10px] text-slate-400 max-w-[200px] truncate font-mono"
                              >
                                {m.plan.goal}
                              </Badge>
                            </CardHeader>

                            <CardContent className="p-4 space-y-3">
                              {m.plan.subtasks.map((step) => {
                                const isCompleted = step.status === 'completed';
                                const isExecuting = step.status === 'executing';
                                const isFailed = step.status === 'failed';

                                return (
                                  <div
                                    key={step.id}
                                    className={`p-3.5 rounded-xl border transition-all ${
                                      isExecuting
                                        ? 'bg-indigo-950/20 border-indigo-500/40 shadow-inner'
                                        : 'bg-slate-950/40 border-slate-800/60'
                                    }`}
                                  >
                                    <div className="flex items-center justify-between gap-4">
                                      <div className="flex items-center space-x-3">
                                        <div className="shrink-0">
                                          {isCompleted && (
                                            <CheckCircle2 className="h-4.5 w-4.5 text-emerald-400 shadow-sm" />
                                          )}
                                          {isExecuting && (
                                            <Loader2 className="h-4.5 w-4.5 animate-spin text-indigo-400" />
                                          )}
                                          {isFailed && <XCircle className="h-4.5 w-4.5 text-rose-500" />}
                                          {step.status === 'pending' && (
                                            <Clock className="h-4.5 w-4.5 text-slate-600" />
                                          )}
                                        </div>
                                        <div>
                                          <h4
                                            className={`text-xs font-medium ${isExecuting ? 'text-indigo-200' : 'text-slate-300'}`}
                                          >
                                            {step.description}
                                          </h4>
                                        </div>
                                      </div>
                                      <Badge
                                        variant={
                                          isCompleted
                                            ? 'success'
                                            : isExecuting
                                              ? 'default'
                                              : isFailed
                                                ? 'destructive'
                                                : 'outline'
                                        }
                                        className={
                                          isExecuting
                                            ? 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20 shadow-none'
                                            : isCompleted
                                              ? 'shadow-none bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                                              : isFailed
                                                ? 'shadow-none bg-rose-500/10 text-rose-400 border-rose-500/20'
                                                : 'shadow-none border-slate-800 text-slate-500'
                                        }
                                      >
                                        {step.status === 'completed'
                                          ? '已完成'
                                          : step.status === 'executing'
                                            ? '执行中'
                                            : step.status === 'failed'
                                              ? '执行失败'
                                              : '待处理'}
                                      </Badge>
                                    </div>

                                    {/* Screenshot visual verification section */}
                                    {step.result?.screenshotPath && (
                                      <div className="mt-3.5 pt-3.5 border-t border-slate-800/60 space-y-3 bg-slate-950/50 p-3.5 rounded-lg border border-slate-850">
                                        <div className="flex items-center justify-between">
                                          <div className="flex items-center space-x-2">
                                            <ImageIcon className="h-3.5 w-3.5 text-indigo-400" />
                                            <span className="text-[11px] text-slate-300 font-medium">
                                              📷 真实物理看板快照已生成：
                                            </span>
                                          </div>
                                          <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => setSelectedScreenshot(step.result.screenshotPath)}
                                            className="h-6 text-[10px] text-indigo-400 hover:text-indigo-300 hover:bg-indigo-500/10 transition-colors px-2"
                                          >
                                            <span>查看高清原图</span>
                                            <Maximize2 className="h-2.5 w-2.5 ml-1" />
                                          </Button>
                                        </div>
                                        <div className="relative group overflow-hidden rounded-xl border border-slate-800 bg-slate-900 aspect-video">
                                          <img
                                            src={step.result.screenshotPath}
                                            alt="物理界面快照"
                                            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                                          />
                                          <div className="absolute inset-0 bg-slate-950/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center backdrop-blur-xs">
                                            <Button
                                              variant="secondary"
                                              size="sm"
                                              onClick={() => setSelectedScreenshot(step.result.screenshotPath)}
                                              className="text-xs"
                                            >
                                              点击查看大图
                                            </Button>
                                          </div>
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </CardContent>
                          </Card>
                        )}
                      </div>

                      {m.role === 'user' && (
                        <Avatar className="h-9 w-9 border border-indigo-500/30 shadow-md shrink-0">
                          <AvatarFallback className="bg-indigo-600 text-white text-xs font-mono">U</AvatarFallback>
                        </Avatar>
                      )}
                    </div>
                  ))}
                  {/* 🌟 历史消息底座锚点：配合 useEffect 物理高稳定滚动对齐 */}
                  <div ref={messagesEndRef} />
                </div>
              </div>

              {/* Input area */}
              <div className="p-4 border-t border-slate-800 bg-slate-900/40 backdrop-blur-sm absolute bottom-0 left-0 right-0 z-10">
                <form onSubmit={handleSend} className="max-w-3xl mx-auto">
                  <div className="relative flex items-center">
                    <Input
                      type="text"
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      placeholder="发送您的业务诉求（例如：'帮我查下 ORD-98712 的发货状态'）..."
                      disabled={isSubmitting || !activeThreadId}
                      className="w-full bg-slate-950/80 border-slate-850 text-slate-100 rounded-xl pl-4 pr-16 py-6 text-sm focus-visible:ring-indigo-500 transition-colors placeholder-slate-500 disabled:opacity-50 font-sans"
                    />
                    <div className="absolute right-2">
                      <Button
                        type="submit"
                        disabled={isSubmitting || !input.trim() || !activeThreadId}
                        className="bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg h-9 px-4 text-xs font-semibold transition flex items-center justify-center space-x-1.5 disabled:opacity-50"
                      >
                        {isSubmitting ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <>
                            <span>发送</span>
                            <Send className="h-3.5 w-3.5" />
                          </>
                        )}
                      </Button>
                    </div>
                  </div>
                </form>
              </div>
            </main>

            {/* Right Execution Detail Logging Panel */}
            <section className="w-full md:w-96 bg-slate-900/50 p-6 flex flex-col justify-between border-t md:border-t-0 border-slate-800 overflow-hidden">
              <div className="space-y-6 flex-1 flex flex-col min-h-0 mb-4">
                <div className="flex items-center justify-between shrink-0">
                  <div className="flex items-center space-x-2">
                    <Cpu className="h-4.5 w-4.5 text-indigo-400 animate-spin-slow shrink-0" />
                    <h2 className="text-sm font-bold tracking-wider text-slate-200 uppercase">
                      有向有环图（DAG）实时执行监控
                    </h2>
                  </div>
                  {tokensConsumed > 0 && (
                    <Badge
                      variant="outline"
                      className="border-indigo-500/30 text-indigo-400 bg-indigo-950/10 font-mono text-[10px] px-1.5 py-0.5 shrink-0"
                    >
                      {tokensConsumed} Tokens
                    </Badge>
                  )}
                </div>

                <div className="flex-1 overflow-y-auto pr-2 min-h-0">
                  <div className="space-y-4">
                    {/* 🛡️ HUMAN-IN-THE-LOOP (HITL) 人工授权核准/模拟后台审批面板 */}
                    {pendingApprovalsList.length > 0 && (
                      <Card className="border-amber-500/50 bg-amber-950/20 shadow-2xl animate-pulse border-l-4 border-l-amber-500 rounded-xl overflow-hidden">
                        <CardHeader className="p-3.5 pb-2 border-b border-amber-500/15 bg-amber-500/5">
                          <div className="flex items-center space-x-2">
                            <Shield className="h-4.5 w-4.5 text-amber-400 animate-bounce shrink-0" />
                            <span className="text-[11px] font-bold text-amber-300 uppercase tracking-wider">
                              🛡️ 安全红线拦截：待人工核准放行
                            </span>
                          </div>
                        </CardHeader>
                        <CardContent className="p-3.5 space-y-3">
                          <div className="text-xs text-slate-300 leading-relaxed font-sans">
                            决策引擎拦截了高危动作：
                            <strong className="text-amber-300 font-semibold">
                              {pendingApprovalsList[0].actionType}
                            </strong>
                            。
                            <div className="mt-1.5 text-[10px] text-slate-400 font-mono bg-slate-950/40 p-2 rounded border border-slate-850 overflow-x-auto">
                              参数: {JSON.stringify(pendingApprovalsList[0].actionPayload?.args || {})}
                            </div>
                          </div>

                          <div className="space-y-2">
                            <Input
                              type="text"
                              value={rejectionInput}
                              onChange={(e) => setRejectionReason(e.target.value)}
                              placeholder="若驳回，请在此处输入拒绝原因..."
                              className="w-full bg-slate-950 text-xs py-1 border-slate-850 focus-visible:ring-amber-500 text-slate-100 rounded-lg placeholder-slate-600"
                            />
                            <div className="flex gap-2">
                              <Button
                                onClick={() => handleApprovalAction(pendingApprovalsList[0].id, 'approve')}
                                className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg h-8 text-[10px] font-bold transition flex items-center justify-center space-x-1"
                              >
                                <CheckCircle2 className="h-3 w-3" />
                                <span>核准放行 (Approve)</span>
                              </Button>
                              <Button
                                onClick={() => handleApprovalAction(pendingApprovalsList[0].id, 'reject')}
                                variant="destructive"
                                className="flex-1 bg-rose-600 hover:bg-rose-500 text-white rounded-lg h-8 text-[10px] font-bold transition flex items-center justify-center space-x-1"
                              >
                                <XCircle className="h-3 w-3" />
                                <span>驳回申请 (Reject)</span>
                              </Button>
                            </div>
                          </div>
                        </CardContent>
                      </Card>
                    )}

                    {runningDetails.length === 0 ? (
                      <div className="py-20 text-center space-y-3">
                        <Clock className="h-8 w-8 text-slate-600 mx-auto animate-pulse" />
                        <p className="text-xs text-slate-500 leading-relaxed">
                          等待触发会话...
                          <br />
                          输入消息后，此处将呈现详细的后台运行节点数据流。
                        </p>
                      </div>
                    ) : (
                      runningDetails.map((log, lIdx) => (
                        <Card
                          key={lIdx}
                          className="bg-slate-950/60 border-slate-800 shadow-lg border-l-2 border-l-indigo-500"
                        >
                          <CardHeader className="p-3 pb-1.5 flex flex-row items-center justify-between space-y-0">
                            <Badge className="bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded-md font-mono text-[10px] px-2 py-0.5">
                              {log.node}
                            </Badge>
                            <span className="text-[9px] text-slate-500 font-mono">STEP {lIdx + 1}</span>
                          </CardHeader>
                          <CardContent className="p-3 pt-0 space-y-2">
                            <p className="text-xs text-slate-300 leading-relaxed font-medium">{log.desc}</p>
                            <div className="bg-slate-900/80 p-2.5 rounded-lg border border-slate-850/80">
                              <span className="text-[10px] text-slate-500 block font-mono uppercase tracking-wider mb-1">
                                执行反馈/输出
                              </span>
                              <span
                                className={`text-xs font-mono leading-relaxed block whitespace-pre-wrap ${log.resultText.includes('❌') || log.resultText.includes('failed') ? 'text-rose-400' : 'text-emerald-400'}`}
                              >
                                {log.resultText}
                              </span>
                            </div>
                          </CardContent>
                        </Card>
                      ))
                    )}

                    {/* Live planning box at the bottom */}
                    {activePlan && (
                      <Card className="border-indigo-500/40 bg-indigo-950/10 shadow-2xl animate-fade-in border-l-2 border-l-indigo-400">
                        <CardHeader className="p-3 pb-2 border-b border-indigo-500/15">
                          <div className="flex items-center space-x-2">
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-400" />
                            <span className="text-[11px] font-bold text-indigo-300 uppercase tracking-wider">
                              实时生成执行规划图
                            </span>
                          </div>
                        </CardHeader>

                        <CardContent className="p-3 space-y-2">
                          <div className="text-[10px] text-slate-400 mb-1 font-semibold">目标: {activePlan.goal}</div>
                          {activePlan.subtasks.map((step) => (
                            <div
                              key={step.id}
                              className="flex items-center justify-between text-[11px] bg-slate-950/80 p-2 rounded-lg border border-slate-850"
                            >
                              <span className="text-slate-300 truncate pr-2 max-w-[180px]">{step.description}</span>
                              <Badge
                                variant={
                                  step.status === 'completed'
                                    ? 'success'
                                    : step.status === 'executing'
                                      ? 'default'
                                      : 'outline'
                                }
                                className={`text-[9px] px-1.5 py-0 shadow-none ${
                                  step.status === 'completed'
                                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/15'
                                    : step.status === 'executing'
                                      ? 'bg-indigo-500/15 text-indigo-400 border border-indigo-500/20'
                                      : 'border-slate-800 text-slate-500'
                                }`}
                              >
                                {step.status === 'completed'
                                  ? '已完成'
                                  : step.status === 'executing'
                                    ? '执行中'
                                    : '未开始'}
                              </Badge>
                            </div>
                          ))}
                        </CardContent>
                      </Card>
                    )}
                  </div>
                </div>
              </div>

              <div className="pt-4 border-t border-slate-800 space-y-3.5">
                <div>
                  <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block">
                    观测探针运行状态
                  </span>
                  <span className="text-xs text-slate-400 font-medium mt-1 block flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse shrink-0" />
                    本地 LangGraph 探针已激活
                  </span>
                </div>

                <div className="pt-3 border-t border-slate-800/60">
                  <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block">
                    单次会话算力消耗
                  </span>
                  <span className="text-xs text-indigo-400 font-mono font-medium mt-1 block flex items-center gap-1.5">
                    <Cpu className="h-3.5 w-3.5 animate-pulse shrink-0" />
                    <span>
                      已消耗 Token: <strong className="text-slate-100 font-bold text-sm">{tokensConsumed}</strong>
                    </span>
                  </span>
                </div>
              </div>
            </section>
          </>
        ) : (
          /* 🛡️ smartServe 客服大盘核签与安全中心 */
          <div className="flex-1 flex flex-col bg-slate-950 p-6 overflow-hidden">
            {/* Header */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800 shrink-0">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Shield className="h-5 w-5 text-indigo-400" />
                  <h1 className="text-lg font-bold tracking-tight text-slate-100 uppercase">
                    smartServe 客服安全审查与核签大盘
                  </h1>
                </div>
                <p className="text-xs text-slate-500 font-medium">
                  全渠道多租户 Human-in-the-Loop 安全拦截工单审计平台
                </p>
              </div>
              <div className="flex gap-1.5 bg-slate-900 p-1 rounded-xl border border-slate-800 self-start shrink-0">
                {(['ALL', 'WAITING', 'APPROVED', 'REJECTED', 'EXPIRED'] as const).map((filter) => {
                  const count = allApprovals.filter(
                    (a) => filter === 'ALL' || a.status.toUpperCase() === filter,
                  ).length;
                  const labelMap = {
                    ALL: '全部',
                    WAITING: '待审批',
                    APPROVED: '已核准',
                    REJECTED: '已驳回',
                    EXPIRED: '已超时',
                  };
                  const active = auditFilter === filter;

                  return (
                    <button
                      key={filter}
                      type="button"
                      onClick={() => {
                        setAuditFilter(filter);
                        setSelectedApprovalId(null);
                      }}
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold tracking-wide transition flex items-center gap-1.5 ${
                        active
                          ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/10'
                          : 'text-slate-400 hover:text-slate-200 bg-transparent'
                      }`}
                    >
                      <span>{labelMap[filter]}</span>
                      <span
                        className={`text-[10px] px-1 rounded-md ${active ? 'bg-indigo-700 text-white' : 'bg-slate-800 text-slate-500'}`}
                      >
                        {count}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Content Area */}
            <div className="flex-1 flex gap-6 overflow-hidden pt-6">
              {/* Left Column: Approvals List */}
              <div className="w-80 md:w-96 flex flex-col bg-slate-900/40 rounded-2xl border border-slate-900 overflow-y-auto shrink-0 p-3 space-y-2">
                <span className="text-[10px] font-bold text-slate-500 tracking-wider uppercase block px-2 mb-1">
                  安全审核工单清单 (
                  {allApprovals.filter((a) => auditFilter === 'ALL' || a.status.toUpperCase() === auditFilter).length})
                </span>
                {allApprovals.filter((a) => auditFilter === 'ALL' || a.status.toUpperCase() === auditFilter).length ===
                0 ? (
                  <div className="py-20 text-center flex flex-col items-center justify-center gap-3">
                    <CheckCircle2 className="h-8 w-8 text-slate-700 animate-pulse" />
                    <span className="text-xs text-slate-500 font-medium">当前列表下没有任何审核工单</span>
                  </div>
                ) : (
                  allApprovals
                    .filter((a) => auditFilter === 'ALL' || a.status.toUpperCase() === auditFilter)
                    .map((item) => {
                      const active = selectedApprovalId === item.id;
                      const dateStr = new Date(item.createdAt).toLocaleString([], {
                        month: '2-digit',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit',
                      });

                      const badgeStyle =
                        {
                          waiting: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
                          approved: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
                          rejected: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
                          expired: 'bg-slate-800 text-slate-500 border-transparent',
                        }[item.status as 'waiting' | 'approved' | 'rejected' | 'expired'] ||
                        'bg-slate-800 text-slate-400 border-transparent';

                      const statusTextMap = {
                        waiting: '待审批',
                        approved: '已核准',
                        rejected: '已驳回',
                        expired: '已超时',
                      };

                      return (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => setSelectedApprovalId(item.id)}
                          className={`w-full text-left p-3.5 rounded-xl border transition group ${
                            active
                              ? 'bg-indigo-600/10 border-indigo-500/30'
                              : 'bg-slate-900 border-slate-850/60 hover:bg-slate-850/40 hover:border-slate-800'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2 mb-2">
                            <span className="text-xs font-bold text-slate-200 truncate font-mono">
                              ID: {item.id.substring(0, 8)}...
                            </span>
                            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${badgeStyle}`}>
                              {statusTextMap[item.status as 'waiting' | 'approved' | 'rejected' | 'expired'] ||
                                item.status}
                            </span>
                          </div>
                          <div className="text-xs text-slate-300 font-semibold mb-1">
                            动作类别: <span className="text-indigo-400 font-bold">{item.actionType}</span>
                          </div>
                          <div className="flex items-center justify-between mt-2.5 pt-2 border-t border-slate-800/60 text-[10px] text-slate-500 font-mono">
                            <span>{dateStr}</span>
                            <span className="truncate max-w-[150px]">会话: {item.threadId.substring(0, 10)}...</span>
                          </div>
                        </button>
                      );
                    })
                )}
              </div>

              {/* Right Column: Selected Approval Detail view */}
              <div className="flex-1 bg-slate-900/20 border border-slate-900 rounded-2xl p-6 overflow-y-auto">
                {(() => {
                  const selectedApproval = allApprovals.find((a) => a.id === selectedApprovalId);
                  if (!selectedApproval) {
                    return (
                      <div className="h-full flex flex-col items-center justify-center text-center gap-3">
                        <Shield className="h-10 w-10 text-slate-850" />
                        <h3 className="text-sm font-semibold text-slate-400">请在左侧选择一个安全核签工单</h3>
                        <p className="text-xs text-slate-600 max-w-[280px]">
                          选择工单后，此处将全量展示拦截现场的业务上下文、参数序列、及管理员审批决策动作。
                        </p>
                      </div>
                    );
                  }

                  const deadlineObj = new Date(selectedApproval.deadline);
                  const isExpired = new Date() > deadlineObj;
                  const formattedPayload = JSON.stringify(
                    selectedApproval.actionPayload?.args || selectedApproval.actionPayload || {},
                    null,
                    2,
                  );

                  const statusBadges =
                    {
                      waiting: 'bg-amber-500/10 text-amber-400 border-amber-500/30 shadow-lg shadow-amber-500/5',
                      approved: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
                      rejected: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
                      expired: 'bg-slate-800 text-slate-500 border-transparent',
                    }[selectedApproval.status as 'waiting' | 'approved' | 'rejected' | 'expired'] || '';

                  return (
                    <div className="space-y-6">
                      {/* Top detail head */}
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-bold text-slate-100 font-mono">
                              工单: {selectedApproval.id}
                            </span>
                            <span className={`text-xs font-bold px-2.5 py-0.5 rounded border ${statusBadges}`}>
                              {selectedApproval.status === 'waiting'
                                ? '待审批 (Waiting)'
                                : selectedApproval.status === 'approved'
                                  ? '已核准 (Approved)'
                                  : selectedApproval.status === 'rejected'
                                    ? '已驳回 (Rejected)'
                                    : '已超时 (Expired)'}
                            </span>
                          </div>
                          <p className="text-xs text-slate-500">
                            拦截触发时间: {new Date(selectedApproval.createdAt).toLocaleString()}
                          </p>
                        </div>
                      </div>

                      {/* Detail metadata cards */}
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <Card className="bg-slate-900 border-slate-850">
                          <CardContent className="p-4 space-y-1.5">
                            <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block">
                              会话通道 (Thread Session)
                            </span>
                            <span className="text-xs font-semibold text-slate-300 block font-mono leading-relaxed truncate">
                              {selectedApproval.threadId}
                            </span>
                          </CardContent>
                        </Card>
                        <Card className="bg-slate-900 border-slate-850">
                          <CardContent className="p-4 space-y-1.5">
                            <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block">
                              截止自动释放日期 (Deadline)
                            </span>
                            <span
                              className={`text-xs font-semibold block font-mono leading-relaxed ${isExpired && selectedApproval.status === 'waiting' ? 'text-rose-400' : 'text-slate-300'}`}
                            >
                              {deadlineObj.toLocaleString()}{' '}
                              {isExpired && selectedApproval.status === 'waiting' && ' [已超时]'}
                            </span>
                          </CardContent>
                        </Card>
                      </div>

                      {/* JSON Payload arguments */}
                      <div className="space-y-2">
                        <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block font-semibold">
                          拦截动作及物理参数 (Action Payload Arguments)
                        </span>
                        <div className="bg-slate-950 p-4 rounded-xl border border-slate-850 font-mono text-xs leading-relaxed text-indigo-300 whitespace-pre-wrap max-h-60 overflow-y-auto shadow-inner">
                          {formattedPayload}
                        </div>
                      </div>

                      {/* Action desk if status is waiting */}
                      {selectedApproval.status === 'waiting' ? (
                        <div className="space-y-4 pt-4 border-t border-slate-800">
                          <div className="space-y-2">
                            <span className="text-[11px] text-slate-400 font-semibold uppercase font-sans tracking-wide block">
                              审核操作理由 (可留空，驳回时用户可见)
                            </span>
                            <Input
                              type="text"
                              value={rejectionInput}
                              onChange={(e) => setRejectionReason(e.target.value)}
                              placeholder="核准放行可留空。若驳回建议在此处输入具体的驳回原因..."
                              className="w-full bg-slate-950 text-xs py-2 border-slate-850 focus-visible:ring-indigo-500 text-slate-100 rounded-xl placeholder-slate-600"
                            />
                          </div>

                          <div className="flex gap-4">
                            <Button
                              onClick={async () => {
                                const actionId = selectedApproval.id;
                                await handleApprovalAction(actionId, 'approve');
                                // 强制切回聊天面板，前端会自动连接 SSE 订阅恢复决策流
                                setActiveTab('CHAT_DESK');
                              }}
                              disabled={isSubmitting}
                              className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl h-11 text-xs font-bold transition flex items-center justify-center space-x-1.5 shadow-lg shadow-emerald-600/10"
                            >
                              {isSubmitting ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <CheckCircle2 className="h-4.5 w-4.5" />
                              )}
                              <span>核准通过此申请 (Approve)</span>
                            </Button>
                            <Button
                              onClick={async () => {
                                const actionId = selectedApproval.id;
                                await handleApprovalAction(actionId, 'reject');
                                setActiveTab('CHAT_DESK');
                              }}
                              disabled={isSubmitting}
                              variant="destructive"
                              className="flex-1 bg-rose-600 hover:bg-rose-500 text-white rounded-xl h-11 text-xs font-bold transition flex items-center justify-center space-x-1.5 shadow-lg shadow-rose-600/10"
                            >
                              {isSubmitting ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <XCircle className="h-4.5 w-4.5" />
                              )}
                              <span>驳回此高危动作 (Reject)</span>
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="p-4 bg-slate-900 border border-slate-850 rounded-xl space-y-1">
                          <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block">
                            工单审计回执
                          </span>
                          <p className="text-xs text-slate-300 font-medium leading-relaxed font-sans">
                            本工单已被管理员处理完成，处理决议：
                            <strong
                              className={`font-bold ${selectedApproval.status === 'approved' ? 'text-emerald-400' : 'text-rose-400'}`}
                            >
                              {selectedApproval.status === 'approved'
                                ? '已核准放行'
                                : selectedApproval.status === 'rejected'
                                  ? '已驳回动作'
                                  : '已被系统自动超时拦截'}
                            </strong>
                            。
                          </p>
                          {selectedApproval.actionPayload?.rejectionReason && (
                            <p className="text-xs text-slate-500 mt-2 font-mono">
                              理由/说明: &quot;{selectedApproval.actionPayload.rejectionReason}&quot;
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
            </div>
          </div>
        )}
      </div>
      {selectedScreenshot && (
        <div className="fixed inset-0 bg-slate-950/95 backdrop-blur-md z-50 flex items-center justify-center p-6">
          <Card className="bg-slate-900 border-slate-800 max-w-4xl w-full overflow-hidden shadow-2xl">
            <CardHeader className="px-6 py-4 border-b border-slate-800 flex flex-row justify-between items-center space-y-0">
              <div className="flex items-center space-x-2.5">
                <ImageIcon className="h-4.5 w-4.5 text-indigo-400" />
                <CardTitle className="text-sm font-semibold text-slate-200">网页看板・快照渲染核验大图</CardTitle>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setSelectedScreenshot(null)}
                className="h-8 w-8 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg"
              >
                <X className="h-4.5 w-4.5" />
              </Button>
            </CardHeader>
            <CardContent className="p-6 bg-slate-950 flex items-center justify-center min-h-[350px]">
              <img
                src={selectedScreenshot}
                alt="Viewport Verification"
                className="max-h-[60vh] rounded-lg border border-slate-800 shadow-2xl object-contain bg-slate-900"
              />
            </CardContent>
            <CardFooter className="px-6 py-3 border-t border-slate-800 flex justify-end">
              <Button onClick={() => setSelectedScreenshot(null)} variant="secondary" size="sm">
                关闭大图
              </Button>
            </CardFooter>
          </Card>
        </div>
      )}
    </div>
  );
}
