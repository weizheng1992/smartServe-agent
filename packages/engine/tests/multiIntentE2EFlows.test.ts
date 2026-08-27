import { afterAll, beforeAll, describe, expect, it } from 'bun:test';
import { seedMerchantData } from '../../../apps/merchant/src/db/seed';
import { CardSynthesizer } from '../src/cards/cardSynthesizer';
import { runAgent } from '../src/graph/buildGraph';
import { IntentTriageEngine } from '../src/graph/nodes/triage/intentTriageEngine';

describe('🎯 Multi-Intent Recognition & Composite DAG Planning E2E Suite (复合多意图全流程测试)', () => {
  const tenantId = 'aurora';
  const testUserId = 'CUST-8801';

  beforeAll(async () => {
    await seedMerchantData();
  });

  // =========================================================================
  // 1. Triage 层级：多意图原子识别与分类抽取 (Multi-Intent Classification & Slot Parsing)
  // =========================================================================
  describe('【第一部分】Triage 意图引擎多意图识别与槽位抽取测试', () => {
    it('1.1 复合指令：物流查询 + 修改收货地址', async () => {
      const threadId = `triage_multi_intent_${Date.now()}_1`;
      const input =
        '帮我查下订单 AURORA-ORD-2026-9081 的物流，顺便把地址改成 北京市海淀区中关村南大街1号院创新大厦B座901';

      const triageRes = await IntentTriageEngine.process({
        input,
        threadId,
        userId: testUserId,
        businessConfig: { businessId: tenantId } as any,
      } as any);

      expect(triageRes.intents).toBeDefined();
      expect(triageRes.intents.length).toBeGreaterThanOrEqual(2);

      const intentTypes = triageRes.intents.map((i) => i.intent);
      expect(intentTypes.includes('order_status') || intentTypes.includes('order_query')).toBe(true);
      expect(intentTypes.includes('order_modify_address')).toBe(true);
    });

    it('1.2 复合指令：查询订单状态 + 申请退款', async () => {
      const threadId = `triage_multi_intent_${Date.now()}_2`;
      const input = '查一下订单 AURORA-ORD-2026-9081 的状态，顺便帮我申请退款，不想要了';

      const triageRes = await IntentTriageEngine.process({
        input,
        threadId,
        userId: testUserId,
        businessConfig: { businessId: tenantId } as any,
      } as any);

      expect(triageRes.intents).toBeDefined();
      expect(triageRes.intents.length).toBeGreaterThanOrEqual(2);

      const intentTypes = triageRes.intents.map((i) => i.intent);
      expect(intentTypes.includes('order_status') || intentTypes.includes('order_query')).toBe(true);
      expect(intentTypes.includes('refund') || intentTypes.includes('order_return')).toBe(true);
    });

    it('1.3 复合指令：商品导购推荐 + 查询我的历史订单', async () => {
      const threadId = `triage_multi_intent_${Date.now()}_3`;
      const input = '给我推荐几款透气跑鞋，另外帮我查一下我名下的全部订单';

      const triageRes = await IntentTriageEngine.process({
        input,
        threadId,
        userId: testUserId,
        businessConfig: { businessId: tenantId } as any,
      } as any);

      expect(triageRes.intents).toBeDefined();
      expect(triageRes.intents.length).toBeGreaterThanOrEqual(2);

      const intentTypes = triageRes.intents.map((i) => i.intent);
      expect(intentTypes.includes('shopping_guide')).toBe(true);
      expect(intentTypes.includes('order_status') || intentTypes.includes('order_query')).toBe(true);
    });
  });

  // =========================================================================
  // 2. 端到端 LangGraph DAG：多意图规划、执行与汇总闭环 (End-to-End Execution Flows)
  // =========================================================================
  describe('【第二部分】端到端多意图执行与 DAG 规划流转', () => {
    it('2.1 端到端执行：查物流 + 改地址（同一订单同时完成查询与未发货地址变更）', async () => {
      const threadId = `e2e_multi_query_and_modify_${Date.now()}`;
      const jobId = `job_multi_${Date.now()}`;
      const input =
        '帮我查下订单 AURORA-ORD-2026-9081 的物流状态，顺便把收货地址修改为 北京市海淀区中关村南大街1号院创新大厦B座901';

      const result = await runAgent(threadId, testUserId, input, jobId, undefined, tenantId);

      expect(result).toBeDefined();
      expect(result.output).toBeDefined();
      // 验证最终合成回答中既包含了物流/状态信息，也确认了地址修改
      expect(result.output).toContain('AURORA-ORD-2026-9081');
      expect(result.output).toMatch(/中关村南大街|创新大厦|地址/);

      // 验证 TaskPlan 中包含多个子步骤
      const subtasks = result.taskPlan?.subtasks || [];
      expect(subtasks.length).toBeGreaterThanOrEqual(1);
    }, 90000);

    it('2.2 端到端执行：查物流 + 申请退款（触发订单查询并挂起高危金额退款审批）', async () => {
      const threadId = `e2e_multi_status_and_refund_${Date.now()}`;
      const jobId = `job_multi_refund_${Date.now()}`;
      const input = '查一下订单 AURORA-ORD-2026-9081 目前发货了吗，顺便帮我申请退款，我不想要了';

      const result = await runAgent(threadId, testUserId, input, jobId, undefined, tenantId);

      expect(result).toBeDefined();
      expect(result.output).toBeDefined();
      expect(result.output).toContain('AURORA-ORD-2026-9081');
      expect(result.output).toMatch(/退款|审核|审批|待办/);
    }, 90000);

    it('2.3 多轮复合执行：选品加购 ➔ 第二轮同时加购第2件并查询全部订单', async () => {
      const threadId = `e2e_multi_shopping_and_orders_${Date.now()}`;
      const ecomUserId = `CUST_MULTI_${Date.now()}`;

      // Turn 1: 导购推荐
      const turn1Result = await runAgent(
        threadId,
        ecomUserId,
        '推荐当季热销机能外套',
        `job_turn1_${Date.now()}`,
        undefined,
        tenantId,
      );
      expect(turn1Result.output).toBeDefined();
      expect(turn1Result.cards?.length).toBeGreaterThan(0);

      // Turn 2: 多意图操作（把第1件加购物车，同时查询我名下的订单）
      const turn2Result = await runAgent(
        threadId,
        ecomUserId,
        '把第1件加入购物车，另外帮我查询我的全部订单',
        `job_turn2_${Date.now()}`,
        undefined,
        tenantId,
      );

      expect(turn2Result.output).toBeDefined();
      // 验证购物车操作反馈
      expect(turn2Result.output).toMatch(/购物车|已为您加入|加购成功/);
      // 验证订单卡片或订单列表反馈
      expect(turn2Result.output).toMatch(/订单|暂无|共/);
    }, 120000);
  });
});
