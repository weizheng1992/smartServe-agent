'use client';

import { usePathname } from 'next/navigation';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { RichCardBlock } from 'types';
import { Button, Input, RichCardRenderer } from 'ui';
import { useCurrentUser } from '../../context/UserContext';
import { type RouteGreetingContext, getGreetingForRoute } from './routeGreetingConfig';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  time: string;
  cards?: RichCardBlock[];
  isDivider?: boolean;
}

// 辅助函数：将对话中的购物车卡片物理同步到浏览器端 localStorage，并广播 cart_updated 事件
function syncCartToLocalStorage(cards?: RichCardBlock[]) {
  if (typeof window === 'undefined' || !cards || cards.length === 0) return;
  const cartCard = cards.find((c) => c.type === 'cart_card');
  if (!cartCard || !('items' in cartCard.data)) return;

  try {
    const rawStored = localStorage.getItem('aurora_store_cart');
    const existingCart: any[] = rawStored ? JSON.parse(rawStored) : [];
    const actionType = cartCard.data.actionType;

    if (actionType === 'cleared') {
      localStorage.setItem('aurora_store_cart', JSON.stringify([]));
      window.dispatchEvent(new Event('cart_updated'));
      window.dispatchEvent(new Event('storage'));
      return;
    }

    const items = cartCard.data.items || [];
    for (const item of items) {
      const skuCode = item.skuCode || item.skuId || item.id;
      if (!skuCode) continue;

      const idx = existingCart.findIndex((it: any) => (it.skuCode || it.sku?.skuCode || it.id) === skuCode);

      if (idx >= 0) {
        if (actionType === 'added') {
          existingCart[idx].quantity = (existingCart[idx].quantity || 0) + (item.quantity || 1);
        } else {
          existingCart[idx].quantity = item.quantity || 1;
        }
      } else {
        existingCart.push({
          id: skuCode,
          spuId: item.spuId || 'SPU-AURORA-001',
          skuCode: skuCode,
          title: item.title,
          skuTitle: item.specSummary || item.skuTitle || '官方精选规格',
          imageUrl:
            item.imageUrl ||
            'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=800&auto=format&fit=crop&q=60',
          price: Number(item.price || 899.0),
          quantity: Number(item.quantity || 1),
          stock: 99,
          specAttributes: {},
          selected: true,
          sku: {
            skuCode: skuCode,
            skuTitle: item.specSummary || item.skuTitle || '官方精选规格',
            price: Number(item.price || 899.0),
          },
          product: {
            id: item.spuId || 'SPU-AURORA-001',
            title: item.title,
          },
        });
      }
    }

    localStorage.setItem('aurora_store_cart', JSON.stringify(existingCart));
    window.dispatchEvent(new Event('cart_updated'));
    window.dispatchEvent(new Event('storage'));
  } catch (err) {
    console.warn('[FloatingChatWidget] Failed to sync cart to localStorage:', err);
  }
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
  const [userThreads, setUserThreads] = useState<any[]>([]);
  const [showHistoryList, setShowHistoryList] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const [hasMoreOlder, setHasMoreOlder] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messageContainerRef = useRef<HTMLDivElement>(null);
  const prevScrollHeightRef = useRef<number>(0);
  const isInitialLoadRef = useRef(true);

  // 消息变动时自动持久化至本地缓存 (按用户与会话隔离)
  useEffect(() => {
    if (typeof window === 'undefined' || !user?.id || !threadId) return;
    if (messages.length > 0) {
      try {
        localStorage.setItem(`aurora_chat_msgs_${user.id}_${threadId}`, JSON.stringify(messages));
      } catch {
        // ignore
      }
    }
  }, [messages, user?.id, threadId]);

  // 按需从服务端拉取用户历史会话列表或指定历史会话的消息
  const fetchHistory = useCallback(
    async (targetThreadId?: string) => {
      if (!user?.id) return;
      try {
        const queryTid = targetThreadId || '';
        const res = await fetch(`/api/store/chat/messages?threadId=${queryTid}&userId=${user.id}&tenantId=aurora`);
        const data = await res.json();
        if (data.success) {
          if (Array.isArray(data.userThreads)) {
            setUserThreads(data.userThreads);
          }
          if (targetThreadId && Array.isArray(data.messages) && data.messages.length > 0) {
            const formattedMsgs: ChatMessage[] = data.messages.map((m: any, idx: number) => ({
              id: m.id || `msg_hist_${idx}`,
              role: m.role === 'user' ? 'user' : 'assistant',
              text: m.content || m.text || '',
              cards: Array.isArray(m.cards) ? m.cards : [],
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
          }
        }
      } catch (err) {
        console.error('Failed to load chat history:', err);
      }
    },
    [user?.id],
  );

  // 下拉 / 触顶加载更早的历史聊天记录 (跨轮次与全量历史会话)
  const loadOlderHistory = useCallback(async () => {
    if (!user?.id || isLoadingOlder || !hasMoreOlder) return;
    setIsLoadingOlder(true);
    try {
      const container = messageContainerRef.current;
      if (container) {
        prevScrollHeightRef.current = container.scrollHeight;
      }

      const res = await fetch(`/api/store/chat/messages?userId=${user.id}&tenantId=aurora&includeOlder=true`);
      const data = await res.json();
      if (data.success && Array.isArray(data.allHistoricalMessages)) {
        const allMsgs = data.allHistoricalMessages;
        const currentTexts = new Set(messages.map((m) => `${m.role}:${m.text.trim()}`));
        const olderToAdd = allMsgs.filter(
          (m: any) =>
            !currentTexts.has(`${m.role === 'user' ? 'user' : 'assistant'}:${(m.content || m.text || '').trim()}`),
        );

        if (olderToAdd.length === 0) {
          setHasMoreOlder(false);
        } else {
          const formattedOlder: ChatMessage[] = olderToAdd.map((m: any, idx: number) => ({
            id: m.id || `hist_old_${idx}`,
            role: m.role === 'user' ? 'user' : 'assistant',
            text: m.content || m.text || '',
            cards: Array.isArray(m.cards) ? m.cards : [],
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

          setMessages((prev) => [
            {
              id: `sep_${Date.now()}`,
              role: 'assistant',
              text: `🕒 更早的历史会话记录 (${formattedOlder.length}条)`,
              time: '',
              isDivider: true,
            },
            ...formattedOlder,
            ...prev,
          ]);
          setHasMoreOlder(false);
        }
      } else {
        setHasMoreOlder(false);
      }
    } catch (err) {
      console.error('Failed to load older chat history:', err);
    } finally {
      setIsLoadingOlder(false);
      setTimeout(() => {
        const container = messageContainerRef.current;
        if (container && prevScrollHeightRef.current) {
          container.scrollTop = container.scrollHeight - prevScrollHeightRef.current;
        }
      }, 60);
    }
  }, [user?.id, isLoadingOlder, hasMoreOlder, messages]);

  // 监听向上滚动触顶触发下拉加载历史
  const handleScroll = () => {
    if (!messageContainerRef.current) return;
    if (messageContainerRef.current.scrollTop === 0 && hasMoreOlder && !isLoadingOlder) {
      loadOlderHistory();
    }
  };

  // 初始化对应用户的会话：优先从本地缓存或后端恢复活跃会话，避免切换路由时冲掉记录
  useEffect(() => {
    if (!user?.id) return;

    let activeTid = threadId;
    if (!activeTid && typeof window !== 'undefined') {
      activeTid =
        localStorage.getItem(`aurora_active_thread_${user.id}`) ||
        sessionStorage.getItem(`aurora_active_thread_${user.id}`) ||
        '';
    }

    // 1. 如果已有本地缓存的消息，秒级呈现
    if (activeTid && typeof window !== 'undefined') {
      const cached = localStorage.getItem(`aurora_chat_msgs_${user.id}_${activeTid}`);
      if (cached) {
        try {
          const parsed = JSON.parse(cached);
          if (Array.isArray(parsed) && parsed.length > 0) {
            setThreadId(activeTid);
            setMessages(parsed);
            fetchHistory(activeTid);
            return;
          }
        } catch {
          // ignore
        }
      }
    }

    // 2. 若无本地缓存，向后端查询该用户最新活跃会话
    fetch(`/api/store/chat/messages?userId=${user.id}&tenantId=aurora`)
      .then((res) => res.json())
      .then((data) => {
        if (data.success && data.threadId && Array.isArray(data.messages) && data.messages.length > 0) {
          setThreadId(data.threadId);
          if (typeof window !== 'undefined') {
            localStorage.setItem(`aurora_active_thread_${user.id}`, data.threadId);
          }
          const formattedMsgs: ChatMessage[] = data.messages.map((m: any, idx: number) => ({
            id: m.id || `msg_hist_${idx}`,
            role: m.role === 'user' ? 'user' : 'assistant',
            text: m.content || m.text || '',
            cards: Array.isArray(m.cards) ? m.cards : [],
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
          if (Array.isArray(data.userThreads)) {
            setUserThreads(data.userThreads);
          }
        } else {
          // 纯新会话：注入路由首句欢迎语
          const freshTid = activeTid || `merchant_thread_${user.id}_aurora_${Date.now()}`;
          setThreadId(freshTid);
          if (typeof window !== 'undefined') {
            localStorage.setItem(`aurora_active_thread_${user.id}`, freshTid);
          }
          const greetingText = getGreetingForRoute({
            pathname,
            ...contextOverride,
          });
          setMessages([
            {
              id: `msg_init_${Date.now()}`,
              role: 'assistant',
              text: greetingText,
              cards: [],
              time: new Date().toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
              }),
            },
          ]);
        }
      })
      .catch(() => {
        const freshTid = activeTid || `merchant_thread_${user.id}_aurora_${Date.now()}`;
        setThreadId(freshTid);
        const greetingText = getGreetingForRoute({
          pathname,
          ...contextOverride,
        });
        setMessages([
          {
            id: `msg_init_${Date.now()}`,
            role: 'assistant',
            text: greetingText,
            cards: [],
            time: new Date().toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            }),
          },
        ]);
      });
  }, [user?.id]);

  // 路由切换时仅在会话为空时更新欢迎语，不覆盖已有聊天记录
  useEffect(() => {
    if (messages.length === 1 && messages[0].id.startsWith('msg_init_')) {
      const greetingText = getGreetingForRoute({
        pathname,
        ...contextOverride,
      });
      setMessages([
        {
          id: `msg_init_${Date.now()}`,
          role: 'assistant',
          text: greetingText,
          cards: [],
          time: new Date().toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          }),
        },
      ]);
    }
  }, [pathname]);

  // 方案 B：基于 SSE (Server-Sent Events) 的实时事件流，替代无节制的 3 秒 HTTP 轮询
  useEffect(() => {
    if (!threadId || !isOpen) return;

    let eventSource: EventSource | null = null;
    try {
      eventSource = new EventSource(`/api/store/chat/stream?threadId=${encodeURIComponent(threadId)}`);

      eventSource.addEventListener('message', (e) => {
        try {
          const msgData = JSON.parse(e.data);
          if (msgData && msgData.content) {
            const incomingText = String(msgData.content).trim();
            const incomingId = msgData.id || `sse_${Date.now()}`;
            const incomingRole = msgData.role === 'user' ? 'user' : 'assistant';
            const incomingCards = Array.isArray(msgData.cards) ? msgData.cards : [];

            if (incomingCards.length > 0) {
              syncCartToLocalStorage(incomingCards);
            }

            setMessages((prev) => {
              // 避免与已有的消息重复添加
              const alreadyExists = prev.some(
                (m) =>
                  (incomingId && m.id === incomingId) || (m.role === incomingRole && m.text.trim() === incomingText),
              );
              if (alreadyExists) return prev;

              return [
                ...prev,
                {
                  id: incomingId,
                  role: incomingRole,
                  text: incomingText,
                  cards: incomingCards,
                  time: msgData.timestamp
                    ? new Date(msgData.timestamp).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })
                    : new Date().toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      }),
                },
              ];
            });
          }
        } catch (err) {
          console.warn('[SSE] Failed to parse SSE message event:', err);
        }
      });

      eventSource.onerror = (err) => {
        // SSE 断线将由浏览器 EventSource 机制自动安全重连
        console.debug('[SSE] EventSource connection info:', err);
      };
    } catch (err) {
      console.warn('[SSE] Failed to initialize EventSource:', err);
    }

    return () => {
      if (eventSource) {
        eventSource.close();
      }
    };
  }, [threadId, isOpen]);

  // 滚动到底部 (仅在用户主动发信或接收新回复时平滑滚动)
  useEffect(() => {
    if (isOpen && !isLoadingOlder) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages.length, isOpen, isLoadingOlder]);

  // 开启新会话
  const handleStartNewThread = () => {
    if (!user?.id) return;
    const newTid = `merchant_thread_${user.id}_aurora_${Date.now()}`;
    setThreadId(newTid);
    setHasMoreOlder(true);
    if (typeof window !== 'undefined') {
      localStorage.setItem(`aurora_active_thread_${user.id}`, newTid);
      sessionStorage.setItem(`aurora_active_thread_${user.id}`, newTid);
    }
    const greetingText = getGreetingForRoute({
      pathname,
      ...contextOverride,
    });
    setMessages([
      {
        id: `msg_new_${Date.now()}`,
        role: 'assistant',
        text: greetingText,
        cards: [],
        time: new Date().toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        }),
      },
    ]);
  };

  // 发送消息到后端决策引擎
  const handleSendMessage = async (customMsg?: string, cardsToSend?: RichCardBlock[]) => {
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
      cards: cardsToSend || [],
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
      const replyCards = Array.isArray(data.cards) ? data.cards : [];
      const msgId = data.messageId || `ast_${Date.now()}`;

      if (replyCards.length > 0) {
        syncCartToLocalStorage(replyCards);
      }

      setMessages((prev) => {
        // 🛡️ 防御式去重与卡片同步：若 SSE 流式推送已经抢先注入了文本，补充注入卡片并去重
        const existingIdx = prev.findIndex(
          (m) => m.id === msgId || (m.role === 'assistant' && m.text.trim() === replyText.trim()),
        );
        if (existingIdx !== -1) {
          const updated = [...prev];
          if ((!updated[existingIdx].cards || updated[existingIdx].cards.length === 0) && replyCards.length > 0) {
            updated[existingIdx] = {
              ...updated[existingIdx],
              cards: replyCards,
            };
          }
          return updated;
        }

        return [
          ...prev,
          {
            id: msgId,
            role: 'assistant',
            text: replyText,
            cards: replyCards,
            time: new Date().toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            }),
          },
        ];
      });
      fetchHistory();
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: `ast_err_${Date.now()}`,
          role: 'assistant',
          text: '网络通信异常，请检查商户后端服务连接。',
          cards: [],
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

  // 卡片点击交互回调 (支持查看物流、申请退款、快速问答等)
  const handleCardAction = (action: string, payload?: Record<string, unknown>) => {
    if (action === 'select_order' && payload?.orderId) {
      const orderIdStr = String(payload.orderId);
      const orderData = payload.order as OrderCardData | undefined;

      // 在对话记录中展示已选中的单一订单卡片
      const orderCards: RichCardBlock[] = orderData
        ? [{ type: 'order_card', data: orderData }]
        : [
            {
              type: 'order_card',
              data: {
                orderId: orderIdStr,
                status: '已选择',
                totalAmount: 0,
                actions: [
                  {
                    label: '查看物流轨迹',
                    action: 'track_order',
                    payload: { orderId: orderIdStr },
                  },
                  {
                    label: '申请退款',
                    action: 'request_refund',
                    payload: { orderId: orderIdStr },
                  },
                ],
              },
            },
          ];

      handleSendMessage(`已选定订单 ${orderIdStr}，请帮我查询该订单的具体信息和最新物流进度。`, orderCards);
    } else if (action === 'checkout_cart' || action === 'go_to_checkout') {
      window.location.href = '/cart';
    } else if (action === 'view_cart') {
      window.location.href = '/cart';
    } else if (action === 'clear_cart') {
      handleSendMessage('清空购物车');
    } else if (action === 'send_message' && payload?.text) {
      handleSendMessage(String(payload.text));
    } else if (action === 'track_order' && payload?.orderId) {
      handleSendMessage(`帮我查一下订单 ${payload.orderId} 的物流轨迹`);
    } else if (action === 'request_refund' && payload?.orderId) {
      handleSendMessage(`帮我申请订单 ${payload.orderId} 的退款`);
    } else if (action === 'confirm_refund' && payload?.orderId) {
      handleSendMessage(`我已确认提交订单 ${payload.orderId} 的退款核签`);
    } else if (typeof payload?.query === 'string') {
      handleSendMessage(payload.query);
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
            <div className="flex items-center space-x-1.5">
              <button
                type="button"
                onClick={() => {
                  const nextState = !showHistoryList;
                  setShowHistoryList(nextState);
                  if (nextState) {
                    fetchHistory();
                  }
                }}
                title="查看历史对话"
                className={`text-[11px] px-2 py-0.5 rounded cursor-pointer transition ${
                  showHistoryList
                    ? 'bg-emerald-900 text-white font-semibold'
                    : 'bg-emerald-800/80 hover:bg-emerald-800 text-emerald-100'
                }`}
              >
                📜 历史 {userThreads.length > 0 ? `(${userThreads.length})` : ''}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowHistoryList(false);
                  handleStartNewThread();
                }}
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

          {/* 历史对话列表抽屉 / 覆盖层 */}
          {showHistoryList && (
            <div className="bg-slate-50 border-b border-slate-200 p-2 max-h-48 overflow-y-auto space-y-1 z-10 shadow-inner">
              <div className="flex items-center justify-between text-[11px] font-semibold text-slate-500 px-1 mb-1">
                <span>我的历史会话列表</span>
                <span className="text-[10px] text-slate-400">点击切换继续对话</span>
              </div>
              {userThreads.map((t) => {
                const isActive = t.threadId === threadId;
                return (
                  <button
                    key={t.threadId}
                    type="button"
                    onClick={() => {
                      if (!user?.id) return;
                      setThreadId(t.threadId);
                      if (typeof window !== 'undefined') {
                        sessionStorage.setItem(`aurora_active_thread_${user.id}`, t.threadId);
                      }
                      fetchHistory(t.threadId);
                      setShowHistoryList(false);
                    }}
                    className={`w-full text-left p-2 rounded-lg text-xs transition border flex flex-col space-y-0.5 cursor-pointer ${
                      isActive
                        ? 'bg-emerald-50 border-emerald-300 text-emerald-900 shadow-xs'
                        : 'bg-white border-slate-200 hover:border-emerald-200 hover:bg-slate-100 text-slate-700'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium truncate max-w-[200px]">
                        {t.lastMessageSnippet || t.title || '咨询对话'}
                      </span>
                      {isActive && (
                        <span className="text-[10px] bg-emerald-600 text-white px-1.5 py-0.2 rounded-full">
                          当前会话
                        </span>
                      )}
                    </div>
                    <div className="flex items-center justify-between text-[10px] text-slate-400">
                      <span>ID: {t.threadId.slice(-12)}</span>
                      <span>{t.updatedAt ? new Date(t.updatedAt).toLocaleDateString() : ''}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}

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

          {/* 对话消息流 (支持向下/触顶滚动加载更早历史消息) */}
          <div
            ref={messageContainerRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-50/50"
          >
            {/* 顶部触顶/下拉加载历史记录指示器 */}
            <div className="flex justify-center pb-2">
              {isLoadingOlder ? (
                <div className="flex items-center space-x-1.5 text-[11px] text-slate-500 bg-white border border-slate-200 px-3 py-1 rounded-full shadow-2xs">
                  <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping" />
                  <span>正在加载更早历史记录...</span>
                </div>
              ) : hasMoreOlder ? (
                <button
                  type="button"
                  onClick={loadOlderHistory}
                  className="text-[11px] text-emerald-700 hover:text-emerald-800 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 px-3 py-1 rounded-full transition shadow-2xs cursor-pointer flex items-center space-x-1"
                >
                  <span>📜 下拉或点击加载更早历史记录</span>
                </button>
              ) : (
                messages.length > 2 && (
                  <span className="text-[10px] text-slate-400 bg-slate-100 px-2.5 py-0.5 rounded-full">
                    已加载全部历史消息
                  </span>
                )
              )}
            </div>

            {messages.map((m) => {
              if (m.isDivider) {
                return (
                  <div key={m.id} className="flex items-center my-3 text-[10px] text-slate-400 select-none">
                    <div className="flex-grow border-t border-slate-200" />
                    <span className="px-2.5 bg-slate-100 rounded-full py-0.5 font-medium">{m.text}</span>
                    <div className="flex-grow border-t border-slate-200" />
                  </div>
                );
              }

              return (
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
                  {m.cards && m.cards.length > 0 && (
                    <div className="w-full max-w-[95%]">
                      <RichCardRenderer cards={m.cards} onAction={handleCardAction} />
                    </div>
                  )}
                  {m.time && <span className="text-[10px] text-slate-400 mt-1 px-1">{m.time}</span>}
                </div>
              );
            })}
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
