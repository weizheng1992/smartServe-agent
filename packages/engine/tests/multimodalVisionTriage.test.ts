import { describe, expect, it } from "bun:test";
import { CardSynthesizer } from "../src/cards/cardSynthesizer";
import { VisionAnalyzerService } from "../src/vision/visionAnalyzerService";

describe("📷 Multimodal Vision & Rich Cards Suite", () => {
  it("VisionAnalyzerService: 自动识别破损照片并生成定责评估", async () => {
    const res = await VisionAnalyzerService.analyzeImages(
      ["https://cdn.store.com/uploads/broken_shoes.jpg"],
      "鞋底脱胶开裂了，申请退货退款 ORD-77889",
    );

    expect(res).toBeDefined();
    expect(res.extractedOrderId).toBe("ORD-77889");
    expect(res.damageAssessment).toBeDefined();
    expect(res.damageAssessment?.damageLevel).toBeOneOf([
      "minor",
      "severe",
      "negligible",
    ]);
    expect(res.damageAssessment?.imageUrl).toBe(
      "https://cdn.store.com/uploads/broken_shoes.jpg",
    );
  });

  it("VisionAnalyzerService: 自动提取快递面单 OCR 运单号与脱敏 PII", async () => {
    const res = await VisionAnalyzerService.analyzeImages(
      ["https://cdn.store.com/uploads/shipping_label.png"],
      "这是我的快递面单 SF9876543210，我的电话 13812345678",
    );

    expect(res).toBeDefined();
    expect(res.extractedTrackingNumber).toBe("SF9876543210");
  });

  it("CardSynthesizer: 自动合成订单卡片、物流轨迹时间轴与退款核签卡", () => {
    const mockTaskPlan = {
      subtasks: [
        {
          id: "step_query",
          description: "Get order status for ORD-99001",
          status: "completed",
          result: {
            output: {
              orderId: "ORD-99001",
              status: "Delivered",
              totalAmount: 199.99,
              carrier: "SF Express",
              trackingNumber: "SF1002938475",
            },
          },
        },
        {
          id: "step_refund",
          description: "Process refund for ORD-99001",
          status: "completed",
          result: {
            output: {
              orderId: "ORD-99001",
              refundAmount: 199.99,
              reason: "Size mismatch",
              success: true,
            },
          },
        },
      ],
    };

    const cards = CardSynthesizer.synthesizeCards({
      taskPlan: mockTaskPlan,
      damageAssessment: {
        damageLevel: "minor",
        summary: "外包装明显挤压破损",
        confidence: 0.92,
        suggestedAction: "human_review",
        imageUrl: "https://example.com/dmg.jpg",
      },
    });

    expect(cards.length).toBeGreaterThanOrEqual(4);

    const damageCard = cards.find((c) => c.type === "damage_assessment");
    expect(damageCard).toBeDefined();
    expect(damageCard?.data.summary).toBe("外包装明显挤压破损");

    const orderCard = cards.find((c) => c.type === "order_card");
    expect(orderCard).toBeDefined();
    expect((orderCard?.data as any).orderId).toBe("ORD-99001");

    const timelineCard = cards.find((c) => c.type === "tracking_timeline");
    expect(timelineCard).toBeDefined();
    expect((timelineCard?.data as any).trackingNumber).toBe("SF1002938475");

    const refundCard = cards.find((c) => c.type === "refund_confirmation");
    expect(refundCard).toBeDefined();
    expect((refundCard?.data as any).refundAmount).toBe(199.99);

    const quickReplies = cards.find((c) => c.type === "quick_replies");
    expect(quickReplies).toBeDefined();
    expect((quickReplies?.data as any).options.length).toBeGreaterThan(0);
  });

  it("triageNode: 接收 imageUrls 并在 AgentState 中透传 damageAssessment", async () => {
    const { triageNode } = await import("../src/graph/nodes/triage.node");
    const threadId = `test_multimodal_triage_${Date.now()}`;

    const state = {
      threadId,
      userId: "test_user_multimodal",
      input: "鞋底完全断裂脱胶了，申请退款 ORD-88888",
      imageUrls: ["https://cdn.store.com/broken.jpg"],
      intents: [],
      globalTransitionsCount: 0,
      toolErrorsCount: 0,
    } as any;

    const res = await triageNode(state);
    expect(res.damageAssessment).toBeDefined();
    expect(res.damageAssessment?.damageLevel).toBeOneOf(["minor", "severe"]);
    expect(res.intents.some((i: any) => i.intent === "refund")).toBeTrue();
  });
});
