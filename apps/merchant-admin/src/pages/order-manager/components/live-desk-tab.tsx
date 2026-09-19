import React from "react";
import {
  ApprovalContextDrawer,
  ApprovalRiskBadge,
  Badge,
  Button,
  CheckCircle2,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  RichCardRenderer,
  ShieldAlert,
  Textarea,
} from "ui";
import { useWorkbench } from "../workbench";

export function LiveDeskTab() {
  const {
    activeThreadId, activeThreadMessages, fetchDashboardData, filteredConversations, handleSendMessage, handleTakeover, inputMessage, isTakingOver, liveDeskSearchQuery, liveDeskStatusFilter, loadConversationMessages, messagesEndRef, setActiveThreadId, setInputMessage, setLiveDeskSearchQuery, setLiveDeskStatusFilter,
  } = useWorkbench();
  return (
    <>
          <div className="bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden flex flex-col md:flex-row h-[700px]">
            {/* 左侧会话列表 */}
            <div className="w-full md:w-80 border-r border-slate-200 flex flex-col bg-slate-50">
              <div className="p-3.5 border-b border-slate-200 bg-white space-y-2">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-xs font-bold text-slate-900">💬 客服会话队列</h3>
                    <span className="text-[10px] text-slate-500">商户专属客户会话实时接入</span>
                  </div>
                  <button
                    type="button"
                    onClick={fetchDashboardData}
                    className="text-xs text-slate-500 hover:text-slate-800 cursor-pointer"
                  >
                    🔄
                  </button>
                </div>

                <div className="flex gap-1 bg-slate-100 p-0.5 rounded-lg text-[11px]">
                  {[
                    { key: 'ALL', label: '全部' },
                    { key: 'takeover', label: '人工接管' },
                    { key: 'ai', label: 'AI 托管' },
                  ].map((f) => (
                    <button
                      key={f.key}
                      type="button"
                      onClick={() => setLiveDeskStatusFilter(f.key as any)}
                      className={`flex-1 py-1 rounded text-center font-medium transition cursor-pointer ${
                        liveDeskStatusFilter === f.key
                          ? 'bg-white text-slate-900 shadow-xs font-bold'
                          : 'text-slate-500 hover:text-slate-800'
                      }`}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>

                <Input
                  type="text"
                  placeholder="搜索客户 / 会话 / 摘要..."
                  value={liveDeskSearchQuery}
                  onChange={(e) => setLiveDeskSearchQuery(e.target.value)}
                  className="text-xs h-7 bg-white"
                />
              </div>

              <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
                {filteredConversations.length === 0 ? (
                  <div className="p-8 text-center text-xs text-slate-400">暂无匹配会话记录</div>
                ) : (
                  filteredConversations.map((c) => {
                    const threadId = c.threadId || c.id;
                    const isSelected = activeThreadId === threadId;
                    const isTakeover = c.status === 'human_takeover';
                    return (
                      // biome-ignore lint/a11y/useKeyWithClickEvents: 会话行点击打开详情;键盘操作由行内按钮承担
                      <div
                        key={threadId}
                        onClick={() => {
                          setActiveThreadId(threadId);
                          loadConversationMessages(threadId);
                        }}
                        className={`p-3.5 cursor-pointer transition flex flex-col space-y-1.5 ${
                          isSelected ? 'bg-blue-50/80 border-l-4 border-blue-600' : 'hover:bg-slate-100/70'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-xs text-slate-900 truncate">
                            {c.userId || '顾客 CUST-8801'}
                          </span>
                          <span
                            className={`text-[10px] px-1.5 py-0.5 rounded-full font-semibold ${
                              isTakeover ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800'
                            }`}
                          >
                            {isTakeover ? '👨‍💼 人工接管中' : '🤖 AI 托管中'}
                          </span>
                        </div>
                        <p className="text-[11px] text-slate-500 truncate font-mono">{threadId}</p>
                        {c.lastMessage && (
                          <p className="text-[11px] text-slate-600 truncate bg-slate-100/80 px-2 py-0.5 rounded">
                            {c.lastMessage}
                          </p>
                        )}
                        <div className="text-[10px] text-slate-400 flex justify-between">
                          <span>{new Date(c.updatedAt || c.createdAt).toLocaleTimeString()}</span>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            {/* 右侧实时聊天与接管面板 */}
            <div className="flex-1 flex flex-col bg-slate-100/50">
              {activeThreadId ? (
                <>
                  {/* 对话 Header */}
                  <div className="p-3.5 bg-white border-b border-slate-200 flex items-center justify-between">
                    <div>
                      <div className="flex items-center space-x-2">
                        <span className="font-bold text-xs text-slate-900">会话: {activeThreadId}</span>
                        <span className="text-[10px] bg-slate-100 text-slate-600 px-2 py-0.5 rounded font-mono">
                          Tenant: aurora
                        </span>
                      </div>
                      <div className="text-[11px] text-slate-500 mt-0.5">
                        支持客服实时监听、主动发送消息或一键接管会话
                      </div>
                    </div>

                    <div className="flex items-center space-x-2">
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => handleTakeover(activeThreadId)}
                        disabled={isTakingOver}
                        className="bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold h-8 cursor-pointer"
                      >
                        <span>🚨 主动接管会话</span>
                      </Button>
                    </div>
                  </div>

                  {/* 消息流 */}
                  <div className="flex-1 p-4 overflow-y-auto space-y-3">
                    {activeThreadMessages.length === 0 ? (
                      <div className="p-12 text-center text-xs text-slate-400">正在等待消息流接入...</div>
                    ) : (
                      activeThreadMessages.map((msg, idx) => {
                        const isUser = msg.role === 'user';
                        const isSystem = msg.role === 'system';
                        const isOperator =
                          msg.content?.startsWith('[人工客服]') || msg.content?.startsWith('[商户客服]');

                        if (isSystem) {
                          return (
                            <div key={msg.id || idx} className="text-center my-2">
                              <span className="text-[10px] bg-slate-200/80 text-slate-600 px-3 py-1 rounded-full font-medium">
                                {msg.content}
                              </span>
                            </div>
                          );
                        }

                        return (
                          <div key={msg.id || idx} className={`flex flex-col ${isUser ? 'items-start' : 'items-end'}`}>
                            <span className="text-[10px] text-slate-400 mb-1 px-1">
                              {isUser ? '👤 顾客' : isOperator ? '👨‍💼 商户客服' : '🤖 AI 助手'} ·{' '}
                              {msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString() : ''}
                            </span>
                            <div
                              className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-xs shadow-2xs leading-relaxed ${
                                isUser
                                  ? 'bg-white text-slate-800 border border-slate-200'
                                  : isOperator
                                    ? 'bg-amber-600 text-white font-medium'
                                    : 'bg-emerald-600 text-white'
                              }`}
                            >
                              <div className="whitespace-pre-wrap">{msg.content}</div>

                              {/* 卡片渲染 */}
                              {msg.cards && msg.cards.length > 0 && (
                                <div className="mt-2 pt-2 border-t border-white/20 space-y-2">
                                  <RichCardRenderer cards={msg.cards} />
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })
                    )}
                    <div ref={messagesEndRef} />
                  </div>

                  {/* 快捷常用话术栏 */}
                  <div className="px-3 py-1.5 bg-slate-50 border-t border-slate-200 flex items-center gap-1.5 overflow-x-auto text-[11px]">
                    <span className="text-slate-400 shrink-0">快捷回复:</span>
                    {[
                      '您好！极光潮品商户客服为您服务，请问有什么可以协助您？',
                      '已为您核实订单状态，商品正在仓库质检出库中。',
                      '您的退款诉求已转交售后专员核实，请耐心等候。',
                      '收货地址已为您记录，出库前均可为您办理变更。',
                    ].map((reply) => (
                      <button
                        key={reply}
                        type="button"
                        onClick={() => handleSendMessage(reply)}
                        className="bg-white hover:bg-slate-100 text-slate-700 px-2.5 py-1 rounded-md border border-slate-200 whitespace-nowrap cursor-pointer transition"
                      >
                        {reply.slice(0, 16)}...
                      </button>
                    ))}
                  </div>

                  {/* 输入框 Footer */}
                  <div className="p-3 bg-white border-t border-slate-200 flex items-center space-x-2">
                    <Input
                      type="text"
                      value={inputMessage}
                      onChange={(e) => setInputMessage(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault();
                          handleSendMessage();
                        }
                      }}
                      placeholder="以商户客服身份发送消息并直接与顾客沟通..."
                      className="text-xs h-9 bg-white"
                    />
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => handleSendMessage()}
                      disabled={!inputMessage.trim()}
                      className="bg-blue-600 hover:bg-blue-500 disabled:bg-slate-300 text-white text-xs font-semibold h-9 px-4 cursor-pointer"
                    >
                      发送
                    </Button>
                  </div>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center text-xs text-slate-400">
                  请在左侧选择一个会话以开始监控与客服接管
                </div>
              )}
            </div>
          </div>
    </>
  );
}
