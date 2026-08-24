'use client';

import React, { useEffect, useState } from 'react';
import {
  Bot,
  Button,
  ChevronRight,
  Input,
  Loader2,
  Maximize2,
  MessageSquare,
  RichCardRenderer,
  Send,
  Sparkles,
  User,
  X,
} from 'ui';

export interface ChatWidgetProps {
  businessId?: string;
  themeColor?: string;
  brandName?: string;
  brandLogoUrl?: string;
  welcomeText?: string;
  initialOpen?: boolean;
}

export function ChatWidget({
  businessId = 'ecommerce',
  themeColor = '#4f46e5',
  brandName = '官方智能客服',
  brandLogoUrl,
  welcomeText = '您好！我是您的专属智能客服助手，请问有什么可以帮您？',
  initialOpen = false,
}: ChatWidgetProps) {
  const [isOpen, setIsOpen] = useState(initialOpen);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<Array<{ id: string; role: string; content: string; cards?: any[] }>>([
    {
      id: 'welcome',
      role: 'assistant',
      content: welcomeText,
    },
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const [threadId] = useState(() => `widget_thread_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`);

  // 动态注入商户 CSS 主题变量
  useEffect(() => {
    document.documentElement.style.setProperty('--widget-theme-color', themeColor);
  }, [themeColor]);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    const text = input.trim();
    setInput('');

    const userMsg = { id: `u_${Date.now()}`, role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const res = await fetch('http://localhost:4000/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-tenant-id': businessId,
        },
        body: JSON.stringify({
          message: text,
          threadId,
          businessId,
          sync: true,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setMessages((prev) => [
          ...prev,
          {
            id: `a_${Date.now()}`,
            role: 'assistant',
            content: data.output || data.result || '已为您处理完毕。',
            cards: data.cards || [],
          },
        ]);
      } else {
        setMessages((prev) => [
          ...prev,
          {
            id: `err_${Date.now()}`,
            role: 'assistant',
            content: '抱歉，当前网络异常，请稍后重试。',
          },
        ]);
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: `err_${Date.now()}`,
          role: 'assistant',
          content: '连接网关失败，请确保本地服务正常运行。',
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col items-end font-sans">
      {/* 💬 Expanded Chatbot Container */}
      {isOpen && (
        <div className="w-[380px] h-[580px] mb-4 bg-slate-900 border border-slate-800 rounded-3xl shadow-2xl flex flex-col overflow-hidden animate-in fade-in slide-in-from-bottom-5 duration-200">
          {/* Header */}
          <div
            className="p-4 flex items-center justify-between text-white border-b border-slate-800"
            style={{ backgroundColor: themeColor }}
          >
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-full bg-white/20 flex items-center justify-center font-bold text-white shadow-inner">
                {brandLogoUrl ? (
                  <img src={brandLogoUrl} alt={brandName} className="w-6 h-6 rounded-full" />
                ) : (
                  <Bot className="w-5 h-5" />
                )}
              </div>
              <div>
                <h3 className="text-sm font-bold tracking-wide">{brandName}</h3>
                <div className="flex items-center gap-1 text-[10px] text-white/80">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                  <span>AI 在线客服</span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="p-1 rounded-lg hover:bg-white/10 text-white transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Message Feed */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-950/60">
            {messages.map((m) => {
              const isUser = m.role === 'user';
              return (
                <div key={m.id} className={`flex flex-col ${isUser ? 'items-end' : 'items-start'}`}>
                  <div
                    className={`max-w-[85%] p-3 rounded-2xl text-xs leading-relaxed ${
                      isUser
                        ? 'text-white rounded-tr-sm shadow-md'
                        : 'bg-slate-800 text-slate-200 border border-slate-700/80 rounded-tl-sm'
                    }`}
                    style={isUser ? { backgroundColor: themeColor } : undefined}
                  >
                    {m.content}
                    {m.cards && m.cards.length > 0 && (
                      <div className="mt-2 space-y-2">
                        <RichCardRenderer cards={m.cards} />
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {isLoading && (
              <div className="flex items-center gap-2 text-xs text-slate-400 bg-slate-800/60 p-2.5 rounded-xl w-fit">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-indigo-400" />
                <span>AI 正在查询并组织回复...</span>
              </div>
            )}
          </div>

          {/* Footer Input */}
          <div className="p-3 bg-slate-900 border-t border-slate-800 flex items-center gap-2">
            <Input
              placeholder="输入您的问题..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              className="h-9 text-xs bg-slate-950 border-slate-800 rounded-xl focus:border-indigo-500"
            />
            <Button
              size="icon"
              onClick={handleSend}
              disabled={isLoading || !input.trim()}
              className="h-9 w-9 rounded-xl text-white shadow-md disabled:opacity-50"
              style={{ backgroundColor: themeColor }}
            >
              <Send className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}

      {/* 🚀 Floating Trigger Bubble */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="h-14 w-14 rounded-full text-white shadow-2xl flex items-center justify-center transition-all transform hover:scale-105 active:scale-95 border-2 border-white/20"
        style={{ backgroundColor: themeColor }}
      >
        {isOpen ? <X className="w-6 h-6" /> : <MessageSquare className="w-6 h-6" />}
      </button>
    </div>
  );
}
