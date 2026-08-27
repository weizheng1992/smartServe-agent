import { describe, expect, it } from 'bun:test';
import { ShortMemory } from '../../../packages/engine/src/memory/shortMemory';
import { db } from '../src/client';

describe('🃏 Historical Messages & Rich Cards Physical Persistence Suite', () => {
  const testThreadId = `test_thread_cards_persist_${Date.now()}`;
  const testBusinessId = 'aurora';

  it('1. 验证通过 db.addMessage 写入富媒体卡片并能通过 db.getMessages 完整回显', async () => {
    const mockCards = [
      {
        type: 'order_picker',
        data: {
          title: '为您查询到 2 笔订单记录',
          totalCount: 2,
          orders: [
            {
              orderId: 'AURORA-ORD-2026-9081',
              status: 'PAID',
              totalAmount: 1299,
              currency: 'USD',
              carrier: '顺丰速运',
              trackingNumber: 'SF7200153839',
              createdAt: new Date().toISOString(),
              actions: [
                {
                  label: '查看物流轨迹',
                  action: 'track_order',
                  payload: { orderId: 'AURORA-ORD-2026-9081' },
                },
              ],
            },
          ],
        },
      },
    ];

    await db.createThread(testThreadId, 'CUST-8801', testBusinessId);
    await db.addMessage({
      id: `msg_user_${Date.now()}`,
      threadId: testThreadId,
      businessId: testBusinessId,
      role: 'user',
      content: '查询我的全部订单',
      timestamp: new Date().toISOString(),
    });

    const assistantMsgId = `msg_asst_${Date.now()}`;
    await db.addMessage({
      id: assistantMsgId,
      threadId: testThreadId,
      businessId: testBusinessId,
      role: 'assistant',
      content: '为您查询到以下订单信息：',
      cards: mockCards,
      timestamp: new Date().toISOString(),
    });

    const messages = await db.getMessages(testThreadId);
    expect(messages.length).toBe(2);

    const assistantMsg = messages.find((m) => m.id === assistantMsgId);
    expect(assistantMsg).toBeDefined();
    expect(assistantMsg?.cards).toBeDefined();
    expect(Array.isArray(assistantMsg?.cards)).toBe(true);
    expect(assistantMsg?.cards?.[0].type).toBe('order_picker');
    expect(assistantMsg?.cards?.[0].data.orders[0].orderId).toBe('AURORA-ORD-2026-9081');
  });

  it('2. 验证 ShortMemory.getMessages 和 ShortMemory.addMessage 完整透传 cards 字段', async () => {
    const shortMemory = new ShortMemory(testThreadId, 10, testBusinessId);
    const mockCard = [
      {
        type: 'order_card',
        data: {
          orderId: 'AURORA-ORD-2026-9082',
          status: 'SHIPPED',
          totalAmount: 589,
        },
      },
    ];

    await shortMemory.addMessage('assistant', '这是您的单笔订单卡片', mockCard);

    const history = await shortMemory.getMessages();
    expect(history.length).toBeGreaterThanOrEqual(3);

    const lastMsg = history[history.length - 1];
    expect(lastMsg.role).toBe('assistant');
    expect(lastMsg.content).toBe('这是您的单笔订单卡片');
    expect(lastMsg.cards).toBeDefined();
    expect(lastMsg.cards?.[0].type).toBe('order_card');
    expect(lastMsg.cards?.[0].data.orderId).toBe('AURORA-ORD-2026-9082');
  });
});
