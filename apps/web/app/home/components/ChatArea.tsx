import type React from "react";
import type { RunningDetail, TaskPlan } from "types";
import {
  Avatar,
  AvatarFallback,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CheckCircle2,
  Clock,
  ImageIcon,
  Input,
  Laptop,
  Loader2,
  Maximize2,
  MessageSquare,
  RefreshCw,
  Send,
  XCircle,
} from "ui";
import type { Message } from "../hooks/types";

interface ChatAreaProps {
  activeThreadId: string;
  messages: Message[];
  input: string;
  setInput: (val: string) => void;
  isSubmitting: boolean;
  loadHistory: (id: string) => Promise<void>;
  handleSend: (e: React.FormEvent) => Promise<void>;
  setActivePlan: (plan: TaskPlan | null) => void;
  setCurrentStepText: (text: string) => void;
  setRunningDetails: (
    details: RunningDetail[] | ((prev: RunningDetail[]) => RunningDetail[]),
  ) => void;
  setSelectedScreenshot: (url: string | null) => void;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  onStartHumanSupport?: () => void;
}

export function ChatArea({
  activeThreadId,
  messages,
  input,
  setInput,
  isSubmitting,
  loadHistory,
  handleSend,
  setActivePlan,
  setCurrentStepText,
  setRunningDetails,
  setSelectedScreenshot,
  messagesEndRef,
  onStartHumanSupport,
}: ChatAreaProps) {
  return (
    <main className="flex-1 flex flex-col h-full bg-slate-950 relative border-r border-slate-900">
      {/* Header */}
      <header className="px-6 py-4 border-b border-slate-800 bg-slate-900/60 backdrop-blur-md flex justify-between items-center z-10">
        <div className="flex items-center space-x-3 min-w-0">
          <div className="h-2.5 w-2.5 rounded-full bg-indigo-500 shadow-lg shadow-indigo-500/50 shrink-0" />
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 font-mono truncate">
            会话: {activeThreadId || "未选择任何对话"}
          </span>
        </div>
        <div className="flex items-center space-x-2.5 shrink-0">
          {onStartHumanSupport && (
            <Button
              variant="outline"
              size="sm"
              onClick={onStartHumanSupport}
              disabled={isSubmitting || !activeThreadId}
              className="h-8 px-2.5 text-xs font-medium border-indigo-500/40 bg-indigo-950/20 text-indigo-300 hover:bg-indigo-600 hover:text-white rounded-lg transition-all flex items-center gap-1.5"
            >
              <MessageSquare className="h-3.5 w-3.5 text-indigo-400" />
              <span>🎧 呼叫人工客服 (实时 IM)</span>
            </Button>
          )}
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
              setCurrentStepText("");
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
            <div
              key={idx}
              className={`flex gap-4 ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {m.role === "assistant" && (
                <Avatar className="h-9 w-9 border border-slate-800 shadow-md shrink-0">
                  <AvatarFallback className="bg-indigo-600/10 text-indigo-400 text-xs">
                    AI
                  </AvatarFallback>
                </Avatar>
              )}

              <div className="space-y-3.5 max-w-[85%] shrink-0">
                {/* Chat Message Box */}
                <div
                  className={`rounded-2xl px-5 py-4 text-sm leading-relaxed shadow-xl border ${
                    m.role === "user"
                      ? "bg-gradient-to-br from-indigo-600 to-indigo-700 text-white border-indigo-500/30"
                      : "bg-slate-900/90 text-slate-200 border-slate-800"
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
                        const isCompleted = step.status === "completed";
                        const isExecuting = step.status === "executing";
                        const isFailed = step.status === "failed";

                        return (
                          <div
                            key={step.id}
                            className={`p-3.5 rounded-xl border transition-all ${
                              isExecuting
                                ? "bg-indigo-950/20 border-indigo-500/40 shadow-inner"
                                : "bg-slate-950/40 border-slate-800/60"
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
                                  {isFailed && (
                                    <XCircle className="h-4.5 w-4.5 text-rose-500" />
                                  )}
                                  {step.status === "pending" && (
                                    <Clock className="h-4.5 w-4.5 text-slate-600" />
                                  )}
                                </div>
                                <div>
                                  <h4
                                    className={`text-xs font-medium ${isExecuting ? "text-indigo-200" : "text-slate-300"}`}
                                  >
                                    {step.description}
                                  </h4>
                                </div>
                              </div>
                              <Badge
                                variant={
                                  isCompleted
                                    ? "success"
                                    : isExecuting
                                      ? "default"
                                      : isFailed
                                        ? "destructive"
                                        : "outline"
                                }
                                className={
                                  isExecuting
                                    ? "bg-indigo-500/10 text-indigo-400 border-indigo-500/20 shadow-none"
                                    : isCompleted
                                      ? "shadow-none bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                                      : isFailed
                                        ? "shadow-none bg-rose-500/10 text-rose-400 border-rose-500/20"
                                        : "shadow-none border-slate-800 text-slate-500"
                                }
                              >
                                {step.status === "completed"
                                  ? "已完成"
                                  : step.status === "executing"
                                    ? "执行中"
                                    : step.status === "failed"
                                      ? "执行失败"
                                      : "待处理"}
                              </Badge>
                            </div>

                            {/* Screenshot visual verification section */}
                            {Boolean(step.result?.screenshotPath) && (
                              <div className="mt-3.5 pt-3.5 border-t border-slate-800/60 space-y-3 bg-slate-950/50 p-3.5 rounded-lg border border-slate-850">
                                <div className="flex items-center justify-between">
                                  <div className="flex items-center space-x-2">
                                    <span className="text-[11px] text-slate-300 font-medium flex items-center gap-1">
                                      <ImageIcon className="h-3.5 w-3.5 text-indigo-400" />
                                      📷 真实物理看板快照已生成：
                                    </span>
                                  </div>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() =>
                                      setSelectedScreenshot(
                                        String(
                                          step.result?.screenshotPath || "",
                                        ),
                                      )
                                    }
                                    className="h-6 text-[10px] text-indigo-400 hover:text-indigo-300 hover:bg-indigo-500/10 transition-colors px-2"
                                  >
                                    <span>查看高清原图</span>
                                    <Maximize2 className="h-2.5 w-2.5 ml-1" />
                                  </Button>
                                </div>
                                <div className="relative group overflow-hidden rounded-xl border border-slate-800 bg-slate-900 aspect-video">
                                  <img
                                    src={String(
                                      step.result?.screenshotPath || "",
                                    )}
                                    alt="物理界面快照"
                                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                                  />
                                  <div className="absolute inset-0 bg-slate-950/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center backdrop-blur-xs">
                                    <Button
                                      variant="secondary"
                                      size="sm"
                                      onClick={() =>
                                        setSelectedScreenshot(
                                          String(
                                            step.result?.screenshotPath || "",
                                          ),
                                        )
                                      }
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

              {m.role === "user" && (
                <Avatar className="h-9 w-9 border border-indigo-500/30 shadow-md shrink-0">
                  <AvatarFallback className="bg-indigo-600 text-white text-xs font-mono">
                    U
                  </AvatarFallback>
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
  );
}
