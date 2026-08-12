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
});
