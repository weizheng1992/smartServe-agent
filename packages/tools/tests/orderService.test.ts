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

  test('getUserOrdersDetailed queries structured order list with products and items', async () => {
    const testUser = await db.findOrCreateUserByEmail('buyer_history_test@example.com');
    const threadId = `thread_buyer_${Date.now()}`;
    await db.createThread(threadId, testUser.id, 'nike');

    const orderId = `ORD-NIKE-${Date.now().toString().slice(-5)}`;
    await OrderDomainService.createOrder({
      orderId,
      userId: testUser.id,
      businessId: 'nike',
      totalAmount: 899.0,
      carrier: '顺丰速运',
      trackingNumber: 'SF1234567890',
    });

    // 1. Query by userId and businessId
    const ordersByUserId = await OrderDomainService.getUserOrdersDetailed({
      userId: testUser.id,
      businessId: 'nike',
    });

    expect(ordersByUserId.length).toBeGreaterThanOrEqual(1);
    const targetOrder = ordersByUserId.find((o) => o.orderId === orderId);
    expect(targetOrder).toBeDefined();
    expect(targetOrder?.totalAmount).toBe(899.0);
    expect(targetOrder?.carrier).toBe('顺丰速运');
    expect(targetOrder?.items && targetOrder.items.length > 0).toBe(true);

    // 2. Query by threadId
    const ordersByThread = await OrderDomainService.getUserOrdersDetailed({
      threadId,
    });
    const foundInThread = ordersByThread.some((o) => o.orderId === orderId);
    expect(foundInThread).toBe(true);
  });
});
