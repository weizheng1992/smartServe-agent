// 坐席台数据面 hook(live-desk-rework P2):socket.io operator 连接即在线,
// 列表/时间线走员工形态 HTTP,认领/释放/发言走 socket ack(服务端裁决原子
// 守卫与 perm 闸,前端只呈递结果)。tenantId 与 api.ts 同取 dev 单租户
// 'aurora'(x-tenant-id 同值,见 .claude/rules/merchant-admin.md §1.1)。
import { type DeskAgentRow, type DeskConversationRow, api, authToken, currentStaffEmail } from '@/lib/api';
import type { MessageItem } from '@/lib/api';
import { useCallback, useEffect, useRef, useState } from 'react';
import { type Socket, io } from 'socket.io-client';

const TENANT_ID = 'aurora';
const LIST_REFRESH_MS = 30_000; // 兜底轮询(socket 事件即时增量,轮询防漏)
const PRESENCE_REFRESH_MS = 20_000;
const PRESENCE_PING_MS = 30_000;
const NOW_TICK_MS = 1_000; // 排队等待计时刷新
const ACK_TIMEOUT_MS = 8_000;

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
  const [now, setNow] = useState(() => Date.now());
  const socketRef = useRef<Socket | null>(null);

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

  const openThread = useCallback(async (threadId: string) => {
    setSelectedThreadId(threadId);
    setTimeline([]);
    // 入房:房间广播(new_message / conversation_state_changed)必须 join 才收
    socketRef.current?.emit('join_thread', { threadId, tenantId: TENANT_ID, role: 'operator' });
    try {
      const body = await api.liveDesk.timeline(threadId);
      if (body.success && body.data) setTimeline(body.data.messages || []);
    } catch (err) {
      console.error('[live-desk] 时间线加载失败', err);
    }
  }, []);

  // 选中线程的 ref(new_message 闭包读取最新值,不重连 socket)
  const selectedThreadIdRef = useRef<string | null>(null);
  useEffect(() => {
    selectedThreadIdRef.current = selectedThreadId;
  }, [selectedThreadId]);

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
    socket.on('connect', () => setConnected(true));
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
    return () => {
      socket.close();
      socketRef.current = null;
      setConnected(false);
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
  const sendMessage = useCallback(
    async (threadId: string, content: string) => {
      const ack = await emitAck('send_message', { threadId, tenantId: TENANT_ID, content });
      if (ack.success) await openThread(threadId); // 发完即对齐时间线(含自己一行)
      return ack;
    },
    [emitAck, openThread],
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

  return {
    myEmail,
    conversations,
    agents,
    connected,
    dnd,
    now,
    selectedThreadId,
    timeline,
    openThread,
    claim,
    release,
    sendMessage,
    toggleDnd,
  };
}
