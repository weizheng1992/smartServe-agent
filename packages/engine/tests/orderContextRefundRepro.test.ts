import { describe, expect, it } from 'bun:test';
import { runAgent } from '../src/graph/buildGraph';

describe('🐛 Repro Bug: Multi-turn Context Order Refund Missing OrderId', () => {
  const testUserId = 'CUST-8801';
  const testBusinessId = 'aurora';
  const testThreadId = `repro_order_refund_context_${Date.now()}`;

  it('多轮对话复现：第一轮选定订单后，第二轮提问【我想申请退款】，应自动结合上下文中的订单编号 AURORA-ORD-2026-9081 进行处理，而不是盲目反问提供订单号', async () => {
    // Turn 1: 用户选定订单并查询物流
    const turn1Res = await runAgent(
      testThreadId,
      testUserId,
      '已选定订单 AURORA-ORD-2026-9081，请帮我查询该订单的具体信息和最新物流进度。',
      undefined,
      undefined,
      testBusinessId,
    );

    expect(turn1Res.output).toBeDefined();
    expect(turn1Res.output).toContain('AURORA-ORD-2026-9081');

    // Turn 2: 用户紧接着在同一会话中说【我想申请退款】
    const turn2Res = await runAgent(testThreadId, testUserId, '我想申请退款', undefined, undefined, testBusinessId);

    console.log('[Turn 2 Response Output]:', turn2Res.output);

    // 用户遇到的 Bug 现象：返回了 "请问您需要为哪笔订单申请退款/退货？请提供您的【订单编号】。"
    // 正确的期望：应该结合上下文中的订单 AURORA-ORD-2026-9081，推进退款/返回退款信息，绝不能盲目反问索要订单编号
    expect(turn2Res.output).not.toContain('请提供您的【订单编号】');
    expect(turn2Res.output).not.toContain('请提供【订单编号】');
    expect(turn2Res.output).toContain('AURORA-ORD-2026-9081');
  }, 120000);

  it('多轮对话：第一轮选定订单后，第二轮提问【修改收货地址为上海市浦东新区张江高科园区】，应自动结合上下文订单', async () => {
    const threadId = `repro_order_address_context_${Date.now()}`;
    await runAgent(
      threadId,
      testUserId,
      '已选定订单 AURORA-ORD-2026-9081，请帮我查询该订单的具体信息和最新物流进度。',
      undefined,
      undefined,
      testBusinessId,
    );

    const turn2Res = await runAgent(
      threadId,
      testUserId,
      '修改收货地址为上海市浦东新区张江高科园区1号楼',
      undefined,
      undefined,
      testBusinessId,
    );

    expect(turn2Res.output).not.toContain('请提供您的【订单编号】');
    expect(turn2Res.output).toContain('AURORA-ORD-2026-9081');
  }, 120000);
});
