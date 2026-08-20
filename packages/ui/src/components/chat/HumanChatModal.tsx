import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import { MessageSquare, RefreshCw, ShieldAlert, X } from "../icons";
import { ChatMessageFeed, type MessageItem } from "./ChatMessageFeed";
import { HumanChatFooter } from "./HumanChatFooter";

export interface ChatApprovalRecord {
  id: string;
  threadId: string;
  businessId?: string;
  status?: string;
  actionType?: string;
  actionPayload?: {
    reason?: string;
    userInput?: string;
    args?: Record<string, unknown>;
    [key: string]: unknown;
  } | null;
  [key: string]: unknown;
}

export interface HumanChatModalProps {
  approval: ChatApprovalRecord | null;
  isOpen: boolean;
  onClose: () => void;
  onSendReply: (
    approvalId: string,
    replyMessage: string,
    isFinish?: boolean,
  ) => Promise<unknown>;
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
        `/api/chat/messages?threadId=${encodeURIComponent(approval.threadId)}`,
      );
      const data = await res.json();
      if (data.success && data.messages) {
        setMessages(data.messages);
      }
    } catch (err) {
      console.error("[HumanChatModal] Failed to fetch message history:", err);
    }
  }, [approval?.threadId]);

  useEffect(() => {
    if (isOpen && approval) {
      setIsLoadingMessages(true);
      fetchHistory().finally(() => setIsLoadingMessages(false));
      setReplyMessage("");

      const interval = setInterval(fetchHistory, 2000);
      return () => clearInterval(interval);
    }
  }, [isOpen, approval, fetchHistory]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  if (!isOpen || !approval) return null;

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
      <DialogContent className="max-w-3xl bg-slate-900 border-slate-800 p-0 overflow-hidden shadow-2xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="bg-slate-950 px-6 py-4 border-b border-slate-800 flex flex-row items-center justify-between shrink-0">
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
        </div>

        {/* Escalation Reason */}
        <div className="bg-amber-500/10 border-b border-amber-500/20 px-6 py-2.5 flex items-center justify-between shrink-0">
          <div className="flex items-center space-x-2.5 min-w-0">
            <ShieldAlert className="h-4 w-4 text-amber-400 shrink-0 animate-pulse" />
            <span className="text-xs text-amber-200 font-medium truncate">
              <strong className="text-amber-400">熔断/介入原因:</strong>{" "}
              {String(triggerReason)}
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

        {/* Chat Feed */}
        <ChatMessageFeed
          isLoadingMessages={isLoadingMessages}
          messages={messages}
          scrollRef={scrollRef}
        />

        {/* Footer */}
        <HumanChatFooter
          replyMessage={replyMessage}
          setReplyMessage={setReplyMessage}
          isSubmitting={isSubmitting}
          isEnding={isEnding}
          handleSendMessage={handleSendMessage}
          handleFinishHumanChat={handleFinishHumanChat}
        />
      </DialogContent>
    </Dialog>
  );
}
