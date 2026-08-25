/**
 * SaaS Admin 全局 API 客户端与网关接口封装
 * 统一管理多租户请求头注入、统一错误处理与 RESTful 调用
 */

export const API_BASE_URL =
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE_URL) || 'http://localhost:4000';

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
  const resolvedHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    'x-tenant-id': resolvedTenant,
    'x-business-id': resolvedTenant,
    'x-role': 'admin',
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
    apiKey?: string;
    config?: Record<string, any>;
  }) => {
    return adminApi.post('/api/tenant', body);
  },

  delete: (id: string) => {
    return adminApi.delete(`/api/tenant/${id}`);
  },
};

/** 5. RAG 知识库 API */
export const ragApi = {
  list: (tenantId?: string) => {
    return adminApi.get('/api/rag/documents', tenantId);
  },

  createDoc: (
    body: {
      title: string;
      category: string;
      content: string;
      tenantId?: string;
    },
    tenantId?: string,
  ) => {
    return adminApi.post('/api/rag/documents', body, tenantId);
  },

  deleteDoc: (id: string, tenantId?: string) => {
    return adminApi.delete(`/api/rag/documents/${id}`, tenantId);
  },

  search: (query: string, tenantId?: string, category?: string) => {
    return adminApi.post('/api/rag/search', { query, category, tenantId }, tenantId);
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

  update: (id: string, body: any, tenantId?: string) => {
    return adminApi.put(`/api/guardrails/${id}`, body, tenantId);
  },
};

/** 8. 多租户账单与 Token 计量 API */
export const billingApi = {
  getOverview: (tenantId?: string) => {
    return adminApi.get('/api/billing/overview', tenantId);
  },

  listTenantUsages: () => {
    return adminApi.get('/api/billing/usages');
  },

  updateQuota: (tenantId: string, quota: number) => {
    return adminApi.post('/api/billing/quota', { tenantId, quota }, tenantId);
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

/** 10. 评测与自动化基准 API */
export const evalsApi = {
  getResults: () => {
    return adminApi.get('/api/evals/results');
  },

  runEval: (suiteName: string) => {
    return adminApi.post('/api/evals/run', { suiteName });
  },
};
