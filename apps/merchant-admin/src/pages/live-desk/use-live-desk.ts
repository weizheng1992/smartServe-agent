// 坐席台数据面 hook(live-desk-rework P2/P4):socket.io operator 连接即在线,
// 列表/时间线走员工形态 HTTP,认领/释放/发言走 socket ack(服务端裁决原子
// 守卫与 perm 闸,前端只呈递结果)。P4:发言带 clientMsgId 幂等(乐观气泡 +
// 失败回真源重同步)、typing 输入态收发、工单批驳走 /api/chat/approvals。
// tenantId 与 api.ts 同取 dev 单租户 'aurora'(x-tenant-id 同值,见
// .claude/rules/merchant-admin.md §1.1)。
import {
  type ApprovalItem,
  type DeskAgentRow,
  type DeskConversationRow,
  type DeskNoteItem,
  type LiveDeskContext,
  api,
  authToken,
  currentStaffEmail,
} from '@/lib/api';
import type { MessageItem } from '@/lib/api';
import { useCallback, useEffect, useRef, useState } from 'react';
import { type Socket, io } from 'socket.io-client';

const TENANT_ID = 'aurora';
const LIST_REFRESH_MS = 30_000; // 兜底轮询(socket 事件即时增量,轮询防漏)
const PRESENCE_REFRESH_MS = 20_000;
const PRESENCE_PING_MS = 30_000;
const NOW_TICK_MS = 1_000; // 排队等待计时刷新
const ACK_TIMEOUT_MS = 8_000;
const TYPING_THROTTLE_MS = 1_500; // 输入态上行节流
const TYPING_HOLD_MS = 2_500; // 「对方正在输入」显示保持窗

export interface LiveDeskAck {
  success: boolean;
  error?: string;
  status?: string;
  assignedOperatorId?: string | null;
  messageId?: string;
}

export function useLiveDesk() {
  const myEmail = currentStaffEmail();
  const [conversations, setConversations] = useState<DeskConversationRow[]>([]);
  const [agents, setAgents] = useState<DeskAgentRow[]>([]);
  const [connected, setConnected] = useState(false);
  const [dnd, setDnd] = useState(false);
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<MessageItem[]>([]);
  const [context, setContext] = useState<LiveDeskContext | null>(null);
  const [pendingTicket, setPendingTicket] = useState<ApprovalItem | null>(null);
  const [peerTyping, setPeerTyping] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const socketRef = useRef<Socket | null>(null);
  const typingSentAtRef = useRef(0); // 上行节流
  const typingHoldRef = useRef<ReturnType<typeof setTimeout> | null>(null); // 显示保持窗
  const joinedRoomsRef = useRef<Set<string>>(new Set()); // 已入房集合(join 去重,重连清空重进)

  const loadConversations = useCallback(async () => {
    try {
      const body = await api.liveDesk.conversations({ limit: 100 });
      if (body.success) setConversations(body.conversations);
    } catch (err) {
      console.error('[live-desk] 会话列表加载失败(网关未启动?)', err);
    }
  }, []);

  const loadPresence = useCallback(async () => {
    try {
      const body = await api.liveDesk.presence();
      if (body.success) {
        setAgents(body.agents);
        const mine = body.agents.find((a) => a.email === currentStaffEmail());
        if (mine) setDnd(mine.dnd);
      }
    } catch {
      // presence 是纯展示增强,失败按空态呈现,不打断台面
    }
  }, []);

  const loadContext = useCallback(async (threadId: string) => {
    try {
      const body = await api.liveDesk.context(threadId);
      if (body.success) setContext(body);
    } catch {
      // 上下文栏是辅助面,失败按空态呈现不阻断时间线
    }
  }, []);

  // 本会话待批工单(P4 台内批驳):员工 JWT 列表本租户收窄,threadId 就地过滤。
  const loadPendingTicket = useCallback(async (threadId: string) => {
    try {
      const body = await api.liveDesk.pendingApprovals();
      if (body.success) {
        setPendingTicket(body.approvals.find((a) => a.threadId === threadId) || null);
      }
    } catch {
      // 待批卡是辅助面,拉取失败按无工单呈现,不阻断时间线
    }
  }, []);

  // 选中线程的 ref(闭包读取最新值:new_message 回环与同会话重入判定,不重连 socket)
  const selectedThreadIdRef = useRef<string | null>(null);
  useEffect(() => {
    selectedThreadIdRef.current = selectedThreadId;
  }, [selectedThreadId]);

  const openThread = useCallback(
    async (threadId: string) => {
      // 同会话重入(new_message 房间回环、发送后对齐真源)不清态 —— 塌空再
      // 重灌即实弹「每次发消息抖一下」(时间线闪空 + 右栏闪白 + 滚动跳位);
      // 仅真正切换会话才清旧时间线/上下文/待批卡(防串栏)。
      const switching = selectedThreadIdRef.current !== threadId;
      setSelectedThreadId(threadId);
      if (switching) {
        setTimeline([]);
        setContext(null);
        setPendingTicket(null);
      }
      // 入房:房间广播(new_message / conversation_state_changed)必须 join 才收;
      // 已入房去重(重连时 connect 钩子清集合并对当前会话重进)
      if (!joinedRoomsRef.current.has(threadId)) {
        joinedRoomsRef.current.add(threadId);
        socketRef.current?.emit('join_thread', { threadId, tenantId: TENANT_ID, role: 'operator' });
      }
      try {
        const body = await api.liveDesk.timeline(threadId);
        if (body.success && body.data) setTimeline(body.data.messages || []);
      } catch (err) {
        console.error('[live-desk] 时间线加载失败', err);
      }
      void loadContext(threadId);
      void loadPendingTicket(threadId);
    },
    [loadContext, loadPendingTicket],
  );

  // socket.io operator 连接(员工 JWT 必须有效且租户一致,服务端裁)
  useEffect(() => {
    if (!authToken()) return;
    const socket = io('/ws/chat', {
      path: '/socket.io',
      transports: ['websocket'],
      auth: { tenantId: TENANT_ID, userId: myEmail, role: 'operator', token: authToken() },
      reconnection: true,
    });
    socketRef.current = socket;
    socket.on('connect', () => {
      setConnected(true);
      // 重连后房间成员资格失效:清已入房集合,并对当前选中会话立即重进,
      // 否则断线期间打开的会话要等手动重点一次才恢复实时广播
      joinedRoomsRef.current.clear();
      const tid = selectedThreadIdRef.current;
      if (tid) {
        joinedRoomsRef.current.add(tid);
        socket.emit('join_thread', { threadId: tid, tenantId: TENANT_ID, role: 'operator' });
      }
    });
    socket.on('disconnect', () => setConnected(false));
    socket.on('connect_error', () => setConnected(false));
    // 认领/释放广播:就地更新行(threads 真源三键 status/assignedOperatorId/unreadCount)
    socket.on('conversation_state_changed', (payload: Partial<DeskConversationRow> & { threadId?: string }) => {
      if (!payload?.threadId) return;
      setConversations((prev) =>
        prev.map((c) => (c.threadId === payload.threadId ? ({ ...c, ...payload } as DeskConversationRow) : c)),
      );
      void loadConversations(); // 兜底对齐(排队新行/列表序变化)
    });
    // 选中会话的实时消息(顾客/同事坐席发言)
    socket.on('new_message', (payload: { threadId?: string }) => {
      if (payload?.threadId && payload.threadId === selectedThreadIdRef.current) void openThread(payload.threadId);
    });
    // P4 typing 接线:对端输入态透传广播(skip_sid 已排除发送者);仅顾客侧
    // 输入点亮「对方正在输入」,同事坐席的输入态不显示。
    socket.on('user_typing', (payload: { threadId?: string; role?: string }) => {
      if (payload?.threadId !== selectedThreadIdRef.current || payload?.role === 'operator') return;
      setPeerTyping(true);
      if (typingHoldRef.current) clearTimeout(typingHoldRef.current);
      typingHoldRef.current = setTimeout(() => setPeerTyping(false), TYPING_HOLD_MS);
    });
    return () => {
      socket.close();
      socketRef.current = null;
      setConnected(false);
      if (typingHoldRef.current) clearTimeout(typingHoldRef.current);
    };
    // loadConversations/openThread 均为稳定 useCallback;myEmail 为稳定字符串,
    // 不会引发重连
  }, [loadConversations, openThread, myEmail]);

  // 初始加载 + 兜底轮询 + 排队计时 tick
  useEffect(() => {
    void loadConversations();
    void loadPresence();
    const timers = [
      setInterval(() => void loadConversations(), LIST_REFRESH_MS),
      setInterval(() => void loadPresence(), PRESENCE_REFRESH_MS),
      setInterval(() => setNow(Date.now()), NOW_TICK_MS),
    ];
    return () => timers.forEach(clearInterval);
  }, [loadConversations, loadPresence]);

  // presence 心跳(socket 在线时;空闲坐席保活)
  useEffect(() => {
    const timer = setInterval(() => {
      socketRef.current?.emit('presence_ping', {});
    }, PRESENCE_PING_MS);
    return () => clearInterval(timer);
  }, []);

  const emitAck = useCallback((event: string, payload: Record<string, unknown>): Promise<LiveDeskAck> => {
    return new Promise((resolve) => {
      const socket = socketRef.current;
      if (!socket || !socket.connected) {
        resolve({ success: false, error: '未连接实时通道,请稍候重试' });
        return;
      }
      const timer = setTimeout(() => resolve({ success: false, error: '响应超时,请重试' }), ACK_TIMEOUT_MS);
      socket.emit(event, payload, (ack: LiveDeskAck) => {
        clearTimeout(timer);
        resolve(ack || { success: false, error: '空响应' });
      });
    });
  }, []);

  const claim = useCallback(
    async (threadId: string) => {
      const ack = await emitAck('takeover_conversation', { threadId, tenantId: TENANT_ID });
      if (ack.success) {
        // 坐席未入房时收不到房间广播,ack 即就地更新 + 兜底重拉
        setConversations((prev) =>
          prev.map((c) =>
            c.threadId === threadId
              ? { ...c, status: ack.status || 'human_takeover', assignedOperatorId: myEmail, unreadCount: 0 }
              : c,
          ),
        );
        void loadConversations();
      }
      return ack;
    },
    [emitAck, myEmail, loadConversations],
  );
  const release = useCallback(
    async (threadId: string) => {
      const ack = await emitAck('release_takeover', { threadId, tenantId: TENANT_ID });
      if (ack.success) {
        setConversations((prev) =>
          prev.map((c) =>
            c.threadId === threadId ? { ...c, status: ack.status || 'active', assignedOperatorId: null } : c,
          ),
        );
        void loadConversations();
      }
      return ack;
    },
    [emitAck, loadConversations],
  );
  // P4 typing 上行:输入即节流 emit;服务端透传广播给房间内其他人。
  const emitTyping = useCallback((threadId: string) => {
    const now = Date.now();
    if (now - typingSentAtRef.current < TYPING_THROTTLE_MS) return;
    typingSentAtRef.current = now;
    socketRef.current?.emit('typing', { threadId, tenantId: TENANT_ID, role: 'operator' });
  }, []);

  const sendMessage = useCallback(
    async (threadId: string, content: string) => {
      // P4 消息幂等(spec §2.7):客户端 UUID 作消息主键 —— 先挂乐观气泡,
      // ack 成功即整表重同步(服务端真相同 id 单行);失败/超时不盲删,重拉
      // 时间线以真源裁决(重放可能已落库,只有 ack 未达)。重放静默由服务端
      // ON CONFLICT DO NOTHING 保证,ack 恒回既有 messageId。
      const clientMsgId =
        typeof crypto !== 'undefined' && 'randomUUID' in crypto
          ? crypto.randomUUID()
          : `opt-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      setTimeline((prev) =>
        prev.some((m) => m.id === clientMsgId)
          ? prev
          : [...prev, { id: clientMsgId, role: 'operator', content, timestamp: new Date().toISOString() }],
      );
      const ack = await emitAck('send_message', { threadId, tenantId: TENANT_ID, content, clientMsgId });
      // 发完即对齐时间线;ack 失败(含超时)同样回真源 —— 没落库则乐观行消失
      // (回滚),落库而 ack 未达则如实显示,盲删会把已落库真消息一并抹掉。
      await openThread(threadId);
      return ack;
    },
    [emitAck, openThread],
  );

  // P4 台内批驳(spec §2.6):员工代行 approve/reject 走 /api/chat/approvals,
  // 服务端闸 live_desk:approve(403 如实透传);批驳后不自动释放,工单终局
  // 只刷新待批卡与列表。
  const reviewTicket = useCallback(
    async (approvalId: string, action: 'approve' | 'reject', rejectionReason?: string) => {
      try {
        const body = await api.liveDesk.resolveApproval({ approvalId, action, rejectionReason });
        if (body.success) {
          const tid = selectedThreadIdRef.current;
          if (tid) void loadPendingTicket(tid);
          void loadConversations();
          return { success: true };
        }
        return { success: false, error: body.detail || body.error || '批驳失败' };
      } catch (err) {
        return { success: false, error: err instanceof Error ? err.message : '批驳失败' };
      }
    },
    [loadPendingTicket, loadConversations],
  );
  const toggleDnd = useCallback(
    async (enabled: boolean) => {
      try {
        const body = await api.liveDesk.setDnd(enabled);
        if (body.success) setDnd(body.dnd);
      } catch {
        // HTTP 通道失败回落 socket 通道
        const ack = await emitAck('presence_dnd', { enabled });
        if (ack.success) setDnd(enabled);
      }
    },
    [emitAck],
  );

  // 内部备注增删(P3):就地对齐 notes 列表;增删都只动本线程面板
  const addNote = useCallback(async (threadId: string, content: string) => {
    try {
      const body = await api.liveDesk.noteCreate(threadId, content);
      if (body.success && body.note) {
        setContext((prev) =>
          prev && prev.thread.threadId === threadId
            ? { ...prev, notes: [body.note as DeskNoteItem, ...prev.notes] }
            : prev,
        );
        return { success: true };
      }
      return { success: false, error: '备注写入失败' };
    } catch (err) {
      return { success: false, error: err instanceof Error ? err.message : '备注写入失败' };
    }
  }, []);
  const removeNote = useCallback(async (threadId: string, noteId: string) => {
    try {
      const body = await api.liveDesk.noteDelete(threadId, noteId);
      if (body.success) {
        setContext((prev) =>
          prev && prev.thread.threadId === threadId
            ? { ...prev, notes: prev.notes.filter((n) => n.id !== noteId) }
            : prev,
        );
      }
      return { success: body.success };
    } catch (err) {
      return { success: false, error: err instanceof Error ? err.message : '备注删除失败' };
    }
  }, []);

  return {
    myEmail,
    conversations,
    agents,
    connected,
    dnd,
    now,
    selectedThreadId,
    timeline,
    context,
    pendingTicket,
    peerTyping,
    openThread,
    claim,
    release,
    sendMessage,
    emitTyping,
    reviewTicket,
    toggleDnd,
    addNote,
    removeNote,
  };
}
