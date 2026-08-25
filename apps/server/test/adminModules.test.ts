import { describe, expect, it } from 'bun:test';
import { ApprovalsController } from '../src/modules/approvals/approvals.controller';
import { ApprovalsService } from '../src/modules/approvals/approvals.service';
import { BillingController } from '../src/modules/billing/billing.controller';
import { BillingService } from '../src/modules/billing/billing.service';
import { ConversationsController } from '../src/modules/conversations/conversations.controller';
import { EvalsController } from '../src/modules/evals/evals.controller';
import { EvalsService } from '../src/modules/evals/evals.service';
import { GuardrailsController } from '../src/modules/guardrails/guardrails.controller';
import { GuardrailsService } from '../src/modules/guardrails/guardrails.service';
import { PersonasController } from '../src/modules/personas/personas.controller';
import { PersonasService } from '../src/modules/personas/personas.service';
import { RagController } from '../src/modules/rag/rag.controller';
import { RagService } from '../src/modules/rag/rag.service';
import { SkillsController } from '../src/modules/skills/skills.controller';
import { SkillsService } from '../src/modules/skills/skills.service';
import { SystemLogsController } from '../src/modules/system-logs/system-logs.controller';
import { SystemLogsService } from '../src/modules/system-logs/system-logs.service';
import { TenantController } from '../src/modules/tenant/tenant.controller';
import { TenantService } from '../src/modules/tenant/tenant.service';

describe('Admin Modules Backend Gateway Endpoints & Unit Tests', () => {
  describe('ConversationsModule', () => {
    const controller = new ConversationsController();

    it('should list conversations for all tenants and specific tenants', async () => {
      const allRes = await controller.listConversations(undefined, undefined, undefined, '10', '0', {
        headers: { 'x-tenant-id': 'all', 'x-role': 'admin' },
      } as any);
      expect(allRes.success).toBe(true);
      expect(Array.isArray(allRes.items)).toBe(true);

      const ecomRes = await controller.listConversations(undefined, undefined, undefined, '10', '0', {
        headers: { 'x-tenant-id': 'ecommerce' },
      } as any);
      expect(ecomRes.success).toBe(true);
      expect(Array.isArray(ecomRes.items)).toBe(true);
    });
  });

  describe('ApprovalsModule', () => {
    const service = new ApprovalsService();
    const controller = new ApprovalsController(service);

    it('should list pending approvals with tenant and status filters', async () => {
      const res = await controller.getApprovals(undefined, undefined, 'all', {
        headers: { 'x-tenant-id': 'all' },
      } as any);
      expect(res.success).toBe(true);
      expect(Array.isArray(res.approvals)).toBe(true);
    });
  });

  describe('SkillsModule', () => {
    const service = new SkillsService();
    const controller = new SkillsController(service);

    it('should return skill registry and tenant config', async () => {
      const registryRes = controller.getRegistry();
      expect(registryRes.success).toBe(true);
      expect(Array.isArray(registryRes.skills)).toBe(true);
      expect(registryRes.skills.length).toBeGreaterThan(0);

      const configRes = await controller.getSkillsConfig({
        tenantId: 'ecommerce',
        userId: 'admin',
        role: 'admin',
      });
      expect(configRes.success).toBe(true);
      expect(Array.isArray(configRes.skills)).toBe(true);
    });
  });

  describe('TenantModule', () => {
    const service = new TenantService();
    const controller = new TenantController(service);

    it('should list all registered SaaS tenants', async () => {
      const res = await controller.listTenants();
      expect(res.success).toBe(true);
      expect(Array.isArray(res.tenants)).toBe(true);
      expect(res.tenants.length).toBeGreaterThan(0);
      expect(res.tenants.some((t: any) => t.id === 'nike' || t.id === 'ecommerce')).toBe(true);
    });
  });

  describe('RagModule', () => {
    const service = new RagService();
    const controller = new RagController(service);

    it('should list RAG documents with tenant filter', async () => {
      const allRes = await controller.listDocuments();
      expect(allRes.success).toBe(true);
      expect(Array.isArray(allRes.data)).toBe(true);
      expect(allRes.data.length).toBeGreaterThan(0);
      expect(allRes.data[0].docTitle).toBeDefined();
      expect(allRes.data[0].content).toBeDefined();

      const nikeRes = await controller.listDocuments('nike');
      expect(nikeRes.success).toBe(true);
      expect(nikeRes.data.every((d: any) => d.businessId === 'nike')).toBe(true);
    });

    it('should upload a new RAG chunk document', async () => {
      const createdRes = await controller.uploadDocument({
        chunkText: '耐克会员生日当月专享 85 折优惠券，全平台通用。',
        businessId: 'nike',
        contextualSummary: '耐克会员生日礼遇',
        metadata: { category: 'member_benefit' },
      });

      expect(createdRes.success).toBe(true);
      expect(createdRes.data.id).toBeDefined();
      expect(createdRes.data.chunkText).toContain('生日当月');

      // Verify deletion
      const delRes = await controller.deleteDocument(createdRes.data.id, 'nike');
      expect(delRes.success).toBe(true);
    });

    it('should query knowledge base and return relevance matches', async () => {
      const queryRes = await controller.queryKnowledge({
        query: '退换货',
        tenantId: 'nike',
      });

      expect(queryRes.success).toBe(true);
      expect(queryRes.data.matches.length).toBeGreaterThan(0);
      expect(queryRes.data.matches[0].score).toBeGreaterThan(0);
    });
  });

  describe('PersonasModule', () => {
    const service = new PersonasService();
    const controller = new PersonasController(service);

    it('should list persona facts with tenant and user filter', async () => {
      const res = await controller.list('nike');
      expect(res.success).toBe(true);
      expect(res.data.every((f: any) => f.businessId === 'nike')).toBe(true);
    });

    it('should create, update, and delete persona memory facts', async () => {
      const createRes = await controller.create({
        userId: 'u_test_999',
        businessId: 'nike',
        fact: '偏好夜间跑步，鞋码 43 码',
        confidence: 0.95,
        source: 'chat_inference',
        status: 'approved',
      });

      expect(createRes.success).toBe(true);
      const factId = createRes.data.id;

      const updateRes = await controller.update(factId, {
        fact: '偏好夜间跑步，鞋码 43.5 码 (已核实)',
        confidence: 0.99,
      });
      expect(updateRes.success).toBe(true);
      expect(updateRes.data.fact).toContain('43.5');

      const delRes = await controller.delete(factId);
      expect(delRes.success).toBe(true);
    });
  });

  describe('GuardrailsModule', () => {
    const service = new GuardrailsService();
    const controller = new GuardrailsController(service);

    it('should list guardrails rules', async () => {
      const res = await controller.list();
      expect(res.success).toBe(true);
      expect(res.data.length).toBeGreaterThan(0);
    });

    it('should create, update and delete a guardrail rule', async () => {
      const createRes = await controller.create({
        ruleName: '自定义敏感词过滤测试',
        ruleType: 'sensitive_keyword',
        pattern: 'internal_secret_token',
        action: 'block',
        severity: 'high',
        isEnabled: true,
      });

      expect(createRes.success).toBe(true);
      const ruleId = createRes.data.id;

      const updateRes = await controller.update(ruleId, {
        action: 'mask',
        isEnabled: false,
      });
      expect(updateRes.success).toBe(true);
      expect(updateRes.data.action).toBe('mask');
      expect(updateRes.data.isEnabled).toBe(false);

      const delRes = await controller.delete(ruleId);
      expect(delRes.success).toBe(true);
    });
  });

  describe('BillingModule', () => {
    const service = new BillingService();
    const controller = new BillingController(service);

    it('should list tenant usages and calculate quota usage', async () => {
      const res = await controller.getTenantUsages();
      expect(res.success).toBe(true);
      expect(Array.isArray(res.data)).toBe(true);
      expect(res.data.length).toBeGreaterThan(0);

      const nikeBilling = res.data.find((b: any) => b.businessId === 'nike');
      expect(nikeBilling).toBeDefined();
      expect(nikeBilling.monthlyLimitTokens).toBeGreaterThan(0);
    });

    it('should update tenant quota and recalculate status', async () => {
      const res = await controller.updateQuota({
        businessId: 'nike',
        monthlyLimitTokens: 10000000,
      });

      expect(res.success).toBe(true);
      expect(res.data.monthlyLimitTokens).toBe(10000000);
    });
  });

  describe('SystemLogsModule', () => {
    const service = new SystemLogsService();
    const controller = new SystemLogsController(service);

    it('should query system logs with type and tenant filtering', async () => {
      const res = await controller.getLogs('nike', 'llm_call', '10');
      expect(res.success).toBe(true);
      expect(Array.isArray(res.data)).toBe(true);
      expect(res.data.every((l: any) => l.logType === 'llm_call')).toBe(true);
    });
  });

  describe('EvalsModule', () => {
    const service = new EvalsService();
    const controller = new EvalsController(service);

    it('should retrieve evaluation historical results', async () => {
      const res = await controller.getResults();
      expect(res.success).toBe(true);
      expect(Array.isArray(res.data)).toBe(true);
      expect(res.data.length).toBeGreaterThan(0);
      expect(res.data[0].toolAccuracy).toBeGreaterThan(0);
    });

    it('should trigger a new evaluation run', async () => {
      const res = await controller.triggerRun({
        datasetName: 'ecommerce_regression_test_v3',
        runName: '单元测试自动化金标评测批次',
      });

      expect(res.success).toBe(true);
      expect(res.data.id).toBeDefined();
      expect(res.data.status).toBe('completed');
      expect(res.data.sampleCount).toBe(50);
    });
  });
});
