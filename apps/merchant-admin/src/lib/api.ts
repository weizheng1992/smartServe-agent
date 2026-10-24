// 网关 API 客户端(0013 收口:身份 = Bearer JWT,后端不再信任 x-user-id 头)。
// 老板可经 /staff/switch 换签任意员工 token 体验各角色视角;原始老板凭证
// 单独保存在 BOSS_KEY,切换动作始终以老板身份发起(非老板无权签发)。
import { type SseFrame, createFrameParser, parseSseFrames } from '@/lib/sse';

const TOKEN_KEY = 'merchant-admin.token';
const STAFF_KEY = 'merchant-admin.staff';
const BOSS_KEY = 'merchant-admin.boss';

/** ask 流最终失败(3 次续传仍断)且已拿到 askId:携带恢复句柄 —— 流还在
 * Redis(600s TTL)、生产者仍在后台跑,拿 askId+lastEventId 重新进 ask 的
 * resume 参数即可续播剩余帧,不重算;frames = 断线前已收到的帧(恢复成功
 * 时与服务端重放帧恰好互补,无重叠)。 */
export class AskStreamError extends Error {
  askId: string;
  lastEventId: number;
  frames: SseFrame[];
  constructor(message: string, askId: string, lastEventId: number, frames: SseFrame[]) {
    super(message);
    this.name = 'AskStreamError';
    this.askId = askId;
    this.lastEventId = lastEventId;
    this.frames = frames;
  }
}

export function authToken(): string {
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function currentStaffEmail(): string {
  return localStorage.getItem(STAFF_KEY) || '';
}

export function setSession(token: string, email: string) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(STAFF_KEY, email);
}

export function clearSession() {
  for (const k of [TOKEN_KEY, STAFF_KEY, BOSS_KEY]) localStorage.removeItem(k);
}

/** 是否持有老板凭证(顶栏身份切换器仅对老板可见)。 */
export function hasBossSession(): boolean {
  try {
    return !!JSON.parse(localStorage.getItem(BOSS_KEY) || 'null')?.token;
  } catch {
    return false;
  }
}

export function authHeaders(): Record<string, string> {
  const token = authToken();
  return {
    'Content-Type': 'application/json',
    'x-tenant-id': 'aurora',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

/** 401 统一出口:清会话回登录页(login 不走此 transport,自带防枚举语义)。 */
function bounce401() {
  clearSession();
  location.href = '/';
}

/** 域数据请求 —— 唯一 transport(2026-10-15 候选②归一;此前 req「非 2xx 即
 *  throw」与 fetchJson「400 级返 body」两套语义并存,规约 §1.1 本就规定后者):
 *  - 401:清会话回登录(唯一收口);
 *  - 业务错误(4xx/5xx 带 JSON body):body 原样返回,由页面按 success/message
 *    呈现文案 —— 严禁吞进 throw;
 *  - 传输失败(网络不可达 / 非 JSON 体,如 proxy ECONNREFUSED 回 HTML):
 *    throw 诚实报错,严禁裸 SyntaxError(login 同款实弹教训)。
 *  authedFetch(ui 审批机注入面,不吞非 2xx)、login(唯一无会话端点,10s 超时)、
 *  api.ask(SSE 流式,ADR-0013)各保留自有形状。 */
async function requestJson<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: { ...authHeaders(), ...(init?.headers || {}) } });
  if (res.status === 401) {
    bounce401();
    throw new Error('401 登录已过期');
  }
  const raw = await res.text();
  try {
    return JSON.parse(raw) as T;
  } catch {
    throw new Error(`${res.status} 非 JSON 响应:${raw.slice(0, 120) || '(空体)'}`);
  }
}

/** 服务端错误体文案单点出口(message/detail/error 三键并存,冻结面不抹平 body)。
 *  页面呈现失败文案一律走此,严禁再散写 `b.error || b.message` 式三读法。 */
export function errMsgOf(body: unknown, fallback = '操作失败'): string {
  const b = body as { message?: string; error?: string; detail?: string } | null;
  return String(b?.message || b?.error || b?.detail || fallback);
}

/** 注入 ui 包 useApprovalMachine 的鉴权 fetch(夜审 A4/A5):只附加身份头与
 *  401 收口,不吞非 2xx —— 业务错误由 hook 按 success/error 呈现。 */
export async function authedFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const res = await fetch(input, { ...init, headers: { ...authHeaders(), ...(init?.headers || {}) } });
  if (res.status === 401) {
    bounce401();
    throw new Error('401 登录已过期');
  }
  return res;
}

export interface Spu {
  id: string;
  spu_code: string;
  title: string;
  category: string;
  status: string;
  price: number;
  stock: number;
  /** 负责人 staff id(Q15 数据原生;null = 未分配,解析端诚实降级)。 */
  ownerId: string | null;
}

export interface Sku {
  id: string;
  sku_code: string;
  sku_title: string | null;
  price: number;
  stock: number;
  spec_attributes: string | null;
}

/** SKU 库存总表行(跨 SPU;SKU 库存独立页用) */
export interface SkuStockRow extends Sku {
  spu_id: string;
  spu_title: string;
}

export interface Promotion {
  id: string;
  name: string;
  promoType: string;
  threshold: number | null;
  value: number;
  scopeType: string;
  scopeValue: string | null;
  status: string;
  startAt: string | null;
  endAt: string | null;
  /** 发放上限(仅券型;null = 不限) */
  totalQuota: number | null;
  /** 已发放张数(claimed+used 都占额度) */
  claimedCount: number;
  usedCount: number;
  /** 核销单数 / 让利总额(活动维度效果,行内注记用) */
  redemptionCount: number;
  discountTotal: number;
  /** 服务端派生生效态:disabled > ended > scheduled > running(前端不自算) */
  effectiveStatus: 'disabled' | 'ended' | 'scheduled' | 'running';
}

export interface PromoEffect {
  activePromotions: number;
  redemptions: number;
  totalDiscount: number;
}

export interface Customer {
  customer_id: string;
  name: string;
  phone: string;
  email: string;
  member_level: string;
  /** JSON 文本(merchant_customers.addresses;商城收货地址簿) */
  addresses: string;
  total_spent: number;
  order_count: number;
}

export interface CustomerCoupon {
  id: string;
  name: string;
  value: number;
  status: string;
  claimedAt: string | null;
  usedOrderId: string | null;
}

export type { SseFrame };

/** 订单详情(网关 GET /api/admin/orders/{orderId};camelCase,与 storefront SPI 同形)。 */
export interface OrderDetailItem {
  skuId: string;
  productId: string;
  title: string;
  quantity: number;
  price: number | null;
  imageUrl: string | null;
  specSummary: string | null;
}

export interface OrderTracking {
  carrier?: string;
  trackingNumber?: string;
  timeline?: Array<{ time?: string; status?: string; description?: string; location?: string }>;
}

export interface OrderDetail {
  orderId: string;
  userId: string;
  status: string;
  totalAmount: number;
  discountAmount: number;
  originalAmount: number;
  currency: string;
  createdAt: string;
  shippingAddress: { recipientName?: string; phone?: string; fullAddress?: string } | null;
  tracking: OrderTracking | null;
  isAddressModifiable: boolean;
  isReturnable: boolean;
  items: OrderDetailItem[];
}

/** 订单审计时间线行(merchant_audit_logs 裸行;snake_case)。 */
export interface OrderAuditLog {
  id: number;
  action_type: string;
  order_id: string;
  idempotency_key: string;
  operator: string;
  payload: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  created_at: string;
}

/** 工作台订单行(merchant_orders 裸行;snake_case,列表/审计同源 GET /api/admin/orders)。 */
export interface OrderRow {
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

export interface AuditLogRow {
  id: string;
  action_type: string;
  order_id: string;
  idempotency_key: string;
  operator: string;
  payload: Record<string, unknown>;
  result: Record<string, unknown>;
  created_at: string;
}

export interface ApprovalItem {
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

export interface ConversationItem {
  id: string;
  /** 恒有两键(api.conversations.list adapter 互补修补;部分行只有 threadId) */
  threadId: string;
  businessId: string;
  userId?: string;
  status: string;
  assignedOperatorId?: string;
  lastMessage?: string;
  lastMessageSnippet?: string;
  updatedAt: string;
  createdAt: string;
}

export interface MessageItem {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'operator';
  content: string;
  cards?: any[];
  operatorInfo?: { operatorId: string; operatorName: string };
  timestamp: string;
}

/** GET /api/conversations 行(threads 真源 camelCase 透传;坐席台 P2 数据源)。 */
export interface DeskConversationRow {
  threadId: string;
  businessId: string;
  userId?: string | null;
  status: string;
  assignedOperatorId?: string | null;
  unreadCount?: number;
  tags?: string[];
  metadata?: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
  lastMessageSnippet?: string | null;
  lastMessageRole?: string | null;
  lastMessageTime?: string | null;
  messageCount?: number;
  totalTokens?: number;
  costUsd?: number;
  llmCalls?: number;
}

/** GET /api/merchant/live-desk/presence 行(员工行 ⨝ presence 汇总)。 */
export interface DeskAgentRow {
  email: string;
  name: string;
  role: string;
  online: boolean;
  dnd: boolean;
  lastSeenAt?: string | null;
}

/** GET /api/merchant/live-desk/threads/{id}/context 五项聚合(P3 坐席上下文栏)。 */
export interface LiveDeskContext {
  success: boolean;
  thread: {
    threadId: string;
    userId?: string | null;
    status?: string | null;
    assignedOperatorId?: string | null;
  };
  /** 弱关联诚实:聊天身份 ↔ 商户 customer_id 无桥时 matched:false,前端照实呈现。 */
  customer: {
    matched: boolean;
    customerId?: string;
    name?: string;
    phoneMasked?: string | null;
    email?: string;
    memberLevel?: string;
    tags?: string[];
    totalSpent?: number;
    orderCount?: number;
  };
  recentOrders: Array<{ orderId: string; status: string; totalAmount: number; createdAt: string | null }>;
  afterSaleTickets: Array<{
    id: string;
    orderId: string;
    type: string;
    reason: string;
    status: string;
    refundAmount: number;
    createdAt: string | null;
  }>;
  profile: { global: string[]; tenant: string[] };
  notes: DeskNoteItem[];
}

/** 坐席内部备注(thread_notes;仅 agent_merchant 库,顾客链路物理触不到)。 */
export interface DeskNoteItem {
  id: string;
  content: string;
  authorEmail: string;
  createdAt: string | null;
}

export interface MenuNode {
  id: string;
  name: string;
  menuType: 'directory' | 'menu' | 'button';
  route: string | null;
  permCode: string | null;
  children: MenuNode[];
}

/** 商户积分池台账行(GET /api/admin/credits;2026-10-21 用量配额闸)。 */
export interface CreditTransaction {
  id: string;
  /** 正 = 充值/赠送/退回,负 = 消耗/核减 */
  delta: number;
  /** 机读枚举(admin_adjust 携「前缀: 详情」复合形态);呈现层经 creditReasonMeta 转人话 */
  reason: string;
  refJobId: string | null;
  operator: string | null;
  createdAt: string | null;
}

/** 服务额度明细(本商户只读;充值/核减走平台面,商户侧 v1 无写路径)。 */
export interface CreditsDetail {
  businessId: string;
  /** null = 积分账户未初始化(未开通),诚实呈现,严禁前端编 0 */
  balance: number | null;
  transactions: CreditTransaction[];
}

/** AI 用量自然月汇总(docs/ai-usage-panel.md P0;turn_path 闭集见引擎
 *  turn_path_for_route —— unknown = 降级/中断轮路径未决,诚实呈现不编造)。 */
export interface AiUsageSummary {
  businessId: string;
  quota: { monthlyLimitTokens: number | null; usedTokens: number; usageRate: number | null };
  turns: { total: number; avgLatencyMs: number; zeroLlmRate: number; fastPathRate: number };
  byDay: Array<{ day: string; tokens: number; turns: number }>;
  byPath: Array<{ path: string; turns: number; tokens: number }>;
  calls: { total: number; totalTokens: number; avgLatencyMs: number };
  /** 多轮任务健康度(docs/multi-turn-task-state.md P1-2):全部派生自既有遥测;
   *  clarifyFollowupAccuracy null = 本月无澄清后继轮(诚实缺省,严禁编 0) */
  taskHealth: {
    totalTurns: number;
    resolvedTurns: number;
    completionRate: number;
    clarifyTurns: number;
    clarifyFollowupAccuracy: number | null;
    clarifyFollowupCompleted: number;
    clarifyFollowupReclarified: number;
    toolErrorTurnRate: number;
    duplicateBypassRate: number;
    avgTokensPerTurn: number;
  };
  notes: string[];
}

export interface AiUsageTurn {
  /** 问候旁路补行前的历史轮无 job 关联,诚实 null(不可下钻) */
  jobId: string | null;
  threadId: string;
  turnPath: string | null;
  totalTokens: number;
  latencyMs: number;
  resolutionStatus: string;
  createdAt: string | null;
}

export interface AiUsageCall {
  node: string;
  model: string;
  tokensIn: number;
  tokensOut: number;
  totalTokens: number;
  latencyMs: number;
  createdAt: string | null;
}

export const api = {
  menus: async (): Promise<{ role: string; perms: string[]; menus: MenuNode[] }> =>
    requestJson('/api/admin/analytics/menus'),

  staffList: async (): Promise<{
    staff: Array<{
      id: string;
      email: string;
      displayName: string;
      role: string;
      dept: string | null;
      level: string | null;
    }>;
  }> => requestJson('/api/admin/analytics/staff'),

  /** 老板切换查看身份:服务端为目标员工签发 JWT;保存原始老板凭证供切回。
   *  Authorization 覆写默认头 —— 切换动作始终以留底老板凭证发起。
   *  业务错误(非老板 403 等)按 transport 语义返 body,由调用方 errMsgOf 呈现。 */
  staffSwitch: async (
    email: string,
  ): Promise<{
    success: boolean;
    token?: string;
    staffId?: string;
    displayName?: string;
    role?: string;
    message?: string;
    error?: string;
  }> => {
    const boss = JSON.parse(localStorage.getItem(BOSS_KEY) || 'null') as { token: string; email: string } | null;
    const switchAs = boss ?? { token: authToken(), email: currentStaffEmail() };
    if (!switchAs.token) throw new Error('缺少老板凭证,无法切换');
    const body = await requestJson<{
      success: boolean;
      token?: string;
      staffId?: string;
      role?: string;
      message?: string;
      error?: string;
    }>('/api/admin/analytics/staff/switch', {
      method: 'POST',
      headers: { Authorization: `Bearer ${switchAs.token}` },
      body: JSON.stringify({ staffId: email }),
    });
    if (body.success && body.token && body.staffId) {
      localStorage.setItem(BOSS_KEY, JSON.stringify(switchAs));
      setSession(body.token, body.staffId);
    }
    return body;
  },

  roles: {
    list: async (): Promise<{ roles: Array<{ role: string; menuCount: number; staffCount: number }> }> =>
      requestJson('/api/admin/analytics/roles'),
    menusOf: async (role: string): Promise<{ role: string; menuIds: string[] }> =>
      requestJson(`/api/admin/analytics/roles/${role}/menus`),
    saveMenus: async (role: string, menuIds: string[]) =>
      requestJson(`/api/admin/analytics/roles/${role}/menus`, { method: 'POST', body: JSON.stringify({ menuIds }) }),
    create: async (role: string, menuIds: string[]) =>
      requestJson('/api/admin/analytics/roles', { method: 'POST', body: JSON.stringify({ role, menuIds }) }),
  },

  ask: async (
    question: string,
    pageContext?: object,
    /** 流式渲染回调:每凑齐一帧即触发(帧同时聚全量返回,兼容旧用法)。 */
    onFrame?: (f: SseFrame) => void,
    /** 断线恢复入口(AskStreamError 携带句柄,错误帧「恢复结果」按钮走此路):
     * 首连即带 askId+lastEventId,服务端只补剩余帧不重算。 */
    resume?: { askId: string; lastEventId: number },
  ): Promise<SseFrame[]> => {
    // SSE 经 fetch 流式读取;增量解析逐帧回调(ADR-0005 流式渲染)。
    // 断线续传(夜审 A6):首连留 X-Ask-Id;网络中断携 askId+lastEventId 重试,
    // 服务端只补 seq>last 的帧不重算 —— 去重由服务端水位保证,客户端无需按
    // id 去重(重放帧本就不会与已收帧重叠)。最终失败抛 AskStreamError(带
    // 恢复句柄与已收帧):流还在 Redis(600s)、生产者仍在后台跑,恢复不重算。
    const frames: SseFrame[] = [];
    let askId = resume?.askId || '';
    let lastEventId = resume?.lastEventId || 0;
    for (let attempt = 0; ; attempt++) {
      try {
        // authedFetch 而非 requestJson:SSE 要的是原始 Response 流式读取,严禁经
        // requestJson 的 res.text() 消费 body;身份头与 401 收口照旧。
        // ok 闸(2026-10-15 终审 M1):authedFetch 只收 401,其余非 2xx 若不在此
        // 判 ok 会把错误应答当「零帧成功流」静默吞掉(旧 req 的 !res.ok throw 语义)
        const res = await authedFetch('/api/admin/analytics/ask', {
          method: 'POST',
          body: JSON.stringify({
            question,
            pageContext,
            ...(askId ? { askId, lastEventId } : {}),
          }),
        });
        askId = res.headers.get('X-Ask-Id') || askId;
        if (!res.ok) {
          // 非 2xx:应答体不是帧流,按传输失败 throw(进 ask 的重试/AskStreamError 通路)
          throw new Error(`${res.status} ${await res.text().then((t) => t.slice(0, 120))}`);
        }
        const parser = createFrameParser((f) => {
          frames.push(f);
          if (typeof f.id === 'number' && f.id > lastEventId) lastEventId = f.id;
          onFrame?.(f);
        });
        const reader = res.body?.getReader();
        if (reader) {
          const decoder = new TextDecoder();
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            parser(decoder.decode(value, { stream: true }));
          }
          parser(decoder.decode());
        } else {
          parser(await res.text());
        }
        return frames;
      } catch (err) {
        if (attempt >= 2 || !askId) {
          throw askId ? new AskStreamError(String(err), askId, lastEventId, frames) : err;
        }
      }
    }
  },

  /** 答案反馈(反馈闭环 v3.1):traceId 来自终局帧,👎 可带自由文本备注。 */
  feedback: {
    submit: async (p: { traceId: string; verdict: 'up' | 'down'; note?: string }) =>
      requestJson('/api/admin/analytics/feedback', {
        method: 'POST',
        body: JSON.stringify(p),
      }),
  },

  /** 服务额度(积分池):本商户只读(余额 + 最近流水;充值/核减由平台管理员
   *  在 admin 面操作,商户侧 v1 无写路径)。balance null = 未开通,严禁编 0。 */
  credits: {
    get: async (): Promise<{ success: boolean; data?: CreditsDetail; error?: string }> =>
      requestJson('/api/admin/credits'),
  },

  /** AI 用量(docs/ai-usage-panel.md P0):轮 = session_metrics 行,下钻 =
   *  llm_call_logs 按 jobId。商户口径无美元 —— 成本是平台内部数据,配额对照
   *  走 token;自然月窗口由服务端 date_trunc 单点计算。 */
  aiUsage: {
    summary: async (): Promise<{ success: boolean; data?: AiUsageSummary; message?: string; error?: string }> =>
      requestJson('/api/admin/ai-usage/summary'),
    turns: async (
      threadId?: string,
    ): Promise<{ success: boolean; data?: { turns: AiUsageTurn[] }; message?: string; error?: string }> =>
      requestJson(`/api/admin/ai-usage/turns${threadId ? `?threadId=${encodeURIComponent(threadId)}` : ''}`),
    calls: async (
      jobId: string,
    ): Promise<{
      success: boolean;
      data?: { jobId: string; threadId: string | null; turnPath: string | null; calls: AiUsageCall[] };
      message?: string;
      error?: string;
    }> => requestJson(`/api/admin/ai-usage/calls?jobId=${encodeURIComponent(jobId)}`),
  },

  /** 员工管理(邀请/改角色/停用;新员工以种子密码可登录;dept/level 为责任人路由人事属性)。 */
  staff: {
    list: async (): Promise<{
      success: boolean;
      staff: Array<{
        id: string;
        email: string;
        displayName: string;
        role: string;
        status: string;
        dept: string | null;
        level: string | null;
      }>;
    }> => requestJson('/api/admin/analytics/staff'),
    invite: async (p: { email: string; displayName: string; role: string; dept?: string; level?: string }) =>
      requestJson('/api/admin/analytics/staff', { method: 'POST', body: JSON.stringify(p) }),
    update: async (
      id: string,
      patch: Partial<{ role: string; status: string; displayName: string; dept: string; level: string }>,
    ) => requestJson(`/api/admin/analytics/staff/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  },

  /** 「该找谁」责任人映射(品类/指标 → 员工;PUT/DELETE 仅老板/管理员,闸在服务端)。 */
  ownerMappings: {
    list: async (): Promise<{
      success: boolean;
      mappings: Array<{
        mapType: string;
        mapValue: string;
        staffId: string;
        ownerType: string;
        updatedAt: string;
        displayName: string | null;
        dept: string | null;
        level: string | null;
        enabled: boolean;
      }>;
      categories: string[];
      metrics: Array<{ key: string; label: string }>;
    }> => requestJson('/api/admin/analytics/owner-mappings'),
    upsert: async (p: { mapType: string; mapValue: string; staffId: string }) =>
      requestJson('/api/admin/analytics/owner-mappings', { method: 'PUT', body: JSON.stringify(p) }),
    remove: async (mapType: string, mapValue: string) =>
      requestJson(
        `/api/admin/analytics/owner-mappings?mapType=${encodeURIComponent(mapType)}&mapValue=${encodeURIComponent(mapValue)}`,
        {
          method: 'DELETE',
        },
      ),
  },

  /** 菜单管理 CRUD(目录/菜单/按钮 + 权限点;系统菜单护栏在服务端)。 */
  menuAdmin: {
    create: async (p: {
      name: string;
      menuType: string;
      route?: string;
      permCode?: string;
      parentId?: string | null;
      sort?: number;
    }) => requestJson('/api/admin/analytics/menus', { method: 'POST', body: JSON.stringify(p) }),
    update: async (
      id: string,
      patch: Partial<{ name: string; route: string; permCode: string; sort: number; status: string }>,
    ) => requestJson(`/api/admin/analytics/menus/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    remove: async (id: string) => requestJson(`/api/admin/analytics/menus/${id}`, { method: 'DELETE' }),
  },

  /** 客户管理(商户库客户;会员级编辑/新增/删除/详情关联数据)。 */
  customers: {
    list: async (): Promise<{ success: boolean; customers: Customer[] }> =>
      requestJson('/api/admin/analytics/customers'),
    coupons: async (customerId: string): Promise<{ success: boolean; coupons: CustomerCoupon[] }> =>
      requestJson(`/api/admin/analytics/customers/${customerId}/coupons`),
    create: async (p: { name: string; phone: string; memberLevel?: string }) =>
      requestJson('/api/admin/analytics/customers', { method: 'POST', body: JSON.stringify(p) }),
    update: async (id: string, patch: { memberLevel: string }) =>
      requestJson(`/api/admin/analytics/customers/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    remove: async (id: string) => requestJson(`/api/admin/analytics/customers/${id}`, { method: 'DELETE' }),
  },

  reports: {
    list: async (): Promise<{
      success: boolean;
      reports: Array<{ id: string; title: string; timeWindow: string; createdAt: string | null }>;
    }> => requestJson('/api/admin/analytics/reports'),
    create: async (): Promise<{ success: boolean; title?: string; message?: string; error?: string }> =>
      requestJson('/api/admin/analytics/reports', { method: 'POST', body: '{}' }),
    csv: async (id: string): Promise<{ csv?: string; filename?: string; message?: string; error?: string }> =>
      requestJson(`/api/admin/analytics/reports/${id}/csv`),
    detail: async (
      id: string,
    ): Promise<{
      success: boolean;
      id: string;
      title: string;
      chart: string | null;
      rows: Record<string, Record<string, unknown>[]>;
    }> => requestJson(`/api/admin/analytics/reports/${id}`),
    saveFromResult: async (p: {
      question: string;
      metric: string;
      unit: string;
      caliber: string;
      rows: Record<string, unknown>[];
      chart?: string;
    }) =>
      requestJson<{ success: boolean; message?: string; error?: string }>('/api/admin/analytics/reports/from-result', {
        method: 'POST',
        body: JSON.stringify(p),
      }),
  },

  /** 商品目录(SPU/SKU;页面只做编排,数据操作收口在此)。 */
  products: {
    list: async (): Promise<{ success: boolean; spus: Spu[] }> => requestJson('/api/admin/analytics/spus'),
    listAllSkus: async (): Promise<{ success: boolean; skus: SkuStockRow[] }> =>
      requestJson('/api/admin/analytics/skus'),
    create: async (p: { title: string; category: string; price: number; stock: number; ownerId?: string }) =>
      requestJson('/api/admin/analytics/spus', { method: 'POST', body: JSON.stringify(p) }),
    update: async (
      id: string,
      patch: Partial<{ title: string; price: number; stock: number; status: string; ownerId: string }>,
    ) => requestJson(`/api/admin/analytics/spus/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    remove: async (id: string) => requestJson(`/api/admin/analytics/spus/${id}`, { method: 'DELETE' }),
    listSkus: async (spuId: string): Promise<{ success: boolean; skus: Sku[] }> =>
      requestJson(`/api/admin/analytics/spus/${spuId}/skus`),
    createSku: async (spuId: string, sku: { skuTitle: string; price: string; stock: string }) =>
      requestJson(`/api/admin/analytics/spus/${spuId}/skus`, { method: 'POST', body: JSON.stringify(sku) }),
    updateSku: async (skuId: string, patch: { price: number; stock: number }) =>
      requestJson(`/api/admin/analytics/skus/${skuId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    removeSku: async (skuId: string) => requestJson(`/api/admin/analytics/skus/${skuId}`, { method: 'DELETE' }),
  },

  /** 优惠活动(创建/编辑/启停/删除/核销)。 */
  promotions: {
    list: async (): Promise<{ success: boolean; promotions: Promotion[]; effect: PromoEffect }> =>
      requestJson('/api/admin/analytics/promotions'),
    create: async (p: {
      name: string;
      promoType: string;
      threshold?: number;
      value: number;
      scopeType?: string;
      scopeValue?: string;
      /** ISO / datetime-local;起缺省服务端 NOW,止空 = 长期 */
      startAt?: string;
      endAt?: string;
      /** 发放上限,仅券型消费;非券型服务端忽略 */
      totalQuota?: number;
    }) => requestJson('/api/admin/analytics/promotions', { method: 'POST', body: JSON.stringify(p) }),
    /** 商家向指定客户发券(仅券型/在售/同人同活动一次,服务端护栏)。 */
    grant: async (id: string, customerId: string) =>
      requestJson(`/api/admin/analytics/promotions/${id}/grant`, {
        method: 'POST',
        body: JSON.stringify({ customerId }),
      }),
    /** 编辑(PATCH):携带的 key 才参与更新(服务端区分「未传」与「传 null」)。
     * endAt: null = 置长期;totalQuota: null = 清除上限;startAt 传空保持原值。 */
    update: async (
      id: string,
      patch: Partial<{
        name: string;
        value: number;
        threshold: number | null;
        scopeType: string;
        scopeValue: string | null;
        startAt: string;
        endAt: string | null;
        totalQuota: number | null;
      }>,
    ) => requestJson(`/api/admin/analytics/promotions/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    setStatus: async (id: string, status: string) =>
      requestJson(`/api/admin/analytics/promotions/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) }),
    remove: async (id: string) => requestJson(`/api/admin/analytics/promotions/${id}`, { method: 'DELETE' }),
    redeem: async (id: string, orderId: string) =>
      requestJson(`/api/admin/analytics/promotions/${id}/redeem`, {
        method: 'POST',
        body: JSON.stringify({ orderId }),
      }),
  },

  /** 登录(唯一无会话接口;错误以 body 呈现,不走 401 清会话跳转)。
   *  网关不可达/挂起曾以两种劣形漏给用户:proxy 500 非 JSON 体 → 裸
   *  SyntaxError 文案;挂起 → 永久「登录中…」无超时(2026-10-10 实弹)。
   *  10s 超时 + 非 2xx 诚实报错,失败类一目了然。 */
  login: async (
    email: string,
    password: string,
  ): Promise<{
    success: boolean;
    error?: string;
    message?: string;
    data?: { token: string; user: { email: string } };
  }> => {
    let res: Response;
    try {
      res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        signal: AbortSignal.timeout(10_000),
      });
    } catch (err) {
      const name = err instanceof Error ? err.name : '';
      throw new Error(
        name === 'TimeoutError' || name === 'AbortError'
          ? '登录服务无响应(10s 超时),请确认网关(4000)是否存活'
          : '登录服务不可达,请确认网关(4000)是否已启动',
      );
    }
    // 5xx = 服务/proxy 异常诚实报错;401 等仍返回 body(凭证错误由页面呈现,
    // 与后端防枚举统一文案契约对齐)
    if (res.status >= 500) throw new Error(`登录服务异常(HTTP ${res.status}),请稍后重试`);
    return res.json();
  },

  /** 订单(400 级错误经 fetchJson 返回 body 由调用方按 success 呈现)。 */
  orders: {
    detail: async (
      orderId: string,
    ): Promise<{ success: boolean; order?: OrderDetail; auditLogs?: OrderAuditLog[]; error?: string }> =>
      requestJson(`/api/admin/orders/${encodeURIComponent(orderId)}`),
    /** 列表 + 审计流水(工作台轮询数据源;snake_case 裸行)。 */
    list: async (): Promise<{ success: boolean; orders: OrderRow[]; auditLogs: AuditLogRow[] }> =>
      requestJson('/api/admin/orders'),
    /** 发货(服务端 RBAC order:ship 闸;真实世界副作用,失败以 message 呈现)。 */
    ship: async (p: { orderId: string; carrierCode: string; trackingNo: string }): Promise<{
      success: boolean;
      message?: string;
    }> => requestJson('/api/admin/orders/ship', { method: 'POST', body: JSON.stringify(p) }),
  },

  /** 审批工单(裁决/人工回复经 useApprovalMachine 同端点)。 */
  approvals: {
    list: async (): Promise<{ success: boolean; approvals: ApprovalItem[]; total: number }> =>
      requestJson('/api/admin/approvals?tenantId=aurora'),
    /** 人工接管开席:返回 approvalId 供人工回复直投。 */
    takeover: async (threadId: string): Promise<{ success: boolean; approvalId?: string; error?: string }> =>
      requestJson('/api/admin/approvals', {
        method: 'POST',
        body: JSON.stringify({ threadId, action: 'start_human_takeover' }),
      }),
    /** 释放接管回 AI(P1 事故止血):写真源 threads → active,幂等。 */
    release: async (threadId: string): Promise<{ success: boolean; released?: boolean; error?: string }> =>
      requestJson('/api/admin/approvals', {
        method: 'POST',
        body: JSON.stringify({ threadId, action: 'release_takeover' }),
      }),
  },

  /** 会话(客服工作台;tenantId 与 x-tenant-id 同值)。 */
  conversations: {
    /** 行形状修补在此收口(2026-10-15 候选②,此前 workbench 页内 reconcile):
     *  id/threadId 互补恒有两键、lastMessage 回退 snippet —— 调用方拿成品行。 */
    list: async (): Promise<{ success: boolean; conversations: ConversationItem[] }> => {
      const json = await requestJson<{ success: boolean; conversations?: Array<Record<string, unknown>> }>(
        '/api/admin/conversations?tenantId=aurora',
      );
      return {
        ...json,
        conversations: (json.conversations || []).map((item) => ({
          ...item,
          id: String(item.id || item.threadId || ''),
          threadId: String(item.threadId || item.id || ''),
          lastMessage: (item.lastMessage || item.lastMessageSnippet) as string | undefined,
        })) as ConversationItem[],
      };
    },
    messages: async (threadId: string): Promise<{ success: boolean; data?: { messages: MessageItem[] } }> =>
      requestJson(`/api/admin/conversations/${encodeURIComponent(threadId)}?tenantId=aurora`),
  },

  /** 坐席台(live-desk-rework P2;员工 JWT,持 live_desk:operate 打开时间线顺带清未读)。 */
  liveDesk: {
    /** 全租户会话列表(threads 真源;status=search= 分页可选)。 */
    conversations: async (params?: { status?: string; search?: string; limit?: number; offset?: number }) => {
      const qs = new URLSearchParams();
      if (params?.status && params.status !== 'all') qs.set('status', params.status);
      if (params?.search) qs.set('search', params.search);
      qs.set('limit', String(params?.limit ?? 100));
      const suffix = qs.toString() ? `?${qs.toString()}` : '';
      return requestJson(`/api/conversations${suffix}`) as Promise<{
        success: boolean;
        tenantId: string;
        conversations: DeskConversationRow[];
        total: number;
      }>;
    },
    timeline: async (threadId: string): Promise<{ success: boolean; data?: { messages: MessageItem[] } }> =>
      requestJson(`/api/conversations/${encodeURIComponent(threadId)}`),
    /** 坐席在线态(员工行 ⨝ presence;Redis 不可用如实空态)。 */
    presence: async (): Promise<{ success: boolean; tenantId: string; agents: DeskAgentRow[] }> =>
      requestJson('/api/merchant/live-desk/presence'),
    setDnd: async (enabled: boolean): Promise<{ success: boolean; dnd: boolean }> =>
      requestJson('/api/merchant/live-desk/presence/dnd', { method: 'POST', body: JSON.stringify({ enabled }) }),
    /** 坐席上下文五项一次聚合(单次往返);弱关联未匹配由前端诚实呈现。 */
    context: async (threadId: string): Promise<LiveDeskContext> =>
      requestJson(`/api/merchant/live-desk/threads/${encodeURIComponent(threadId)}/context`),
    /** 待批工单(P4 台内批驳;员工 JWT 本租户收窄,threadId 由前端就地过滤)。 */
    pendingApprovals: async (): Promise<{ success: boolean; approvals: ApprovalItem[] }> =>
      requestJson('/api/chat/approvals?status=waiting'),
    /** 批/驳(P4 spec §2.6):员工代行走 /api/chat/approvals,服务端闸
     *  live_desk:approve;400 级业务错误(403 无权限/已处理过)照 fetchJson
     *  语义返回 body,由调用方按 error/detail 呈现。 */
    resolveApproval: async (body: {
      approvalId: string;
      action: 'approve' | 'reject';
      rejectionReason?: string;
    }): Promise<{ success?: boolean; status?: string; error?: string; detail?: string }> =>
      requestJson('/api/chat/approvals', { method: 'POST', body: JSON.stringify(body) }),
    noteCreate: async (threadId: string, content: string): Promise<{ success: boolean; note?: DeskNoteItem }> =>
      requestJson(`/api/merchant/live-desk/threads/${encodeURIComponent(threadId)}/notes`, {
        method: 'POST',
        body: JSON.stringify({ content }),
      }),
    /** 幂等删除:重复删/非法 id 服务端都 success,前端直接对齐本地态。 */
    noteDelete: async (threadId: string, noteId: string): Promise<{ success: boolean }> =>
      requestJson(
        `/api/merchant/live-desk/threads/${encodeURIComponent(threadId)}/notes/${encodeURIComponent(noteId)}`,
        {
          method: 'DELETE',
        },
      ),
  },
};
