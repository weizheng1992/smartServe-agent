import { describe, expect, it } from 'bun:test';
import { ConversationRepository } from '../src/services/conversationRepository';

describe('ConversationRepository Multi-Tenant Isolation & Timeline', () => {
  const threadNike = `test_thread_nike_${Date.now()}`;
  const threadApple = `test_thread_apple_${Date.now()}`;

  it('should append messages and enforce tenant isolation in listConversations', async () => {
    // 1. Insert Nike conversation messages
    await ConversationRepository.appendMessage({
      threadId: threadNike,
      businessId: 'nike',
      role: 'user',
      content: '我想退掉我买的 Pegasus 42 跑鞋',
    });

    await ConversationRepository.appendMessage({
      threadId: threadNike,
      businessId: 'nike',
      role: 'assistant',
      content: '已收到您的退货申请，请确认您的订单信息。',
      cards: [{ cardType: 'RefundCard', payload: { amount: 120 } }],
    });

    // 2. Insert Apple conversation messages
    await ConversationRepository.appendMessage({
      threadId: threadApple,
      businessId: 'apple',
      role: 'user',
      content: '我的 iPhone 16 Pro 怎么还没发货？',
    });

    // 3. Query conversations for Nike - should only contain Nike thread
    const nikeList = await ConversationRepository.listConversations({
      businessId: 'nike',
      searchKeyword: 'Pegasus',
    });

    expect(nikeList.items.some((i) => i.threadId === threadNike)).toBe(true);
    expect(nikeList.items.some((i) => i.threadId === threadApple)).toBe(false);

    // 4. Query conversations for Apple - should not contain Nike thread
    const appleList = await ConversationRepository.listConversations({
      businessId: 'apple',
      searchKeyword: 'iPhone',
    });

    expect(appleList.items.some((i) => i.threadId === threadApple)).toBe(true);
    expect(appleList.items.some((i) => i.threadId === threadNike)).toBe(false);
  });

  it('should retrieve full conversation timeline with cards and thought steps', async () => {
    const timeline = await ConversationRepository.getConversationTimeline(threadNike, 'nike');
    expect(timeline).not.toBeNull();
    expect(timeline?.thread.businessId).toBe('nike');
    expect(timeline?.messages.length).toBeGreaterThanOrEqual(2);
    expect(timeline?.messages[1].cards?.[0]?.cardType).toBe('RefundCard');
  });

  it('should update conversation status and assigned operator', async () => {
    await ConversationRepository.updateConversationStatus({
      threadId: threadNike,
      businessId: 'nike',
      status: 'human_takeover',
      assignedOperatorId: 'staff_101',
      tags: ['REFUND', 'HIGH_VALUE'],
    });

    const updated = await ConversationRepository.getConversationTimeline(threadNike, 'nike');
    expect(updated?.thread.status).toBe('human_takeover');
    expect(updated?.thread.assignedOperatorId).toBe('staff_101');
    expect(updated?.thread.tags).toContain('REFUND');
  });
});
