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

/** 同进程成功会话记忆(2026-10-23 夜评审收口):网关自 8a00c75 起对
 * /api/auth/login 挂 10/min 限流(生产审计防爆破),全量套件 5 个 live 文件
 * 合计 ~11 次登录按时间聚集度非确定性撞闸(429「请求过于频繁」假红)。
 * 每凭据每进程仍走一次真实登录链路(bcrypt + JWT),之后复用 30 天期
 * token;失败登录不记忆(401 路径保持真实)。单轮登录请求降至 7 次。 */
const sessionCache = new Map<string, LiveSession>();

/** 真实登录(bcrypt + JWT,同生产链路)。 */
export async function login(email: string, password = 'agent-all-dev'): Promise<LiveSession> {
  const key = `${email}:${password}`;
  const cached = sessionCache.get(key);
  if (cached) return cached;
  const r = await fetch(`${GATEWAY}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const b = await r.json();
  if (!b.success) throw new Error(`登录失败 ${email}: ${JSON.stringify(b)}`);
  const session: LiveSession = { token: b.data.token, email: b.data.user.email };
  sessionCache.set(key, session);
  return session;
}
