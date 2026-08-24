'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ApprovalContextDrawer,
  CheckCircle2,
  PendingApprovalCard,
  RichCardRenderer,
  ShieldAlert,
  useApprovalMachine,
} from 'ui';

interface OrderRow {
  order_id: string;
  customer_id: string;
  status: string;
  total_amount: number;
  shipping_address: {
    recipientName: string;
    phone: string;
    fullAddress: string;
  };
  tracking_info?: {
    carrier: string;
    trackingNumber: string;
    status: string;
  };
  is_address_modifiable: boolean;
  is_returnable: boolean;
  created_at: string;
}

interface AuditLogRow {
  id: string;
  action_type: string;
  order_id: string;
  idempotency_key: string;
  operator: string;
  payload: Record<string, unknown>;
  result: Record<string, unknown>;
  created_at: string;
}

interface SkuRow {
  id: string;
  sku_code: string;
  sku_title: string;
  spu_title: string;
  brand: string;
  category: string;
  spec_attributes: Record<string, string>;
  price: number;
  original_price?: number;
  stock: number;
}

interface SpuRow {
  id: string;
  spu_code: string;
  title: string;
  subtitle: string;
  category: string;
  brand: string;
  main_image: string;
  spec_dimensions: Array<{ name: string; values: string[] }>;
  specs: Record<string, string>;
}

interface ApprovalItem {
  id: string;
  threadId: string;
  businessId?: string;
  userId?: string;
  userEmail?: string;
  actionType: string;
  actionPayload: any;
  status: string;
  reason?: string;
  deadline?: string;
  createdAt: string;
}

interface ConversationItem {
  id: string;
  threadId?: string;
  businessId: string;
  userId?: string;
  status: string;
  assignedOperatorId?: string;
  lastMessage?: string;
  lastMessageSnippet?: string;
  updatedAt: string;
  createdAt: string;
}

interface MessageItem {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'operator';
  content: string;
  cards?: any[];
  operatorInfo?: { operatorId: string; operatorName: string };
  timestamp: string;
}

export default function MerchantAdminPage() {
  const [activeTab, setActiveTab] = useState<'orders' | 'approvals' | 'live_desk' | 'spus' | 'skus' | 'spi_logs'>(
    'orders',
  );
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogRow[]>([]);
  const [spus, setSpus] = useState<SpuRow[]>([]);
  const [skus, setSkus] = useState<SkuRow[]>([]);
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [activeThreadMessages, setActiveThreadMessages] = useState<MessageItem[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const [shippingOrderId, setShippingOrderId] = useState<string | null>(null);
  const [trackingNumberInput, setTrackingNumberInput] = useState('');
  const [carrierInput, setCarrierInput] = useState('SF');
  const [selectedLog, setSelectedLog] = useState<AuditLogRow | null>(null);
  const [inspectingApproval, setInspectingApproval] = useState<ApprovalItem | null>(null);
  const [isTakingOver, setIsTakingOver] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { submittingActionId, rejectionReasons, setRejectionReasons, executeApprovalAction, executeHumanReplyAction } =
    useApprovalMachine('/api/admin/approvals');

  const loadConversationMessages = useCallback(async (threadId: string) => {
    if (!threadId) return;
    try {
      const resp = await fetch(`/api/admin/conversations/${threadId}?tenantId=aurora`);
      if (resp.ok) {
        const json = await resp.json();
        if (json.success && json.data) {
          setActiveThreadMessages(json.data.messages || []);
        }
      }
    } catch (err) {
      console.error('Failed to fetch thread timeline:', err);
    }
  }, []);

  const fetchDashboardData = useCallback(async () => {
    try {
      setLoading(true);
      const [orderResp, appResp, convResp] = await Promise.all([
        fetch('/api/admin/orders').catch(() => null),
        fetch('/api/admin/approvals?tenantId=aurora').catch(() => null),
        fetch('/api/admin/conversations?tenantId=aurora').catch(() => null),
      ]);

      if (orderResp && orderResp.ok) {
        const data = await orderResp.json();
        if (data.success) {
          setOrders(data.orders || []);
          setAuditLogs(data.auditLogs || []);
          setSpus(data.spus || []);
          setSkus(data.skus || []);
        }
      }

      if (appResp && appResp.ok) {
        const appData = await appResp.json();
        if (appData.success) {
          setApprovals(appData.approvals || []);
        }
      }

      if (convResp && convResp.ok) {
        const convData = await convResp.json();
        if (convData.success) {
          const rawList = convData.conversations || [];
          const convList: ConversationItem[] = rawList.map((item: any) => ({
            ...item,
            id: item.id || item.threadId,
            threadId: item.threadId || item.id,
            lastMessage: item.lastMessage || item.lastMessageSnippet,
          }));
          setConversations(convList);
          if (convList.length > 0 && !activeThreadId) {
            const initialId = convList[0].threadId || convList[0].id;
            setActiveThreadId(initialId);
            loadConversationMessages(initialId);
          }
        }
      }
    } catch (err) {
      console.error('Failed to fetch merchant admin data:', err);
    } finally {
      setLoading(false);
    }
  }, [activeThreadId, loadConversationMessages]);

  useEffect(() => {
    fetchDashboardData();
    const interval = setInterval(fetchDashboardData, 8000);
    return () => clearInterval(interval);
  }, [fetchDashboardData]);

  useEffect(() => {
    if (activeThreadId) {
      loadConversationMessages(activeThreadId);
      const interval = setInterval(() => loadConversationMessages(activeThreadId), 3000);
      return () => clearInterval(interval);
    }
  }, [activeThreadId, loadConversationMessages]);

  useEffect(() => {
    if (activeTab === 'live_desk') {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [activeThreadMessages, activeTab]);

  const handleApprovalAction = async (approvalId: string, action: 'approve' | 'reject') => {
    const result = await executeApprovalAction({
      approvalId,
      action,
      apiEndpoint: '/api/admin/approvals',
    });
    if (result.success) {
      await fetchDashboardData();
      if (inspectingApproval?.id === approvalId) {
        setInspectingApproval(null);
      }
    } else if (result.error) {
      alert(result.error);
    }
  };

  const handleHumanReply = async (approvalId: string, replyMessage: string, isFinish = false) => {
    const result = await executeHumanReplyAction({
      approvalId,
      replyMessage,
      isFinish,
      apiEndpoint: '/api/admin/approvals',
    });
    if (result.success) {
      await fetchDashboardData();
    } else if (result.error) {
      alert(result.error);
    }
  };

  const handleTakeover = async (threadId: string) => {
    setIsTakingOver(true);
    try {
      await fetch('/api/admin/approvals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          threadId,
          action: 'start_human_takeover',
        }),
      });
      await fetchDashboardData();
      if (activeThreadId) {
        await loadConversationMessages(activeThreadId);
      }
    } catch (err) {
      console.error('Takeover failed:', err);
    } finally {
      setIsTakingOver(false);
    }
  };

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || !activeThreadId) return;
    const msg = inputMessage.trim();
    setInputMessage('');

    // Optimistic append
    const optMsg: MessageItem = {
      id: `opt_${Date.now()}`,
      role: 'assistant',
      content: `[商户客服] ${msg}`,
      timestamp: new Date().toISOString(),
    };
    setActiveThreadMessages((prev) => [...prev, optMsg]);

    try {
      // Find active approval or trigger resolve
      const app = approvals.find((a) => a.threadId === activeThreadId && a.status === 'waiting');
      if (app) {
        await executeHumanReplyAction({
          approvalId: app.id,
          replyMessage: msg,
          isFinish: false,
          apiEndpoint: '/api/admin/approvals',
        });
      } else {
        // Direct start takeover and send message
        const res = await fetch('/api/admin/approvals', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            threadId: activeThreadId,
            action: 'start_human_takeover',
          }),
        });
        const d = await res.json();
        if (d.approvalId) {
          await executeHumanReplyAction({
            approvalId: d.approvalId,
            replyMessage: msg,
            isFinish: false,
            apiEndpoint: '/api/admin/approvals',
          });
        }
      }
      await loadConversationMessages(activeThreadId);
    } catch (err) {
      console.error('Failed to send live message:', err);
    }
  };

  const handleShipOrder = async (orderId: string) => {
    if (!trackingNumberInput.trim()) {
      alert('请填写快递运单号');
      return;
    }

    try {
      const resp = await fetch('/api/admin/orders/ship', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          orderId,
          carrierCode: carrierInput,
          trackingNo: trackingNumberInput.trim(),
        }),
      });
      const data = await resp.json();
      if (data.success) {
        alert('🎉 发货成功！已流转为已发货状态并锁定收货地址');
        setShippingOrderId(null);
        setTrackingNumberInput('');
        fetchDashboardData();
      } else {
        alert(`发货失败: ${data.message || '未知错误'}`);
      }
    } catch (err) {
      alert('网络请求失败');
    }
  };

  const pendingApprovalsCount = approvals.filter((a) => a.status === 'waiting').length;

  return (
    <div className="min-h-screen bg-slate-100 flex flex-col font-sans">
      {/* 顶部商户后台 Header */}
      <header className="bg-slate-900 text-white border-b border-slate-800 h-16 flex items-center justify-between px-6 sticky top-0 z-20">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 rounded bg-emerald-600 flex items-center justify-center font-bold text-white shadow-sm">
            A
          </div>
          <div>
            <div className="font-bold text-base tracking-tight flex items-center space-x-2">
              <span>极光潮品商户后台管理系统</span>
              <span className="text-[10px] bg-emerald-950 text-emerald-300 border border-emerald-800 px-2 py-0.5 rounded font-mono">
                Aurora Merchant Port 3005
              </span>
            </div>
            <div className="text-[11px] text-slate-400">
              独立物理隔离 · SPU/SKU 多规格电商 · HITL 审批中枢 · LiveDesk 在线客服
            </div>
          </div>
        </div>

        <div className="flex items-center space-x-4 text-xs">
          <button
            type="button"
            onClick={fetchDashboardData}
            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-700 transition flex items-center space-x-1 cursor-pointer"
          >
            <span>🔄 刷新数据</span>
          </button>
          <a
            href="/"
            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded transition flex items-center space-x-1 shadow-xs"
          >
            <span>🛍️ 返回商城前台</span>
          </a>
        </div>
      </header>

      {/* 主体工作台 */}
      <div className="max-w-7xl w-full mx-auto p-6 flex-1 flex flex-col space-y-6">
        {/* 顶部四栏指标卡 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs flex items-center justify-between">
            <div>
              <div className="text-xs text-slate-500 font-medium">累计订单总数</div>
              <div className="text-2xl font-bold text-slate-900 mt-1">{orders.length} 笔</div>
            </div>
            <div className="text-3xl text-slate-300">📋</div>
          </div>

          <div
            onClick={() => setActiveTab('approvals')}
            className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs flex items-center justify-between cursor-pointer hover:border-amber-400 transition"
          >
            <div>
              <div className="text-xs text-slate-500 font-medium flex items-center space-x-1">
                <span>待人工审核工单</span>
                {pendingApprovalsCount > 0 && <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />}
              </div>
              <div
                className={`text-2xl font-bold mt-1 ${pendingApprovalsCount > 0 ? 'text-amber-600' : 'text-slate-900'}`}
              >
                {pendingApprovalsCount} 笔
              </div>
            </div>
            <div className="text-3xl text-amber-300">🛡️</div>
          </div>

          <div
            onClick={() => setActiveTab('live_desk')}
            className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs flex items-center justify-between cursor-pointer hover:border-blue-400 transition"
          >
            <div>
              <div className="text-xs text-slate-500 font-medium">活跃在线会话</div>
              <div className="text-2xl font-bold text-blue-600 mt-1">{conversations.length} 组</div>
            </div>
            <div className="text-3xl text-blue-300">💬</div>
          </div>

          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs flex items-center justify-between">
            <div>
              <div className="text-xs text-slate-500 font-medium">接收 AI SPI 履约调用</div>
              <div className="text-2xl font-bold text-emerald-600 mt-1">{auditLogs.length} 次</div>
            </div>
            <div className="text-3xl text-slate-300">⚡</div>
          </div>
        </div>

        {/* 标签栏导航 */}
        <div className="flex border-b border-slate-200 bg-white rounded-t-xl px-4 pt-3 gap-6 shadow-2xs overflow-x-auto">
          <button
            type="button"
            onClick={() => setActiveTab('orders')}
            className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition whitespace-nowrap cursor-pointer ${
              activeTab === 'orders'
                ? 'border-emerald-600 text-emerald-700'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            <span>📋 订单中心</span>
            <span className="bg-slate-100 text-slate-600 text-xs px-2 py-0.5 rounded-full">{orders.length}</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('approvals')}
            className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition whitespace-nowrap cursor-pointer ${
              activeTab === 'approvals'
                ? 'border-amber-500 text-amber-700'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            <span>🛡️ 待办审核 (HITL)</span>
            <span
              className={`text-xs px-2 py-0.5 rounded-full font-bold ${
                pendingApprovalsCount > 0 ? 'bg-amber-100 text-amber-800 animate-pulse' : 'bg-slate-100 text-slate-600'
              }`}
            >
              {pendingApprovalsCount}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('live_desk')}
            className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition whitespace-nowrap cursor-pointer ${
              activeTab === 'live_desk'
                ? 'border-blue-600 text-blue-700'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            <span>💬 在线客服工作台</span>
            <span className="bg-blue-100 text-blue-700 text-xs px-2 py-0.5 rounded-full font-bold">
              {conversations.length}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('spus')}
            className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition whitespace-nowrap cursor-pointer ${
              activeTab === 'spus'
                ? 'border-emerald-600 text-emerald-700'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            <span>🏷️ SPU 商品库</span>
            <span className="bg-slate-100 text-slate-600 text-xs px-2 py-0.5 rounded-full">{spus.length}</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('skus')}
            className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition whitespace-nowrap cursor-pointer ${
              activeTab === 'skus'
                ? 'border-emerald-600 text-emerald-700'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            <span>📦 SKU 规格库存</span>
            <span className="bg-slate-100 text-slate-600 text-xs px-2 py-0.5 rounded-full">{skus.length}</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('spi_logs')}
            className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition whitespace-nowrap cursor-pointer ${
              activeTab === 'spi_logs'
                ? 'border-emerald-600 text-emerald-700'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            <span>🔌 SPI 开放审计流水</span>
            <span className="bg-emerald-100 text-emerald-700 text-xs px-2 py-0.5 rounded-full font-bold">
              {auditLogs.length}
            </span>
          </button>
        </div>

        {/* Tab 1: 订单中心 */}
        {activeTab === 'orders' && (
          <div className="bg-white rounded-b-xl border border-slate-200 shadow-2xs overflow-hidden">
            <div className="p-4 border-b border-slate-100 flex justify-between items-center bg-slate-50">
              <span className="text-xs text-slate-600">
                实时展示商户订单。
                <strong>如果用户通过 AI 客服成功修改了地址或退款，此处将实时展示最新变更！</strong>
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 uppercase font-semibold">
                  <tr>
                    <th className="p-3.5">订单流水号</th>
                    <th className="p-3.5">顾客 ID</th>
                    <th className="p-3.5">订单状态</th>
                    <th className="p-3.5">实付金额</th>
                    <th className="p-3.5">收货人 & 联系方式</th>
                    <th className="p-3.5">配送收货地址</th>
                    <th className="p-3.5">物流单号</th>
                    <th className="p-3.5 text-right">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {orders.map((o) => (
                    <tr key={o.order_id} className="hover:bg-slate-50/80 transition">
                      <td className="p-3.5 font-semibold text-slate-900 font-mono">{o.order_id}</td>
                      <td className="p-3.5 text-slate-500">{o.customer_id}</td>
                      <td className="p-3.5">
                        <span
                          className={`px-2 py-0.5 rounded-full font-semibold ${
                            o.status === 'PAID'
                              ? 'bg-amber-100 text-amber-800'
                              : o.status === 'SHIPPED'
                                ? 'bg-blue-100 text-blue-800'
                                : o.status === 'REFUNDED'
                                  ? 'bg-purple-100 text-purple-800'
                                  : 'bg-slate-100 text-slate-800'
                          }`}
                        >
                          {o.status === 'PAID' && '待发货'}
                          {o.status === 'SHIPPED' && '已发货'}
                          {o.status === 'REFUNDED' && '已退款'}
                          {!['PAID', 'SHIPPED', 'REFUNDED'].includes(o.status) && o.status}
                        </span>
                      </td>
                      <td className="p-3.5 font-bold text-slate-900">¥{Number(o.total_amount).toFixed(2)}</td>
                      <td className="p-3.5">
                        <div className="font-medium text-slate-800">{o.shipping_address?.recipientName || '张伟'}</div>
                        <div className="text-[11px] text-slate-400">{o.shipping_address?.phone || '13800138000'}</div>
                      </td>
                      <td className="p-3.5 max-w-xs">
                        <span className="text-slate-800 line-clamp-2" title={o.shipping_address?.fullAddress}>
                          {o.shipping_address?.fullAddress}
                        </span>
                      </td>
                      <td className="p-3.5">
                        {o.tracking_info ? (
                          <span className="text-blue-600 font-mono text-[11px]">
                            {o.tracking_info.carrier} {o.tracking_info.trackingNumber}
                          </span>
                        ) : (
                          <span className="text-slate-400 italic">未发货</span>
                        )}
                      </td>
                      <td className="p-3.5 text-right">
                        {o.status === 'PAID' ? (
                          <button
                            type="button"
                            onClick={() => {
                              setShippingOrderId(o.order_id);
                              setTrackingNumberInput(`SF${Math.floor(10000000000 + Math.random() * 90000000000)}`);
                            }}
                            className="px-2.5 py-1 bg-blue-600 text-white rounded hover:bg-blue-500 transition font-medium cursor-pointer"
                          >
                            一键发货
                          </button>
                        ) : (
                          <span className="text-slate-400 text-[11px]">不可操作</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Tab 2: 待办审核中心 (HITL) */}
        {activeTab === 'approvals' && (
          <div className="space-y-4">
            <div className="bg-amber-50 border border-amber-200 p-4 rounded-xl flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <ShieldAlert className="w-6 h-6 text-amber-600 shrink-0" />
                <div>
                  <h4 className="text-sm font-bold text-amber-900">
                    商户待办安全审核中心 (Human-in-the-Loop Safe Approvals)
                  </h4>
                  <p className="text-xs text-amber-700 mt-0.5">
                    展示 AI
                    决策引擎拦截的高危操作（如大额退款、发货前改地址等）。商户审核决议后，系统将通过事务发件箱自动恢复工作流执行。
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={fetchDashboardData}
                className="px-3 py-1.5 bg-amber-600 text-white rounded-lg text-xs font-semibold hover:bg-amber-700 transition cursor-pointer shrink-0"
              >
                刷新工单
              </button>
            </div>

            {approvals.length === 0 ? (
              <div className="bg-white rounded-xl border border-slate-200 p-12 text-center space-y-3 shadow-2xs">
                <CheckCircle2 className="w-10 h-10 text-emerald-500 mx-auto" />
                <h4 className="text-sm font-bold text-slate-800">当前大盘一片绿灯</h4>
                <p className="text-xs text-slate-400">暂无待审核任务。当顾客在商城发起超阈值退款时将在此展示。</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {approvals.map((approval) => (
                  <PendingApprovalCard
                    key={approval.id}
                    approval={approval as any}
                    rejectionReason={rejectionReasons[approval.id] || ''}
                    setRejectionReason={(val) =>
                      setRejectionReasons((prev) => ({
                        ...prev,
                        [approval.id]: val,
                      }))
                    }
                    isSubmitting={submittingActionId === approval.id}
                    onApprove={(id) => handleApprovalAction(id, 'approve')}
                    onReject={(id) => handleApprovalAction(id, 'reject')}
                    onOpenChat={() => {
                      setActiveThreadId(approval.threadId);
                      setActiveTab('live_desk');
                    }}
                    onInspect={() => setInspectingApproval(approval)}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab 3: 在线客服工作台 (Live Desk Takeover) */}
        {activeTab === 'live_desk' && (
          <div className="bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden flex flex-col md:flex-row h-[700px]">
            {/* 左侧会话列表 */}
            <div className="w-full md:w-80 border-r border-slate-200 flex flex-col bg-slate-50">
              <div className="p-3.5 border-b border-slate-200 bg-white flex items-center justify-between">
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

              <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
                {conversations.length === 0 ? (
                  <div className="p-8 text-center text-xs text-slate-400">暂无会话记录</div>
                ) : (
                  conversations.map((c) => {
                    const threadId = c.threadId || c.id;
                    const isSelected = activeThreadId === threadId;
                    const isTakeover = c.status === 'human_takeover';
                    return (
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
                      <button
                        type="button"
                        onClick={() => handleTakeover(activeThreadId)}
                        disabled={isTakingOver}
                        className="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded-lg text-xs font-semibold transition cursor-pointer shadow-xs flex items-center space-x-1"
                      >
                        <span>🚨 主动接管会话</span>
                      </button>
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
                                  {msg.cards.map((c, cIdx) => (
                                    <RichCardRenderer key={cIdx} card={c} />
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })
                    )}
                    <div ref={messagesEndRef} />
                  </div>

                  {/* 输入框 Footer */}
                  <div className="p-3 bg-white border-t border-slate-200 flex items-center space-x-2">
                    <input
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
                      className="flex-1 px-3.5 py-2 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                    />
                    <button
                      type="button"
                      onClick={handleSendMessage}
                      disabled={!inputMessage.trim()}
                      className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-300 text-white rounded-lg text-xs font-semibold transition cursor-pointer shadow-xs"
                    >
                      发送
                    </button>
                  </div>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center text-xs text-slate-400">
                  请在左侧选择一个会话以开始监控与客服接管
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tab 4: SPU 商品库 */}
        {activeTab === 'spus' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {spus.map((spu) => (
              <div key={spu.id} className="bg-white rounded-xl border border-slate-200 p-5 shadow-2xs space-y-3">
                <div className="flex items-start justify-between">
                  <div>
                    <span className="text-[10px] bg-slate-100 text-slate-600 px-2 py-0.5 rounded font-mono">
                      {spu.spu_code}
                    </span>
                    <h4 className="font-bold text-slate-900 text-sm mt-1">{spu.title}</h4>
                    <p className="text-xs text-slate-500 mt-0.5">{spu.subtitle}</p>
                  </div>
                  <span className="text-xs bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded font-semibold">
                    {spu.category}
                  </span>
                </div>

                {/* 规格维度 */}
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200 space-y-1">
                  <span className="text-[11px] font-bold text-slate-700 block">📐 规格维度矩阵 (Dimensions)</span>
                  <div className="flex flex-wrap gap-2 pt-1">
                    {spu.spec_dimensions?.map((dim) => (
                      <span
                        key={dim.name}
                        className="text-xs bg-white text-slate-700 px-2 py-1 rounded border border-slate-200"
                      >
                        <strong>{dim.name}:</strong> {dim.values.join(' / ')}
                      </span>
                    ))}
                  </div>
                </div>

                {/* 参数 Specs */}
                <div className="text-xs space-y-1 border-t border-slate-100 pt-2">
                  <span className="font-semibold text-slate-700">🔬 材质与技术参数:</span>
                  <div className="grid grid-cols-2 gap-1 text-[11px] text-slate-600">
                    {Object.entries(spu.specs || {}).map(([k, v]) => (
                      <div key={k}>
                        <span className="text-slate-400">{k}:</span> {v}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Tab 5: SKU 规格库存管理 */}
        {activeTab === 'skus' && (
          <div className="bg-white rounded-b-xl border border-slate-200 shadow-2xs overflow-hidden">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 uppercase font-semibold">
                <tr>
                  <th className="p-3.5">SKU 编码</th>
                  <th className="p-3.5">SKU 规格名称</th>
                  <th className="p-3.5">所属 SPU</th>
                  <th className="p-3.5">规格属性快照</th>
                  <th className="p-3.5">独立售价</th>
                  <th className="p-3.5">当前可用库存</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {skus.map((item) => (
                  <tr key={item.sku_code} className="hover:bg-slate-50/80 transition">
                    <td className="p-3.5 font-mono text-slate-600 font-semibold">{item.sku_code}</td>
                    <td className="p-3.5 font-bold text-slate-900">{item.sku_title}</td>
                    <td className="p-3.5 text-slate-500">{item.spu_title}</td>
                    <td className="p-3.5">
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(item.spec_attributes || {}).map(([k, v]) => (
                          <span
                            key={k}
                            className="text-[10px] bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded border border-slate-200"
                          >
                            {k}: {v}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="p-3.5 font-extrabold text-emerald-600">¥{Number(item.price).toFixed(2)}</td>
                    <td className="p-3.5 font-semibold text-slate-800">{item.stock} 件</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Tab 6: AI 客服对接配置与 SPI 审计流水 */}
        {activeTab === 'spi_logs' && (
          <div className="space-y-6">
            <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs space-y-4">
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <h3 className="text-sm font-bold text-slate-900">🔌 商户 SPI 开放接入参数 (Aurora SPI Specs)</h3>
                <span className="text-xs bg-emerald-100 text-emerald-800 px-2.5 py-0.5 rounded font-medium">
                  在线就绪 (Ready)
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                  <div className="text-slate-500 font-medium">SPI 基础服务 URL (spiBaseUrl)</div>
                  <div className="font-mono text-slate-900 font-bold mt-1">http://localhost:3005</div>
                </div>

                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                  <div className="text-slate-500 font-medium">API 签名密钥 (HMAC-SHA256 Secret)</div>
                  <div className="font-mono text-slate-900 font-bold mt-1">aurora_secret_key_8899</div>
                </div>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden">
              <div className="p-4 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
                <span className="text-xs font-bold text-slate-900">
                  📥 来自 Agent 平台的实时 SPI 调度审计流水 (merchant_audit_logs)
                </span>
                <span className="text-xs text-slate-500">物理落盘于商户独立数据库，自动记录幂等防重 Token 与签名</span>
              </div>

              {auditLogs.length === 0 ? (
                <div className="p-12 text-center text-slate-400 text-xs">
                  暂无 SPI 变更记录。请在商城前台拉起 AI 客服发起改地址或退款进行测试！
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 uppercase font-semibold">
                      <tr>
                        <th className="p-3.5">流水 ID</th>
                        <th className="p-3.5">对应订单号</th>
                        <th className="p-3.5">动作类型</th>
                        <th className="p-3.5">幂等防重 Key</th>
                        <th className="p-3.5">执行时间</th>
                        <th className="p-3.5 text-right">报文详情</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 text-slate-700">
                      {auditLogs.map((log) => (
                        <tr key={log.id} className="hover:bg-slate-50/80 transition">
                          <td className="p-3.5 font-mono text-slate-900">{log.id.slice(0, 8)}...</td>
                          <td className="p-3.5 font-semibold text-slate-800">{log.order_id}</td>
                          <td className="p-3.5">
                            <span className="px-2 py-0.5 rounded-full font-bold bg-blue-100 text-blue-800">
                              {log.action_type}
                            </span>
                          </td>
                          <td className="p-3.5 font-mono text-[11px] text-slate-500">
                            {log.idempotency_key?.slice(0, 16)}...
                          </td>
                          <td className="p-3.5 text-slate-500">{new Date(log.created_at).toLocaleTimeString()}</td>
                          <td className="p-3.5 text-right">
                            <button
                              type="button"
                              onClick={() => setSelectedLog(log)}
                              className="px-2.5 py-1 bg-slate-100 text-slate-700 hover:bg-slate-200 rounded font-medium transition cursor-pointer"
                            >
                              查看 Payload
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 审核上下文抽屉 */}
      <ApprovalContextDrawer
        isOpen={Boolean(inspectingApproval)}
        onClose={() => setInspectingApproval(null)}
        approval={inspectingApproval as any}
        onApprove={async (id) => {
          await handleApprovalAction(id, 'approve');
        }}
        onReject={async (id, reason) => {
          if (reason) {
            setRejectionReasons((prev) => ({ ...prev, [id]: reason }));
          }
          await handleApprovalAction(id, 'reject');
        }}
        onHumanReply={async (id, replyMsg, isFinish) => {
          await handleHumanReply(id, replyMsg, isFinish);
        }}
      />

      {/* 发货弹窗 */}
      {shippingOrderId && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl max-w-sm w-full p-5 shadow-xl border border-slate-200">
            <h3 className="text-base font-bold text-slate-900 mb-3">订单一键发货</h3>
            <p className="text-xs text-slate-500 mb-4">订单号: {shippingOrderId}</p>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">承运快递公司</label>
                <select
                  value={carrierInput}
                  onChange={(e) => setCarrierInput(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white"
                >
                  <option value="SF">顺丰速运 (SF Express)</option>
                  <option value="JD">京东快递 (JD Logistics)</option>
                  <option value="ZTO">中通快递 (ZTO)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">快递运单号</label>
                <input
                  type="text"
                  value={trackingNumberInput}
                  onChange={(e) => setTrackingNumberInput(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-blue-500"
                />
              </div>
            </div>

            <div className="mt-5 flex justify-end space-x-2">
              <button
                type="button"
                onClick={() => setShippingOrderId(null)}
                className="px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 rounded-lg cursor-pointer"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => handleShipOrder(shippingOrderId)}
                className="px-4 py-1.5 text-xs font-bold bg-blue-600 text-white rounded-lg hover:bg-blue-500 cursor-pointer"
              >
                确认发货并锁定地址
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 报文查看抽屉 */}
      {selectedLog && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl max-w-lg w-full p-5 shadow-xl border border-slate-200">
            <div className="flex justify-between items-center pb-3 border-b border-slate-100">
              <h3 className="text-sm font-bold text-slate-900">SPI 调用结果 Payload</h3>
              <button
                type="button"
                onClick={() => setSelectedLog(null)}
                className="text-slate-400 hover:text-slate-600 text-lg font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            <div className="py-3">
              <pre className="bg-slate-900 text-emerald-400 p-3 rounded-lg text-xs overflow-x-auto max-h-64 font-mono">
                {JSON.stringify(selectedLog.payload, null, 2)}
              </pre>
            </div>

            <div className="pt-3 border-t border-slate-100 flex justify-end">
              <button
                type="button"
                onClick={() => setSelectedLog(null)}
                className="px-4 py-1.5 text-xs font-semibold bg-slate-900 text-white rounded-lg cursor-pointer"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
