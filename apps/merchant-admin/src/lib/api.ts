// 网关 API 客户端(0013 收口:身份 = Bearer JWT,后端不再信任 x-user-id 头)。
// 老板可经 /staff/switch 换签任意员工 token 体验各角色视角;原始老板凭证
// 单独保存在 BOSS_KEY,切换动作始终以老板身份发起(非老板无权签发)。
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
  [TOKEN_KEY, STAFF_KEY, BOSS_KEY].forEach((k) => localStorage.removeItem(k));
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
    list: async (): Promise<{ roles: Array<{ role: string; menuCount: number; staffCount: number; builtin: boolean }> }> =>
      (await req('/api/admin/analytics/roles')).json(),
    menusOf: async (role: string): Promise<{ role: string; menuIds: string[] }> =>
      (await req(`/api/admin/analytics/roles/${role}/menus`)).json(),
    saveMenus: async (role: string, menuIds: string[]) =>
      (await req(`/api/admin/analytics/roles/${role}/menus`, { method: 'POST', body: JSON.stringify({ menuIds }) })).json(),
    create: async (role: string, menuIds: string[]) =>
      (await req('/api/admin/analytics/roles', { method: 'POST', body: JSON.stringify({ role, menuIds }) })).json(),
  },

  ask: async (question: string, pageContext?: object): Promise<Array<{ event: string; data: any }>> => {
    // SSE 经 fetch 流式读取;逐帧解析 event/data
    const res = await req('/api/admin/analytics/ask', {
      method: 'POST',
      body: JSON.stringify({ question, pageContext }),
    });
    const text = await res.text();
    const frames: Array<{ event: string; data: any }> = [];
    let event = '';
    for (const line of text.split('\n')) {
      if (line.startsWith('event: ')) event = line.slice(7).trim();
      else if (line.startsWith('data: ') && event) {
        try { frames.push({ event, data: JSON.parse(line.slice(6)) }); } catch { /* 跳过坏帧 */ }
        event = '';
      }
    }
    return frames;
  },

  reports: {
    list: async () => (await req('/api/admin/analytics/reports')).json(),
    create: async () => (await req('/api/admin/analytics/reports', { method: 'POST', body: '{}' })).json(),
    csv: async (id: string) => (await req(`/api/admin/analytics/reports/${id}/csv`)).json(),
  },
};
