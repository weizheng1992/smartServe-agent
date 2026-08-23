import { describe, expect, test } from "bun:test";
import { ApprovalService } from "./approvalService";
import { ChatSessionService } from "./chatSessionService";

describe("API Domain Services Unit Tests", () => {
  describe("ChatSessionService", () => {
    test("Should reject request if message, threadId or userId is missing", async () => {
      const resNoMsg = await ChatSessionService.dispatchChatRequest({});
      expect(resNoMsg.error).toBe("Message is required");
      expect(resNoMsg.statusCode).toBe(400);

      const resNoThread = await ChatSessionService.dispatchChatRequest({
        message: "hello",
      });
      expect(resNoThread.error).toBe("threadId is strictly required");

      const resNoUser = await ChatSessionService.dispatchChatRequest({
        message: "hello",
        threadId: "t_123",
      });
      expect(resNoUser.error).toBe("userId is strictly required");
    });

    test("Should successfully dispatch valid chat request", async () => {
      const result = await ChatSessionService.dispatchChatRequest({
        message: "查询我的最近订单状态",
        threadId: "t_test_service_001",
        userId: "u_test_service_001",
      });

      expect(result.success).toBe(true);
      expect(result.threadId).toBe("t_test_service_001");
      expect(result.jobId).toBeDefined();
    });
  });

  describe("ApprovalService", () => {
    test("Should start human takeover session successfully", async () => {
      const { db } = await import("db");
      await db.createThread("t_takeover_test_001", "u_test_service_001");

      const result = await ApprovalService.processApprovalAction({
        action: "start_human_takeover",
        threadId: "t_takeover_test_001",
      });

      expect(result.success).toBe(true);
      expect(result.approvalId).toBeDefined();
      expect(result.approval).toBeDefined();
    });

    test("Should validate missing approvalId or action", async () => {
      const result = await ApprovalService.processApprovalAction({});
      expect(result.error).toBe("approvalId and action are required");
      expect(result.statusCode).toBe(400);
    });
  });

  describe("OrderHistory API Route", () => {
    test("Should query user purchase history via /api/chat/orders", async () => {
      const { GET } = await import("../orders/route");
      const { NextRequest } = await import("next/server");
      const { db } = await import("db");
      const { OrderDomainService } = await import("tools");

      const testUser = await db.findOrCreateUserByEmail(
        "api_order_test@example.com",
      );
      const orderId = `ORD-API-${Date.now().toString().slice(-5)}`;
      await OrderDomainService.createOrder({
        orderId,
        userId: testUser.id,
        businessId: "nike",
        totalAmount: 1299.0,
        carrier: "顺丰速运",
      });

      const req = new NextRequest(
        `http://localhost:3000/api/chat/orders?userId=${encodeURIComponent(testUser.id)}&businessId=nike`,
      );
      const res = await GET(req);
      const json = await res.json();

      expect(json.success).toBe(true);
      expect(Array.isArray(json.orders)).toBe(true);
      expect(json.orders.some((o: any) => o.orderId === orderId)).toBe(true);
    });
  });
});
