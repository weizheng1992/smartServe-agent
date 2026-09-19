import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, authHeaders, clearSession, hasBossSession, setSession } from './api';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

beforeEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe('会话凭证', () => {
  it('无 token 时 authHeaders 不带 Authorization', () => {
    expect(authHeaders().Authorization).toBeUndefined();
    expect(authHeaders()['x-tenant-id']).toBe('aurora');
  });

  it('setSession 后 authHeaders 带 Bearer;clearSession 清空全部键', () => {
    setSession('tok-1', 'boss@aurora');
    expect(authHeaders().Authorization).toBe('Bearer tok-1');
    clearSession();
    expect(localStorage.getItem('merchant-admin.token')).toBeNull();
    expect(localStorage.getItem('merchant-admin.staff')).toBeNull();
    expect(authHeaders().Authorization).toBeUndefined();
  });

  it('hasBossSession 仅在保存了老板凭证后为真', () => {
    expect(hasBossSession()).toBe(false);
    setSession('tok', 'ops@aurora');
    expect(hasBossSession()).toBe(false);
    localStorage.setItem('merchant-admin.boss', JSON.stringify({ token: 'boss-tok', email: 'test@example.com' }));
    expect(hasBossSession()).toBe(true);
  });
});

describe('域客户端(fetchJson)', () => {
  it('业务 4xx 也返回 body(页面按 success/message 展示,不抛错)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ success: false, message: '仅老板可分配权限' }, 403)));
    setSession('tok', 'test@example.com');
    const body = await api.roles.saveMenus('sales_viewer', []);
    expect(body.success).toBe(false);
    expect(body.message).toContain('仅老板');
  });

  it('请求自动携带 Bearer 与租户头', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, spus: [] }));
    vi.stubGlobal('fetch', fetchMock);
    setSession('tok-9', 'test@example.com');
    await api.products.list();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer tok-9');
    expect(headers['x-tenant-id']).toBe('aurora');
  });
});

describe('staffSwitch(老板换签目标员工 token)', () => {
  it('成功:保存原始老板凭证 + 切换会话', async () => {
    setSession('boss-tok', 'test@example.com');
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      success: true, staffId: 'wh@aurora', displayName: '仓储', role: 'warehouse_operator',
      menus: [], token: 'wh-tok',
    }));
    vi.stubGlobal('fetch', fetchMock);

    const out = await api.staffSwitch('wh@aurora');
    expect(out.role).toBe('warehouse_operator');
    // 当前会话切到目标员工
    expect(authHeaders().Authorization).toBe('Bearer wh-tok');
    expect(localStorage.getItem('merchant-admin.staff')).toBe('wh@aurora');
    // 老板凭证留存,可切回
    const boss = JSON.parse(localStorage.getItem('merchant-admin.boss')!);
    expect(boss.token).toBe('boss-tok');
    // 切换请求本身以老板 token 发起
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer boss-tok');
  });

  it('服务端拒绝(非老板)时抛错且不动会话', async () => {
    setSession('ops-tok', 'ops@aurora');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ success: false, message: '仅老板可切换查看身份' }, 403)));
    await expect(api.staffSwitch('wh@aurora')).rejects.toThrow('仅老板');
    expect(localStorage.getItem('merchant-admin.staff')).toBe('ops@aurora');
    expect(hasBossSession()).toBe(false);
  });
});
