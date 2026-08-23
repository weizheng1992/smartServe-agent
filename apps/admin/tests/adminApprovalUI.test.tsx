import { describe, expect, it, mock } from "bun:test";
import React from "react";
import type { Approval } from "types";
import { HistoricalAudits } from "../src/components/HistoricalAudits";
import { PendingApprovals } from "../src/components/PendingApprovals";

describe("Admin Approval UI Integration Tests", () => {
  const mockApprovals: Approval[] = [
    {
      id: "app_ref_001",
      threadId: "thread_111",
      businessId: "nike",
      status: "waiting",
      actionType: "processRefund",
      reason: "退款金额超过自动放行阈值 ¥200",
      actionPayload: {
        orderId: "ORD-NIKE-99",
        refundAmount: 899.0,
        userInput: "鞋底断裂，要求全额退款",
        args: {
          orderId: "ORD-NIKE-99",
          refundAmount: 899.0,
        },
      },
    },
    {
      id: "app_addr_002",
      threadId: "thread_222",
      businessId: "adidas",
      status: "waiting",
      actionType: "changeShippingAddress",
      reason: "包裹已出库修改地址风险拦截",
      actionPayload: {
        orderId: "ORD-ADI-55",
        oldAddress: "北京市朝阳区酒仙桥路",
        newAddress: "深圳市南山区科技园",
        recipientName: "王五",
        phone: "13700002222",
        userInput: "出差了，帮我改派送到深圳科技园",
      },
    },
    {
      id: "app_human_003",
      threadId: "thread_333",
      businessId: "ecommerce",
      status: "waiting",
      actionType: "human_escalation",
      reason: "检测到用户负面情绪与升级诉求",
      actionPayload: {
        userInput: "你们的处理太慢了，请人工客服介入！",
        triggerSource: "sentiment_escalation",
      },
    },
  ];

  it("renders PendingApprovals with multi-type approval cards and context", () => {
    const handleApprovalAction = mock(async () => {});
    const setRejectionReasons = mock(() => {});

    const element = React.createElement(PendingApprovals, {
      pendingApprovals: mockApprovals,
      rejectionReasons: {},
      setRejectionReasons,
      submittingActionId: null,
      handleApprovalAction,
    });

    expect(element).toBeDefined();
    expect(element.props.pendingApprovals.length).toBe(3);
  });

  it("renders HistoricalAudits with contextual information", () => {
    const auditedApprovals: Approval[] = [
      {
        ...mockApprovals[0],
        status: "approved",
      },
      {
        ...mockApprovals[1],
        status: "rejected",
        actionPayload: {
          ...mockApprovals[1].actionPayload,
          rejectionReason: "包裹已在派送中，无法拦截修改",
        },
      },
    ];

    const element = React.createElement(HistoricalAudits, {
      auditedApprovals,
    });

    expect(element).toBeDefined();
    expect(element.props.auditedApprovals.length).toBe(2);
  });
});
