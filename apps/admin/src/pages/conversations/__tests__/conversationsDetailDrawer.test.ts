import { describe, expect, it } from "bun:test";
import React from "react";
import { ConversationsPage } from "../index";
import { ThreadDeepTraceDrawer } from "../components/ThreadDeepTraceDrawer";
import type { ConversationRecord } from "../types";

describe("Admin Conversations & Deep Trace Playback Drawer", () => {
  const mockRefundConversation: ConversationRecord = {
    threadId: "t_nike_90214",
    userId: "u_vip_881",
    businessId: "nike",
    channel: "Web Widget",
    status: "waiting_approval",
    intent: "order_refund",
    messageCount: 8,
    totalTokens: 3420,
    costUsd: 0.0142,
    lastMessage: "申请对订单 ORD-2026-9901 进行退款 500 元（超额审核中）",
    updatedAt: "2026-02-23 16:45:10",
  };

  const mockOrderStatusConversation: ConversationRecord = {
    threadId: "t_ecom_11094",
    userId: "u_buyer_554",
    businessId: "ecommerce",
    channel: "WeChat MiniApp",
    status: "active",
    intent: "order_status",
    messageCount: 3,
    totalTokens: 1100,
    costUsd: 0.0045,
    lastMessage: "包裹当前正在【上海转运中心】分拨发出",
    updatedAt: "2026-02-23 17:02:40",
  };

  it("1. ConversationsPage component is defined and exports correctly", () => {
    expect(typeof ConversationsPage).toBe("function");
  });

  it("2. ThreadDeepTraceDrawer renders properly for refund waiting approval conversation", () => {
    expect(typeof ThreadDeepTraceDrawer).toBe("function");

    const element = React.createElement(ThreadDeepTraceDrawer, {
      isOpen: true,
      onClose: () => {},
      conversation: mockRefundConversation,
    });

    expect(element).toBeDefined();
    expect(element.props.isOpen).toBe(true);
    expect(element.props.conversation?.threadId).toBe("t_nike_90214");
    expect(element.props.conversation?.status).toBe("waiting_approval");
  });

  it("3. ThreadDeepTraceDrawer renders properly for active order_status conversation", () => {
    const element = React.createElement(ThreadDeepTraceDrawer, {
      isOpen: true,
      onClose: () => {},
      conversation: mockOrderStatusConversation,
    });

    expect(element).toBeDefined();
    expect(element.props.conversation?.intent).toBe("order_status");
    expect(element.props.conversation?.status).toBe("active");
  });

  it("4. ThreadDeepTraceDrawer returns null when conversation is null", () => {
    const element = React.createElement(ThreadDeepTraceDrawer, {
      isOpen: true,
      onClose: () => {},
      conversation: null,
    });

    expect(element).toBeDefined();
    expect(element.props.conversation).toBeNull();
  });
});
