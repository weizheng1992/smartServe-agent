/**
 * 📜 HTTP 路由契约测试 — Phase 0.3
 *
 * 目的:把 13 个控制器 39 条路由的响应契约(envelope 形状 + 关键字段)钉死,
 * 作为 Phase 2 gateway-py(FastAPI)1:1 复刻的验收网。
 *
 * 覆盖地图(39 条全量):
 * - 本文件直测:health 1 / tenant 4 / skills 5 / approvals 2(+双前缀别名) /
 *   chat 2(messages, orders) / conversations 3 / rag 3(documents CRUD) /
 *   personas 4 / guardrails 4 / billing 2 / evals 2 / system-logs 1
 * - realtime.contract.test.ts:chat SSE 1(GET :jobId/stream)
 * - merchantSpi.e2e-spec.ts:spi 3
 * - 显式豁免(外部 LLM/embedding 依赖,由 promptfoo 基线覆盖行为等价):
 *   POST /api/chat(dispatchChat→runAgent→LLM)、POST /api/rag/query(ContextualRAG→embedding)
 */
import { afterAll, beforeAll, describe, expect, it } from 'bun:test';
import { type SealedEnv, initSealedEnv, loadDb } from '../helpers/sealedEnv';

type DbModule = typeof import('db');

let sealed: SealedEnv;
let db: DbModule['db'];
let getDrizzle: DbModule['getDrizzle'];
let pendingApprovals: DbModule['pendingApprovals'];
let ConversationRepository: DbModule['ConversationRepository'];
let eq: typeof import('drizzle-orm')['eq'];
let request: typeof import('supertest')['default'];
let app: import('@nestjs/common').INestApplication;

const TS = Date.now();
const CONTRACT_THREAD = `contract_thread_${TS}`;
const CONTRACT_APPROVAL = `app_contract_${TS}`;

beforeAll(async () => {
  sealed = await initSealedEnv();
  await sealed.seedTenants();

  const dbMod = await loadDb();
  db = dbMod.db;
  getDrizzle = dbMod.getDrizzle;
  pendingApprovals = dbMod.pendingApprovals;
  ConversationRepository = dbMod.ConversationRepository;
  ({ eq } = await import('drizzle-orm'));
  ({ default: request } = await import('supertest'));

  const { AppModule } = await import('../../src/app.module');
  const { Test } = await import('@nestjs/testing');
  const moduleFixture = await Test.createTestingModule({ imports: [AppModule] }).compile();
  app = moduleFixture.createNestApplication();
  await app.init();

  // ---- 最小契约 fixtures ----
  await db.createThread(CONTRACT_THREAD, 'u_contract', 'nike');
  await ConversationRepository.appendMessage({
    threadId: CONTRACT_THREAD,
    businessId: 'nike',
    userId: 'u_contract',
    role: 'user',
    content: 'contract fixture message',
  });
  await getDrizzle()
    .insert(pendingApprovals)
    .values({
      id: CONTRACT_APPROVAL,
      threadId: CONTRACT_THREAD,
      businessId: 'nike',
      status: 'waiting',
      actionType: 'processRefund',
      reason: '契约测试 fixture',
      actionPayload: { orderId: 'ORD-CONTRACT-1', amount: 300 },
    });
});

afterAll(async () => {
  await app.close();
});

describe('📜 Contract: api/health', () => {
  it('GET /api/health → 200 + success envelope', async () => {
    const res = await request(app.getHttpServer()).get('/api/health');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });
});

describe('📜 Contract: api/tenant', () => {
  it('GET /api/tenant/ping → 200 + tenant 上下文 + config', async () => {
    const res = await request(app.getHttpServer()).get('/api/tenant/ping').set('x-tenant-id', 'nike');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.tenant).toMatchObject({ tenantId: 'nike' });
    expect(res.body.config).toBeDefined();
    expect(typeof res.body.timestamp).toBe('string');
  });

  it('GET /api/tenant/list → 200 + tenants 数组含已播种租户', async () => {
    const res = await request(app.getHttpServer()).get('/api/tenant/list');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(Array.isArray(res.body.tenants)).toBe(true);
    const ids = res.body.tenants.map((t: { businessId?: string }) => t.businessId);
    expect(ids).toContain('nike');
    expect(ids).toContain('adidas');
  });

  it('POST /api/tenant → 创建租户后可列出,DELETE 后消失(往返契约)', async () => {
    const createRes = await request(app.getHttpServer())
      .post('/api/tenant')
      .send({ businessId: `ct_${TS}`, name: '契约测试租户' });
    expect([200, 201]).toContain(createRes.status);
    expect(createRes.body.success).toBe(true);

    const listAfterCreate = await request(app.getHttpServer()).get('/api/tenant/list');
    const created = listAfterCreate.body.tenants.find((t: { businessId?: string }) => t.businessId === `ct_${TS}`);
    expect(created).toBeDefined();

    const delRes = await request(app.getHttpServer()).delete(`/api/tenant/${created.id}`);
    expect([200, 200]).toContain(delRes.status);
    expect(delRes.body.success).toBe(true);
  });
});

describe('📜 Contract: api/skills', () => {
  it('GET /api/skills/registry → 200 + skills 数组', async () => {
    const res = await request(app.getHttpServer()).get('/api/skills/registry');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(Array.isArray(res.body.skills)).toBe(true);
    expect(res.body.skills.length).toBeGreaterThanOrEqual(5);
  });

  it('GET /api/skills/config → 200 + tenantId + skills', async () => {
    const res = await request(app.getHttpServer()).get('/api/skills/config').set('x-tenant-id', 'nike');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.tenantId).toBe('nike');
    expect(Array.isArray(res.body.skills)).toBe(true);
  });

  it('PUT /api/skills/config → 200 + tenantId + skillId + config', async () => {
    const res = await request(app.getHttpServer())
      .put('/api/skills/config')
      .set('x-tenant-id', 'nike')
      .send({ skillId: 'skill_order_refund', approvalThresholdAmount: 260 });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.tenantId).toBe('nike');
    expect(res.body.skillId).toBe('skill_order_refund');
    expect(res.body.config).toBeDefined();
  });

  it('GET /api/skills/tenant → 别名路由等价', async () => {
    const res = await request(app.getHttpServer()).get('/api/skills/tenant').set('x-tenant-id', 'nike');
    expect(res.status).toBe(200);
    expect(res.body.tenantId).toBe('nike');
  });

  it('PATCH /api/skills/tenant/:skillId → 200 + config', async () => {
    const res = await request(app.getHttpServer())
      .patch('/api/skills/tenant/skill_order_refund')
      .set('x-tenant-id', 'nike')
      .send({ enabled: true });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.skillId).toBe('skill_order_refund');
    expect(res.body.config).toBeDefined();
  });
});

describe('📜 Contract: api/approvals(双前缀)', () => {
  it('GET /api/approvals?tenantId=nike → 200 + approvals + total + tenantId', async () => {
    const res = await request(app.getHttpServer()).get('/api/approvals?tenantId=nike');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(Array.isArray(res.body.approvals)).toBe(true);
    expect(res.body.total).toBe(res.body.approvals.length);
    expect(res.body.tenantId).toBe('nike');
    const fixture = res.body.approvals.find((a: { id?: string }) => a.id === CONTRACT_APPROVAL);
    expect(fixture).toMatchObject({ businessId: 'nike', actionType: 'processRefund', status: 'waiting' });
  });

  it('GET /api/chat/approvals(别名前缀)→ 与主前缀同构', async () => {
    const res = await request(app.getHttpServer()).get('/api/chat/approvals?tenantId=nike');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(Array.isArray(res.body.approvals)).toBe(true);
  });

  it('POST /api/approvals → 决议 fixture 审批单', async () => {
    const res = await request(app.getHttpServer())
      .post('/api/approvals')
      .set('x-tenant-id', 'nike')
      .send({ approvalId: CONTRACT_APPROVAL, action: 'approve' });
    expect(res.status).toBe(200);
    expect(res.body).toBeDefined();
    // ApprovalsService.resolveApproval 直接透传结果;status 应推进为 approved
    expect(res.body.status === 'approved' || res.body.success === true).toBe(true);
  });
});

describe('📜 Contract: api/chat(非 LLM 路由)', () => {
  it('GET /api/chat/messages?threadId=… → 200 + thread + messages', async () => {
    const res = await request(app.getHttpServer()).get(
      `/api/chat/messages?threadId=${CONTRACT_THREAD}&businessId=nike`,
    );
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.thread).toMatchObject({ businessId: 'nike' });
    expect(Array.isArray(res.body.messages)).toBe(true);
    expect(res.body.messages.length).toBeGreaterThanOrEqual(1);
    expect(res.body.messages[0]).toHaveProperty('role');
    expect(res.body.messages[0]).toHaveProperty('content');
  });

  it('GET /api/chat/orders → 200 + orders 数组(空库亦为数组)', async () => {
    const res = await request(app.getHttpServer()).get('/api/chat/orders?userId=CUST-8801&businessId=ecommerce');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(Array.isArray(res.body.orders)).toBe(true);
  });
});

describe('📜 Contract: api/conversations', () => {
  it('GET /api/conversations → 200 + 分页结构含 fixture 会话', async () => {
    const res = await request(app.getHttpServer()).get('/api/conversations?tenantId=nike&status=all&limit=20&offset=0');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.tenantId).toBe('nike');
    // ConversationRepository.listConversations 返回 {conversations, total, ...} 展开
    expect(res.body).toHaveProperty('total');
    const list: Array<{ threadId?: string; id?: string }> = res.body.conversations || res.body.data || [];
    const ids = list.map((c) => c.threadId || c.id);
    expect(ids).toContain(CONTRACT_THREAD);
  });

  it('GET /api/conversations/:threadId → 200 + data.timeline(thread+messages)', async () => {
    const res = await request(app.getHttpServer())
      .get(`/api/conversations/${CONTRACT_THREAD}`)
      .set('x-tenant-id', 'nike');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.data.thread).toMatchObject({ businessId: 'nike' });
    expect(Array.isArray(res.body.data.messages)).toBe(true);
  });

  it('POST /api/conversations/:threadId/status → 200 + 状态推进', async () => {
    const res = await request(app.getHttpServer())
      .post(`/api/conversations/${CONTRACT_THREAD}/status`)
      .set('x-tenant-id', 'nike')
      .send({ status: 'human_takeover', assignedOperatorId: 'op_contract' });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.data).toBeDefined();
  });
});

describe('📜 Contract: api/rag(documents CRUD)', () => {
  let docId: string;

  it('POST /api/rag/documents → 201 + data', async () => {
    const res = await request(app.getHttpServer())
      .post('/api/rag/documents')
      .set('x-tenant-id', 'nike')
      .send({ chunkText: '契约测试:Nike 退换货政策 30 天内可退。' });
    expect(res.status).toBe(201);
    expect(res.body.success).toBe(true);
    expect(res.body.data).toBeDefined();
    docId = res.body.data.id;
  });

  it('GET /api/rag/documents → 200 + total + data', async () => {
    const res = await request(app.getHttpServer()).get('/api/rag/documents?tenantId=nike');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.tenantId).toBe('nike');
    expect(res.body.total).toBeGreaterThanOrEqual(1);
    expect(Array.isArray(res.body.data)).toBe(true);
  });

  it('DELETE /api/rag/documents/:id → 200 + message', async () => {
    const res = await request(app.getHttpServer()).delete(`/api/rag/documents/${docId}`).set('x-tenant-id', 'nike');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(typeof res.body.message).toBe('string');
  });
});

describe('📜 Contract: api/personas(CRUD 往返)', () => {
  let factId: string;

  it('POST /api/personas → 201 + data', async () => {
    const res = await request(app.getHttpServer())
      .post('/api/personas')
      .set('x-tenant-id', 'nike')
      .send({ userId: 'u_contract_persona', fact: '偏好深色跑鞋', businessId: 'nike', scope: 'tenant' });
    expect(res.status).toBe(201);
    expect(res.body.success).toBe(true);
    expect(res.body.data).toBeDefined();
    factId = res.body.data.id;
  });

  it('GET /api/personas → 200 + total + data 含 fixture', async () => {
    const res = await request(app.getHttpServer()).get('/api/personas?tenantId=nike');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.total).toBeGreaterThanOrEqual(1);
    expect(res.body.data.some((f: { id?: string }) => f.id === factId)).toBe(true);
  });

  it('PUT /api/personas/:id → 200 + data', async () => {
    const res = await request(app.getHttpServer())
      .put(`/api/personas/${factId}`)
      .set('x-tenant-id', 'nike')
      .send({ confidence: 0.9 });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.data).toBeDefined();
  });

  it('DELETE /api/personas/:id → 200 + message', async () => {
    const res = await request(app.getHttpServer()).delete(`/api/personas/${factId}`).set('x-tenant-id', 'nike');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });
});

describe('📜 Contract: api/guardrails(CRUD 往返)', () => {
  let ruleId: string;

  it('POST /api/guardrails → 201 + data', async () => {
    const res = await request(app.getHttpServer())
      .post('/api/guardrails')
      .set('x-tenant-id', 'nike')
      .send({ ruleName: '契约-禁词', ruleType: 'keyword', pattern: '诈骗' });
    expect(res.status).toBe(201);
    expect(res.body.success).toBe(true);
    expect(res.body.data).toBeDefined();
    ruleId = res.body.data.id;
  });

  it('GET /api/guardrails → 200 + total + data', async () => {
    const res = await request(app.getHttpServer()).get('/api/guardrails?tenantId=nike');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.tenantId).toBe('nike');
    expect(res.body.total).toBeGreaterThanOrEqual(1);
  });

  it('PUT /api/guardrails/:id → 200 + data', async () => {
    const res = await request(app.getHttpServer())
      .put(`/api/guardrails/${ruleId}`)
      .set('x-tenant-id', 'nike')
      .send({ severity: 'high' });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  it('DELETE /api/guardrails/:id → 200 + message', async () => {
    const res = await request(app.getHttpServer()).delete(`/api/guardrails/${ruleId}`).set('x-tenant-id', 'nike');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });
});

describe('📜 Contract: api/billing', () => {
  it('GET /api/billing/usages → 200 + data 数组', async () => {
    const res = await request(app.getHttpServer()).get('/api/billing/usages');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(Array.isArray(res.body.data)).toBe(true);
  });

  it('PUT /api/billing/quota → 200 + data', async () => {
    const res = await request(app.getHttpServer())
      .put('/api/billing/quota')
      .send({ businessId: 'nike', monthlyLimitTokens: 5_000_000 });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.data).toBeDefined();
  });
});

describe('📜 Contract: api/evals', () => {
  it('GET /api/evals/results → 200 + total + data', async () => {
    const res = await request(app.getHttpServer()).get('/api/evals/results');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(typeof res.body.total).toBe('number');
    expect(Array.isArray(res.body.data)).toBe(true);
  });

  it('POST /api/evals/run → 200 + data(本地随机指标,无外部依赖)', async () => {
    const res = await request(app.getHttpServer())
      .post('/api/evals/run')
      .send({ datasetName: 'contract_dataset', runName: `contract_${TS}` });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.data).toBeDefined();
  });
});

describe('📜 Contract: api/logs', () => {
  it('GET /api/logs → 200 + success envelope', async () => {
    const res = await request(app.getHttpServer()).get('/api/logs?tenantId=nike');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });
});
