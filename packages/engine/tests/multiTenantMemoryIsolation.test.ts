import { describe, expect, it } from "bun:test";
import { db } from "db";
import { OrderDomainService } from "tools";
import { EpisodicMemory, LongMemory, ShortMemory } from "../src/memory";

describe("🏢 Multi-Tenant Context & Memory Isolation Suite", () => {
  it("ShortMemory: 线程会话严格隔离且支持独立读写", async () => {
    const threadA = `test_tenant_thread_nike_${Date.now()}`;
    const threadB = `test_tenant_thread_adidas_${Date.now()}`;

    await db.createThread(threadA, "user_tenant_001", "nike");
    await db.createThread(threadB, "user_tenant_001", "adidas");

    const shortA = new ShortMemory(threadA);
    const shortB = new ShortMemory(threadB);

    await shortA.addMessage("user", "我想咨询耐克跑鞋");
    await shortA.addMessage("assistant", "您好，耐克跑鞋为您推荐飞马40。");

    await shortB.addMessage("user", "我想咨询阿迪达斯椰子");
    await shortB.addMessage("assistant", "您好，阿迪达斯推荐UB系列。");

    const msgsA = await shortA.getMessages();
    const msgsB = await shortB.getMessages();

    expect(msgsA.length).toBe(2);
    expect(msgsA[0].content).toContain("耐克");
    expect(msgsB.length).toBe(2);
    expect(msgsB[0].content).toContain("阿迪达斯");
  });

  it("createThread: 已存在线程不会被无意覆盖原有 business_id", async () => {
    const threadId = `test_persistent_thread_${Date.now()}`;
    const userId = "user_persistent_001";

    // 1. 初始化为 nike
    const created = await db.createThread(threadId, userId, "nike");
    expect(created.businessId).toBe("nike");

    // 2. 模拟后续消息调用 createThread 但未传递 businessId (默认 undefined)
    const reloaded = await db.createThread(threadId, userId);
    expect(reloaded.businessId).toBe("nike");

    // 3. 验证 OrderDomainService.getThreadSessionContext 读取该会话的 businessId
    const sessionCtx =
      await OrderDomainService.getThreadSessionContext(threadId);
    expect(sessionCtx.businessId).toBe("nike");
  });

  it("EpisodicMemory & LongMemory: 携带用户与商户租户隔离标识，防止未授权越权检索", async () => {
    const userA = `user_iso_a_${Date.now()}`;
    const userB = `user_iso_b_${Date.now()}`;

    const episodicA = new EpisodicMemory(userA, "nike");
    const episodicB = new EpisodicMemory(userB, "adidas");

    await episodicA.addEvent("用户喜欢耐克暗黑系穿搭", 8);

    const retrievedA = await episodicA.retrieveEvents(
      "用户喜欢耐克暗黑系穿搭",
      5,
    );
    const retrievedB = await episodicB.retrieveEvents(
      "用户喜欢耐克暗黑系穿搭",
      5,
    );

    expect(retrievedA.length).toBeGreaterThanOrEqual(1);
    expect(retrievedB.length).toBe(0); // userB 绝对隔离，不可检索到 userA 的记忆

    // 空 userId 防御
    const episodicEmpty = new EpisodicMemory("", "ecommerce");
    const emptyEvents = await episodicEmpty.retrieveEvents("任何偏好");
    expect(emptyEvents).toEqual([]);

    const longEmpty = new LongMemory("", "ecommerce");
    const emptyFacts = await longEmpty.searchRelevantFacts("任何偏好");
    expect(emptyFacts).toEqual([]);
  });
});
