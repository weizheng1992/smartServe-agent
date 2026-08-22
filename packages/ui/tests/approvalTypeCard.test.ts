import { describe, expect, it } from 'bun:test';
import type { Approval } from 'types';
import { getApprovalCategory, getApprovalContextData } from '../src/components/approval/approvalUtils';

describe('Admin Approval UI - Type Differentiation & Context Extraction (TDD)', () => {
  describe('getApprovalCategory', () => {
    it('correctly categorizes refund action types', () => {
      expect(getApprovalCategory('processRefund')).toBe('refund');
      expect(getApprovalCategory('refund')).toBe('refund');
      expect(getApprovalCategory('refund_approval')).toBe('refund');
      expect(getApprovalCategory('ORDER_REFUND')).toBe('refund');
    });

    it('correctly categorizes address modification action types', () => {
      expect(getApprovalCategory('changeShippingAddress')).toBe('address');
      expect(getApprovalCategory('modify_address')).toBe('address');
      expect(getApprovalCategory('address_modification')).toBe('address');
      expect(getApprovalCategory('updateShippingInfo')).toBe('address');
    });

    it('correctly categorizes human escalation action types', () => {
      expect(getApprovalCategory('human_escalation')).toBe('human');
      expect(getApprovalCategory('human_takeover')).toBe('human');
      expect(getApprovalCategory('transfer_to_human')).toBe('human');
      expect(getApprovalCategory('human_support')).toBe('human');
    });

    it('falls back to generic for unknown or custom tools', () => {
      expect(getApprovalCategory('custom_tool')).toBe('generic');
      expect(getApprovalCategory(undefined)).toBe('generic');
      expect(getApprovalCategory('')).toBe('generic');
    });
  });

  describe('getApprovalContextData', () => {
    it('extracts refund context data accurately', () => {
      const approval: Approval = {
        id: 'app_12345678',
        threadId: 'thread_abc',
        businessId: 'nike',
        status: 'waiting',
        actionType: 'processRefund',
        reason: '退款金额超过安全阈值 ¥200',
        actionPayload: {
          orderId: 'ORD-998877',
          refundAmount: 399.0,
          reason: '商品瑕疵申请退款',
          userInput: '我收到的鞋子有划痕，要求全额退款 399 元',
          args: {
            orderId: 'ORD-998877',
            refundAmount: 399.0,
            reason: '商品瑕疵申请退款',
            paymentMethod: 'alipay',
          },
        },
      };

      const context = getApprovalContextData(approval);
      expect(context.category).toBe('refund');
      expect(context.orderId).toBe('ORD-998877');
      expect(context.refundAmount).toBe(399.0);
      expect(context.reason).toBe('退款金额超过安全阈值 ¥200');
      expect(context.userInput).toBe('我收到的鞋子有划痕，要求全额退款 399 元');
      expect(context.extraArgs).toEqual({ paymentMethod: 'alipay' });
    });

    it('extracts shipping address context data accurately', () => {
      const approval: Approval = {
        id: 'app_addr_88',
        threadId: 'thread_xyz',
        businessId: 'adidas',
        status: 'waiting',
        actionType: 'changeShippingAddress',
        reason: '订单处于分拣中，修改地址需人工审核',
        actionPayload: {
          orderId: 'ORD-ADIDAS-102',
          newAddress: '上海市浦东新区陆家嘴环路1000号',
          oldAddress: '北京市海淀区中关村南大街1号',
          recipientName: '张三',
          phone: '13800138000',
          userInput: '我写错地址了，帮我改成上海陆家嘴',
          args: {
            orderId: 'ORD-ADIDAS-102',
            newAddress: '上海市浦东新区陆家嘴环路1000号',
            recipientName: '张三',
            phone: '13800138000',
          },
        },
      };

      const context = getApprovalContextData(approval);
      expect(context.category).toBe('address');
      expect(context.orderId).toBe('ORD-ADIDAS-102');
      expect(context.newAddress).toBe('上海市浦东新区陆家嘴环路1000号');
      expect(context.oldAddress).toBe('北京市海淀区中关村南大街1号');
      expect(context.recipientName).toBe('张三');
      expect(context.phone).toBe('13800138000');
      expect(context.userInput).toBe('我写错地址了，帮我改成上海陆家嘴');
    });

    it('extracts human escalation context data accurately', () => {
      const approval: Approval = {
        id: 'app_human_01',
        threadId: 'thread_escalate_01',
        businessId: 'apple',
        status: 'waiting',
        actionType: 'human_escalation',
        reason: '用户情绪激动且连续多次重试失败',
        actionPayload: {
          userInput: '你们客服机器人根本听不懂，叫真人来！',
          triggerSource: 'sentiment_escalation',
          args: {
            reason: '用户情绪激动且连续多次重试失败',
          },
        },
      };

      const context = getApprovalContextData(approval);
      expect(context.category).toBe('human');
      expect(context.reason).toBe('用户情绪激动且连续多次重试失败');
      expect(context.userInput).toBe('你们客服机器人根本听不懂，叫真人来！');
      expect(context.triggerSource).toBe('sentiment_escalation');
    });
  });
});
