import { describe, expect, it } from "bun:test";
import { ConversationRepository } from "db";
import { NextRequest } from "next/server";
import { POST as postApprovalsRoute } from "../app/api/admin/approvals/route";
import { GET as getStoreChatMessagesRoute } from "../app/api/store/chat/messages/route";
import { POST as postStoreChatRoute } from "../app/api/store/chat/route";

describe("🧪 TDD: Merchant Storefront Chat History & Live Desk Takeover Sync", () => {
  const tenantId = "aurora";
  const testUserId = `CUST_TDD_${Date.now()}`;
  const testThreadId = `thread_tdd_${Date.now()}`;

  it("1. [Red -> Green] 客户端发送第一条消息后，应自动创建会话并持久化 threadId 与消息记录", async () => {
    const sendReq = new NextRequest("http://localhost:3005/api/store/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "我想查一下我最近的订单物流",
        userId: testUserId,
        threadId: testThreadId,
        businessId: tenantId,
      }),
    });

    const sendRes = await postStoreChatRoute(sendReq);
    expect(sendRes.status).toBe(200);
    const sendJson = await sendRes.json();
    expect(sendJson.success).toBe(true);
    expect(sendJson.threadId).toBe(testThreadId);

    // 验证数据库物理持久化
    const timeline = await ConversationRepository.getConversationTimeline(
      testThreadId,
      tenantId,
    );
    expect(timeline).toBeDefined();
    expect(timeline?.messages.length).toBeGreaterThanOrEqual(1);
    expect(timeline?.messages[0].content).toContain(
      "我想查一下我最近的订单物流",
    );
  }, 30000);

  it("2. [Red -> Green] 同一用户在新窗口/刷新页面打开时，应能通过 userId/threadId 恢复完整的历史对话记录", async () => {
    // 模拟新打开网页或刷新，通过 userId 或 threadId 查询消息历史
    const getHistoryReq = new NextRequest(
      `http://localhost:3005/api/store/chat/messages?userId=${testUserId}&threadId=${testThreadId}&businessId=${tenantId}`,
    );
    const historyRes = await getStoreChatMessagesRoute(getHistoryReq);
    expect(historyRes.status).toBe(200);

    const historyJson = await historyRes.json();
    expect(historyJson.success).toBe(true);
    expect(historyJson.threadId).toBe(testThreadId);
    expect(Array.isArray(historyJson.messages)).toBe(true);
    expect(historyJson.messages.length).toBeGreaterThanOrEqual(1);
    expect(historyJson.messages[0].role).toBe("user");
  }, 30000);

  it("3. [Red -> Green] 管理员在 Admin 后台发送人工回复后，商城客户端应能同步拉取到人工客服消息", async () => {
    // 1. 管理员发起接管并回复
    const takeoverReq = new NextRequest(
      "http://localhost:3005/api/admin/approvals",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          threadId: testThreadId,
          action: "start_human_takeover",
        }),
      },
    );
    const takeoverRes = await postApprovalsRoute(takeoverReq);
    const takeoverJson = await takeoverRes.json();
    expect(takeoverJson.success).toBe(true);

    const replyText =
      "您好！我是极光潮品人工客服主管，已为您核实到物流正在派送中。";
    const adminReplyReq = new NextRequest(
      "http://localhost:3005/api/admin/approvals",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          approvalId: takeoverJson.approvalId,
          threadId: testThreadId,
          action: "human_message",
          humanReply: replyText,
        }),
      },
    );
    const adminReplyRes = await postApprovalsRoute(adminReplyReq);
    expect(adminReplyRes.status).toBe(200);

    // 2. 商城客户端轮询同步消息
    const clientSyncReq = new NextRequest(
      `http://localhost:3005/api/store/chat/messages?threadId=${testThreadId}&businessId=${tenantId}`,
    );
    const clientSyncRes = await getStoreChatMessagesRoute(clientSyncReq);
    const clientSyncJson = await clientSyncRes.json();

    expect(clientSyncJson.success).toBe(true);
    const msgs = clientSyncJson.messages;
    const humanMsg = msgs.find((m: any) => m.content.includes(replyText));
    expect(humanMsg).toBeDefined();
    expect(humanMsg.role).toBe("assistant");
  }, 30000);

  it("4. [Red -> Green] 发送'你好'问候语后，消息历史中不应产生重复的用户消息记录 (用户只发了1次'你好')", async () => {
    const greetingThreadId = `thread_greeting_${Date.now()}`;
    const sendGreetingReq = new NextRequest(
      "http://localhost:3005/api/store/chat",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: "你好",
          userId: testUserId,
          threadId: greetingThreadId,
          businessId: tenantId,
        }),
      },
    );

    const sendRes = await postStoreChatRoute(sendGreetingReq);
    expect(sendRes.status).toBe(200);

    const historyReq = new NextRequest(
      `http://localhost:3005/api/store/chat/messages?threadId=${greetingThreadId}&businessId=${tenantId}`,
    );
    const historyRes = await getStoreChatMessagesRoute(historyReq);
    const historyJson = await historyRes.json();

    expect(historyJson.success).toBe(true);
    const userMessages = historyJson.messages.filter(
      (m: any) => m.role === "user" && m.content === "你好",
    );
    // 严格断言：用户发送1次"你好"，历史记录里应该恰好有且仅有1条"你好"
    expect(userMessages.length).toBe(1);
  }, 30000);

  it("5. [Red -> Green] 模拟用户在极光商城中刷新页面，通过 threadId 与 tenantId 拉取历史记录应保证数据不丢失且正确呈现", async () => {
    const refreshThreadId = `merchant_thread_CUST-8801_aurora_${Date.now()}`;
    // 1. 发送第一轮打招呼
    const sendReq1 = new NextRequest("http://localhost:3005/api/store/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "你好",
        userId: "CUST-8801",
        threadId: refreshThreadId,
        businessId: "aurora",
      }),
    });
    const res1 = await postStoreChatRoute(sendReq1);
    expect(res1.status).toBe(200);

    // 2. 模拟页面刷新重新获取消息历史
    const refreshReq = new NextRequest(
      `http://localhost:3005/api/store/chat/messages?threadId=${refreshThreadId}&tenantId=aurora`,
    );
    const refreshRes = await getStoreChatMessagesRoute(refreshReq);
    expect(refreshRes.status).toBe(200);
    const refreshJson = await refreshRes.json();
    expect(refreshJson.success).toBe(true);
    expect(refreshJson.messages.length).toBeGreaterThanOrEqual(2);
    expect(refreshJson.messages[0].content).toBe("你好");
    expect(refreshJson.messages[1].role).toBe("assistant");
  }, 30000);

  it("6. [Red -> Green] 即使租户下存在大量其他会话，指定 userId 查询时仍能准确检索到该用户的历史会话列表", async () => {
    const customUser = `CUST_MULTI_${Date.now()}`;
    const customThread = `merchant_thread_${customUser}_aurora_${Date.now()}`;

    // 1. 创建该用户的真实会话
    await ConversationRepository.appendMessage({
      threadId: customThread,
      businessId: "aurora",
      userId: customUser,
      role: "user",
      content: "昨天的订单发货了吗？",
    });
    await ConversationRepository.appendMessage({
      threadId: customThread,
      businessId: "aurora",
      userId: customUser,
      role: "assistant",
      content: "已为您查询，订单正在顺丰陆运中。",
    });

    // 2. 模拟并发产生 60 个其他无关用户的会话（模拟真实商户海量历史会话场景）
    for (let i = 0; i < 60; i++) {
      const otherThread = `other_noise_thread_${Date.now()}_${i}`;
      await ConversationRepository.appendMessage({
        threadId: otherThread,
        businessId: "aurora",
        userId: `other_user_${i}`,
        role: "user",
        content: `噪音消息测试 ${i}`,
      });
    }

    // 3. 按当前用户 userId 请求列表
    const queryReq = new NextRequest(
      `http://localhost:3005/api/store/chat/messages?userId=${customUser}&tenantId=aurora`,
    );
    const queryRes = await getStoreChatMessagesRoute(queryReq);
    expect(queryRes.status).toBe(200);
    const queryJson = await queryRes.json();

    expect(queryJson.success).toBe(true);
    expect(Array.isArray(queryJson.userThreads)).toBe(true);
    // 必须能检索到该用户的历史会话，不受其他 60 个会话挤占截断影响
    const matchedThread = queryJson.userThreads.find(
      (t: any) => t.threadId === customThread,
    );
    expect(matchedThread).toBeDefined();
    expect(matchedThread.lastMessageSnippet).toContain("已为您查询");
  }, 30000);
});
