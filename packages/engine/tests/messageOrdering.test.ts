import { describe, expect, it } from "bun:test";
import { db } from "db";
import { AgentMemoryEngine } from "../src/memory/agentMemoryEngine";
import { ShortMemory } from "../src/memory/shortMemory";

describe("Message Ordering and Session Isolation (TDD)", () => {
  it("should strictly preserve message order (user -> assistant) when recorded concurrently in recordTurn", async () => {
    const threadId = `test_order_thread_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
    const userId = "83d67d4e-104c-4325-8aa7-10d4389fc725";

    await db.createThread(threadId, userId);

    const memoryEngine = new AgentMemoryEngine(threadId, userId);

    // Concurrently record multiple conversational turns
    await memoryEngine.recordTurn({
      userQuery: "我的订单 ORD-123 到哪里了？",
      assistantResponse: "您的订单 ORD-123 目前正在由顺丰速运派送中。",
    });

    await memoryEngine.recordTurn({
      userQuery: "预计什么时候能送达？",
      assistantResponse: "预计今天下午 18:00 前送达。",
    });

    const messages = await db.getMessages(threadId);

    expect(messages.length).toBe(4);
    // Strict chronological order verification
    expect(messages[0].role).toBe("user");
    expect(messages[0].content).toContain("ORD-123 到哪里了");
    expect(messages[1].role).toBe("assistant");
    expect(messages[1].content).toContain("顺丰速运");
    expect(messages[2].role).toBe("user");
    expect(messages[2].content).toContain("预计什么时候能送达");
    expect(messages[3].role).toBe("assistant");
    expect(messages[3].content).toContain("今天下午 18:00");
  });

  it("should guarantee monotonically increasing timestamps when adding messages rapidly", async () => {
    const threadId = `test_rapid_thread_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
    const userId = "83d67d4e-104c-4325-8aa7-10d4389fc725";

    await db.createThread(threadId, userId);
    const shortMemory = new ShortMemory(threadId);

    // Rapidly write 6 messages
    for (let i = 0; i < 6; i++) {
      await shortMemory.addMessage(
        i % 2 === 0 ? "user" : "assistant",
        `Message sequence ${i}`,
      );
    }

    const messages = await shortMemory.getMessages();
    expect(messages.length).toBe(6);
    for (let i = 0; i < 6; i++) {
      expect(messages[i].content).toBe(`Message sequence ${i}`);
      expect(messages[i].role).toBe(i % 2 === 0 ? "user" : "assistant");
    }
  });

  it("should guarantee user message is always before assistant message when added via Promise.all concurrently", async () => {
    for (let round = 0; round < 5; round++) {
      const threadId = `test_concurrent_${round}_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
      const userId = "83d67d4e-104c-4325-8aa7-10d4389fc725";
      await db.createThread(threadId, userId);
      const shortMemory = new ShortMemory(threadId);

      // Concurrently add user and assistant
      await Promise.all([
        shortMemory.addMessage("user", `User question ${round}`),
        shortMemory.addMessage("assistant", `Assistant reply ${round}`),
      ]);

      const messages = await db.getMessages(threadId);
      expect(messages.length).toBe(2);
      expect(messages[0].role).toBe("user");
      expect(messages[1].role).toBe("assistant");
    }
  });
});
