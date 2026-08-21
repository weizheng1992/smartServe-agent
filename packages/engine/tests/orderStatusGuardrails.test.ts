import { describe, expect, it } from 'bun:test';
import { OrderDomainService } from 'tools';

describe('🌟 TDD Slice 3: Order Status Guardrail & Address Modification State Machine', () => {
  it('should block address change if order is already shipped or delivered', async () => {
    // ORD-ECOM-889901 is shipped
    const res = await OrderDomainService.changeShippingAddress('ORD-ECOM-889901', '北京市海淀区中关村南大街1号');

    expect(res).toHaveProperty('error');
    expect(String(res.error)).toContain('Address modification blocked');
  });

  it('should block address modification if order does not exist or user is unauthorized (Zero IDOR)', async () => {
    const res = await OrderDomainService.changeShippingAddress('ORD-NON-EXISTENT-9999', '北京市海淀区中关村南大街1号');

    expect(res).toHaveProperty('error');
    expect(String(res.error)).toContain('未找到订单');
  });
});
