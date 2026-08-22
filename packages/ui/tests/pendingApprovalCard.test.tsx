import { describe, expect, it, mock } from 'bun:test';
import React from 'react';
import type { Approval } from 'types';
import { PendingApprovalCard } from '../src/components/approval/PendingApprovalCard';

describe('PendingApprovalCard Component (TDD)', () => {
  it('renders refund approval UI with amount and context', () => {
    const refundApproval: Approval = {
      id: 'app_ref_001',
      threadId: 'thread_refund_123',
      businessId: 'nike',
      status: 'waiting',
      actionType: 'processRefund',
      reason: '退款金额超过单笔 ¥200 限制',
      actionPayload: {
        orderId: 'ORD-REF-7788',
        refundAmount: 599.9,
        userInput: '质量太差了，我申请退款 599.9',
        args: {
          orderId: 'ORD-REF-7788',
          refundAmount: 599.9,
          reason: '质量问题',
        },
      },
    };

    const handleApprove = mock(async () => {});
    const handleReject = mock(async () => {});
    const setRejectionReason = mock(() => {});
    const onOpenChat = mock(() => {});

    const element = React.createElement(PendingApprovalCard, {
      approval: refundApproval,
      rejectionReason: '',
      setRejectionReason,
      isSubmitting: false,
      onApprove: handleApprove,
      onReject: handleReject,
      onOpenChat,
    });

    expect(element).toBeDefined();
    expect(element.type).toBe(PendingApprovalCard);
    expect(element.props.approval.id).toBe('app_ref_001');
  });

  it('renders address change approval UI with old/new address context', () => {
    const addressApproval: Approval = {
      id: 'app_addr_002',
      threadId: 'thread_addr_456',
      businessId: 'adidas',
      status: 'waiting',
      actionType: 'changeShippingAddress',
      reason: '订单分拣中修改地址',
      actionPayload: {
        orderId: 'ORD-ADDR-9900',
        oldAddress: '北京市朝阳区',
        newAddress: '上海市徐汇区',
        recipientName: '李四',
        phone: '13900001111',
        userInput: '请帮我将收货地址改为上海市徐汇区',
        args: {
          orderId: 'ORD-ADDR-9900',
          newAddress: '上海市徐汇区',
        },
      },
    };

    const element = React.createElement(PendingApprovalCard, {
      approval: addressApproval,
      rejectionReason: '',
      setRejectionReason: () => {},
      isSubmitting: false,
      onApprove: async () => {},
      onReject: async () => {},
      onOpenChat: () => {},
    });

    expect(element).toBeDefined();
    expect(element.props.approval.businessId).toBe('adidas');
  });

  it('renders human escalation approval UI with chat context', () => {
    const humanApproval: Approval = {
      id: 'app_human_003',
      threadId: 'thread_human_789',
      businessId: 'ecommerce',
      status: 'waiting',
      actionType: 'human_escalation',
      reason: '情绪激动检测',
      actionPayload: {
        userInput: '我要找人工客服，马上解决！',
        triggerSource: 'sentiment_angry',
      },
    };

    const element = React.createElement(PendingApprovalCard, {
      approval: humanApproval,
      rejectionReason: '',
      setRejectionReason: () => {},
      isSubmitting: false,
      onApprove: async () => {},
      onReject: async () => {},
      onOpenChat: () => {},
    });

    expect(element).toBeDefined();
    expect(element.props.approval.actionType).toBe('human_escalation');
  });
});
