import { describe, expect, it } from "bun:test";
import { ConversationRepository } from "db";
import { NextRequest } from "next/server";
import { GET as getStoreChatMessagesRoute } from "../app/api/store/chat/messages/route";
import { POST as postStoreChatRoute } from "../app/api/store/chat/route";

describe("🧪 TDD: Merchant Route Switch Chat Persistence & Pull-Down History Loading", () => {
  const tenantId = "aurora";
  const testUserId = `CUST_PULL_${Date.now()}`;
  const thread1 = `merchant_thread_${testUserId}_aurora_1001`;
  const thread2 = `merchant_thread_${testUserId}_aurora_1002`;

  it("1. [Red -> Green] 模拟用户在第一个页面发起对话，切换路由或新会话后，历史会话能按用户全量回溯", async () => {
    // 1. 在 thread1 发送消息（模拟在首页对话）
    await ConversationRepository.appendMessage({
      threadId: thread1,
      businessId: tenantId,
      userId: testUserId,
      role: "user",
      content: "你好，我想看看有没有优惠券？",
    });
    await ConversationRepository.appendMessage({
      threadId: thread1,
      businessId: tenantId,
      userId: testUserId,
      role: "assistant",
      content: "您好！当前全场满300减30，可在结算时自动抵扣。",
    });

    // 2. 在 thread2 发送消息（模拟在购物车页面发起新对话）
    await ConversationRepository.appendMessage({
      threadId: thread2,
      businessId: tenantId,
      userId: testUserId,
      role: "user",
      content: "这件外套支持7天无理由退货吗？",
    });
    await ConversationRepository.appendMessage({
      threadId: thread2,
      businessId: tenantId,
      userId: testUserId,
      role: "assistant",
      content: "是的，只要吊牌完整未拆封，支持7天无理由退货。",
    });

    // 3. 用户切换路由或拉取最新会话，服务端应能自动返回最新活跃会话 (thread2)
    const latestReq = new NextRequest(
      `http://localhost:3005/api/store/chat/messages?userId=${testUserId}&tenantId=${tenantId}`,
    );
    const latestRes = await getStoreChatMessagesRoute(latestReq);
    expect(latestRes.status).toBe(200);
    const latestJson = await latestRes.json();

    expect(latestJson.success).toBe(true);
    expect(latestJson.userThreads.length).toBeGreaterThanOrEqual(2);
    expect(latestJson.threadId).toBe(thread2);
    expect(latestJson.messages.length).toBe(2);
    expect(latestJson.messages[0].content).toContain("支持7天无理由退货");
  }, 30000);

  it("2. [Red -> Green] 支持在当前会话中下拉/加载更早的完整历史会话流 (all_history=true / load_older)", async () => {
    // 请求合并拉取该用户的所有历史会话消息 (包含 thread1 和 thread2)
    const allReq = new NextRequest(
      `http://localhost:3005/api/store/chat/messages?userId=${testUserId}&tenantId=${tenantId}&includeOlder=true`,
    );
    const allRes = await getStoreChatMessagesRoute(allReq);
    expect(allRes.status).toBe(200);
    const allJson = await allRes.json();

    expect(allJson.success).toBe(true);
    expect(allJson.allHistoricalMessages).toBeDefined();
    expect(Array.isArray(allJson.allHistoricalMessages)).toBe(true);
    // 应该包含 thread1 和 thread2 的全部消息 (至少 4 条)
    expect(allJson.allHistoricalMessages.length).toBeGreaterThanOrEqual(4);

    const hasCouponMsg = allJson.allHistoricalMessages.some((m: any) =>
      m.content.includes("优惠券"),
    );
    const hasReturnMsg = allJson.allHistoricalMessages.some((m: any) =>
      m.content.includes("7天无理由"),
    );
    expect(hasCouponMsg).toBe(true);
    expect(hasReturnMsg).toBe(true);
  }, 30000);
});
