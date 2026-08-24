import { describe, expect, it } from 'bun:test';
import { AgentIntentType, type IntentResult } from 'types';
import { IntentTriageEngine, resolveDomainRole } from '../src/graph/nodes/triage/intentTriageEngine';
import { SlotExtractor } from '../src/graph/nodes/triage/slotExtractor';

describe('Multi-Agent Router & State Bus Integration', () => {
  it('correctly maps intents and query keywords to specialized domain roles', () => {
    // 1. Shopping Guide
    const guideIntent: IntentResult[] = [{ intent: 'shopping_guide', confidence: 0.95, type: 'primary' }];
    expect(resolveDomainRole(guideIntent, '推荐几双透气的跑步鞋')).toBe('shopping_guide');

    // 2. Cart Manage
    const cartIntent: IntentResult[] = [{ intent: 'cart_manage', confidence: 0.95, type: 'primary' }];
    expect(resolveDomainRole(cartIntent, '把刚才那件衣服加购物车')).toBe('cart');

    // 3. Order & Service
    const orderIntent: IntentResult[] = [{ intent: 'order_status', confidence: 0.95, type: 'primary' }];
    expect(resolveDomainRole(orderIntent, '查询我的订单物流')).toBe('order_service');

    const refundIntent: IntentResult[] = [{ intent: 'refund', confidence: 0.95, type: 'primary' }];
    expect(resolveDomainRole(refundIntent, '我要申请退货退款')).toBe('order_service');

    // 4. Chitchat
    const chatIntent: IntentResult[] = [{ intent: 'general_query', confidence: 0.8, type: 'primary' }];
    expect(resolveDomainRole(chatIntent, '你好呀')).toBe('chitchat');
  });

  it('extracts shopping guide and cart intents accurately via SlotExtractor', () => {
    const guideSpec = SlotExtractor.extract('推荐几款适合夏天穿的透气运动鞋');
    expect(guideSpec.intentType).toBe(AgentIntentType.SHOPPING_GUIDE);

    const cartSpec = SlotExtractor.extract('把第二件加入购物车，数量 2 件');
    expect(cartSpec.intentType).toBe(AgentIntentType.CART_MANAGE);
  });
});
