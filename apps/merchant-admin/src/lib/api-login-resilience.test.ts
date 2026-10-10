import { api } from '@/lib/api';
// api.login 失败类钉子(2026-10-10 实弹):网关不可达/挂起时登录页曾以两种
// 劣形漏给用户 —— Vite proxy 对 ECONNREFUSED 回 500(非 JSON 体)→ 裸
// res.json() 抛 SyntaxError 文案;网关挂起 → fetch 无超时,按钮永久「登录中…」。
// 修复后:超时/不可达/非 2xx 一律诚实文案;凭证类 401 仍走 body 由页面呈现。
import { afterEach, describe, expect, it, vi } from 'vitest';

const okJson = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('api.login 失败类(诚实降级)', () => {
  it('proxy 500 非 JSON 体 → 「登录服务异常(HTTP 500)」,不再漏 SyntaxError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('Error occurred while trying to proxy', { status: 500 })),
    );
    await expect(api.login('ops@aurora', 'x')).rejects.toThrow('登录服务异常(HTTP 500)');
  });

  it('网关挂起(AbortSignal 超时)→ 「登录服务无响应」,不永久 登录中…', async () => {
    const timeoutErr = Object.assign(new Error('The operation was aborted due to timeout'), { name: 'TimeoutError' });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(timeoutErr)),
    );
    await expect(api.login('ops@aurora', 'x')).rejects.toThrow('登录服务无响应(10s 超时)');
  });

  it('连接拒绝(TypeError,ECONNREFUSED 形态)→ 「登录服务不可达」', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))),
    );
    await expect(api.login('ops@aurora', 'x')).rejects.toThrow('登录服务不可达');
  });

  it('凭证错误 401 仍返回 body(邮箱或密码错误由登录页呈现,不吞)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ success: false, error: '邮箱或密码错误' }), { status: 401 })),
    );
    const out = await api.login('ops@aurora', 'wrong');
    expect(out.success).toBe(false);
    expect(out.error).toBe('邮箱或密码错误');
  });

  it('成功登录返回体原样透传(token/email)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => okJson({ success: true, data: { token: 't1', user: { email: 'ops@aurora' } } })),
    );
    const out = await api.login('ops@aurora', 'agent-all-dev');
    expect(out.success).toBe(true);
    expect(out.data?.token).toBe('t1');
  });
});
