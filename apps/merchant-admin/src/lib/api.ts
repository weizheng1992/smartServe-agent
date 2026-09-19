// 网关 API 客户端(0013 收口:身份 = Bearer JWT,后端不再信任 x-user-id 头)。
// 老板可经 /staff/switch 换签任意员工 token 体验各角色视角;原始老板凭证
// 单独保存在 BOSS_KEY,切换动作始终以老板身份发起(非老板无权签发)。
import { parseSseFrames, type SseFrame } from '@/lib/sse';

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
    return !!(JSON.parse(localStorage.getItem(BOSS_KEY) || 'null')?.token);
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
      headers: { 'Content-Type': 'application/json', 'x-tenant-id': 'aurora', Authorization: `Bearer ${switchAs.token}` },
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

  ask: async (question: string, pageContext?: object): Promise<SseFrame[]> => {
    // SSE 经 fetch 流式读取;逐帧解析 event/data
    const res = await req('/api/admin/analytics/ask', {
      method: 'POST',
      body: JSON.stringify({ question, pageContext }),
    });
    return parseSseFrames(await res.text());
  },

  /** 员工管理(邀请/改角色/停用;新员工以种子密码可登录)。 */
  staff: {
    list: async (): Promise<{ success: boolean; staff: Array<{ id: string; email: string; displayName: string; role: string; status: string }> }> =>
      fetchJson('/api/admin/analytics/staff'),
    invite: async (p: { email: string; displayName: string; role: string }) =>
      fetchJson('/api/admin/analytics/staff', { method: 'POST', body: JSON.stringify(p) }),
    update: async (id: string, patch: Partial<{ role: string; status: string; displayName: string }>) =>
      fetchJson(`/api/admin/analytics/staff/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  },

  /** 菜单管理 CRUD(目录/菜单/按钮 + 权限点;系统菜单护栏在服务端)。 */
  menuAdmin: {
    create: async (p: { name: string; menuType: string; route?: string; permCode?: string; parentId?: string | null; sort?: number }) =>
      fetchJson('/api/admin/analytics/menus', { method: 'POST', body: JSON.stringify(p) }),
    update: async (id: string, patch: Partial<{ name: string; route: string; permCode: string; sort: number; status: string }>) =>
      fetchJson(`/api/admin/analytics/menus/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
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
    create: async (p: { name: string; promoType: string; threshold?: number; value: number; scopeType?: string; scopeValue?: string }) =>
      fetchJson('/api/admin/analytics/promotions', { method: 'POST', body: JSON.stringify(p) }),
    /** 商家向指定客户发券(仅券型/在售/同人同活动一次,服务端护栏)。 */
    grant: async (id: string, customerId: string) =>
      fetchJson(`/api/admin/analytics/promotions/${id}/grant`, { method: 'POST', body: JSON.stringify({ customerId }) }),
    update: async (id: string, patch: { name: string; value: number }) =>
      fetchJson(`/api/admin/analytics/promotions/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    setStatus: async (id: string, status: string) =>
      fetchJson(`/api/admin/analytics/promotions/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) }),
    remove: async (id: string) => fetchJson(`/api/admin/analytics/promotions/${id}`, { method: 'DELETE' }),
    redeem: async (id: string, orderId: string) =>
      fetchJson(`/api/admin/analytics/promotions/${id}/redeem`, { method: 'POST', body: JSON.stringify({ orderId }) }),
  },
};
