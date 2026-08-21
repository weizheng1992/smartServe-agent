import { describe, expect, it } from 'bun:test';
import { AgentIntentType, type AgentTaskSpec } from 'types';
import { SlotExtractor } from '../src/graph/nodes/triage/slotExtractor';

describe('🌟 TDD Slice 1: Intent & Slot Clarification State Machine', () => {
  it('should detect ORDER_MODIFY_ADDRESS and identify missing slots when user gives no parameters', () => {
    const input = '我想修改一下收货地址';
    const spec: AgentTaskSpec = SlotExtractor.extract(input);

    expect(spec.intentType).toBe(AgentIntentType.ORDER_MODIFY_ADDRESS);
    expect(spec.missingSlots).toContain('orderId');
    expect(spec.missingSlots).toContain('newAddress');
    expect(spec.confidence).toBeGreaterThanOrEqual(0.8);
    expect(spec.clarificationMessage).toBeDefined();
    expect(spec.clarificationMessage).toContain('订单编号');
    expect(spec.clarificationMessage).toContain('收货地址');
  });

  it('should detect ORDER_MODIFY_ADDRESS with partial slots (only orderId given)', () => {
    const input = '订单 ORD-ECOM-889901 帮我改下地址';
    const spec: AgentTaskSpec = SlotExtractor.extract(input);

    expect(spec.intentType).toBe(AgentIntentType.ORDER_MODIFY_ADDRESS);
    expect(spec.slots.orderId).toBe('ORD-ECOM-889901');
    expect(spec.missingSlots).not.toContain('orderId');
    expect(spec.missingSlots).toContain('newAddress');
    expect(spec.clarificationMessage).toContain('新的收货地址');
  });

  it('should extract full slots when both orderId and new address are provided', () => {
    const input = '请帮我把订单 ORD-ECOM-889901 的收货地址改成 北京市海淀区中关村南大街1号院3号楼802室';
    const spec: AgentTaskSpec = SlotExtractor.extract(input);

    expect(spec.intentType).toBe(AgentIntentType.ORDER_MODIFY_ADDRESS);
    expect(spec.slots.orderId).toBe('ORD-ECOM-889901');
    expect(spec.slots.newAddress).toContain('北京市海淀区中关村南大街1号院3号楼802室');
    expect(spec.missingSlots).toHaveLength(0);
  });

  it('should detect ORDER_RETURN with missing return reason or missing orderId', () => {
    const input = '我要申请退货退款';
    const spec: AgentTaskSpec = SlotExtractor.extract(input);

    expect(spec.intentType).toBe(AgentIntentType.ORDER_RETURN);
    expect(spec.missingSlots).toContain('orderId');
    expect(spec.clarificationMessage).toContain('订单编号');
  });

  describe('🌟 TDD Slice 2: Multi-turn Slot Accumulation & Context Retention', () => {
    it('should incrementally accumulate slots across conversation turns', () => {
      // Turn 1: "我想修改地址"
      const turn1Spec = SlotExtractor.extract('我想修改地址');
      expect(turn1Spec.missingSlots).toEqual(['orderId', 'newAddress']);

      // Turn 2: User provides order ID: "ORD-ECOM-889901"
      const turn2Spec = SlotExtractor.extract('ORD-ECOM-889901', turn1Spec.intentType, turn1Spec.slots);
      expect(turn2Spec.intentType).toBe(AgentIntentType.ORDER_MODIFY_ADDRESS);
      expect(turn2Spec.slots.orderId).toBe('ORD-ECOM-889901');
      expect(turn2Spec.missingSlots).toEqual(['newAddress']);

      // Turn 3: User provides new address: "送到上海市浦东新区张江高科"
      const turn3Spec = SlotExtractor.extract('送到上海市浦东新区张江高科', turn2Spec.intentType, turn2Spec.slots);
      expect(turn3Spec.intentType).toBe(AgentIntentType.ORDER_MODIFY_ADDRESS);
      expect(turn3Spec.slots.orderId).toBe('ORD-ECOM-889901');
      expect(turn3Spec.slots.newAddress).toContain('上海市浦东新区张江高科');
      expect(turn3Spec.missingSlots).toHaveLength(0);
    });
  });
});
