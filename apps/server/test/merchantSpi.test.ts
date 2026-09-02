/**
 * 🌟 Merchant SPI Open Gateway Suite (Direct Service Test)(密封版)
 *
 * Phase 0 改造:db 与被测 Service 延迟到容器 env 注入后动态导入;
 * 断言与原版完全一致(包括 pendingApprovals 不带 businessId 的原始写法)。
 */
import { beforeAll, describe, expect, it } from 'bun:test';
import { randomUUID } from 'node:crypto';
import { type SealedEnv, initSealedEnv, loadDb } from './helpers/sealedEnv';

type DbModule = typeof import('db');

let sealed: SealedEnv;
let db: DbModule['db'];
let getDrizzle: DbModule['getDrizzle'];
let pendingApprovals: DbModule['pendingApprovals'];
let eq: typeof import('drizzle-orm')['eq'];
let MerchantSpiService: typeof import('../src/modules/spi/merchant-spi.controller')['MerchantSpiService'];
let service: InstanceType<typeof MerchantSpiService>;

describe('🌟 Merchant SPI Open Gateway Suite (Direct Service Test)', () => {
  beforeAll(async () => {
    sealed = await initSealedEnv();

    const dbMod = await loadDb();
    db = dbMod.db;
    getDrizzle = dbMod.getDrizzle;
    pendingApprovals = dbMod.pendingApprovals;
    ({ eq } = await import('drizzle-orm'));

    ({ MerchantSpiService } = await import('../src/modules/spi/merchant-spi.controller'));
    service = new MerchantSpiService();
  });

  describe('1. 商户安全审批决议 (Resolve Approval)', () => {
    it('should allow merchant to resolve pending approval via service', async () => {
      const threadId = `spi_app_${Date.now()}`;
      const approvalId = randomUUID();
      const businessId = 'nike';

      await db.createThread(threadId, 'u_spi_user', businessId);

      const drizzle = getDrizzle();
      if (drizzle) {
        await drizzle.insert(pendingApprovals).values({
          id: approvalId,
          threadId,
          status: 'waiting',
          actionType: 'processRefund',
          actionPayload: {
            orderId: 'ORD-TEST-999',
            amount: 500,
            reason: '超额退款待商户核验',
          },
          deadline: new Date(Date.now() + 3600000),
        });
      }

      // 商户在其系统内审批通过
      const res = await service.resolveApproval(
        approvalId,
        {
          action: 'approve',
          reviewerId: 'nike_manager_01',
        },
        'nike',
      );

      expect(res.success).toBe(true);
      expect(res.status).toBe('approved');

      // 验证物理数据库已更新为 approved
      if (drizzle) {
        const rows = await drizzle.select().from(pendingApprovals).where(eq(pendingApprovals.id, approvalId));
        expect(rows.length).toBe(1);
        expect(rows[0].status).toBe('approved');
      }
    });

    it('should reject invalid action or cross-merchant approval access', async () => {
      expect(service.resolveApproval('any_id', { action: 'invalid_action' as any }, 'nike')).rejects.toThrow();
    });
  });

  describe('2. 商户人工客服消息回复与结单 (Escalation Bridge)', () => {
    it('should bridge merchant operator reply directly into customer thread', async () => {
      const threadId = `spi_chat_${Date.now()}`;
      const businessId = 'adidas';

      await db.createThread(threadId, 'u_adi_user', businessId);

      // 商户客服通过 API 回复消息
      const replyRes = await service.replyEscalation(
        threadId,
        {
          message: '您好，我是 Adidas 售后专员，已为您核实到该款跑鞋有现货。',
          operatorId: 'adi_rep_102',
          operatorName: 'Adidas客服小李',
        },
        'adidas',
      );

      expect(replyRes.success).toBe(true);
      expect(replyRes.delivered).toBe(true);

      // 验证消息已存入物理数据库
      const messages = await db.getMessages(threadId);
      const repMsg = messages.find((m) => m.content.includes('我是 Adidas 售后专员'));
      expect(repMsg).toBeDefined();
      expect(repMsg?.role).toBe('assistant');

      // 商户客服结单
      const closeRes = await service.closeEscalation(threadId, 'adidas');
      expect(closeRes.success).toBe(true);
    });
  });
});
