import { describe, expect, it } from "bun:test";
import { ConversationRepository } from "db";
import { GET } from "../app/api/store/chat/messages/route";
import { NextRequest } from "next/server";

describe("New Thread Creation Isolation", () => {
  it("should return empty messages for a newly created thread without hijacking back to old thread", async () => {
    // 1. Seed an old thread with messages for CUST-8801
    const oldThreadId = `merchant_thread_CUST-8801_aurora_old_${Date.now()}`;
    await ConversationRepository.appendMessage({
      threadId: oldThreadId,
      businessId: "aurora",
      userId: "CUST-8801",
      role: "user",
      content: "你好，我是张伟，请问我的退款进度如何？",
    });
    await ConversationRepository.appendMessage({
      threadId: oldThreadId,
      businessId: "aurora",
      userId: "CUST-8801",
      role: "assistant",
      content: "您好张伟先生，已为您核实到退款正在原路退回中。",
    });

    // 2. Simulate user creating a brand new thread
    const newThreadId = `merchant_thread_CUST-8801_aurora_new_${Date.now()}`;
    const req = new NextRequest(
      `http://localhost:3005/api/store/chat/messages?threadId=${newThreadId}&userId=CUST-8801&tenantId=aurora`,
    );

    const res = await GET(req);
    const data = await res.json();

    // 3. Expected: the response MUST preserve newThreadId and return empty messages, NOT oldThreadId
    expect(data.success).toBe(true);
    expect(data.threadId).toBe(newThreadId);
    expect(data.messages).toEqual([]);
  });
});
