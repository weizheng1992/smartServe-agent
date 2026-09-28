// 网关 API 客户端(0013 收口:身份 = Bearer JWT,后端不再信任 x-user-id 头)。
// 老板可经 /staff/switch 换签任意员工 token 体验各角色视角;原始老板凭证
// 单独保存在 BOSS_KEY,切换动作始终以老板身份发起(非老板无权签发)。
import { type SseFrame, createFrameParser, parseSseFrames } from '@/lib/sse';

const TOKEN_KEY = 'merchant-admin.token';
const STAFF_KEY = 'merchant-admin.staff';
const BOSS_KEY = 'merchant-admin.boss';

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

async function req(path: string, init?: RequestInit) {
  const res = await fetch(path, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers || {}) },
  });
  if (res.status === 401) {
    // 凭证失效/过期 → 清会话回登录页
    clearSession();
    location.href = '/';
    throw new Error('401 登录已过期');
  }
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res;
}

/** 注入 ui 包 useApprovalMachine 的鉴权 fetch(夜审 A4/A5):只附加身份头与
 *  401 收口,不吞非 2xx —— 业务错误由 hook 按 success/error 呈现。 */
export async function authedFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const res = await fetch(input, { ...init, headers: { ...authHeaders(), ...(init?.headers || {}) } });
  if (res.status === 401) {
    clearSession();
    location.href = '/';
    throw new Error('401 登录已过期');
  }
  return res;
}

/** 域数据请求:400 级业务错误也返回 body,由页面按 success/message 呈现文案。 */
async function fetchJson(path: string, init?: RequestInit) {
  const res = await fetch(path, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers || {}) },
  });
  if (res.status === 401) {
    clearSession();
    location.href = '/';
    throw new Error('401 登录已过期');
  }
  return res.json();
}

export interface Spu {
  id: string;
  spu_code: string;
  title: string;
  category: string;
  status: string;
  price: number;
  stock: number;
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

export interface MessageItem {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'operator';
  content: string;
  cards?: any[];
  operatorInfo?: { operatorId: string; operatorName: string };
  timestamp: string;
}

export interface MenuNode {
  id: string;
  name: string;
  menuType: 'directory' | 'menu' | 'button';
  route: string | null;
  permCode: string | null;
  children: MenuNode[];
}

export const api = {
  menus: async (): Promise<{ role: string; perms: string[]; menus: MenuNode[] }> =>
    (await req('/api/admin/analytics/menus')).json(),

  staffList: async (): Promise<{ staff: Array<{ id: string; email: string; displayName: string; role: string }> }> =>
    (await req('/api/admin/analytics/staff')).json(),

  /** 老板切换查看身份:服务端为目标员工签发 JWT;保存原始老板凭证供切回。 */
  staffSwitch: async (email: string): Promise<{ staffId: string; displayName: string; role: string }> => {
    const boss = JSON.parse(localStorage.getItem(BOSS_KEY) || 'null') as { token: string; email: string } | null;
    const switchAs = boss ?? { token: authToken(), email: currentStaffEmail() };
    if (!switchAs.token) throw new Error('缺少老板凭证,无法切换');
    const res = await fetch('/api/admin/analytics/staff/switch', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-tenant-id': 'aurora',
        Authorization: `Bearer ${switchAs.token}`,
      },
      body: JSON.stringify({ staffId: email }),
    });
    const body = await res.json();
    if (!res.ok || !body.success) throw new Error(body.message || body.detail || '切换失败');
    localStorage.setItem(BOSS_KEY, JSON.stringify(switchAs));
    setSession(body.token, body.staffId);
    return body;
  },

  roles: {
    list: async (): Promise<{ roles: Array<{ role: string; menuCount: number; staffCount: number }> }> =>
      fetchJson('/api/admin/analytics/roles'),
    menusOf: async (role: string): Promise<{ role: string; menuIds: string[] }> =>
      fetchJson(`/api/admin/analytics/roles/${role}/menus`),
    saveMenus: async (role: string, menuIds: string[]) =>
      fetchJson(`/api/admin/analytics/roles/${role}/menus`, { method: 'POST', body: JSON.stringify({ menuIds }) }),
    create: async (role: string, menuIds: string[]) =>
      fetchJson('/api/admin/analytics/roles', { method: 'POST', body: JSON.stringify({ role, menuIds }) }),
  },

  ask: async (
    question: string,
    pageContext?: object,
    /** 流式渲染回调:每凑齐一帧即触发(帧同时聚全量返回,兼容旧用法)。 */
    onFrame?: (f: SseFrame) => void,
  ): Promise<SseFrame[]> => {
    // SSE 经 fetch 流式读取;增量解析逐帧回调(ADR-0005 流式渲染)。
    // 断线重连(夜审 A6):首连留 X-Ask-Id;网络中断携 askId+lastEventId 重试,
    // 服务端只补剩余帧不重算(结果卡渲染按 id 去重,重放帧无害)。
    const frames: SseFrame[] = [];
    let askId = '';
    let lastEventId = 0;
    for (let attempt = 0; ; attempt++) {
      try {
        const res = await req('/api/admin/analytics/ask', {
          method: 'POST',
          body: JSON.stringify({
            question,
            pageContext,
            ...(askId ? { askId, lastEventId } : {}),
          }),
        });
        askId = res.headers.get('X-Ask-Id') || askId;
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
        if (attempt >= 2 || !askId) throw err;
      }
    }
  },

  /** 员工管理(邀请/改角色/停用;新员工以种子密码可登录)。 */
  staff: {
    list: async (): Promise<{
      success: boolean;
      staff: Array<{ id: string; email: string; displayName: string; role: string; status: string }>;
    }> => fetchJson('/api/admin/analytics/staff'),
    invite: async (p: { email: string; displayName: string; role: string }) =>
      fetchJson('/api/admin/analytics/staff', { method: 'POST', body: JSON.stringify(p) }),
    update: async (id: string, patch: Partial<{ role: string; status: string; displayName: string }>) =>
      fetchJson(`/api/admin/analytics/staff/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
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
    }) => fetchJson('/api/admin/analytics/menus', { method: 'POST', body: JSON.stringify(p) }),
    update: async (
      id: string,
      patch: Partial<{ name: string; route: string; permCode: string; sort: number; status: string }>,
    ) => fetchJson(`/api/admin/analytics/menus/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    remove: async (id: string) => fetchJson(`/api/admin/analytics/menus/${id}`, { method: 'DELETE' }),
  },

  /** 客户管理(商户库客户;会员级编辑/新增/删除/详情关联数据)。 */
  customers: {
    list: async (): Promise<{ success: boolean; customers: Customer[] }> => fetchJson('/api/admin/analytics/customers'),
    coupons: async (customerId: string): Promise<{ success: boolean; coupons: CustomerCoupon[] }> =>
      fetchJson(`/api/admin/analytics/customers/${customerId}/coupons`),
    create: async (p: { name: string; phone: string; memberLevel?: string }) =>
      fetchJson('/api/admin/analytics/customers', { method: 'POST', body: JSON.stringify(p) }),
    update: async (id: string, patch: { memberLevel: string }) =>
      fetchJson(`/api/admin/analytics/customers/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    remove: async (id: string) => fetchJson(`/api/admin/analytics/customers/${id}`, { method: 'DELETE' }),
  },

  reports: {
    list: async () => (await req('/api/admin/analytics/reports')).json(),
    create: async () => (await req('/api/admin/analytics/reports', { method: 'POST', body: '{}' })).json(),
    csv: async (id: string) => (await req(`/api/admin/analytics/reports/${id}/csv`)).json(),
    detail: async (
      id: string,
    ): Promise<{
      success: boolean;
      id: string;
      title: string;
      chart: string | null;
      rows: Record<string, Record<string, unknown>[]>;
    }> => (await req(`/api/admin/analytics/reports/${id}`)).json(),
    saveFromResult: async (p: {
      question: string;
      metric: string;
      unit: string;
      caliber: string;
      rows: Record<string, unknown>[];
      chart?: string;
    }) =>
      (
        await req('/api/admin/analytics/reports/from-result', {
          method: 'POST',
          body: JSON.stringify(p),
        })
      ).json(),
  },

  /** 商品目录(SPU/SKU;页面只做编排,数据操作收口在此)。 */
  products: {
    list: async (): Promise<{ success: boolean; spus: Spu[] }> => fetchJson('/api/admin/analytics/spus'),
    listAllSkus: async (): Promise<{ success: boolean; skus: SkuStockRow[] }> => fetchJson('/api/admin/analytics/skus'),
    create: async (p: { title: string; category: string; price: number; stock: number }) =>
      fetchJson('/api/admin/analytics/spus', { method: 'POST', body: JSON.stringify(p) }),
    update: async (id: string, patch: Partial<{ title: string; price: number; stock: number; status: string }>) =>
      fetchJson(`/api/admin/analytics/spus/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    remove: async (id: string) => fetchJson(`/api/admin/analytics/spus/${id}`, { method: 'DELETE' }),
    listSkus: async (spuId: string): Promise<{ success: boolean; skus: Sku[] }> =>
      fetchJson(`/api/admin/analytics/spus/${spuId}/skus`),
    createSku: async (spuId: string, sku: { skuTitle: string; price: string; stock: string }) =>
      fetchJson(`/api/admin/analytics/spus/${spuId}/skus`, { method: 'POST', body: JSON.stringify(sku) }),
    updateSku: async (skuId: string, patch: { price: number; stock: number }) =>
      fetchJson(`/api/admin/analytics/skus/${skuId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    removeSku: async (skuId: string) => fetchJson(`/api/admin/analytics/skus/${skuId}`, { method: 'DELETE' }),
  },

  /** 优惠活动(创建/编辑/启停/删除/核销)。 */
  promotions: {
    list: async (): Promise<{ success: boolean; promotions: Promotion[]; effect: PromoEffect }> =>
      fetchJson('/api/admin/analytics/promotions'),
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
    }) => fetchJson('/api/admin/analytics/promotions', { method: 'POST', body: JSON.stringify(p) }),
    /** 商家向指定客户发券(仅券型/在售/同人同活动一次,服务端护栏)。 */
    grant: async (id: string, customerId: string) =>
      fetchJson(`/api/admin/analytics/promotions/${id}/grant`, {
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
    ) => fetchJson(`/api/admin/analytics/promotions/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    setStatus: async (id: string, status: string) =>
      fetchJson(`/api/admin/analytics/promotions/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) }),
    remove: async (id: string) => fetchJson(`/api/admin/analytics/promotions/${id}`, { method: 'DELETE' }),
    redeem: async (id: string, orderId: string) =>
      fetchJson(`/api/admin/analytics/promotions/${id}/redeem`, { method: 'POST', body: JSON.stringify({ orderId }) }),
  },

  /** 登录(唯一无会话接口;错误以 body 呈现,不走 401 清会话跳转)。 */
  login: async (
    email: string,
    password: string,
  ): Promise<{
    success: boolean;
    error?: string;
    message?: string;
    data?: { token: string; user: { email: string } };
  }> => {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    return res.json();
  },

  /** 订单(400 级错误经 fetchJson 返回 body 由调用方按 success 呈现)。 */
  orders: {
    detail: async (
      orderId: string,
    ): Promise<{ success: boolean; order?: OrderDetail; auditLogs?: OrderAuditLog[]; error?: string }> =>
      fetchJson(`/api/admin/orders/${encodeURIComponent(orderId)}`),
    /** 列表 + 审计流水(工作台轮询数据源;snake_case 裸行)。 */
    list: async (): Promise<{ success: boolean; orders: OrderRow[]; auditLogs: AuditLogRow[] }> =>
      fetchJson('/api/admin/orders'),
    /** 发货(服务端 RBAC order:ship 闸;真实世界副作用,失败以 message 呈现)。 */
    ship: async (p: { orderId: string; carrierCode: string; trackingNo: string }): Promise<{
      success: boolean;
      message?: string;
    }> => fetchJson('/api/admin/orders/ship', { method: 'POST', body: JSON.stringify(p) }),
  },

  /** 审批工单(裁决/人工回复经 useApprovalMachine 同端点)。 */
  approvals: {
    list: async (): Promise<{ success: boolean; approvals: ApprovalItem[]; total: number }> =>
      fetchJson('/api/admin/approvals?tenantId=aurora'),
    /** 人工接管开席:返回 approvalId 供人工回复直投。 */
    takeover: async (threadId: string): Promise<{ success: boolean; approvalId?: string; error?: string }> =>
      fetchJson('/api/admin/approvals', {
        method: 'POST',
        body: JSON.stringify({ threadId, action: 'start_human_takeover' }),
      }),
    /** 释放接管回 AI(P1 事故止血):写真源 threads → active,幂等。 */
    release: async (threadId: string): Promise<{ success: boolean; released?: boolean; error?: string }> =>
      fetchJson('/api/admin/approvals', {
        method: 'POST',
        body: JSON.stringify({ threadId, action: 'release_takeover' }),
      }),
  },

  /** 会话(客服工作台;tenantId 与 x-tenant-id 同值)。 */
  conversations: {
    list: async (): Promise<{ success: boolean; conversations: ConversationItem[] }> =>
      fetchJson('/api/admin/conversations?tenantId=aurora'),
    messages: async (threadId: string): Promise<{ success: boolean; data?: { messages: MessageItem[] } }> =>
      fetchJson(`/api/admin/conversations/${encodeURIComponent(threadId)}?tenantId=aurora`),
  },
};
