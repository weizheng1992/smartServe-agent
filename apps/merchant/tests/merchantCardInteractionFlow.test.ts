import { describe, expect, it } from "bun:test";
import { NextRequest } from "next/server";
import { POST as postStoreChatRoute } from "../app/api/store/chat/route";
import { GET as getStoreChatMessagesRoute } from "../app/api/store/chat/messages/route";

describe("🃏 Merchant Order Card Selection & Card Action Simulation Suite", () => {
  const tenantId = "aurora";
  const testUserId = "CUST-8801";
  const testThreadId = `merchant_thread_card_sim_${Date.now()}`;

  it("1. 模拟用户提问【查询我的全部订单】，AI 成功返回订单列表与结构化卡片", async () => {
    const req = new NextRequest("http://localhost:3005/api/store/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "查询我的全部订单",
        userId: testUserId,
        threadId: testThreadId,
        businessId: tenantId,
      }),
    });

    const res = await postStoreChatRoute(req);
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.success).toBe(true);
    expect(json.output).toBeDefined();

    // 验证返回了多模态卡片 (order_picker 或 order_card)
    expect(Array.isArray(json.cards)).toBe(true);
    expect(json.cards.length).toBeGreaterThanOrEqual(1);
    const hasOrderCard = json.cards.some(
      (c: any) => c.type === "order_picker" || c.type === "order_card",
    );
    expect(hasOrderCard).toBe(true);
  }, 40000);

  it("2. 模拟用户在卡片中点击【选择此订单】，触发精准选单查询", async () => {
    const selectedOrderId = "AURORA-ORD-2026-9081";
    const req = new NextRequest("http://localhost:3005/api/store/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: `已选定订单 ${selectedOrderId}，请帮我查询该订单的具体信息和最新物流进度。`,
        userId: testUserId,
        threadId: testThreadId,
        businessId: tenantId,
      }),
    });

    const res = await postStoreChatRoute(req);
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.success).toBe(true);
    expect(json.output).toContain("AURORA-ORD-2026-9081");

    // 验证物理持久化消息流中包含订单信息
    const historyReq = new NextRequest(
      `http://localhost:3005/api/store/chat/messages?threadId=${testThreadId}&tenantId=${tenantId}&userId=${testUserId}`,
    );
    const historyRes = await getStoreChatMessagesRoute(historyReq);
    const historyJson = await historyRes.json();
    expect(historyJson.success).toBe(true);
    expect(historyJson.messages.length).toBeGreaterThanOrEqual(2);
  }, 60000);

  it("3. 模拟点击卡片动作【查看物流轨迹】，触发物流详情与追踪", async () => {
    const req = new NextRequest("http://localhost:3005/api/store/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "帮我查一下订单 AURORA-ORD-2026-9081 的物流轨迹",
        userId: testUserId,
        threadId: testThreadId,
        businessId: tenantId,
      }),
    });

    const res = await postStoreChatRoute(req);
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.success).toBe(true);
    expect(json.output).toBeDefined();
    expect(json.output.length).toBeGreaterThan(0);
  }, 60000);
});
