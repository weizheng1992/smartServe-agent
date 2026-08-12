import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Avatar,
  AvatarFallback,
  Badge,
  Button,
  Card,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Loader2,
  MessageSquare,
  RefreshCw,
  Send,
  ShieldAlert,
  Sparkles,
  User,
  X,
} from "ui";
import type { Approval } from "../hooks/types";

interface MessageItem {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp?: string;
}

interface HumanChatModalProps {
  approval: Approval | null;
  isOpen: boolean;
  onClose: () => void;
  onSendReply: (
    approvalId: string,
    replyMessage: string,
    isFinish?: boolean,
  ) => Promise<void>;
}

export function HumanChatModal({
  approval,
  isOpen,
  onClose,
  onSendReply,
}: HumanChatModalProps) {
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [replyMessage, setReplyMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isEnding, setIsEnding] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const fetchHistory = useCallback(async () => {
    if (!approval?.threadId) return;
    try {
      const res = await fetch(
        `/api/chat/messages?threadId=${approval.threadId}`,
      );
      const data = await res.json();
      if (data.success && data.messages) {
        setMessages(data.messages);
      }
    } catch (err) {
      console.error("[HumanChatModal] Failed to fetch message history:", err);
    }
  }, [approval?.threadId]);

  // 1. 物理组件挂载 & 定时 2 秒无感高频轮询，保障实时 IM 聊天流畅同步！
  useEffect(() => {
    if (isOpen && approval) {
      setIsLoadingMessages(true);
      fetchHistory().finally(() => setIsLoadingMessages(false));
      setReplyMessage("");

      const interval = setInterval(fetchHistory, 2000);
      return () => clearInterval(interval);
    }
  }, [isOpen, approval, fetchHistory]);

  // 2. 消息物理变动时，滚动条平滑自动沉底
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  if (!isOpen || !approval) return null;

  // 3. 人工客服发送实时消息 (不结束对话，保持 IM 处于接管状态)
  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!replyMessage.trim() || isSubmitting) return;

    setIsSubmitting(true);
    try {
      const text = replyMessage.trim();
      setReplyMessage("");
      await onSendReply(approval.id, text, false);
      await fetchHistory();
    } catch (err) {
      console.error("[HumanChatModal] Error sending human message:", err);
    } finally {
      setIsSubmitting(false);
    }
  };

  // 4. 结束人工客服对话，并重新对接/切回 AI 智能 Agent
  const handleFinishHumanChat = async () => {
    setIsEnding(true);
    try {
      const text =
        replyMessage.trim() ||
        "人工客服为您服务完毕。现已为您重新对接 AI 智能助手！";
      await onSendReply(approval.id, text, true);
      onClose();
    } catch (err) {
      console.error(
        "[HumanChatModal] Error finishing human chat session:",
        err,
      );
    } finally {
      setIsEnding(false);
    }
  };

  const triggerReason =
    approval.actionPayload?.reason ||
    approval.actionPayload?.userInput ||
    "用户请求人工客服或触发系统安全熔断";

  return (
    <Dialog open={isOpen}>
      <DialogContent className="max-w-3xl bg-slate-900 border-slate-800 p-0 overflow-hidden shadow-2xl">
        {/* Header */}
        <DialogHeader className="bg-slate-950 px-6 py-4 border-b border-slate-800 flex flex-row items-center justify-between space-y-0">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-indigo-500/10 text-indigo-400 rounded-xl border border-indigo-500/20">
              <MessageSquare className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <DialogTitle className="text-sm font-bold text-slate-100">
                  人工客服 IM 实时工作台
                </DialogTitle>
                <Badge
                  variant="outline"
                  className="border-indigo-500/30 text-indigo-300 bg-indigo-950/20 font-mono text-[10px] uppercase font-bold"
                >
                  {approval.businessId || "ecommerce"}
                </Badge>
              </div>
              <DialogDescription className="text-[11px] font-mono text-slate-400 truncate max-w-md mt-0.5">
                Thread: {approval.threadId}
              </DialogDescription>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-8 w-8 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg"
          >
            <X className="h-4 w-4" />
          </Button>
        </DialogHeader>

        {/* Escalation Reason & Polling Status */}
        <div className="bg-amber-500/10 border-b border-amber-500/20 px-6 py-2.5 flex items-center justify-between">
          <div className="flex items-center space-x-2.5 min-w-0">
            <ShieldAlert className="h-4 w-4 text-amber-400 shrink-0 animate-pulse" />
            <span className="text-xs text-amber-200 font-medium truncate">
              <strong className="text-amber-400">熔断/介入原因:</strong>{" "}
              {triggerReason}
            </span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => fetchHistory()}
            className="text-amber-400 hover:text-amber-300 hover:bg-amber-500/10 h-7 text-xs flex items-center space-x-1 shrink-0 px-2"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>实时同步中</span>
          </Button>
        </div>

        {/* Messages Container */}
        <div
          ref={scrollRef}
          className="p-6 space-y-4 h-[380px] overflow-y-auto bg-slate-950/60"
        >
          {isLoadingMessages ? (
            <div className="flex items-center justify-center py-20 text-slate-500 space-x-2">
              <Loader2 className="h-5 w-5 animate-spin text-indigo-400" />
              <span className="text-xs font-medium">
                正在拉取 IM 实时对话记录...
              </span>
            </div>
          ) : messages.length === 0 ? (
            <div className="text-center py-20 text-slate-500 text-xs">
              暂无物理对话记录
            </div>
          ) : (
            messages.map((msg, idx) => {
              const isUser = msg.role === "user";
              const isSystem = msg.role === "system";

              if (isSystem) {
                return (
                  <div key={idx} className="flex justify-center my-2">
                    <Badge
                      variant="outline"
                      className="bg-slate-900/80 border-slate-800 text-slate-400 text-[10px] font-mono px-3 py-1"
                    >
                      {msg.content}
                    </Badge>
                  </div>
                );
              }

              return (
                <div
                  key={idx}
                  className={`flex items-start gap-3 ${
                    isUser ? "flex-row-reverse" : "flex-row"
                  }`}
                >
                  <Avatar className="h-8 w-8 border border-slate-800 shrink-0">
                    <AvatarFallback
                      className={`text-[11px] font-bold ${
                        isUser
                          ? "bg-indigo-600 text-white"
                          : "bg-amber-500/20 text-amber-400"
                      }`}
                    >
                      {isUser ? (
                        <User className="h-4 w-4" />
                      ) : (
                        <Sparkles className="h-4 w-4" />
                      )}
                    </AvatarFallback>
                  </Avatar>

                  <div className="max-w-[80%] space-y-1">
                    <div
                      className={`flex items-center gap-1.5 ${
                        isUser ? "justify-end" : "justify-start"
                      }`}
                    >
                      <span className="text-[10px] text-slate-400 font-mono">
                        {isUser
                          ? "客户"
                          : msg.content.startsWith("[人工客服]")
                            ? "人工客服"
                            : "AI Agent"}
                      </span>
                    </div>

                    <Card
                      className={`border p-3.5 text-xs leading-relaxed shadow-sm ${
                        isUser
                          ? "bg-indigo-600 text-white border-indigo-500/30 rounded-tr-none"
                          : "bg-slate-900 text-slate-200 border-slate-800 rounded-tl-none"
                      }`}
                    >
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                      {msg.timestamp && (
                        <span className="text-[9px] text-slate-400 mt-1 block opacity-70 font-mono">
                          {new Date(msg.timestamp).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                            second: "2-digit",
                          })}
                        </span>
                      )}
                    </Card>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Action Controls & Input */}
        <div className="p-4 bg-slate-950 border-t border-slate-800 space-y-3">
          <form onSubmit={handleSendMessage} className="flex gap-2">
            <Input
              type="text"
              value={replyMessage}
              onChange={(e) => setReplyMessage(e.target.value)}
              placeholder="输入消息，回车或点击【发送消息】可实时与客户对话..."
              className="bg-slate-900 border-slate-800 text-slate-100 placeholder-slate-500 text-xs h-10 focus-visible:ring-indigo-500"
              disabled={isSubmitting || isEnding}
            />

            <Button
              type="submit"
              disabled={isSubmitting || isEnding || !replyMessage.trim()}
              className="h-10 px-4 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl flex items-center gap-1.5 shrink-0"
            >
              {isSubmitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <>
                  <Send className="h-3.5 w-3.5" />
                  <span>发送消息</span>
                </>
              )}
            </Button>
          </form>

          {/* Handover back to Smart AI Agent */}
          <div className="flex items-center justify-between pt-2 border-t border-slate-900">
            <span className="text-[11px] text-slate-500">
              解答完毕后，点击右侧按钮结束人工对话并切回 AI 智能 Agent：
            </span>
            <Button
              type="button"
              onClick={handleFinishHumanChat}
              disabled={isEnding || isSubmitting}
              className="h-8 px-4 text-xs font-bold bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl flex items-center gap-1.5 transition"
            >
              {isEnding ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <>
                  <Sparkles className="h-3.5 w-3.5" />
                  <span>结束人工对话 (对接智能 Agent)</span>
                </>
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
