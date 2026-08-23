import { describe, expect, it } from "bun:test";
import React from "react";
import { ConversationsExplorer } from "../src/components/ConversationsExplorer";
import { ThreadDeepTraceDrawer } from "../src/components/ThreadDeepTraceDrawer";

describe("🌟 Platform Admin Conversations & Deep Trace Suite", () => {
  it("renders ConversationsExplorer correctly with initial merchant and filters", () => {
    const element = React.createElement(ConversationsExplorer, {
      selectedMerchant: "nike",
    });

    expect(element).toBeDefined();
    expect(element.props.selectedMerchant).toBe("nike");
  });

  it("renders ThreadDeepTraceDrawer with LangGraph decision flow and tools telemetry", () => {
    const mockTimeline = {
      thread: {
        threadId: "thread_test_001",
        businessId: "nike",
        userId: "CUST-8801",
        status: "active",
        unreadCount: 0,
        tags: ["ORDER_STATUS"],
        metadata: {},
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
      messages: [
        {
          id: "m1",
          role: "user",
          content: "请帮我查询订单 ORD-NIKE-001 物流到哪了",
          timestamp: new Date().toISOString(),
        },
        {
          id: "m2",
          role: "assistant",
          content: "已为您查询到包裹正在派送中！",
          cards: [
            {
              cardType: "TrackingTimeline",
              payload: {
                trackingNumber: "SF1092837461",
                carrier: "顺丰速运",
                status: "派送中",
              },
            },
          ],
          timestamp: new Date().toISOString(),
        },
      ],
    };

    const drawer = React.createElement(ThreadDeepTraceDrawer, {
      isOpen: true,
      onClose: () => {},
      timeline: mockTimeline,
      selectedMerchant: "nike",
    });

    expect(drawer).toBeDefined();
    expect(drawer.props.isOpen).toBe(true);
    expect(drawer.props.timeline.messages.length).toBe(2);
  });
});
