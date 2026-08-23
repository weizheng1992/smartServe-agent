import { describe, expect, test } from 'bun:test';
import { db } from 'db';
import { OrderDomainService } from 'tools';
import { CardSynthesizer } from '../src/cards/cardSynthesizer';
import { runAgent } from '../src/graph/buildGraph';

describe('Adidas 会话商户身份与查单回归测试 (Adidas Thread Tenant Identity Bug Repro)', () => {
  test('当在 Adidas 商户下创建会话后，即使后续请求未显式传递 businessId 或传递了默认值，也能正确定位 Adidas 身份与订单', async () => {
    const threadId = `thread_repro_adidas_${Date.now()}`;
    const userId = 'usr_repro_adidas_001';

    // 1. 前端通过 POST /api/chat/threads 创建了 adidas 线程
    await db.createThread(threadId, userId, 'adidas');

    // 验证物理数据库中的 business_id 确实为 adidas
    const ctx1 = await OrderDomainService.getThreadSessionContext(threadId);
    expect(ctx1.businessId).toBe('adidas');

    // 2. 如果后续再次调用 createThread（例如 buildGraph 内部兜底调用，且 overrideBusinessId 为 undefined 或 'ecommerce'）
    // 不能覆盖原本已持久化的 'adidas' 租户标识
    await db.createThread(threadId, userId, undefined);
    const ctx2 = await OrderDomainService.getThreadSessionContext(threadId);
    expect(ctx2.businessId).toBe('adidas');

    // 3. 执行 runAgent("我的订单")，不传递 overrideBusinessId（模拟仅依赖 threadId 追溯多租户）
    const result = await runAgent(threadId, userId, '我的订单', `job_repro_${Date.now()}`);

    expect(result).toBeDefined();
    expect(result.output).toBeDefined();

    // 4. 核心断言：
    // - 绝对不能出现未替换的 [ECOMMERCE] 或 [ADIDAS] 标签
    expect(result.output).not.toContain('[ECOMMERCE]');
    expect(result.output).not.toContain('[ADIDAS]');

    // - 不能将自己错误表述为其他店铺或官方综合商城，必须包含 Adidas 相关品牌称谓
    expect(result.output).toContain('Adidas');

    // - 查单工具应当正常执行并生成订单卡片
    const cards = CardSynthesizer.synthesizeCards({
      taskPlan: result.taskPlan,
    });
    expect(cards.some((c) => c.type === 'order_card')).toBe(true);
  }, 300000);

  test('即使前端因默认状态将 businessId 误传为 ecommerce，对已有 Adidas 会话也必须优先尊重物理库并正确响应 Adidas 身份', async () => {
    const threadId = `thread_repro_adidas_overwrite_${Date.now()}`;
    const userId = 'usr_repro_adidas_002';

    // 1. 创建 adidas 会话
    await db.createThread(threadId, userId, 'adidas');

    // 2. 模拟前端默认值或不一致状态传入 overrideBusinessId = 'ecommerce'
    // 此时调用 db.createThread(threadId, userId, 'ecommerce')
    await db.createThread(threadId, userId, 'ecommerce');

    // 检查 thread 的 businessId 是否被错误覆盖
    const ctx = await OrderDomainService.getThreadSessionContext(threadId);
    expect(ctx.businessId).toBe('adidas');

    const result = await runAgent(threadId, userId, '我的订单', `job_repro2_${Date.now()}`, undefined, 'ecommerce');
    expect(result.output).not.toContain('[ECOMMERCE]');
    expect(result.output).toContain('Adidas');
  }, 300000);
});
