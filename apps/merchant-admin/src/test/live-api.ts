// 前端集成测试基座:直连本地网关 + 真实数据库。
// 原则(用户决议):组件测试不 mock 数据 —— fetch 仅做「相对路径 → 网关地址」
// 透传,响应全部来自真实后端/真实库;网关未启动时相关用例整体跳过。
import { vi } from 'vitest';

export const GATEWAY = process.env.GATEWAY_URL ?? 'http://localhost:4000';

async function probe(): Promise<boolean> {
  try {
    const r = await fetch(`${GATEWAY}/api/health`, { signal: AbortSignal.timeout(3000) });
    return r.ok;
  } catch {
    return false;
  }
}

export const gatewayUp = await probe();

/** 透传 fetch:仅补全相对路径基址;不伪造任何响应。 */
export function installLiveFetch() {
  const original = globalThis.fetch.bind(globalThis);
  vi.stubGlobal('fetch', async (input: any, init?: any) => {
    const url = typeof input === 'string' ? input : String(input?.url ?? '');
    return original(url.startsWith('/') ? GATEWAY + url : url, init);
  });
}

export interface LiveSession {
  token: string;
  email: string;
}

/** 真实登录(bcrypt + JWT,同生产链路)。 */
export async function login(email: string, password = 'agent-all-dev'): Promise<LiveSession> {
  const r = await fetch(`${GATEWAY}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const b = await r.json();
  if (!b.success) throw new Error(`登录失败 ${email}: ${JSON.stringify(b)}`);
  return { token: b.data.token, email: b.data.user.email };
}
