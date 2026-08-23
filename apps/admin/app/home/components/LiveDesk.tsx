'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Badge,
  Bot,
  Button,
  Card,
  Clock,
  Input,
  RefreshCw,
  RichCardRenderer,
  Send,
  ShieldAlert,
  User,
  UserCheck,
} from 'ui';

interface LiveDeskProps {
  selectedMerchant: string;
  initialThreadId?: string;
}

const normalizeCards = (cards?: any[]) => {
  if (!cards || cards.length === 0) return [];
  return cards.map((c) => {
    let type = c.type || c.cardType || '';
    if (type === 'RefundConfirmationCard' || type === 'refundConfirmation') type = 'refund_confirmation';
    if (type === 'TrackingTimeline' || type === 'trackingTimeline') type = 'tracking_timeline';
    if (type === 'OrderCard' || type === 'orderCard') type = 'order_card';
    if (type === 'DamageAssessmentCard' || type === 'damageAssessment') type = 'damage_assessment';
    if (type === 'ProductRankingCard' || type === 'productRanking') type = 'product_ranking';
    if (type === 'QuickReplies' || type === 'quickReplies') type = 'quick_replies';
    return {
      type: type as any,
      data: c.data || c.payload || c,
    };
  });
};

export function LiveDesk({ selectedMerchant, initialThreadId }: LiveDeskProps) {
  const [activeThreadId, setActiveThreadId] = useState<string>(initialThreadId || `thread_${selectedMerchant}_001`);
  const [activeStatus, setActiveStatus] = useState<string>('active');
  const [messages, setMessages] = useState<
    Array<{
      id: string;
      role: string;
      content: string;
      cards?: any[];
      operatorInfo?: { operatorId: string; operatorName: string };
      timestamp: string;
    }>
  >([]);

  const [inputMessage, setInputMessage] = useState('');
  const [isTakingOver, setIsTakingOver] = useState(false);
  const [operatorName] = useState('专家坐席-小王');
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Load conversation messages
  const loadMessages = useCallback(
    async (threadId: string) => {
      try {
        let res: Response | null = null;
        try {
          res = await fetch(`http://localhost:4000/api/conversations/${threadId}?tenantId=${selectedMerchant}`, {
            headers: { 'x-tenant-id': selectedMerchant },
          });
        } catch {
          res = null;
        }

        if (res && res.ok) {
          const json = await res.json();
          if (json.data) {
            setMessages(json.data.messages || []);
            setActiveStatus(json.data.thread.status || 'active');
            return;
          }
        }

        // Default mock fallback
        setMessages([
          {
            id: 'm1',
            role: 'user',
            content: '请问我申请的退款什么时候能够到账？',
            timestamp: new Date().toISOString(),
          },
          {
            id: 'm2',
            role: 'assistant',
            content: '根据商户规则，退款审核已提交，正在等待客服确认。',
            timestamp: new Date().toISOString(),
          },
        ]);
      } catch (err) {
        console.error('[LiveDesk] Failed to load messages:', err);
      }
    },
    [selectedMerchant],
  );

  useEffect(() => {
    if (activeThreadId) {
      loadMessages(activeThreadId);
    }
  }, [activeThreadId, loadMessages]);

  // 一键接管
  const handleTakeover = async () => {
    setIsTakingOver(true);
    try {
      // 1. Try REST status update or gateway
      try {
        await fetch(`http://localhost:4000/api/conversations/${activeThreadId}/status`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'x-tenant-id': selectedMerchant,
          },
          body: JSON.stringify({
            status: 'human_takeover',
            assignedOperatorId: 'op_staff_01',
          }),
        });
      } catch {}

      setActiveStatus('human_takeover');
      setMessages((prev) => [
        ...prev,
        {
          id: `sys_${Date.now()}`,
          role: 'system',
          content: `人工客服【${operatorName}】已接管当前会话，AI 智能体已暂停响应。`,
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsTakingOver(false);
    }
  };

  // 释放接管
  const handleRelease = async () => {
    try {
      try {
        await fetch(`http://localhost:4000/api/conversations/${activeThreadId}/status`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'x-tenant-id': selectedMerchant,
          },
          body: JSON.stringify({
            status: 'active',
            assignedOperatorId: null,
          }),
        });
      } catch {}

      setActiveStatus('active');
      setMessages((prev) => [
        ...prev,
        {
          id: `sys_${Date.now()}`,
          role: 'system',
          content: '已释放接管，会话已重新归还 AI 智能客服托管。',
          timestamp: new Date().toISOString(),
        },
      ]);
    } catch (err) {
      console.error('[LiveDesk] Failed to release takeover:', err);
    }
  };

  // 发送人工消息
  const handleSendMessage = async () => {
    if (!inputMessage.trim()) return;

    const newMsg = {
      id: `msg_op_${Date.now()}`,
      role: 'operator',
      content: inputMessage.trim(),
      operatorInfo: { operatorId: 'op_staff_01', operatorName },
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, newMsg]);
    setInputMessage('');

    // Persist to backend
    try {
      await fetch('http://localhost:4000/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-tenant-id': selectedMerchant,
        },
        body: JSON.stringify({
          threadId: activeThreadId,
          businessId: selectedMerchant,
          role: 'operator',
          message: newMsg.content,
        }),
      });
    } catch {}
  };

  // 快捷发送预制卡片
  const handleSendPresetCard = (cardType: string) => {
    let cardPayload: any = {};
    let snippetText = '';

    if (cardType === 'RefundConfirmationCard') {
      snippetText = '已为您生成退款审核确认卡片，请核对。';
      cardPayload = {
        orderId: 'ORD-2026-001',
        refundAmount: 99.0,
        status: 'approved',
        reason: '商品尺码不合身（7天无理由退货）',
      };
    } else if (cardType === 'TrackingTimeline') {
      snippetText = '已为您推送最新的顺丰物流时间轴。';
      cardPayload = {
        trackingNumber: 'SF1092837461',
        carrier: '顺丰速运',
        status: '已揽件',
      };
    } else {
      snippetText = '已为您推送关联订单卡片。';
      cardPayload = {
        orderId: 'ORD-2026-001',
        status: '已发货',
        totalAmount: 199.0,
      };
    }

    const newCardMsg = {
      id: `msg_card_${Date.now()}`,
      role: 'operator',
      content: snippetText,
      cards: [{ cardType, payload: cardPayload }],
      operatorInfo: { operatorId: 'op_staff_01', operatorName },
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, newCardMsg]);
  };

  return (
    <div className="bg-slate-900/60 rounded-3xl border border-slate-800 overflow-hidden shadow-2xl grid grid-cols-1 lg:grid-cols-12 h-[750px]">
      {/* 📋 Left: Waiting & In-Progress Queue */}
      <div className="lg:col-span-4 border-r border-slate-800 flex flex-col bg-slate-950/40">
        <div className="p-4 border-b border-slate-800 flex justify-between items-center bg-slate-900/80">
          <div>
            <h3 className="text-xs font-bold text-slate-200">在线会话服务队列</h3>
            <span className="text-[10px] text-slate-500 uppercase">当前商户: {selectedMerchant}</span>
          </div>
          <Badge variant="outline" className="text-[10px] bg-emerald-950/40 border-emerald-500/30 text-emerald-400">
            ● 坐席在线
          </Badge>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {[
            {
              id: activeThreadId,
              user: 'CUST-8801',
              status: activeStatus,
              snippet: '请问我申请的退款什么时候能够到账？',
              time: '刚刚',
            },
            {
              id: `thread_${selectedMerchant}_002`,
              user: 'CUST-9902',
              status: 'active',
              snippet: '我想修改收货地址到广东省深圳市...',
              time: '3分钟前',
            },
            {
              id: `thread_${selectedMerchant}_003`,
              user: 'CUST-7715',
              status: 'pending_approval',
              snippet: '退款申请金额超过 $100 触发免审阈值',
              time: '8分钟前',
            },
          ].map((item) => {
            const isSelected = item.id === activeThreadId;
            return (
              <div
                key={item.id}
                onClick={() => {
                  setActiveThreadId(item.id);
                  setActiveStatus(item.status);
                }}
                className={`p-3 rounded-2xl border transition-all cursor-pointer ${
                  isSelected
                    ? 'bg-indigo-950/40 border-indigo-500/50 shadow-md ring-1 ring-indigo-500/30'
                    : 'bg-slate-900/40 border-slate-800 hover:bg-slate-900/80'
                }`}
              >
                <div className="flex justify-between items-center mb-1">
                  <span className="text-xs font-bold text-slate-200">{item.user}</span>
                  <span className="text-[10px] text-slate-500">{item.time}</span>
                </div>
                <p className="text-[11px] text-slate-400 truncate mb-2">{item.snippet}</p>
                <div className="flex justify-between items-center">
                  <span className="text-[9px] font-mono text-slate-500 truncate max-w-[140px]">{item.id}</span>
                  {item.status === 'human_takeover' ? (
                    <Badge className="bg-amber-500/20 text-amber-300 border-amber-500/30 text-[9px] py-0">接管中</Badge>
                  ) : item.status === 'pending_approval' ? (
                    <Badge className="bg-rose-500/20 text-rose-300 border-rose-500/30 text-[9px] py-0">待审核</Badge>
                  ) : (
                    <Badge className="bg-indigo-500/20 text-indigo-300 border-indigo-500/30 text-[9px] py-0">
                      AI 托管
                    </Badge>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 💬 Right: Live Chat Interaction Workspace */}
      <div className="lg:col-span-8 flex flex-col bg-slate-900/20">
        {/* Workspace Top Header */}
        <div className="p-4 border-b border-slate-800 flex justify-between items-center bg-slate-900/80">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-xl bg-indigo-600/20 text-indigo-400 flex items-center justify-center font-bold text-sm">
              <User className="w-5 h-5" />
            </div>
            <div>
              <div className="text-xs font-bold text-slate-200 flex items-center gap-2">
                <span>会话 ID: {activeThreadId}</span>
                {activeStatus === 'human_takeover' ? (
                  <Badge className="bg-amber-500/10 text-amber-400 border border-amber-500/30 text-[10px]">
                    ● 人工坐席已介入 (AI 已静默)
                  </Badge>
                ) : (
                  <Badge className="bg-indigo-500/10 text-indigo-400 border border-indigo-500/30 text-[10px]">
                    ● AI 智能体托管运行中
                  </Badge>
                )}
              </div>
              <div className="text-[10px] text-slate-500 mt-0.5">
                当前坐席: {operatorName} | 商户: {selectedMerchant}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {activeStatus === 'human_takeover' ? (
              <Button
                size="sm"
                variant="outline"
                onClick={handleRelease}
                className="h-8 text-xs font-bold border-slate-700 bg-slate-800 text-slate-200 hover:bg-slate-700 rounded-xl"
              >
                🔄 释放接管 (还给 AI)
              </Button>
            ) : (
              <Button
                size="sm"
                onClick={handleTakeover}
                disabled={isTakingOver}
                className="h-8 text-xs font-bold bg-amber-600 hover:bg-amber-500 text-white rounded-xl shadow-lg shadow-amber-600/20"
              >
                ⚡ 立即人工接管 (Takeover)
              </Button>
            )}
          </div>
        </div>

        {/* Message Stream Scroll Area */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {messages.map((msg, idx) => {
            const isUser = msg.role === 'user';
            const isOperator = msg.role === 'operator';
            const isSystem = msg.role === 'system';

            if (isSystem) {
              return (
                <div key={msg.id || idx} className="text-center py-1">
                  <span className="text-[10px] text-amber-400/90 bg-amber-950/40 border border-amber-500/20 px-3 py-1 rounded-full">
                    {msg.content}
                  </span>
                </div>
              );
            }

            return (
              <div key={msg.id || idx} className={`flex flex-col ${isUser ? 'items-start' : 'items-end'}`}>
                <div className="text-[10px] text-slate-500 mb-1 px-1 flex items-center gap-1.5">
                  <span className="font-bold">
                    {isUser
                      ? '买家 (Customer)'
                      : isOperator
                        ? `客服坐席 (${msg.operatorInfo?.operatorName || operatorName})`
                        : 'AI 智能客服'}
                  </span>
                  <span>{new Date(msg.timestamp).toLocaleTimeString('zh-CN')}</span>
                </div>

                <div
                  className={`max-w-[80%] p-3.5 rounded-2xl text-xs ${
                    isUser
                      ? 'bg-slate-800 text-slate-200 border border-slate-700/80 rounded-tl-sm'
                      : isOperator
                        ? 'bg-amber-600/30 text-amber-100 border border-amber-500/40 rounded-tr-sm shadow-md'
                        : 'bg-indigo-600 text-white rounded-tr-sm'
                  }`}
                >
                  <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>

                  {msg.cards && msg.cards.length > 0 && (
                    <div className="mt-3 space-y-2">
                      <RichCardRenderer cards={normalizeCards(msg.cards)} />
                    </div>
                  )}
                </div>
              </div>
            );
          })}
          <div ref={messagesEndRef} />
        </div>

        {/* 🛠️ Action Toolbar: Quick Preset Cards */}
        <div className="px-4 py-2 border-t border-slate-800/80 bg-slate-950/60 flex items-center gap-2 overflow-x-auto">
          <span className="text-[10px] font-bold text-slate-500 uppercase shrink-0">快捷派发:</span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => handleSendPresetCard('RefundConfirmationCard')}
            className="h-6 px-2 text-[10px] border-slate-800 text-slate-300 hover:text-white bg-slate-900 rounded-lg shrink-0"
          >
            + 退款审核核签卡
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => handleSendPresetCard('TrackingTimeline')}
            className="h-6 px-2 text-[10px] border-slate-800 text-slate-300 hover:text-white bg-slate-900 rounded-lg shrink-0"
          >
            + 顺丰物流轨迹卡
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => handleSendPresetCard('OrderCard')}
            className="h-6 px-2 text-[10px] border-slate-800 text-slate-300 hover:text-white bg-slate-900 rounded-lg shrink-0"
          >
            + 订单明细卡
          </Button>
        </div>

        {/* ⌨️ Bottom Typing Bar */}
        <div className="p-4 border-t border-slate-800 bg-slate-900/80 flex items-center gap-3">
          <Input
            placeholder={
              activeStatus === 'human_takeover'
                ? '以人工客服身份输入回复内容 (按 Enter 发送)...'
                : '当前处于 AI 托管模式，点击上方“立即接管”后可直接与用户对话...'
            }
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
            className="h-10 bg-slate-950 border-slate-800 text-xs text-slate-200 placeholder:text-slate-500 rounded-xl focus:border-indigo-500 flex-1"
          />

          <Button
            size="sm"
            onClick={handleSendMessage}
            disabled={!inputMessage.trim()}
            className="h-10 px-4 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-bold text-xs flex items-center gap-1.5 shadow-lg shadow-indigo-600/20 shrink-0"
          >
            <Send className="w-3.5 h-3.5" />
            <span>发送</span>
          </Button>
        </div>
      </div>
    </div>
  );
}
