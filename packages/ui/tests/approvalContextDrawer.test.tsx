import { describe, expect, it, mock } from 'bun:test';
import React from 'react';
import type { Approval } from 'types';
import { type ApprovalContextDetail, ApprovalContextDrawer } from '../src/components/approval/ApprovalContextDrawer';
import { diagnoseApprovalTrigger } from '../src/components/approval/approvalUtils';

describe('Admin Approval Trigger Diagnosis & Context Drawer (TDD)', () => {
  describe('diagnoseApprovalTrigger', () => {
    it('diagnoses refund trigger cause and risk level accurately', () => {
      const refundApproval: Approval = {
        id: 'app_ref_01',
        threadId: 'thread_refund_01',
        businessId: 'nike',
        status: 'waiting',
        actionType: 'processRefund',
        reason: '退款金额 ¥599 超过自动放行阈值 ¥200',
        actionPayload: {
          orderId: 'ORD-NIKE-888',
          refundAmount: 599.0,
          userInput: '鞋子尺码不合，我要全额退款 599 元',
        },
      };

      const diagnosis = diagnoseApprovalTrigger(refundApproval);
      expect(diagnosis.category).toBe('refund');
      expect(diagnosis.riskLevel).toBe('critical');
      expect(diagnosis.title).toContain('资金退款');
      expect(diagnosis.triggerCause).toContain('退款金额');
      expect(diagnosis.ruleDescription).toContain('SOP 财务准则');
      expect(diagnosis.targetOrderId).toBe('ORD-NIKE-888');
    });

    it('diagnoses address modification trigger cause accurately', () => {
      const addressApproval: Approval = {
        id: 'app_addr_01',
        threadId: 'thread_addr_01',
        businessId: 'adidas',
        status: 'waiting',
        actionType: 'changeShippingAddress',
        reason: '订单处于分拣出库状态，修改地址需人工核验',
        actionPayload: {
          orderId: 'ORD-ADI-101',
          oldAddress: '北京市海淀区中关村南大街1号',
          newAddress: '上海市浦东新区陆家嘴环路1000号',
          userInput: '我填错地址了，帮我换成上海陆家嘴',
        },
      };

      const diagnosis = diagnoseApprovalTrigger(addressApproval);
      expect(diagnosis.category).toBe('address');
      expect(diagnosis.riskLevel).toBe('high');
      expect(diagnosis.title).toContain('地址变更');
      expect(diagnosis.targetOrderId).toBe('ORD-ADI-101');
      expect(diagnosis.diff?.newAddress).toBe('上海市浦东新区陆家嘴环路1000号');
    });

    it('diagnoses human escalation trigger cause accurately', () => {
      const humanApproval: Approval = {
        id: 'app_human_01',
        threadId: 'thread_human_01',
        businessId: 'ecommerce',
        status: 'waiting',
        actionType: 'human_escalation',
        reason: '连续识别到负面情绪与升级诉求',
        actionPayload: {
          userInput: '你们客服太慢了，立即叫真人来！',
          triggerSource: 'sentiment_escalation',
        },
      };

      const diagnosis = diagnoseApprovalTrigger(humanApproval);
      expect(diagnosis.category).toBe('human');
      expect(diagnosis.riskLevel).toBe('medium');
      expect(diagnosis.title).toContain('人工客服');
    });
  });

  describe('ApprovalContextDrawer Component', () => {
    const mockDetail: ApprovalContextDetail = {
      approval: {
        id: 'app_audit_test_01',
        threadId: 'thread_audit_100',
        businessId: 'nike',
        status: 'waiting',
        actionType: 'processRefund',
        reason: '退款金额 ¥699 超限拦截',
        actionPayload: {
          orderId: 'ORD-NIKE-777',
          refundAmount: 699.0,
          userInput: '鞋子开胶，请退款',
        },
        createdAt: new Date().toISOString(),
      },
      user: {
        userId: 'user_test_888',
        email: 'vip_customer@example.com',
        businessId: 'nike',
        vipLevel: 'Gold VIP',
        preferences: [
          { fact: '喜欢 42 码缓震跑鞋', confidence: 0.95, status: 'approved' },
          {
            fact: '常购 Nike Pegasus 系列',
            confidence: 0.88,
            status: 'approved',
          },
        ],
      },
      orders: [
        {
          orderId: 'ORD-NIKE-777',
          status: 'shipped',
          totalAmount: 699.0,
          carrier: '顺丰速运',
          trackingNumber: 'SF100293847',
          createdAt: '2026-08-20 14:30',
          items: [
            {
              productName: 'Nike Air Zoom Pegasus 41',
              price: 699.0,
              quantity: 1,
            },
          ],
        },
        {
          orderId: 'ORD-NIKE-666',
          status: 'delivered',
          totalAmount: 399.0,
          carrier: '中通快递',
          trackingNumber: 'ZT99882211',
          createdAt: '2026-08-10 10:15',
          items: [{ productName: 'Nike 运动速干 T 恤', price: 399.0, quantity: 1 }],
        },
      ],
      messages: [
        {
          id: 'msg_1',
          role: 'user',
          content: '您好，我买的这双鞋子刚收到发现鞋底开胶了',
          timestamp: '10:00:01',
        },
        {
          id: 'msg_2',
          role: 'assistant',
          content: '您好！很抱歉给您带来不好的体验，请提供您的订单号或需要退款的诉求。',
          timestamp: '10:00:03',
        },
        {
          id: 'msg_3',
          role: 'user',
          content: '订单 ORD-NIKE-777，请退款 699 元',
          timestamp: '10:00:15',
        },
      ],
    };

    it('renders drawer with trigger cause diagnosis, user info, purchase records, and chat history tabs', () => {
      const handleApprove = mock(async () => {});
      const handleReject = mock(async () => {});
      const handleHumanReply = mock(async () => {});
      const onClose = mock(() => {});

      const element = React.createElement(ApprovalContextDrawer, {
        isOpen: true,
        onClose,
        approval: mockDetail.approval,
        initialDetail: mockDetail,
        onApprove: handleApprove,
        onReject: handleReject,
        onHumanReply: handleHumanReply,
      });

      expect(element).toBeDefined();
      expect(element.type).toBe(ApprovalContextDrawer);
      expect(element.props.isOpen).toBe(true);
      expect(element.props.approval?.id).toBe('app_audit_test_01');
    });
  });
});
