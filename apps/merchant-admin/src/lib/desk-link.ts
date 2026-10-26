// 坐席数据链路单点(2026-10-15 候选⑤):「operator 发言与认领,客户端只呈递、
// 真源在服务端 threads/messages」的共享不变量 —— 此前新旧两面各写一份且已漂移
// (fallback id 下划线 vs 连字符、同一三种情形的超时文案四种拼法、throw vs resolve)。
//
// 刻意不收口的两处:
// - socket 拨号生命周期:旧面(OrderWorkbench 回退面)模块单例懒拨 vs 新面
//   (useLiveDesk)useEffect 持有随卸载关闭 —— 两个合法所有权,只共享 option
//   块与 auth 构造;旧面缓存认证在首次拨号时定型(boss 切换不刷新)是其
//   已知取舍,不是本模块要统一的行为。
// - receive 拓扑:新面 join_thread 房间广播,旧面纯轮询 —— P4 消息/工单解耦
//   与 live-desk P5 搁置边界,合并即越界。
// resync 目标(admin 面与员工面是两个冻结端点,api.conversations.messages vs
// api.liveDesk.timeline)由 face 注入,本模块不硬编码。
import { type DeskConversationRow, type MessageItem, authToken, currentStaffEmail } from '@/lib/api';
import type { Socket } from 'socket.io-client';
import type { RichCardBlock } from 'types';

export type { Socket };

/** 服务端幂等键正则(realtime.py:34)—— clientMsgId 必须过此闸,否则被静默
 *  剥成空串换发服务端 uuid,幂等键整个丢失(2026-10-15 实弹:旧面下划线分隔)。 */
export const CLIENT_MSG_ID_RE = /^[0-9a-zA-Z-]{8,64}$/;

/** 幂等键唯一词表:randomUUID 优先,降级连字符 fallback(降级探测用
 *  typeof 函数检查 —— `in` 检查在键存在但不可调用时照样炸)。 */
export function newClientMsgId(): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `opt-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** 乐观行构造(坐席发言 role='operator' 无前缀,P1 裁决);cards 乐观同行
 *  (客服优化批:坐席推卡即时可见,ack 后 resync 对齐真源)。 */
export function buildOptimisticMessage(clientMsgId: string, content: string, cards?: RichCardBlock[]): MessageItem {
  return {
    id: clientMsgId,
    role: 'operator',
    content,
    ...(cards && cards.length > 0 ? { cards } : {}),
    timestamp: new Date().toISOString(),
  };
}

/** 去重追加:同 id 已在表则原数组返回(重入/房间回环不重复挂行)。 */
export function appendOptimistic(list: MessageItem[], msg: MessageItem): MessageItem[] {
  return list.some((m) => m.id === msg.id) ? list : [...list, msg];
}

export type DeskAckResult<T> =
  | { ok: true; ack: T }
  | { ok: false; kind: 'disconnected' | 'timeout' | 'empty' | 'ack-error'; error: string };

/** 统一 ack 文案(此前同一三种情形在两面有四种拼法)。 */
export const DESK_ACK_ERRORS = {
  disconnected: '未连接实时通道,请稍候重试',
  timeout: '响应超时,请重试',
  empty: '空响应',
} as const;

/** 守卫式 ack seam:未连接/超时/空响应/失败 ack 一律 resolve(严禁 throw),
 *  调用方按 result.ok 分派;需要 throw 语义的面自己包一层(旧面 catch 即 resync)。 */
export function emitDeskAck<T = Record<string, unknown>>(
  socket: Socket | null,
  event: string,
  payload: Record<string, unknown>,
  timeoutMs = 8_000,
): Promise<DeskAckResult<T>> {
  return new Promise((resolve) => {
    if (!socket || !socket.connected) {
      resolve({ ok: false, kind: 'disconnected', error: DESK_ACK_ERRORS.disconnected });
      return;
    }
    const timer = setTimeout(() => resolve({ ok: false, kind: 'timeout', error: DESK_ACK_ERRORS.timeout }), timeoutMs);
    socket.emit(event, payload, (ack: T | undefined) => {
      clearTimeout(timer);
      if (ack) resolve({ ok: true, ack });
      else resolve({ ok: false, kind: 'empty', error: DESK_ACK_ERRORS.empty });
    });
  });
}

/** 发言组合:幂等键 → 守卫 emit → resync(两面都在 emit 后无条件对齐真源 ——
 *  没落库则乐观行消失,落库而 ack 未达则如实显示,盲删会抹掉已落库真消息;
 *  故 resync 恒调,不由 ok 分支)。socket 提供方由 face 注入(旧面 deskSocket
 *  单例可 reject,新面 socketRef 直取)。cards(客服优化批):非空才携带,
 *  服务端 _cards_gate 闭集闸拒非法形状(ack 诚实回败,resync 后乐观行消失)。 */
export async function sendOperatorMessage<T = { messageId?: string }>(
  deps: {
    socket: () => Promise<Socket | null>;
    threadId: string;
    tenantId: string;
    content: string;
    cards?: RichCardBlock[];
  },
  resync: () => Promise<void> | void,
  clientMsgId = newClientMsgId(),
): Promise<{ clientMsgId: string; result: DeskAckResult<T> }> {
  const socket = await deps.socket();
  const result = await emitDeskAck<T>(socket, 'send_message', {
    threadId: deps.threadId,
    tenantId: deps.tenantId,
    role: 'operator',
    content: deps.content,
    ...(deps.cards && deps.cards.length > 0 ? { cards: deps.cards } : {}),
    clientMsgId,
  });
  await resync();
  return { clientMsgId, result };
}

/** 行就地修补(新面认领/释放/广播三处同构 map-replace 单点)。 */
export function applyConversationPatch(
  rows: DeskConversationRow[],
  threadId: string,
  patch: Partial<DeskConversationRow>,
): DeskConversationRow[] {
  return rows.map((c) => (c.threadId === threadId ? { ...c, ...patch } : c));
}

/** 拨号共享面:namespace/传输/重连全站一致;认证字段两面同形(userId/email、
 *  role、token 读自 localStorage),由各面在自己的生命周期里拨号时构造。 */
export const OPERATOR_DESK_NS = '/ws/chat';
export const OPERATOR_DESK_CONNECT: { path: string; transports: string[]; reconnection: boolean } = {
  path: '/socket.io',
  transports: ['websocket'],
  reconnection: true,
};
export function operatorDeskAuth(tenantId: string) {
  return { tenantId, userId: currentStaffEmail(), role: 'operator' as const, token: authToken() };
}
