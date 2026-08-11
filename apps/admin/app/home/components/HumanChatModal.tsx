import React, { useCallback, useEffect, useState } from "react";
import {
  Button,
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
  onSendReply: (approvalId: string, replyMessage: string) => Promise<void>;
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

  const fetchHistory = useCallback(async () => {
    if (!approval?.threadId) return;
    setIsLoadingMessages(true);
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
    } finally {
      setIsLoadingMessages(false);
    }
  }, [approval?.threadId]);

  useEffect(() => {
    if (isOpen && approval) {
      fetchHistory();
      setReplyMessage("");
    }
  }, [isOpen, approval, fetchHistory]);

  if (!isOpen || !approval) return null;

  const handleSubmitReply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!replyMessage.trim()) return;
    setIsSubmitting(true);
    try {
      await onSendReply(approval.id, replyMessage.trim());
      onClose();
    } catch (err) {
      console.error("[HumanChatModal] Error submitting human reply:", err);
    } finally {
      setIsSubmitting(false);
    }
  };

  const triggerReason =
    approval.actionPayload?.reason ||
    approval.actionPayload?.userInput ||
    "用户请求人工客服或触发系统安全熔断";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 w-full max-w-2xl rounded-2xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden animate-in fade-in zoom-in duration-200">
        {/* Header */}
        <div className="bg-slate-950 px-6 py-4 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-indigo-500/10 text-indigo-400 rounded-xl border border-indigo-500/20">
              <MessageSquare className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h3 className="text-sm font-bold text-slate-100">
                  人工客服接管中心 (IM)
                </h3>
                <span className="text-[10px] font-mono px-2 py-0.5 bg-indigo-500/20 text-indigo-300 rounded-full font-bold uppercase">
                  {approval.businessId || "ecommerce"}
                </span>
              </div>
              <p className="text-[11px] font-mono text-slate-400 truncate max-w-md">
                Thread: {approval.threadId}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 p-1.5 rounded-lg hover:bg-slate-800 transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Escalation Reason Banner */}
        <div className="bg-amber-500/10 border-b border-amber-500/20 px-6 py-3 flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <ShieldAlert className="h-4 w-4 text-amber-400 shrink-0 animate-pulse" />
            <span className="text-xs text-amber-200 font-medium">
              <strong className="text-amber-400">熔断/介入原因:</strong>{" "}
              {triggerReason}
            </span>
          </div>
          <button
            onClick={fetchHistory}
            disabled={isLoadingMessages}
            className="text-amber-400 hover:text-amber-300 text-xs flex items-center space-x-1"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${isLoadingMessages ? "animate-spin" : ""}`}
            />
            <span>刷新</span>
          </button>
        </div>

        {/* Message History Container */}
        <div className="flex-1 p-6 overflow-y-auto space-y-4 min-h-[300px] max-h-[500px] bg-slate-950/50">
          {isLoadingMessages ? (
            <div className="flex items-center justify-center py-12 text-slate-500 space-x-2">
              <Loader2 className="h-5 w-5 animate-spin" />
              <span className="text-xs">正在加载历史会话记录...</span>
            </div>
          ) : messages.length === 0 ? (
            <div className="text-center py-12 text-slate-500 text-xs">
              暂无历史消息记录
            </div>
          ) : (
            messages.map((msg, idx) => {
              const isUser = msg.role === "user";
              return (
                <div
                  key={idx}
                  className={`flex items-start gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}
                >
                  <div
                    className={`p-2 rounded-xl text-xs flex items-center justify-center shrink-0 ${
                      isUser
                        ? "bg-indigo-600 text-white"
                        : "bg-slate-800 text-slate-300 border border-slate-700"
                    }`}
                  >
                    {isUser ? (
                      <User className="h-4 w-4" />
                    ) : (
                      <Sparkles className="h-4 w-4 text-amber-400" />
                    )}
                  </div>
                  <div
                    className={`max-w-[80%] rounded-2xl px-4 py-3 text-xs leading-relaxed ${
                      isUser
                        ? "bg-indigo-600 text-white font-medium rounded-tr-none"
                        : "bg-slate-900 border border-slate-800 text-slate-200 rounded-tl-none shadow-sm"
                    }`}
                  >
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                    {msg.timestamp && (
                      <span className="text-[9px] text-slate-400 mt-1 block opacity-70">
                        {new Date(msg.timestamp).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Input & Send Form */}
        <form
          onSubmit={handleSubmitReply}
          className="p-4 bg-slate-900 border-t border-slate-800 space-y-3"
        >
          <div className="flex gap-2">
            <Input
              type="text"
              value={replyMessage}
              onChange={(e) => setReplyMessage(e.target.value)}
              placeholder="请输入人工客服处理意见或回复客户消息..."
              className="bg-slate-950 border-slate-800 text-slate-100 placeholder-slate-500 text-xs h-10 focus-visible:ring-indigo-500"
              disabled={isSubmitting}
            />
            <Button
              type="submit"
              disabled={isSubmitting || !replyMessage.trim()}
              className="h-10 px-5 text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl flex items-center gap-2 shrink-0"
            >
              {isSubmitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <>
                  <Send className="h-4 w-4" />
                  <span>发送并解挂</span>
                </>
              )}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
