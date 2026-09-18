import React, { createContext, useContext, useCallback, useEffect, useRef, useState } from "react";
import { useApprovalMachine } from "ui";

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


export type WorkbenchTab =
  | "orders"
  | "approvals"
  | "live_desk"
  | "spus"
  | "skus"
  | "spi_logs";

export function useWorkbenchState(initialTab: string) {
  const [activeTab, setActiveTab] = useState<'orders' | 'approvals' | 'live_desk' | 'spus' | 'skus' | 'spi_logs'>(
    initialTab as 'orders',
  );
  const [orders, setOrders] = useState<OrderRow[]>([]);
  // PageContext(19-D3):勾选订单 → 写约定键,悬浮 agent 随问题上行实体过滤
  const [selectedOrderIds, setSelectedOrderIds] = useState<string[]>([]);
  const toggleOrderSelection = (orderId: string) => {
    setSelectedOrderIds((prev) => {
      const next = prev.includes(orderId) ? prev.filter((x) => x !== orderId) : [...prev, orderId];
      try {
        localStorage.setItem('merchant-admin.selection', JSON.stringify(next));
      } catch { /* 隐私模式等存储不可用:选择仍在本页生效 */ }
      return next;
    });
  };
  const [auditLogs, setAuditLogs] = useState<AuditLogRow[]>([]);
  const [spus, setSpus] = useState<SpuRow[]>([]);
  const [skus, setSkus] = useState<SkuRow[]>([]);
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [activeThreadMessages, setActiveThreadMessages] = useState<MessageItem[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [loading, setLoading] = useState(true);

  // Filters & Searches
  const [orderStatusFilter, setOrderStatusFilter] = useState<string>('ALL');
  const [orderSearchQuery, setOrderSearchQuery] = useState<string>('');

  const [approvalStatusFilter, setApprovalStatusFilter] = useState<string>('waiting');
  const [approvalActionFilter, setApprovalActionFilter] = useState<string>('all');
  const [approvalSearchQuery, setApprovalSearchQuery] = useState<string>('');

  const [liveDeskStatusFilter, setLiveDeskStatusFilter] = useState<'ALL' | 'takeover' | 'ai'>('ALL');
  const [liveDeskSearchQuery, setLiveDeskSearchQuery] = useState<string>('');

  const [spuCategoryFilter, setSpuCategoryFilter] = useState<string>('ALL');
  const [spuSearchQuery, setSpuSearchQuery] = useState<string>('');

  const [skuStockFilter, setSkuStockFilter] = useState<'ALL' | 'low' | 'normal'>('ALL');
  const [skuSearchQuery, setSkuSearchQuery] = useState<string>('');

  const [spiActionFilter, setSpiActionFilter] = useState<string>('ALL');
  const [spiSearchQuery, setSpiSearchQuery] = useState<string>('');

  // Modals & Drawers state
  const [shippingOrderId, setShippingOrderId] = useState<string | null>(null);
  const [trackingNumberInput, setTrackingNumberInput] = useState('');
  const [carrierInput, setCarrierInput] = useState('SF');
  const [selectedLog, setSelectedLog] = useState<AuditLogRow | null>(null);
  const [copiedLog, setCopiedLog] = useState(false);
  const [inspectingApproval, setInspectingApproval] = useState<ApprovalItem | null>(null);
  const [isTakingOver, setIsTakingOver] = useState(false);
  const [rejectingApprovalId, setRejectingApprovalId] = useState<string | null>(null);
  const [rejectReasonInput, setRejectReasonInput] = useState<string>('');

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { submittingActionId, setRejectionReasons, executeApprovalAction, executeHumanReplyAction } =
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

      if (orderResp?.ok) {
        const data = await orderResp.json();
        if (data.success) {
          setOrders(data.orders || []);
          setAuditLogs(data.auditLogs || []);
          setSpus(data.spus || []);
          setSkus(data.skus || []);
        }
      }

      if (appResp?.ok) {
        const appData = await appResp.json();
        if (appData.success) {
          setApprovals(appData.approvals || []);
        }
      }

      if (convResp?.ok) {
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

  // biome-ignore lint/correctness/useExhaustiveDependencies: messages.length 为滚动触发器,体内不直接读取
  useEffect(() => {
    if (activeTab === 'live_desk') {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [activeThreadMessages, activeTab]);

  const handleApprovalAction = async (
    approvalId: string,
    action: 'approve' | 'reject',
    /** 弹窗直传驳回原因 —— 不传则由 hook 回退 rejectionReasons/默认文案。
     * 修复(工单 04 审计):弹窗旧实现只写 setRejectionReasons 后立即调用,
     * state 异步更新使 hook 闭包读到旧值,用户填写的原因被吞成兜底文案。 */
    explicitReason?: string,
  ) => {
    const result = await executeApprovalAction({
      approvalId,
      action,
      rejectionReason: action === 'reject' ? (explicitReason ?? undefined) : undefined,
      // 核准人契约(admin-readiness 01):商户面声明身份;控制台暂无登录账号,
      // 以调用面角色声明,接入真实账号后替换为操作员显示名即可,契约不变
      actor: 'merchant_operator',
      actorRole: 'merchant_operator',
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

  const handleSendMessage = async (customText?: string) => {
    const msg = (customText || inputMessage).trim();
    if (!msg || !activeThreadId) return;
    if (!customText) {
      setInputMessage('');
    }

    // Optimistic append
    const optMsg: MessageItem = {
      id: `opt_${Date.now()}`,
      role: 'assistant',
      content: `[商户客服] ${msg}`,
      timestamp: new Date().toISOString(),
    };
    setActiveThreadMessages((prev) => [...prev, optMsg]);

    try {
      const app = approvals.find((a) => a.threadId === activeThreadId && a.status === 'waiting');
      if (app) {
        await executeHumanReplyAction({
          approvalId: app.id,
          replyMessage: msg,
          isFinish: false,
          apiEndpoint: '/api/admin/approvals',
        });
      } else {
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
    } catch {
      alert('网络请求失败');
    }
  };

  // Status counts
  const pendingApprovalsCount = approvals.filter((a) => a.status === 'waiting').length;
  const paidOrdersCount = orders.filter((o) => o.status === 'PAID').length;
  const shippedOrdersCount = orders.filter((o) => o.status === 'SHIPPED').length;
  const refundedOrdersCount = orders.filter((o) => o.status === 'REFUNDED').length;
  const lowStockCount = skus.filter((s) => s.stock < 50).length;

  // Filtered Orders
  const filteredOrders = orders.filter((o) => {
    if (orderStatusFilter !== 'ALL' && o.status !== orderStatusFilter) return false;
    if (orderSearchQuery.trim()) {
      const q = orderSearchQuery.toLowerCase().trim();
      const str =
        `${o.order_id} ${o.customer_id} ${o.shipping_address?.recipientName || ''} ${o.shipping_address?.phone || ''} ${o.shipping_address?.fullAddress || ''} ${o.tracking_info?.trackingNumber || ''}`.toLowerCase();
      if (!str.includes(q)) return false;
    }
    return true;
  });

  // Filtered Conversations
  const filteredConversations = conversations.filter((c) => {
    const isTakeover = c.status === 'human_takeover';
    if (liveDeskStatusFilter === 'takeover' && !isTakeover) return false;
    if (liveDeskStatusFilter === 'ai' && isTakeover) return false;
    if (liveDeskSearchQuery.trim()) {
      const q = liveDeskSearchQuery.toLowerCase().trim();
      const str = `${c.threadId || c.id} ${c.userId || ''} ${c.lastMessage || ''}`.toLowerCase();
      if (!str.includes(q)) return false;
    }
    return true;
  });

  // Categories list for SPU
  const spuCategories = Array.from(new Set(spus.map((s) => s.category))).filter(Boolean);
  const filteredSpus = spus.filter((s) => {
    if (spuCategoryFilter !== 'ALL' && s.category !== spuCategoryFilter) return false;
    if (spuSearchQuery.trim()) {
      const q = spuSearchQuery.toLowerCase().trim();
      const str = `${s.spu_code} ${s.title} ${s.subtitle} ${s.brand} ${s.category}`.toLowerCase();
      if (!str.includes(q)) return false;
    }
    return true;
  });

  // Filtered SKUs
  const filteredSkus = skus.filter((s) => {
    if (skuStockFilter === 'low' && s.stock >= 50) return false;
    if (skuStockFilter === 'normal' && s.stock < 50) return false;
    if (skuSearchQuery.trim()) {
      const q = skuSearchQuery.toLowerCase().trim();
      const str = `${s.sku_code} ${s.sku_title} ${s.spu_title} ${s.brand} ${s.category}`.toLowerCase();
      if (!str.includes(q)) return false;
    }
    return true;
  });

  // Filtered SPI logs
  const filteredAuditLogs = auditLogs.filter((log) => {
    if (spiActionFilter !== 'ALL' && log.action_type !== spiActionFilter) return false;
    if (spiSearchQuery.trim()) {
      const q = spiSearchQuery.toLowerCase().trim();
      const str = `${log.id} ${log.order_id} ${log.action_type} ${log.idempotency_key}`.toLowerCase();
      if (!str.includes(q)) return false;
    }
    return true;
  });

  return {
    activeTab, setActiveTab,
    orders, setOrders, auditLogs, setAuditLogs, spus, setSpus, skus, setSkus,
    approvals, setApprovals, conversations, setConversations,
    activeThreadId, setActiveThreadId, activeThreadMessages, setActiveThreadMessages,
    inputMessage, setInputMessage, loading, setLoading,
    orderStatusFilter, setOrderStatusFilter, orderSearchQuery, setOrderSearchQuery,
    approvalStatusFilter, setApprovalStatusFilter, approvalActionFilter, setApprovalActionFilter,
    approvalSearchQuery, setApprovalSearchQuery,
    liveDeskStatusFilter, setLiveDeskStatusFilter, liveDeskSearchQuery, setLiveDeskSearchQuery,
    spuCategoryFilter, setSpuCategoryFilter, spuSearchQuery, setSpuSearchQuery,
    skuStockFilter, setSkuStockFilter, skuSearchQuery, setSkuSearchQuery,
    spiActionFilter, setSpiActionFilter, spiSearchQuery, setSpiSearchQuery,
    shippingOrderId, setShippingOrderId, trackingNumberInput, setTrackingNumberInput,
    carrierInput, setCarrierInput, selectedLog, setSelectedLog, copiedLog, setCopiedLog,
    inspectingApproval, setInspectingApproval, isTakingOver, setIsTakingOver,
    rejectingApprovalId, setRejectingApprovalId, rejectReasonInput, setRejectReasonInput,
    messagesEndRef,
    selectedOrderIds, setSelectedOrderIds, toggleOrderSelection,
    submittingActionId, setRejectionReasons, executeApprovalAction, executeHumanReplyAction,
    loadConversationMessages, fetchDashboardData,
    handleApprovalAction, handleHumanReply, handleTakeover, handleSendMessage, handleShipOrder,
    pendingApprovalsCount, paidOrdersCount, shippedOrdersCount, refundedOrdersCount, lowStockCount,
    filteredOrders, filteredConversations, spuCategories, filteredSpus, filteredSkus, filteredAuditLogs,
  };
}

export type Workbench = ReturnType<typeof useWorkbenchState>;

const WorkbenchContext = createContext<Workbench | null>(null);

export function WorkbenchProvider({ value, children }: { value: Workbench; children: React.ReactNode }) {
  return <WorkbenchContext.Provider value={value}>{children}</WorkbenchContext.Provider>;
}

export function useWorkbench(): Workbench {
  const w = useContext(WorkbenchContext);
  if (!w) throw new Error("useWorkbench 必须在 WorkbenchProvider 内使用");
  return w;
}
