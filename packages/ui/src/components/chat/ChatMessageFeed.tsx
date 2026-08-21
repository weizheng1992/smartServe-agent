import type React from 'react';
import { Loader2, Sparkles, User } from '../icons';
import { Avatar, AvatarFallback } from '../ui/avatar';
import { Badge } from '../ui/badge';
import { Card } from '../ui/card';

export interface MessageItem {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
}

interface ChatMessageFeedProps {
  isLoadingMessages: boolean;
  messages: MessageItem[];
  scrollRef: React.RefObject<HTMLDivElement | null>;
}

export function ChatMessageFeed({ isLoadingMessages, messages, scrollRef }: ChatMessageFeedProps) {
  return (
    <div
      ref={scrollRef}
      className="p-6 space-y-4 h-[420px] max-h-[50vh] overflow-y-auto bg-slate-950/60 flex-1 min-h-0"
      style={{
        minHeight: '260px',
        maxHeight: '50vh',
        overflowY: 'auto',
      }}
    >
      {isLoadingMessages ? (
        <div className="flex items-center justify-center py-20 text-slate-500 space-x-2">
          <Loader2 className="h-5 w-5 animate-spin text-indigo-400" />
          <span className="text-xs font-medium">正在拉取 IM 实时对话记录...</span>
        </div>
      ) : messages.length === 0 ? (
        <div className="text-center py-20 text-slate-500 text-xs">暂无物理对话记录</div>
      ) : (
        messages.map((msg, idx) => {
          const isUser = msg.role === 'user';
          const isSystem = msg.role === 'system';

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
            <div key={idx} className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
              <Avatar className="h-8 w-8 border border-slate-800 shrink-0">
                <AvatarFallback
                  className={`text-[11px] font-bold ${
                    isUser ? 'bg-indigo-600 text-white' : 'bg-amber-500/20 text-amber-400'
                  }`}
                >
                  {isUser ? <User className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
                </AvatarFallback>
              </Avatar>

              <div className="max-w-[80%] space-y-1">
                <div className={`flex items-center gap-1.5 ${isUser ? 'justify-end' : 'justify-start'}`}>
                  <span className="text-[10px] text-slate-400 font-mono">
                    {isUser ? '客户' : msg.content.startsWith('[人工客服]') ? '人工客服' : 'AI Agent'}
                  </span>
                </div>

                <Card
                  className={`border p-3.5 text-xs leading-relaxed shadow-sm ${
                    isUser
                      ? 'bg-indigo-600 text-white border-indigo-500/30 rounded-tr-none'
                      : 'bg-slate-900 text-slate-200 border-slate-800 rounded-tl-none'
                  }`}
                >
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                  {msg.timestamp && (
                    <span className="text-[9px] text-slate-400 mt-1 block opacity-70 font-mono">
                      {new Date(msg.timestamp).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
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
  );
}
