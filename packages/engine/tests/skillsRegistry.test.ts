import { describe, expect, it } from 'bun:test';
import { OrderAddressModificationSkill, OrderRefundSkill, ProductInquirySkill, SkillRegistry } from '../src/skills';

describe('SkillRegistry & Agent Skills Architecture Test Suite', () => {
  it('should have built-in skills registered successfully', () => {
    const allSkills = SkillRegistry.getAllSkills();
    expect(allSkills.length).toBeGreaterThanOrEqual(3);

    const refundSkill = SkillRegistry.getSkill('skill_order_refund');
    expect(refundSkill).toBeDefined();
    expect(refundSkill?.metadata.name).toBe('售后退款与理赔 SOP');
    expect(refundSkill?.metadata.requiresApproval).toBe(true);

    const addressSkill = SkillRegistry.getSkill('skill_order_address_modification');
    expect(addressSkill).toBeDefined();
    expect(addressSkill?.metadata.id).toBe('skill_order_address_modification');

    const productSkill = SkillRegistry.getSkill('skill_product_inquiry');
    expect(productSkill).toBeDefined();
    expect(productSkill?.metadata.category).toBe('pre_sale');
  });

  it('should correctly match skill based on execution context intent', () => {
    const matchRefund = SkillRegistry.findMatchingSkill({
      threadId: 'test_thread_1',
      tenantId: 'ecommerce',
      input: '帮我申请退款',
      slots: {
        activeIntent: 'refund',
        orderId: 'ORD-98712',
      },
    });
    expect(matchRefund).toBeDefined();
    expect(matchRefund?.metadata.id).toBe('skill_order_refund');

    const matchAddress = SkillRegistry.findMatchingSkill({
      threadId: 'test_thread_2',
      tenantId: 'ecommerce',
      input: '帮我改地址',
      slots: {
        activeIntent: 'order_modify_address',
        orderId: 'ORD-98712',
        newAddress: '北京市海淀区中关村南大街1号',
      },
    });
    expect(matchAddress).toBeDefined();
    expect(matchAddress?.metadata.id).toBe('skill_order_address_modification');
  });

  it('should intercept missing slots in OrderRefundSkill', async () => {
    const refundSkill = new OrderRefundSkill();
    const result = await refundSkill.execute({
      threadId: 'test_thread_3',
      tenantId: 'ecommerce',
      input: '帮我退款',
      slots: {
        activeIntent: 'refund',
      },
    });

    expect(result.success).toBe(false);
    expect(result.output).toContain('请补充您的订单号');
    expect(result.error).toBe('Missing required slot: orderId');
  });

  it('should intercept missing slots in OrderAddressModificationSkill', async () => {
    const addressSkill = new OrderAddressModificationSkill();
    const result = await addressSkill.execute({
      threadId: 'test_thread_4',
      tenantId: 'ecommerce',
      input: '修改地址',
      slots: {
        orderId: 'ORD-98712',
      },
    });

    expect(result.success).toBe(false);
    expect(result.output).toContain('需要提供订单编号和新的收货地址');
  });
});
