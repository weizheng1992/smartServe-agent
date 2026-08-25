'use client';

import { usePathname } from 'next/navigation';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Input } from 'ui';
import { useCurrentUser } from '../../context/UserContext';
import { type RouteGreetingContext, getGreetingForRoute } from './routeGreetingConfig';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  time: string;
}

export function FloatingChatWidget({
  contextOverride,
}: {
  contextOverride?: Partial<RouteGreetingContext>;
}) {
  const pathname = usePathname();
  const { user } = useCurrentUser();
  const [isOpen, setIsOpen] = useState(false);
  const [input, setInput] = useState('');
  const [threadId, setThreadId] = useState<string>('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isSending, setIsSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const hasInitializedRef = useRef(false);

  // 初始化对应用户的 threadId
  useEffect(() => {
    if (!user?.id) return;
    const storageKey = `aurora_store_thread_id_${user.id}`;
    let tid = localStorage.getItem(storageKey);
    if (!tid) {
      tid = `merchant_thread_${user.id}_aurora_${Date.now()}`;
      localStorage.setItem(storageKey, tid);
    }
    setThreadId(tid);
    hasInitializedRef.current = false;
  }, [user?.id]);

  // 从服务端拉取真实历史消息
  const fetchHistory = useCallback(async (currentTid: string) => {
    if (!currentTid) return false;
    try {
      const res = await fetch(`/api/store/chat/messages?threadId=${currentTid}&tenantId=aurora`);
      const data = await res.json();
      if (data.success && Array.isArray(data.messages) && data.messages.length > 0) {
        const formattedMsgs: ChatMessage[] = data.messages.map((m: any, idx: number) => ({
          id: m.id || `msg_hist_${idx}`,
          role: m.role === 'user' ? 'user' : 'assistant',
          text: m.content || m.text || '',
          time: m.createdAt
            ? new Date(m.createdAt).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
              })
            : new Date().toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
              }),
        }));
        setMessages(formattedMsgs);
        return true;
      }
    } catch (err) {
      console.error('Failed to load chat history:', err);
    }
    return false;
  }, []);

  // 挂载与 threadId 变更时加载历史记录，若为空则呈现路由感知问候语
  useEffect(() => {
    if (!threadId) return;
    let isMounted = true;

    const initChat = async () => {
      const hasHistory = await fetchHistory(threadId);
      if (!hasHistory && isMounted) {
        const greetingText = getGreetingForRoute({
          pathname,
          ...contextOverride,
        });
        setMessages([
          {
            id: `msg_init_${Date.now()}`,
            role: 'assistant',
            text: greetingText,
            time: new Date().toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            }),
          },
        ]);
      }
      hasInitializedRef.current = true;
    };

    initChat();

    return () => {
      isMounted = false;
    };
  }, [threadId, fetchHistory, pathname, contextOverride]);

  // 开启定期轮询，实时同步后台人工客服（Live Desk）回复
  useEffect(() => {
    if (!threadId) return;
    const interval = setInterval(() => {
      fetchHistory(threadId);
    }, 3000);
    return () => clearInterval(interval);
  }, [threadId, fetchHistory]);

  // 滚动到底部
  useEffect(() => {
    if (isOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isOpen]);

  // 开启新会话
  const handleStartNewThread = () => {
    if (!user?.id) return;
    const newTid = `merchant_thread_${user.id}_aurora_${Date.now()}`;
    const storageKey = `aurora_store_thread_id_${user.id}`;
    localStorage.setItem(storageKey, newTid);
    setThreadId(newTid);
    const greetingText = getGreetingForRoute({
      pathname,
      ...contextOverride,
    });
    setMessages([
      {
        id: `msg_new_${Date.now()}`,
        role: 'assistant',
        text: greetingText,
        time: new Date().toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        }),
      },
    ]);
  };

  // 发送消息到后端决策引擎
  const handleSendMessage = async (customMsg?: string) => {
    const msgToSend = (customMsg || input).trim();
    if (!msgToSend || isSending) return;

    const userTime = new Date().toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });

    const newMsg: ChatMessage = {
      id: `usr_${Date.now()}`,
      role: 'user',
      text: msgToSend,
      time: userTime,
    };

    setMessages((prev) => [...prev, newMsg]);
    if (!customMsg) setInput('');
    setIsSending(true);

    try {
      const res = await fetch('/api/store/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: msgToSend,
          threadId,
          userId: user.id,
          businessId: 'aurora',
          routeContext: {
            pathname,
            ...contextOverride,
          },
        }),
      });

      const data = await res.json();
      const replyText = data.output || data.result || '抱歉，客服服务遇到一点小问题，请稍候再试。';

      setMessages((prev) => [
        ...prev,
        {
          id: `ast_${Date.now()}`,
          role: 'assistant',
          text: replyText,
          time: new Date().toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          }),
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: `ast_err_${Date.now()}`,
          role: 'assistant',
          text: '网络通信异常，请检查商户后端服务连接。',
          time: new Date().toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          }),
        },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  return (
    <>
      {/* 右下角悬浮按钮 */}
      <div className="fixed bottom-6 right-6 z-40">
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          className="px-4 py-3 bg-emerald-600 text-white font-semibold rounded-full shadow-lg hover:bg-emerald-500 hover:shadow-xl transition-all flex items-center space-x-2 text-xs border-2 border-white cursor-pointer"
        >
          <span className="text-base">💬</span>
          <span>极光智能客服</span>
        </button>
      </div>

      {/* 客服对话挂件窗口 */}
      {isOpen && (
        <div className="fixed bottom-20 right-6 z-50 w-96 max-w-[calc(100vw-2rem)] h-[520px] bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col overflow-hidden animate-in fade-in slide-in-from-bottom-4">
          {/* Header */}
          <div className="bg-emerald-700 text-white px-4 py-3 flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-300 animate-pulse" />
              <div>
                <div className="font-bold text-xs flex items-center space-x-1">
                  <span>极光潮品 AI 智能助理</span>
                  <span className="text-[10px] bg-emerald-800 text-emerald-200 px-1.5 py-0.2 rounded">{user.name}</span>
                </div>
                <div className="text-[10px] text-emerald-200 truncate max-w-[200px]">{pathname} · 历史记录已同步</div>
              </div>
            </div>
            <div className="flex items-center space-x-2">
              <button
                type="button"
                onClick={handleStartNewThread}
                title="开启新对话"
                className="text-[11px] bg-emerald-800/80 hover:bg-emerald-800 text-emerald-100 px-2 py-0.5 rounded cursor-pointer transition"
              >
                + 新对话
              </button>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="text-white/80 hover:text-white text-lg font-bold p-1 cursor-pointer"
              >
                ✕
              </button>
            </div>
          </div>

          {/* 快捷推荐提示胶囊 */}
          <div className="bg-emerald-50 px-3 py-1.5 border-b border-emerald-100 flex items-center space-x-1.5 overflow-x-auto text-[11px] text-emerald-800 shrink-0">
            <span className="font-semibold shrink-0">快捷提问:</span>
            <button
              type="button"
              onClick={() => handleSendMessage('查询我的全部订单')}
              className="px-2 py-0.5 bg-white rounded border border-emerald-200 hover:bg-emerald-100 shrink-0 cursor-pointer"
            >
              📦 查所有订单
            </button>
            <button
              type="button"
              onClick={() => handleSendMessage('推荐当季热销机能外套')}
              className="px-2 py-0.5 bg-white rounded border border-emerald-200 hover:bg-emerald-100 shrink-0 cursor-pointer"
            >
              🧥 推荐热销
            </button>
            <button
              type="button"
              onClick={() => handleSendMessage('修改未发货订单地址')}
              className="px-2 py-0.5 bg-white rounded border border-emerald-200 hover:bg-emerald-100 shrink-0 cursor-pointer"
            >
              📍 改收货地址
            </button>
          </div>

          {/* 对话消息流 */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-50/50">
            {messages.map((m) => (
              <div key={m.id} className={`flex flex-col ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
                <div
                  className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-xs leading-relaxed shadow-2xs whitespace-pre-wrap ${
                    m.role === 'user'
                      ? 'bg-emerald-600 text-white rounded-br-none'
                      : 'bg-white text-slate-800 border border-slate-200 rounded-bl-none'
                  }`}
                >
                  {m.text}
                </div>
                <span className="text-[10px] text-slate-400 mt-1 px-1">{m.time}</span>
              </div>
            ))}
            {isSending && (
              <div className="flex items-center space-x-2 text-xs text-slate-400 bg-white p-2.5 rounded-xl border border-slate-200 w-fit">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping" />
                <span>AI 助理正在思考与检索中...</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* 底部输入框 */}
          <div className="p-3 bg-white border-t border-slate-200 flex items-center space-x-2">
            <Input
              type="text"
              placeholder="请输入您的问题或指令..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
              disabled={isSending}
              className="text-xs flex-1 h-9"
            />
            <Button
              type="button"
              size="sm"
              onClick={() => handleSendMessage()}
              disabled={!input.trim() || isSending}
              className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs h-9 px-3 shrink-0"
            >
              发送
            </Button>
          </div>
        </div>
      )}
    </>
  );
}
