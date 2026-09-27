import { api, authedFetch } from '@/lib/api';
import type { OrderAuditLog, OrderDetail } from '@/lib/api';
import * as pageContext from '@/lib/page-context';
import React, { createContext, useContext, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useApprovalMachine } from 'ui';
import type { ApprovalItem, AuditLogRow, ConversationItem, MessageItem, OrderRow } from './workbench.types';

export type { ApprovalItem, AuditLogRow, ConversationItem, MessageItem, OrderRow };

const contains = (hay: string, q: string) => hay.toLowerCase().includes(q);

/** 集中式状态 hook(功能域:订单/审批/客服/审计;商品库有独立页,不再入工作台)。
 *  派生集合(计数/过滤)useMemo 化:任一 state 变化不再整树逐项重算。 */
export function useWorkbenchState(initialTab: string) {
  const [orders, setOrders] = useState<OrderRow[]>([]);
  // PageContext(19-D3,T5 翻新):勾选订单 → 内存广播库(类型标记 order),
  // 悬浮 agent 实时订阅;不再写 localStorage(残留会静默污染查询)
  const [selectedOrderIds, setSelectedOrderIds] = useState<string[]>([]);
  const toggleOrderSelection = (orderId: string) => {
    setSelectedOrderIds((prev) => {
      const next = prev.includes(orderId) ? prev.filter((x) => x !== orderId) : [...prev, orderId];
      pageContext.setSelectionKind('order', next);
      return next;
    });
  };
  const [auditLogs, setAuditLogs] = useState<AuditLogRow[]>([]);
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

  const [spiActionFilter, setSpiActionFilter] = useState<string>('ALL');
  const [spiSearchQuery, setSpiSearchQuery] = useState<string>('');

  // Modals & Drawers state
  const [shippingOrderId, setShippingOrderId] = useState<string | null>(null);
  const [trackingNumberInput, setTrackingNumberInput] = useState('');
  const [carrierInput, setCarrierInput] = useState('SF');
  const [selectedLog, setSelectedLog] = useState<AuditLogRow | null>(null);
  const [copiedLog, setCopiedLog] = useState(false);
  const [inspectingApproval, setInspectingApproval] = useState<ApprovalItem | null>(null);
  // 订单详情抽屉(orderId null = 关闭;详情独立拉取,不随 8s 轮询整卡刷新)
  const [detailOrderId, setDetailOrderId] = useState<string | null>(null);
  const [orderDetail, setOrderDetail] = useState<OrderDetail | null>(null);
  const [detailAuditLogs, setDetailAuditLogs] = useState<OrderAuditLog[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [isTakingOver, setIsTakingOver] = useState(false);
  const [rejectingApprovalId, setRejectingApprovalId] = useState<string | null>(null);
  const [rejectReasonInput, setRejectReasonInput] = useState<string>('');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  // 轮询稳定性(2026-09-26 夜审 ③):activeThreadId 走 ref —— fetchDashboardData
  // 不再随会话切换重建,8s 轮询间隔不被反复 clearInterval;首载完成后不再置
  // loading,后台轮询刷新不闪整页骨架。
  const activeThreadIdRef = useRef<string | null>(null);
  const hasLoadedRef = useRef(false);

  useEffect(() => {
    activeThreadIdRef.current = activeThreadId;
  }, [activeThreadId]);

  const { submittingActionId, setRejectionReasons, executeApprovalAction, executeHumanReplyAction } =
    useApprovalMachine('/api/admin/approvals', { fetcher: authedFetch });

  const loadConversationMessages = useCallback(async (threadId: string) => {
    if (!threadId) return;
    try {
      const json = await api.conversations.messages(threadId);
      if (json.success && json.data) {
        setActiveThreadMessages(json.data.messages || []);
      }
    } catch (err) {
      console.error('Failed to fetch thread timeline:', err);
    }
  }, []);

  const fetchDashboardData = useCallback(async () => {
    try {
      if (!hasLoadedRef.current) {
        setLoading(true);
      }
      // 单域失败不拖垮面板:各自 catch 落 null,成功的域照常渲染
      const [orderData, appData, convData] = await Promise.all([
        api.orders.list().catch(() => null),
        api.approvals.list().catch(() => null),
        api.conversations.list().catch(() => null),
      ]);

      if (orderData?.success) {
        setOrders(orderData.orders || []);
        setAuditLogs(orderData.auditLogs || []);
      }

      if (appData?.success) {
        setApprovals(appData.approvals || []);
      }

      if (convData?.success) {
        const rawList = convData.conversations || [];
        const convList: ConversationItem[] = rawList.map((item: any) => ({
          ...item,
          id: item.id || item.threadId,
          threadId: item.threadId || item.id,
          lastMessage: item.lastMessage || item.lastMessageSnippet,
        }));
        setConversations(convList);
        if (convList.length > 0 && !activeThreadIdRef.current) {
          const initialId = convList[0].threadId || convList[0].id;
          setActiveThreadId(initialId);
          loadConversationMessages(initialId);
        }
      }
    } catch (err) {
      console.error('Failed to fetch merchant admin data:', err);
    } finally {
      hasLoadedRef.current = true;
      setLoading(false);
    }
  }, [loadConversationMessages]);

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

  // 仅末条消息变化时滚动:数组身份每轮轮询都重建,拿它当触发器会在内容
  // 未变时也整页平滑滚动(3s 一次的滚动抖动)
  const lastMessageId = activeThreadMessages[activeThreadMessages.length - 1]?.id ?? '';
  // biome-ignore lint/correctness/useExhaustiveDependencies: lastMessageId 是派生触发器,体内刻意不读取
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [lastMessageId]);

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
      await api.approvals.takeover(threadId);
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
        const d = await api.approvals.takeover(activeThreadId);
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
      const data = await api.orders.ship({
        orderId,
        carrierCode: carrierInput,
        trackingNo: trackingNumberInput.trim(),
      });
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

  /** 打开订单详情抽屉:拉详情 + 审计时间线(404/失败以 detailError 呈现,不静默空白)。 */
  const openOrderDetail = useCallback(async (orderId: string) => {
    setDetailOrderId(orderId);
    setDetailLoading(true);
    setDetailError(null);
    setOrderDetail(null);
    setDetailAuditLogs([]);
    try {
      const body = await api.orders.detail(orderId);
      if (body.success && body.order) {
        setOrderDetail(body.order);
        setDetailAuditLogs(body.auditLogs || []);
      } else {
        setDetailError(body.error || '订单详情加载失败');
      }
    } catch {
      setDetailError('网络请求失败');
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const closeOrderDetail = useCallback(() => {
    setDetailOrderId(null);
    setOrderDetail(null);
    setDetailAuditLogs([]);
    setDetailError(null);
  }, []);

  // ---- 派生:计数与各域过滤集(useMemo;过滤谓词纯函数内聚在本 hook) ----
  const pendingApprovalsCount = useMemo(() => approvals.filter((a) => a.status === 'waiting').length, [approvals]);
  const paidOrdersCount = useMemo(() => orders.filter((o) => o.status === 'PAID').length, [orders]);
  const shippedOrdersCount = useMemo(() => orders.filter((o) => o.status === 'SHIPPED').length, [orders]);
  const refundedOrdersCount = useMemo(() => orders.filter((o) => o.status === 'REFUNDED').length, [orders]);

  const filteredOrders = useMemo(
    () =>
      orders.filter((o) => {
        if (orderStatusFilter !== 'ALL' && o.status !== orderStatusFilter) return false;
        if (orderSearchQuery.trim()) {
          const q = orderSearchQuery.toLowerCase().trim();
          const hit = contains(
            `${o.order_id} ${o.customer_id} ${o.shipping_address?.recipientName || ''} ${o.shipping_address?.phone || ''} ${o.shipping_address?.fullAddress || ''} ${o.tracking_info?.trackingNumber || ''}`,
            q,
          );
          if (!hit) return false;
        }
        return true;
      }),
    [orders, orderStatusFilter, orderSearchQuery],
  );

  const filteredConversations = useMemo(
    () =>
      conversations.filter((c) => {
        const isTakeover = c.status === 'human_takeover';
        if (liveDeskStatusFilter === 'takeover' && !isTakeover) return false;
        if (liveDeskStatusFilter === 'ai' && isTakeover) return false;
        if (liveDeskSearchQuery.trim()) {
          const q = liveDeskSearchQuery.toLowerCase().trim();
          if (!contains(`${c.threadId || c.id} ${c.userId || ''} ${c.lastMessage || ''}`, q)) return false;
        }
        return true;
      }),
    [conversations, liveDeskStatusFilter, liveDeskSearchQuery],
  );

  const filteredAuditLogs = useMemo(
    () =>
      auditLogs.filter((log) => {
        if (spiActionFilter !== 'ALL' && log.action_type !== spiActionFilter) return false;
        if (spiSearchQuery.trim()) {
          const q = spiSearchQuery.toLowerCase().trim();
          if (!contains(`${log.id} ${log.order_id} ${log.action_type} ${log.idempotency_key}`, q)) return false;
        }
        return true;
      }),
    [auditLogs, spiActionFilter, spiSearchQuery],
  );

  return {
    orders,
    auditLogs,
    approvals,
    setApprovals,
    conversations,
    setConversations,
    activeThreadId,
    setActiveThreadId,
    activeThreadMessages,
    setActiveThreadMessages,
    inputMessage,
    setInputMessage,
    loading,
    setLoading,
    orderStatusFilter,
    setOrderStatusFilter,
    orderSearchQuery,
    setOrderSearchQuery,
    approvalStatusFilter,
    setApprovalStatusFilter,
    approvalActionFilter,
    setApprovalActionFilter,
    approvalSearchQuery,
    setApprovalSearchQuery,
    liveDeskStatusFilter,
    setLiveDeskStatusFilter,
    liveDeskSearchQuery,
    setLiveDeskSearchQuery,
    spiActionFilter,
    setSpiActionFilter,
    spiSearchQuery,
    setSpiSearchQuery,
    shippingOrderId,
    setShippingOrderId,
    trackingNumberInput,
    setTrackingNumberInput,
    carrierInput,
    setCarrierInput,
    selectedLog,
    setSelectedLog,
    copiedLog,
    setCopiedLog,
    inspectingApproval,
    setInspectingApproval,
    detailOrderId,
    orderDetail,
    detailAuditLogs,
    detailLoading,
    detailError,
    openOrderDetail,
    closeOrderDetail,
    isTakingOver,
    setIsTakingOver,
    rejectingApprovalId,
    setRejectingApprovalId,
    rejectReasonInput,
    setRejectReasonInput,
    messagesEndRef,
    selectedOrderIds,
    setSelectedOrderIds,
    toggleOrderSelection,
    submittingActionId,
    setRejectionReasons,
    executeApprovalAction,
    executeHumanReplyAction,
    loadConversationMessages,
    fetchDashboardData,
    handleApprovalAction,
    handleHumanReply,
    handleTakeover,
    handleSendMessage,
    handleShipOrder,
    pendingApprovalsCount,
    paidOrdersCount,
    shippedOrdersCount,
    refundedOrdersCount,
    filteredOrders,
    filteredConversations,
    filteredAuditLogs,
  };
}

export type Workbench = ReturnType<typeof useWorkbenchState>;

const WorkbenchContext = createContext<Workbench | null>(null);

export function WorkbenchProvider({ value, children }: { value: Workbench; children: React.ReactNode }) {
  return <WorkbenchContext.Provider value={value}>{children}</WorkbenchContext.Provider>;
}

export function useWorkbench(): Workbench {
  const w = useContext(WorkbenchContext);
  if (!w) throw new Error('useWorkbench 必须在 WorkbenchProvider 内使用');
  return w;
}
