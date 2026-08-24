'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  Badge,
  Bot,
  BrainCircuit,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ChevronRight,
  Clock,
  Input,
  MessageSquare,
  RefreshCw,
  RichCardRenderer,
  Search,
  ShieldAlert,
  User,
  UserCheck,
} from 'ui';
import { ThreadDeepTraceDrawer } from './ThreadDeepTraceDrawer';

export interface ConversationItem {
  threadId: string;
  businessId: string;
  userId?: string;
  status: string;
  assignedOperatorId?: string;
  unreadCount: number;
  tags: string[];
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  lastMessageSnippet?: string;
  lastMessageRole?: string;
  lastMessageTime?: string;
}

export interface ConversationTimeline {
  thread: ConversationItem;
  messages: Array<{
    id: string;
    role: string;
    content: string;
    thoughtSteps?: Array<{ step: string; status: string }>;
    toolCalls?: Array<{ name: string; args: any; result?: any }>;
    cards?: Array<{ cardType: string; payload: any }>;
    operatorInfo?: { operatorId: string; operatorName: string };
    timestamp: string;
  }>;
}

interface ConversationsExplorerProps {
  selectedMerchant: string;
  onSelectForLiveDesk?: (threadId: string) => void;
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

export function ConversationsExplorer({ selectedMerchant, onSelectForLiveDesk }: ConversationsExplorerProps) {
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [selectedTimeline, setSelectedTimeline] = useState<ConversationTimeline | null>(null);
  const [isLoadingTimeline, setIsLoadingTimeline] = useState(false);
  const [isDeepTraceOpen, setIsDeepTraceOpen] = useState(false);

  const fetchConversations = useCallback(async () => {
    setIsLoading(true);
    try {
      const params = new URLSearchParams({
        businessId: selectedMerchant,
        status: statusFilter,
        search: searchQuery,
      });

      // Try NestJS Gateway at Port 4000 or fallback to local API
      let res: Response | null = null;
      try {
        res = await fetch(`http://localhost:4000/api/conversations?${params.toString()}`, {
          headers: { 'x-tenant-id': selectedMerchant },
        });
      } catch {
        res = null;
      }

      if (!res || !res.ok) {
        // Mock fallback if gateway is loading
        setConversations([
          {
            threadId: `thread_${selectedMerchant}_001`,
            businessId: selectedMerchant,
            userId: 'CUST-8801',
            status: 'active',
            unreadCount: 0,
            tags: ['INQUIRY'],
            metadata: {},
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
            lastMessageSnippet: '请问什么时候发货？',
            lastMessageRole: 'user',
          },
        ]);
        setTotal(1);
        return;
      }

      const data = await res.json();
      setConversations(data.items || []);
      setTotal(data.total || 0);
    } catch (err) {
      console.error('[ConversationsExplorer] Failed to fetch:', err);
    } finally {
      setIsLoading(false);
    }
  }, [selectedMerchant, statusFilter, searchQuery]);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  const loadTimeline = async (threadId: string) => {
    setIsLoadingTimeline(true);
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
        setSelectedTimeline(json.data);
      } else {
        setSelectedTimeline({
          thread: {
            threadId,
            businessId: selectedMerchant,
            userId: 'CUST-8801',
            status: 'active',
            unreadCount: 0,
            tags: [],
            metadata: {},
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          },
          messages: [
            {
              id: 'm1',
              role: 'user',
              content: '你好，我的包裹还没到，可以帮我查下吗？',
              timestamp: new Date().toISOString(),
            },
            {
              id: 'm2',
              role: 'assistant',
              content: '已为您查询到最新物流信息，当前正在派送中。',
              cards: [
                {
                  cardType: 'TrackingTimeline',
                  payload: {
                    trackingNumber: 'SF1092837461',
                    carrier: '顺丰速运',
                    status: '派送中',
                  },
                },
              ],
              timestamp: new Date().toISOString(),
            },
          ],
        });
      }
    } catch (err) {
      console.error('[ConversationsExplorer] Failed to load timeline:', err);
    } finally {
      setIsLoadingTimeline(false);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'human_takeover':
        return (
          <Badge className="bg-amber-500/10 text-amber-400 border border-amber-500/30 flex items-center gap-1">
            <UserCheck className="w-3 h-3" /> 人工接管中
          </Badge>
        );
      case 'pending_approval':
        return (
          <Badge className="bg-rose-500/10 text-rose-400 border border-rose-500/30 flex items-center gap-1">
            <ShieldAlert className="w-3 h-3" /> 待审批
          </Badge>
        );
      case 'resolved':
        return <Badge className="bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">已完结</Badge>;
      default:
        return (
          <Badge className="bg-indigo-500/10 text-indigo-400 border border-indigo-500/30 flex items-center gap-1">
            <Bot className="w-3 h-3" /> AI 托管中
          </Badge>
        );
    }
  };

  return (
    <div className="space-y-6">
      {/* 🔍 Top Search & Filter Bar */}
      <div className="flex flex-col sm:flex-row justify-between items-stretch sm:items-center gap-4 bg-slate-900/60 p-4 rounded-2xl border border-slate-800">
        <div className="flex flex-wrap items-center gap-2">
          {[
            { id: 'all', label: '全部会话' },
            { id: 'active', label: 'AI 托管中' },
            { id: 'human_takeover', label: '人工接管中' },
            { id: 'pending_approval', label: '待审批' },
            { id: 'resolved', label: '已完结' },
          ].map((tab) => (
            <Button
              key={tab.id}
              size="sm"
              variant={statusFilter === tab.id ? 'default' : 'ghost'}
              onClick={() => setStatusFilter(tab.id)}
              className={`text-xs h-8 px-3 rounded-xl transition-all ${
                statusFilter === tab.id
                  ? 'bg-indigo-600 text-white font-bold shadow-md shadow-indigo-600/20'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/80'
              }`}
            >
              {tab.label}
            </Button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
            <Input
              placeholder="搜索消息/会话 ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && fetchConversations()}
              className="pl-9 h-9 bg-slate-950 border-slate-800 text-xs text-slate-200 placeholder:text-slate-500 rounded-xl focus:border-indigo-500"
            />
          </div>

          <Button
            size="icon"
            variant="outline"
            onClick={fetchConversations}
            className="h-9 w-9 rounded-xl bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin text-indigo-400' : ''}`} />
          </Button>
        </div>
      </div>

      {/* 📊 Content Layout: Left Conversation List + Right 360° Timeline */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: Conversation Items */}
        <div className="lg:col-span-6 space-y-3">
          <div className="text-xs font-semibold text-slate-400 px-1 flex justify-between items-center">
            <span>当前商户共找到 {total} 条会话</span>
            <span className="text-[10px] text-slate-500 uppercase">商户: {selectedMerchant}</span>
          </div>

          {conversations.length === 0 ? (
            <div className="p-12 text-center bg-slate-900/30 rounded-2xl border border-slate-800/60 text-slate-500 text-xs">
              暂无匹配的会话记录
            </div>
          ) : (
            conversations.map((conv) => {
              const isSelected = selectedTimeline?.thread.threadId === conv.threadId;
              return (
                <div
                  key={conv.threadId}
                  onClick={() => loadTimeline(conv.threadId)}
                  className={`p-4 rounded-2xl border transition-all cursor-pointer ${
                    isSelected
                      ? 'bg-slate-900 border-indigo-500/60 shadow-lg shadow-indigo-950/40 ring-1 ring-indigo-500/30'
                      : 'bg-slate-900/40 border-slate-800/80 hover:bg-slate-900/80 hover:border-slate-700'
                  }`}
                >
                  <div className="flex justify-between items-start gap-2">
                    <div className="flex items-center gap-2">
                      <div className="h-8 w-8 rounded-lg bg-slate-800 flex items-center justify-center text-slate-300">
                        <MessageSquare className="w-4 h-4" />
                      </div>
                      <div>
                        <div className="text-xs font-bold text-slate-200 flex items-center gap-2">
                          <span>{conv.threadId}</span>
                          {getStatusBadge(conv.status)}
                        </div>
                        <div className="text-[10px] text-slate-500 flex items-center gap-2 mt-0.5">
                          <span className="flex items-center gap-1">
                            <User className="w-3 h-3" /> {conv.userId || '访客'}
                          </span>
                          <span className="flex items-center gap-1">
                            <Clock className="w-3 h-3" /> {new Date(conv.updatedAt).toLocaleTimeString('zh-CN')}
                          </span>
                        </div>
                      </div>
                    </div>

                    {onSelectForLiveDesk && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectForLiveDesk(conv.threadId);
                        }}
                        className="h-7 px-2.5 text-[11px] font-bold text-indigo-400 hover:text-indigo-300 hover:bg-indigo-950/40 rounded-lg"
                      >
                        转接入工作台 ➔
                      </Button>
                    )}
                  </div>

                  {conv.lastMessageSnippet && (
                    <div className="mt-2.5 text-xs text-slate-300 bg-slate-950/60 p-2.5 rounded-xl border border-slate-800/60 flex items-start gap-2">
                      <span className="text-[10px] font-bold uppercase text-slate-500 shrink-0 mt-0.5">
                        {conv.lastMessageRole === 'user' ? '买家' : conv.lastMessageRole === 'operator' ? '坐席' : 'AI'}
                        :
                      </span>
                      <span className="line-clamp-2">{conv.lastMessageSnippet}</span>
                    </div>
                  )}

                  {conv.tags && conv.tags.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {conv.tags.map((tag) => (
                        <span
                          key={tag}
                          className="px-2 py-0.5 text-[9px] font-bold rounded-md bg-slate-800 text-slate-400 border border-slate-700/50"
                        >
                          #{tag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Right: 360° Conversation Timeline Viewer */}
        <div className="lg:col-span-6">
          <div className="bg-slate-900/60 rounded-2xl border border-slate-800 p-5 h-[680px] flex flex-col">
            <div className="flex justify-between items-center pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <div className="h-6 w-6 rounded-md bg-indigo-600/20 text-indigo-400 flex items-center justify-center text-xs font-bold">
                  360°
                </div>
                <h3 className="text-sm font-bold text-slate-200">
                  {selectedTimeline
                    ? `会话消息时序回放 (${selectedTimeline.thread.threadId})`
                    : '请选择左侧会话以查看完整时序'}
                </h3>
              </div>

              <div className="flex items-center gap-2">
                {selectedTimeline && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setIsDeepTraceOpen(true)}
                    className="h-7 px-2.5 text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-indigo-300 border-indigo-500/40 rounded-lg flex items-center gap-1"
                  >
                    <BrainCircuit className="w-3.5 h-3.5 text-indigo-400" />
                    决策透视
                  </Button>
                )}

                {selectedTimeline && onSelectForLiveDesk && (
                  <Button
                    size="sm"
                    onClick={() => onSelectForLiveDesk(selectedTimeline.thread.threadId)}
                    className="h-7 px-3 text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg shadow-md"
                  >
                    ⚡ 人工接管此会话
                  </Button>
                )}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto space-y-4 py-4 pr-1">
              {isLoadingTimeline ? (
                <div className="h-full flex items-center justify-center text-xs text-slate-500">
                  <RefreshCw className="w-4 h-4 animate-spin mr-2 text-indigo-400" />
                  正在装配 360° 上下文时序...
                </div>
              ) : !selectedTimeline ? (
                <div className="h-full flex flex-col items-center justify-center text-slate-500 text-xs">
                  <MessageSquare className="w-10 h-10 text-slate-700 mb-2" />
                  <span>点击左侧任意会话卡片可回放包含思考链与富卡片的完整上下文</span>
                </div>
              ) : (
                selectedTimeline.messages.map((msg, idx) => {
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
                    <div key={msg.id || idx} className={`flex flex-col ${isUser ? 'items-end' : 'items-start'}`}>
                      <div className="text-[10px] text-slate-500 mb-1 px-1 flex items-center gap-1.5">
                        <span className="font-bold">
                          {isUser
                            ? '终端买家'
                            : isOperator
                              ? `客服坐席 (${msg.operatorInfo?.operatorName || '人工'})`
                              : 'AI 智能体'}
                        </span>
                        <span>{new Date(msg.timestamp).toLocaleTimeString('zh-CN')}</span>
                      </div>

                      <div
                        className={`max-w-[85%] p-3.5 rounded-2xl text-xs ${
                          isUser
                            ? 'bg-indigo-600 text-white rounded-tr-sm'
                            : isOperator
                              ? 'bg-amber-600/30 text-amber-100 border border-amber-500/30 rounded-tl-sm'
                              : 'bg-slate-800 text-slate-200 border border-slate-700/80 rounded-tl-sm'
                        }`}
                      >
                        {/* Thought steps collapse if present */}
                        {msg.thoughtSteps && msg.thoughtSteps.length > 0 && (
                          <div className="mb-2 p-2 rounded-lg bg-slate-900/80 border border-slate-700/60 text-[10px] text-slate-400 space-y-1">
                            <div className="font-bold text-indigo-400">🧠 思考步骤:</div>
                            {msg.thoughtSteps.map((s, i) => (
                              <div key={i} className="line-clamp-1">
                                • {s.step}
                              </div>
                            ))}
                          </div>
                        )}

                        <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>

                        {/* Rich Cards rendering */}
                        {msg.cards && msg.cards.length > 0 && (
                          <div className="mt-3 space-y-2">
                            <RichCardRenderer cards={normalizeCards(msg.cards)} />
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 🧠 Deep Cognitive Trace & Decision Drawer */}
      <ThreadDeepTraceDrawer
        isOpen={isDeepTraceOpen}
        onClose={() => setIsDeepTraceOpen(false)}
        timeline={selectedTimeline}
        selectedMerchant={selectedMerchant}
      />
    </div>
  );
}
