import { describe, expect, test } from 'bun:test';
import { db } from 'db';
import { OrderDomainService } from '../src/orderDomainService';

describe('OrderDomainService (Real PostgreSQL)', () => {
  test('createOrder and listUserOrders complete end-to-end flow', async () => {
    const testUser = await db.findOrCreateUserByEmail('order_test_user@example.com');
    const threadId = `thread_test_${Date.now()}`;
    await db.createThread(threadId, testUser.id, 'ecommerce');

    const customOrderId = `ORD-TEST-${Date.now().toString().slice(-5)}`;
    const createRes = await OrderDomainService.createOrder({
      orderId: customOrderId,
      userId: testUser.id,
      businessId: 'ecommerce',
      totalAmount: 129.5,
      carrier: 'SF Express',
    });

    expect(createRes.success).toBe(true);
    expect(createRes.order?.orderId).toBe(customOrderId);

    const listRes = await OrderDomainService.listUserOrders(threadId);
    expect(listRes.orders).toBeDefined();
    expect(Array.isArray(listRes.orders)).toBe(true);

    const found = listRes.orders?.some((o: any) => o.orderId === customOrderId);
    expect(found).toBe(true);
  });
});
