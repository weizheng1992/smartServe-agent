/**
 * SaaS Admin 全局 API 客户端与网关接口封装
 * 统一管理多租户请求头注入、统一错误处理与 RESTful 调用
 */

export const API_BASE_URL =
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE_URL) || 'http://localhost:4000';

// 平台闸会话(2026-10-18 平台面零鉴权收口):员工 JWT(role='platform_admin')
// 即管控台身份 —— localStorage 形态与 merchant-admin 同款。
const TOKEN_KEY = 'admin.token';
const TOKEN_EMAIL_KEY = 'admin.token.email';

export function setSession(token: string, email: string) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(TOKEN_EMAIL_KEY, email);
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(TOKEN_EMAIL_KEY);
}

export function authToken(): string | null {
  // 浏览器外环境(如 bun test 无 DOM)localStorage 不存在:无会话返回 null,
  // request() 照常走无 Authorization 分支(2026-10-19 CI 实弹:平台闸批把本
  // 函数引入 request 路径后,admin bun 册 10 连红于此——作者当时只跑了
  // merchant-admin 的 vitest,未跑 admin 的 bun test)。
  if (typeof localStorage === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function sessionEmail(): string | null {
  return localStorage.getItem(TOKEN_EMAIL_KEY);
}

export interface ApiResponse<T = any> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
  [key: string]: any;
}

async function request<T = any>(
  path: string,
  options: RequestInit & { tenantId?: string } = {},
): Promise<ApiResponse<T>> {
  const { tenantId, headers = {}, ...restOptions } = options;

  const resolvedTenant = tenantId || 'all';
  const token = authToken();
  const resolvedHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    'x-tenant-id': resolvedTenant,
    'x-business-id': resolvedTenant,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(headers as Record<string, string>),
  };

  const url = path.startsWith('http') ? path : `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;

  try {
    const res = await fetch(url, {
      ...restOptions,
      headers: resolvedHeaders,
    });

    const json = await res.json().catch(() => ({}));

    if (!res.ok) {
      // 401 统一出口:平台闸拒绝(未登录/过期)→ 清会话回登录页
      // (login 自身不走此导流;403 是已登录但角色不足,留在页内诚实报错)
      if (res.status === 401 && !path.includes('/api/auth/login')) {
        clearSession();
        window.location.assign('/login');
      }
      return {
        success: false,
        error: json.message || json.error || `HTTP ${res.status}: 请求失败`,
        ...json,
      };
    }

    return json;
  } catch (err: any) {
    return {
      success: false,
      error: err.message || '网络通信异常，请检查后端网关是否已启动',
    };
  }
}

export const authApi = {
  /** 登录不走统一 request(无 token 可附带;401 是登录失败本身,不得触发导流)。 */
  login: async (email: string, password: string): Promise<ApiResponse> => {
    const res = await fetch(`${API_BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    return (await res.json().catch(() => ({}))) as ApiResponse;
  },
};

export const adminApi = {
  get: <T = any>(path: string, tenantId?: string, query?: Record<string, any>) => {
    let fullPath = path;
    if (query) {
      const searchParams = new URLSearchParams();
      for (const [k, v] of Object.entries(query)) {
        if (v !== undefined && v !== null && v !== '') {
          searchParams.append(k, String(v));
        }
      }
      const qs = searchParams.toString();
      if (qs) {
        fullPath += `${path.includes('?') ? '&' : '?'}${qs}`;
      }
    }
    return request<T>(fullPath, { method: 'GET', tenantId });
  },

  post: <T = any>(path: string, body: any, tenantId?: string) => {
    return request<T>(path, {
      method: 'POST',
      body: JSON.stringify(body),
      tenantId,
    });
  },

  put: <T = any>(path: string, body: any, tenantId?: string) => {
    return request<T>(path, {
      method: 'PUT',
      body: JSON.stringify(body),
      tenantId,
    });
  },

  delete: <T = any>(path: string, tenantId?: string) => {
    return request<T>(path, { method: 'DELETE', tenantId });
  },
};

// ================= 业务模块 API =================

/** 1. 会话中心 API */
export const conversationsApi = {
  telemetry: (threadId: string, tenantId?: string) => {
    return adminApi.get(`/api/conversations/${threadId}/telemetry`, tenantId);
  },

  list: (params: {
    tenantId?: string;
    status?: string;
    search?: string;
    limit?: number;
    offset?: number;
  }) => {
    return adminApi.get('/api/conversations', params.tenantId, {
      status: params.status,
      search: params.search,
      limit: params.limit,
      offset: params.offset,
      tenantId: params.tenantId !== 'all' ? params.tenantId : undefined,
    });
  },

  getTimeline: (threadId: string, tenantId?: string) => {
    return adminApi.get(`/api/conversations/${threadId}`, tenantId);
  },

  updateStatus: (
    threadId: string,
    body: { status: string; assignedOperatorId?: string; tags?: string[] },
    tenantId?: string,
  ) => {
    return adminApi.post(`/api/conversations/${threadId}/status`, body, tenantId);
  },

  sendOperatorMessage: (threadId: string, content: string, tenantId?: string, operatorId = 'op_admin_01') => {
    return adminApi.post(
      '/api/chat',
      {
        message: content,
        threadId,
        businessId: tenantId,
        userId: operatorId,
        role: 'operator',
        sync: true,
      },
      tenantId,
    );
  },
};

/** 2. 人工审批 API */
export const approvalsApi = {
  list: (params: { tenantId?: string; status?: string }) => {
    return adminApi.get('/api/approvals', params.tenantId, {
      status: params.status,
      tenantId: params.tenantId !== 'all' ? params.tenantId : undefined,
    });
  },

  resolve: (body: {
    approvalId?: string;
    threadId?: string;
    action: 'approve' | 'reject' | 'escalate' | string;
    rejectionReason?: string;
    humanReply?: string;
    isFinish?: boolean;
    // 核准人契约(admin-readiness 01):声明身份,缺省由网关按调用面角色兜底
    actor?: string;
    actorRole?: 'platform_admin' | 'merchant_operator' | 'system';
    tenantId?: string;
  }) => {
    return adminApi.post('/api/approvals', body, body.tenantId);
  },
};

/** 3. 技能与工具 API */
export const skillsApi = {
  getRegistry: () => {
    return adminApi.get('/api/skills/registry');
  },

  getConfig: (tenantId: string) => {
    return adminApi.get('/api/skills/config', tenantId);
  },

  updateConfig: (
    tenantId: string,
    skillId: string,
    body: {
      enabled?: boolean;
      approvalThresholdAmount?: number;
      customPolicyPrompt?: string;
    },
  ) => {
    return adminApi.put('/api/skills/config', { skillId, ...body }, tenantId);
  },
};

/** 4. 租户管理 API */
export const tenantsApi = {
  list: () => {
    return adminApi.get('/api/tenant/list');
  },

  create: (body: {
    id: string;
    name: string;
    apiKey?: string | null;
    industry?: string;
    config?: Record<string, any>;
    // 新用户引导配置(2026-09-10):创建即携带,服务端 schema 校验后写入,
    // 消除「先建后编辑」两步走;未携带 = 保持未配置(首访走平台默认)
    onboardingConfig?: Record<string, any> | null;
  }) => {
    return adminApi.post('/api/tenant', body);
  },

  delete: (id: string) => {
    return adminApi.delete(`/api/tenant/${id}`);
  },

  update: (
    id: string,
    body: {
      name: string;
      status?: string;
      webhookUrl?: string | null;
      apiKey?: string | null;
      // null = 租户未配置(诚实回读);undefined/缺省 = 不修改,服务端保留既有
      refundLimit?: number | null;
      industry?: string;
      onboardingConfig?: Record<string, any> | null;
    },
  ) => {
    return adminApi.put(`/api/tenant/${id}`, body);
  },
};

/** 5. RAG 知识库 API */
/**
 * 文档上传摄取(multipart;2026-10-17 文档 RAG)。request() 硬编码 JSON
 * Content-Type,FormData 必须裸 fetch 让浏览器自带 multipart boundary。
 * 后端失败体是 HTTPException 的 {detail},成功体是 {success, data}。
 */
export async function uploadRagDocument(
  file: File,
  businessId: string,
  category: string | undefined,
  tenantId?: string,
): Promise<ApiResponse<{ jobId: string; sourceUrl: string; status: 'processing' }>> {
  const form = new FormData();
  form.append('file', file);
  form.append('businessId', businessId);
  if (category) form.append('category', category);
  try {
    // FormData 必须裸 fetch(request 硬编码 JSON);平台闸与手写切片写同律,
    // Authorization 手动随行(adminApi 同款 token 来源)。
    const token = authToken();
    const res = await fetch(`${API_BASE_URL}/api/rag/documents/upload`, {
      method: 'POST',
      headers: { 'x-tenant-id': tenantId || businessId, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: form,
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      return {
        success: false,
        error: json.detail || json.message || json.error || `HTTP ${res.status}: 上传失败`,
        ...json,
      };
    }
    return json;
  } catch (err: any) {
    return { success: false, error: err.message || '网络通信异常，请检查后端网关是否已启动' };
  }
}

export interface RagUploadJob {
  status: 'processing' | 'completed' | 'failed' | 'skipped' | 'stale';
  sourceUrl?: string;
  docTitle?: string;
  chunks?: number;
  tables?: number;
  images?: number;
  captioned?: number;
  partial?: boolean;
  error?: string;
}

/** 轮询上传作业至终态(间隔 1.5s,上限 5 分钟;超时抛错由调用方 alert) */
export async function pollRagUploadJob(jobId: string, tenantId?: string): Promise<RagUploadJob> {
  const deadline = Date.now() + 5 * 60 * 1000;
  while (Date.now() < deadline) {
    const res = await adminApi.get(`/api/rag/documents/upload/jobs/${jobId}`, tenantId);
    if (!res.success) throw new Error(res.error || '作业状态查询失败');
    const job = res.data as RagUploadJob;
    if (job.status !== 'processing') return job;
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new Error('文档解析超时(超过 5 分钟),请稍后在列表确认或重试');
}

export const ragApi = {
  list: (tenantId?: string) => {
    return adminApi.get('/api/rag/documents', tenantId);
  },

  createDoc: (
    body: {
      chunkText: string;
      businessId?: string;
      title?: string;
      category?: string;
      sourceUrl?: string;
    },
    tenantId?: string,
  ) => {
    return adminApi.post('/api/rag/documents', body, tenantId);
  },

  deleteDoc: (id: string, tenantId?: string) => {
    return adminApi.delete(`/api/rag/documents/${id}`, tenantId);
  },

  search: (query: string, tenantId?: string, category?: string) => {
    return adminApi.post('/api/rag/query', { query, category, tenantId }, tenantId);
  },
};

/** 6. 双层用户画像与记忆 API */
export const personasApi = {
  list: (tenantId?: string) => {
    return adminApi.get('/api/personas', tenantId);
  },

  create: (body: any, tenantId?: string) => {
    return adminApi.post('/api/personas', body, tenantId);
  },

  update: (id: string, body: any, tenantId?: string) => {
    return adminApi.put(`/api/personas/${id}`, body, tenantId);
  },

  delete: (id: string, tenantId?: string) => {
    return adminApi.delete(`/api/personas/${id}`, tenantId);
  },
};

/** 7. 风控护栏与 SOP 规则 API */
export const guardrailsApi = {
  list: (tenantId?: string) => {
    return adminApi.get('/api/guardrails', tenantId);
  },

  create: (body: any, tenantId?: string) => {
    return adminApi.post('/api/guardrails', body, tenantId);
  },

  update: (id: string, body: any, tenantId?: string) => {
    return adminApi.put(`/api/guardrails/${id}`, body, tenantId);
  },

  delete: (id: string, tenantId?: string) => {
    return adminApi.delete(`/api/guardrails/${id}`, tenantId);
  },
};

/** 商户积分池台账行(GET /api/billing/credits/{businessId};2026-10-21 用量配额闸)。 */
export interface CreditTransaction {
  id: string;
  /** 正 = 充值/赠送/退回,负 = 消耗/核减 */
  delta: number;
  /** 机读枚举(admin_adjust 携「前缀: 详情」复合形态);呈现层经 describeCreditReason 转人话 */
  reason: string;
  refJobId: string | null;
  operator: string | null;
  createdAt: string | null;
}

export interface CreditsDetail {
  businessId: string;
  /** null = 积分账户未初始化(未开通),诚实呈现,严禁前端编 0 */
  balance: number | null;
  transactions: CreditTransaction[];
}

export interface CreditsAdjustResult {
  businessId: string;
  balance: number | null;
}

/** 8. 多租户账单与 Token 计量 API */
export const billingApi = {
  getOverview: (tenantId?: string) => {
    return adminApi.get('/api/billing/overview', tenantId);
  },

  listTenantUsages: () => {
    return adminApi.get('/api/billing/usages');
  },

  updateQuota: (tenantId: string, quota: number) => {
    // 契约:PUT /api/billing/quota,body 为 {businessId, monthlyLimitTokens}
    return adminApi.put('/api/billing/quota', { businessId: tenantId, monthlyLimitTokens: quota }, tenantId);
  },

  /** 商户积分池手动充值/核减(2026-10-21 用量配额闸,D4:v1 无支付,台账留审计)。
   *  delta 可负;服务端 400 诚实拒(reason 空 / delta 0 / 核减穿零),body 原样返回。 */
  adjustCredits: (businessId: string, delta: number, reason: string) => {
    return adminApi.post<CreditsAdjustResult>('/api/billing/credits/adjust', { businessId, delta, reason });
  },

  /** 余额 + 最近流水(新→旧;balance null = 未开通,严禁编 0)。 */
  getCredits: (businessId: string) => {
    return adminApi.get<CreditsDetail>(`/api/billing/credits/${encodeURIComponent(businessId)}`);
  },
};

/** 9. 系统日志与审计 API */
export const systemLogsApi = {
  list: (params: { tenantId?: string; level?: string; limit?: number }) => {
    return adminApi.get('/api/logs', params.tenantId, {
      level: params.level,
      limit: params.limit,
    });
  },
};

/** 10. 评测与自动化基准 API(随机评测生成器已退役 410,真实评测走 test:prompt:record) */
export const evalsApi = {
  getResults: () => {
    return adminApi.get('/api/evals/results');
  },
  getResultCases: (runRecordId: string) => {
    return adminApi.get(`/api/evals/results/${runRecordId}/cases`);
  },
};
