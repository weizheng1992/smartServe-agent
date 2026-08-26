import { describe, expect, it } from 'bun:test';
import { runAgent } from '../src/graph/buildGraph';
import { CartManageSkill, ShoppingGuideSkill } from '../src/skills';

describe('End-to-End Multi-Turn Shopping Guide to Cart Flow', () => {
  it('should recommend products in Turn 1, resolve ordinal reference in Turn 2, handle vague ordinal in Turn 3', async () => {
    const threadId = `test_shopping_cart_multi_${Date.now()}`;
    const userId = 'CUST_TEST_MULTI_8801';
    const tenantId = 'aurora';

    // ----------------------------------------------------
    // Turn 1: 用户请求推荐外套
    // ----------------------------------------------------
    const turn1Res: any = await runAgent(threadId, userId, '推荐当季热销机能外套', undefined, undefined, tenantId);

    expect(turn1Res).toBeDefined();
    expect(turn1Res.output).toContain('精选');
    expect(turn1Res.output).toContain('如需加入购物车，直接对我说“把第几件加入购物车”即可');
    expect(turn1Res.cards?.length).toBeGreaterThan(0);

    // ----------------------------------------------------
    // Turn 2: 用户回复 "把第1件加入购物车"
    // ----------------------------------------------------
    const turn2Res: any = await runAgent(threadId, userId, '把第1件加入购物车', undefined, undefined, tenantId);

    expect(turn2Res).toBeDefined();
    expect(turn2Res.output).toContain('已成功将');
    expect(turn2Res.output).toContain('加入购物车');
    expect(turn2Res.cards?.length).toBeGreaterThan(0);
    expect(turn2Res.cards[0].data?.orderId).toBe('CART-ADDED');

    // ----------------------------------------------------
    // Turn 3: 用户询问 "把第几件加入购物车" (模糊指代引导)
    // ----------------------------------------------------
    const turn3Res: any = await runAgent(threadId, userId, '把第几件加入购物车', undefined, undefined, tenantId);

    expect(turn3Res).toBeDefined();
    expect(turn3Res.output).toContain('请问您想将哪一款');
    expect(turn3Res.output).toContain('把第1件加入购物车');

    // ----------------------------------------------------
    // Turn 4: 用户回复 "把第2件加入购物车"
    // ----------------------------------------------------
    const turn4Res: any = await runAgent(threadId, userId, '把第2件加入购物车', undefined, undefined, tenantId);

    expect(turn4Res).toBeDefined();
    expect(turn4Res.output).toContain('已成功将');
    expect(turn4Res.output).toContain('加入购物车');

    // ----------------------------------------------------
    // Turn 5: 用户查看购物车总价
    // ----------------------------------------------------
    const turn5Res: any = await runAgent(threadId, userId, '看下购物车总价', undefined, undefined, tenantId);

    expect(turn5Res).toBeDefined();
    expect(turn5Res.output).toContain('购物车目前共有');
    expect(turn5Res.output).toContain('实付预估');
  });
});
