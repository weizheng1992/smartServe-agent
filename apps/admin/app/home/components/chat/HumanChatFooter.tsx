import type React from 'react';
import { Button, Input, Loader2, Send, Sparkles } from 'ui';

interface HumanChatFooterProps {
  replyMessage: string;
  setReplyMessage: (val: string) => void;
  isSubmitting: boolean;
  isEnding: boolean;
  handleSendMessage: (e?: React.FormEvent) => Promise<void>;
  handleFinishHumanChat: () => Promise<void>;
}

export function HumanChatFooter({
  replyMessage,
  setReplyMessage,
  isSubmitting,
  isEnding,
  handleSendMessage,
  handleFinishHumanChat,
}: HumanChatFooterProps) {
  return (
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

      <div className="flex items-center justify-between pt-2 border-t border-slate-900">
        <span className="text-[11px] text-slate-500">解答完毕后，点击右侧按钮结束人工对话并切回 AI 智能 Agent：</span>
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
  );
}
