import { describe, expect, it } from "bun:test";
import { ConversationRepository } from "db";

describe("Chat History Recovery by User and Thread", () => {
  it("should recover previous chat messages for CUST-8801 even if a new browser/fresh thread opens", async () => {
    // 1. First ensure there is an existing conversation in DB for CUST-8801
    const testThreadId = `merchant_thread_CUST-8801_aurora_${Date.now()}`;
    await ConversationRepository.appendMessage({
      threadId: testThreadId,
      businessId: "aurora",
      userId: "CUST-8801",
      role: "user",
      content: "你好，我是张伟，请问我的退款进度如何？",
    });
    await ConversationRepository.appendMessage({
      threadId: testThreadId,
      businessId: "aurora",
      userId: "CUST-8801",
      role: "assistant",
      content: "您好张伟先生，已为您核实到退款正在原路退回中。",
    });

    // 2. Query conversation messages via userId without knowing the exact new timestamp threadId
    const res = await fetch(
      `http://localhost:3005/api/store/chat/messages?userId=CUST-8801&tenantId=aurora`,
    );
    // Or test the underlying API handler / repository
    const listRes = await ConversationRepository.listConversations({
      businessId: "aurora",
      limit: 10,
      offset: 0,
    });

    // Find thread for CUST-8801
    const found = listRes.items.find(
      (item) =>
        item.userId === "CUST-8801" || item.threadId.includes("CUST-8801"),
    );
    expect(found).toBeDefined();
    expect(found?.threadId).toBe(testThreadId);

    const timeline = await ConversationRepository.getConversationTimeline(
      testThreadId,
      "aurora",
    );
    expect(timeline?.messages.length).toBeGreaterThanOrEqual(2);
    expect(timeline?.messages[0].content).toContain("张伟");
  });
});
