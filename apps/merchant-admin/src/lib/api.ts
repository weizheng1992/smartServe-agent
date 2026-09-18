// 网关 API 客户端(员工面头:x-user-id 模拟当前账号;真实鉴权接线后换 token)
const HEADERS_KEY = 'merchant-admin.staff';

export function currentStaff(): string {
  return localStorage.getItem(HEADERS_KEY) || 'boss@aurora';
}

export function switchStaff(staff: string) {
  localStorage.setItem(HEADERS_KEY, staff);
}

async function req(path: string, init?: RequestInit) {
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'x-tenant-id': 'aurora',
      'x-user-id': currentStaff(),
      ...(init?.headers || {}),
    },
  });
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
  menus: async (): Promise<{ role: string; menus: MenuNode[] }> =>
    (await req('/api/admin/analytics/menus')).json(),

  staffList: async (): Promise<{ staff: Array<{ id: string; email: string; displayName: string; role: string }> }> =>
    (await req('/api/admin/analytics/staff')).json(),

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
