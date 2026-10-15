import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// transport 归一单册(2026-10-15 候选②):api-login-resilience 的失败类钉子
// 平移成 transport 级通用钉 —— 此前同一坑(非 JSON 500 裸 SyntaxError)login 修了
// fetchJson 没修、401 收口逐字三抄、错误模式逐方法记忆,归一后一册钉死。
// api-login-resilience(login 特有:10s 超时/防枚举)与本册(通用 transport)互补。

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return { ...actual };
});

import { api, errMsgOf } from '@/lib/api';

const okJson = (body: unknown, status = 200) =>
  ({ ok: status < 400, status, text: async () => JSON.stringify(body) }) as unknown as Response;
const rawText = (status: number, body: string) =>
  ({ ok: status < 400, status, text: async () => body }) as unknown as Response;

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('merchant-admin.token', 'tok-1');
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('requestJson(唯一 transport)', () => {
  it('业务 400/500 带 JSON body:原样返回由页面呈现,不 throw', async () => {
    fetchMock.mockResolvedValue(okJson({ success: false, message: '仅老板可操作' }, 403));
    const body = await api.roles.saveMenus('sales_viewer', []);
    expect(body).toEqual({ success: false, message: '仅老板可操作' });

    fetchMock.mockResolvedValue(okJson({ success: false, message: '服务内部错误' }, 500));
    const err500 = await api.customers.list();
    expect(err500).toEqual({ success: false, message: '服务内部错误' });
  });

  it('非 JSON 体(proxy ECONNREFUSED 回 HTML 等):诚实报错,绝不裸 SyntaxError', async () => {
    fetchMock.mockResolvedValue(rawText(502, '<html>ECONNREFUSED</html>'));
    await expect(api.customers.list()).rejects.toThrow('502 非 JSON 响应');
    fetchMock.mockResolvedValue(rawText(200, 'not-json'));
    await expect(api.customers.list()).rejects.toThrow('非 JSON 响应:not-json');
  });

  it('网络断:fetch 原生 reject 原样上抛(传输失败语义)', async () => {
    fetchMock.mockRejectedValue(new TypeError('network error'));
    await expect(api.customers.list()).rejects.toThrow('network error');
  });

  it('身份头注入:token 在则带 Bearer + x-tenant-id', async () => {
    fetchMock.mockResolvedValue(okJson({ success: true, customers: [] }));
    await api.customers.list();
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer tok-1');
    expect(headers['x-tenant-id']).toBe('aurora');
  });
});

describe('staffSwitch(老板凭证覆写 + 业务错误返 body)', () => {
  it('Authorization 覆写为留底老板 token(非当前会话 token),成功换签落会话', async () => {
    localStorage.setItem('merchant-admin.boss', JSON.stringify({ token: 'boss-tok', email: 'test@example.com' }));
    fetchMock.mockResolvedValue(
      okJson({ success: true, token: 'wh-tok', staffId: 'wh@aurora', role: 'warehouse_operator' }),
    );

    const body = await api.staffSwitch('wh@aurora');
    expect(body.success).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/api/admin/analytics/staff/switch');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer boss-tok');
    // 换签后当前会话即目标员工;老板凭证留底
    expect(localStorage.getItem('merchant-admin.token')).toBe('wh-tok');
    expect(localStorage.getItem('merchant-admin.staff')).toBe('wh@aurora');
    expect(JSON.parse(localStorage.getItem('merchant-admin.boss')!).email).toBe('test@example.com');
  });

  it('业务错误(非老板 403):返 body 不 throw、会话不动', async () => {
    fetchMock.mockResolvedValue(okJson({ success: false, message: '仅老板可切换' }, 403));
    const body = await api.staffSwitch('wh@aurora');
    expect(body.success).toBe(false);
    expect(localStorage.getItem('merchant-admin.token')).toBe('tok-1');
  });
});

describe('api.conversations.list(行形状修补 adapter)', () => {
  it('id/threadId 互补恒有两键,lastMessage 回退 snippet(此前 workbench 页内 reconcile)', async () => {
    fetchMock.mockResolvedValue(
      okJson({
        success: true,
        conversations: [
          { threadId: 't-1', status: 'active', businessId: 'aurora', lastMessageSnippet: '你好' },
          { id: 'id-2', status: 'active', businessId: 'aurora', lastMessage: '在吗' },
        ],
      }),
    );
    const { conversations } = await api.conversations.list();
    expect(conversations[0]).toMatchObject({ id: 't-1', threadId: 't-1', lastMessage: '你好' });
    expect(conversations[1]).toMatchObject({ id: 'id-2', threadId: 'id-2', lastMessage: '在吗' });
  });
});

describe('errMsgOf(错误文案单点出口)', () => {
  it('message/detail/error 三键读法归一,全缺省走 fallback', () => {
    expect(errMsgOf({ message: 'm' })).toBe('m');
    expect(errMsgOf({ error: 'e' })).toBe('e');
    expect(errMsgOf({ detail: 'd' })).toBe('d');
    expect(errMsgOf({})).toBe('操作失败');
    expect(errMsgOf(null)).toBe('操作失败');
    expect(errMsgOf({}, '导出失败')).toBe('导出失败');
  });
});
