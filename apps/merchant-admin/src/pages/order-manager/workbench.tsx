import { api, authedFetch, errMsgOf } from '@/lib/api';
import type { OrderAuditLog, OrderDetail } from '@/lib/api';
import {
  OPERATOR_DESK_CONNECT,
  OPERATOR_DESK_NS,
  type Socket,
  appendOptimistic,
  buildOptimisticMessage,
  emitDeskAck,
  newClientMsgId,
  operatorDeskAuth,
} from '@/lib/desk-link';
import * as pageContext from '@/lib/page-context';
import React, { createContext, useContext, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { io } from 'socket.io-client';
import { useApprovalMachine } from 'ui';
import type { ApprovalItem, AuditLogRow, ConversationItem, MessageItem, OrderRow } from './workbench.types';

export type { ApprovalItem, AuditLogRow, ConversationItem, MessageItem, OrderRow };

/** 工作台范围(与菜单一一对应):orders=订单;approvals=纯待办;live-desk=聊天+待办;
 *  spi-logs=审计流水。真源在 workbench.tsx,index.tsx 再导出(App 路由传入)。 */
export type WorkbenchScope = 'orders' | 'approvals' | 'live-desk' | 'spi-logs';

const contains = (hay: string, q: string) => hay.toLowerCase().includes(q);

/** P4 消息/工单显式解耦(spec §2.7):回退面坐席发言走 socket send_message,
 *  不再借道/新造审批工单 —— 此前「找 waiting 工单否则先 takeover 再 human_reply」
 *  会把普通聊天偷换为工单回复,并把转人工工单当消息通道吞掉。连接懒建:首条
 *  消息才拨号;拨号/发送失败清缓存下次重拨。clientMsgId 幂等透传(P4 §2.7)。
 *  幂等键/守卫 ack/拨号共享面收口 lib/desk-link(候选⑤);拨号生命周期(模块
 *  单例懒拨)为回退面合法所有权,保留本地。 */
let deskSocketPromise: Promise<Socket> | null = null;
function deskSocket(): Promise<Socket> {
  if (!deskSocketPromise) {
    deskSocketPromise = new Promise<Socket>((resolve, reject) => {
      const socket = io(OPERATOR_DESK_NS, {
        ...OPERATOR_DESK_CONNECT,
        auth: operatorDeskAuth('aurora'),
      });
      const timer = setTimeout(() => {
        // 超时同样毒化缓存:不清单例则后续发送永远 await 同一已 reject 的 promise
        //(整页刷新前所有发送必败),socket 也成了无人消费的孤儿重连器
        deskSocketPromise = null;
        socket.close();
        reject(new Error('实时通道连接超时'));
      }, 8_000);
      socket.on('connect', () => {
        clearTimeout(timer);
        resolve(socket);
      });
      socket.on('connect_error', (err: Error) => {
        clearTimeout(timer);
        deskSocketPromise = null;
        socket.close();
        reject(err);
      });
    });
  }
  return deskSocketPromise;
}

/** throw 语义保留(调用方 catch 即 resync):ack 守卫在 desk-link(resolve 永不
 *  throw),本面在此转 throw —— 文案随 desk-link 统一词表。 */
async function emitDeskMessage(threadId: string, content: string, clientMsgId: string): Promise<void> {
  const socket = await deskSocket();
  const r = await emitDeskAck(socket, 'send_message', {
    threadId,
    tenantId: 'aurora',
    role: 'operator',
    content,
    clientMsgId,
  });
  if (!r.ok) throw new Error(r.error);
}

/** 集中式状态 hook(功能域:订单/审批/客服/审计;商品库有独立页,不再入工作台)。
 *  派生集合(计数/过滤)useMemo 化:任一 state 变化不再整树逐项重算。
 *  scope 数据面裁剪(2026-10-15 候选⑤):此前 scope-blind 三连拉 —— 访问
 *  /spi-logs 也 8s 轮询订单+审批+会话,且 3s 消息轮询在任意 scope 自启
 *  (conversations 载荷一到就自动选首线程);现在只拉本 scope 消费的域。 */
export function useWorkbenchState(scope: WorkbenchScope) {
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
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

  // Filters & Searches
  const [orderStatusFilter, setOrderStatusFilter] = useState<string>('ALL');
  const [orderSearchQuery, setOrderSearchQuery] = useState<string>('');

  const [approvalStatusFilter, setApprovalStatusFilter] = useState<string>('waiting');
  const [approvalActionFilter, setApprovalActionFilter] = useState<string>('all');
  const [approvalSearchQuery, setApprovalSearchQuery] = useState<string>('');

  const [liveDeskStatusFilter, setLiveDeskStatusFilter] = useState<'ALL' | 'takeover' | 'ai'>('ALL');
  const [liveDeskSearchQuery, setLiveDeskSearchQuery] = useState<string>('');

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
  const [isReleasing, setIsReleasing] = useState(false);
  const [rejectingApprovalId, setRejectingApprovalId] = useState<string | null>(null);
  const [rejectReasonInput, setRejectReasonInput] = useState<string>('');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  // 轮询稳定性(2026-09-26 夜审 ③):activeThreadId 走 ref —— fetchDashboardData
  // 不再随会话切换重建,8s 轮询间隔不被反复 clearInterval;首载完成后不再置
  // loading,后台轮询刷新不闪整页骨架。
  const activeThreadIdRef = useRef<string | null>(null);

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
      // 单域失败不拖垮面板:各自 catch 落 null,成功的域照常渲染
      const scope = scopeRef.current;
      const [orderData, appData, convData] = await Promise.all([
        scope === 'orders' || scope === 'spi-logs' ? api.orders.list().catch(() => null) : Promise.resolve(null),
        scope === 'approvals' || scope === 'live-desk' ? api.approvals.list().catch(() => null) : Promise.resolve(null),
        scope === 'live-desk' ? api.conversations.list().catch(() => null) : Promise.resolve(null),
      ]);

      if (orderData?.success) {
        setOrders(orderData.orders || []);
        setAuditLogs(orderData.auditLogs || []);
      }

      if (appData?.success) {
        setApprovals(appData.approvals || []);
      }

      if (convData?.success) {
        // 行形状修补(id/threadId/lastMessage)已收口 api.conversations.list adapter —— 页面拿成品行
        const convList = convData.conversations || [];
        setConversations(convList);
        if (convList.length > 0 && !activeThreadIdRef.current) {
          const initialId = convList[0].threadId;
          setActiveThreadId(initialId);
          loadConversationMessages(initialId);
        }
      }
    } catch (err) {
      console.error('Failed to fetch merchant admin data:', err);
    }
  }, [loadConversationMessages]);

  useEffect(() => {
    fetchDashboardData();
    const interval = setInterval(fetchDashboardData, 8000);
    return () => clearInterval(interval);
  }, [fetchDashboardData]);

  useEffect(() => {
    // 3s 时间线轮询仅 live-desk 面(候选⑤:此前 conversations 载荷一到位就
    // 自动选首线程,任意 scope 都会自启 3s 轮询 —— /orders /spi-logs 全中招)
    if (scope !== 'live-desk' || !activeThreadId) return;
    loadConversationMessages(activeThreadId);
    const interval = setInterval(() => loadConversationMessages(activeThreadId), 3000);
    return () => clearInterval(interval);
  }, [scope, activeThreadId, loadConversationMessages]);

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
      // 核准人真源化(P1,spec §2.2):不再自报 actor —— 网关从员工 JWT
      // 派生 resolvedBy/operator,坐席消息落列与审计据此落座
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

  /** 释放接管回 AI(P1 事故止血,spec §2.1):写真源 threads → active,
   *  AI 暂停闸随状态自然解除;服务端条件 UPDATE 幂等,重复点无副作用。 */
  const handleRelease = async (threadId: string) => {
    setIsReleasing(true);
    try {
      const res = await api.approvals.release(threadId);
      if (res.success === false && res.error) {
        alert(res.error);
      }
      await fetchDashboardData();
      await loadConversationMessages(threadId);
    } catch (err) {
      console.error('Release failed:', err);
    } finally {
      setIsReleasing(false);
    }
  };

  const handleSendMessage = async (customText?: string) => {
    const msg = (customText || inputMessage).trim();
    if (!msg || !activeThreadId) return;
    if (!customText) {
      setInputMessage('');
    }

    // Optimistic append(P1:坐席消息落 role='operator',无前缀;P4 起走
    // socket send_message 直发,消息与工单彻底解耦 —— 不再吞 waiting 工单
    // 当回复通道,也不再为发一条消息暗造接管工单)。幂等键/乐观行构造走
    // lib/desk-link 单点(候选⑤:fallback 下划线违正则的实弹自此绝源)
    const clientMsgId = newClientMsgId();
    const optMsg = buildOptimisticMessage(clientMsgId, msg);
    setActiveThreadMessages((prev) => appendOptimistic(prev, optMsg));

    try {
      await emitDeskMessage(activeThreadId, msg, clientMsgId);
      await loadConversationMessages(activeThreadId);
    } catch (err) {
      // 回滚 = 重拉真源:没落库则乐观行消失;落库而 ack 未达则如实显示
      console.error('Failed to send live message:', err);
      await loadConversationMessages(activeThreadId);
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
        if (spiSearchQuery.trim()) {
          const q = spiSearchQuery.toLowerCase().trim();
          if (!contains(`${log.id} ${log.order_id} ${log.action_type} ${log.idempotency_key}`, q)) return false;
        }
        return true;
      }),
    [auditLogs, spiSearchQuery],
  );

  return {
    orders,
    auditLogs,
    approvals,
    conversations,
    activeThreadId,
    setActiveThreadId,
    activeThreadMessages,
    inputMessage,
    setInputMessage,
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
    isReleasing,
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
    loadConversationMessages,
    fetchDashboardData,
    handleApprovalAction,
    handleHumanReply,
    handleTakeover,
    handleRelease,
    handleSendMessage,
    handleShipOrder,
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
