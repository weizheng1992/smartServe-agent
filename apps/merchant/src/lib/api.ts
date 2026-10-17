// 传输唯一收口(2026-10-17 审查收口,对齐 merchant-admin 候选②同型纪律):
// 页面/组件一切 HTTP 经本模块,严禁裸 fetch。此前 33 个 fetch 站点散落 9 文件,
// 错误语义各写一套(有的 res.json() 裸解析、有的 catch 后 alert)。
//
// 语义三态(与 merchant-admin 候选②同构,但无 401 清会话臂 —— 商户 store 面
// 以显式 userId/businessId 自报身份(guest-* / CUST-*),无员工 JWT 会话可清;
// 401 收口单点在员工面 apps/merchant-admin/src/lib/api.ts):
// ①业务/HTTP 错误:应答体原样返回(含 {success:false,...}),由页面按
//   success/errMsgOf 呈现文案,不吞进 throw;
// ②网络断/构造失败:原样上抛(调用方 catch 呈现「网络异常」类文案);
// ③非 JSON 应答(网关挂时 vite proxy 的 HTML/文本 500 等):ApiError 诚实
//   上抛,严禁把 HTML 当 JSON 解析出 undefined 静默走成功路径。
//
// 刻意不经此模块:SSE 流(storeStreamConnection.ts 自管帧流与重连)、
// localStorage 购物车(storeCart.ts 单点)。

export class ApiError extends Error {}

type JsonBody = Record<string, unknown>;

async function parseResponse<T>(res: Response): Promise<T> {
  const text = await res.text();
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(`非 JSON 应答(HTTP ${res.status}),网关可能未启动`);
  }
}

/** GET/任意方法的 JSON 应答读取:业务错误体原样返回,网络/解析问题 throw */
export async function requestJson<T = JsonBody>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  return parseResponse<T>(res);
}

/** POST JSON 一条龙(序列化 + Content-Type;业务错误体原样返回) */
export async function postJson<T = JsonBody>(url: string, payload: unknown, init?: RequestInit): Promise<T> {
  return requestJson<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    ...init,
  });
}

/** 业务错误文案三键单点(对齐 merchant-admin errMsgOf:message/detail/error) */
export function errMsgOf(body: unknown, fallback = '操作失败'): string {
  if (body && typeof body === 'object') {
    const b = body as Record<string, unknown>;
    for (const key of ['message', 'detail', 'error']) {
      const v = b[key];
      if (typeof v === 'string' && v.trim()) return v;
    }
  }
  return fallback;
}

/** 查询串布料:undefined/null/空串字段剔除,防 `?userId=undefined` 上行 */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : '';
}

/** multipart 上传单点(聊天图片/面单,与 web 端 ChatArea 同一端点) */
export async function uploadJson<T = JsonBody>(url: string, file: File, field = 'file'): Promise<T> {
  const formData = new FormData();
  formData.append(field, file);
  return requestJson<T>(url, { method: 'POST', body: formData });
}

// 自助身份族(StorefrontHeader 注册/登录;CUST-WEB-* 命名空间由调用方经
// UserContext.loginUser 落地,此处只管传输)
export const auth = {
  login: (payload: JsonBody) => postJson('/api/auth/login', payload),
  register: (payload: JsonBody) => postJson('/api/auth/register', payload),
};
