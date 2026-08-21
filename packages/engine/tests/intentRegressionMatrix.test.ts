import { describe, expect, test } from "bun:test";
import { db } from "db";
import { AgentIntentType } from "types";
import { CardSynthesizer } from "../src/cards/cardSynthesizer";
import { runAgent } from "../src/graph/buildGraph";
import { SlotExtractor } from "../src/graph/nodes/triage/slotExtractor";

describe("Comprehensive Intent & Multi-Tenant Regression Matrix", () => {
  describe("1. SlotExtractor Intent & Slot Matrix", () => {
    test("泛查单意图（我的订单、购买记录）不应索要 orderId", () => {
      const inputs = ["我的订单", "看看我买了啥", "我有哪些订单", "订单列表"];
      for (const input of inputs) {
        const res = SlotExtractor.extract(input);
        // 不应误匹配为缺 orderId 的 ORDER_QUERY
        expect(res.intentType).not.toBe(AgentIntentType.ORDER_QUERY);
        expect(res.missingSlots.length).toBe(0);
      }
    });

    test("缺槽位的改地址应精准识别缺失 slots", () => {
      const res = SlotExtractor.extract("我要改地址");
      expect(res.intentType).toBe(AgentIntentType.ORDER_MODIFY_ADDRESS);
      expect(res.missingSlots).toContain("orderId");
      expect(res.missingSlots).toContain("newAddress");
      expect(res.clarificationMessage).toBeDefined();
    });

    test("槽位完整的改地址应直接提取完成，无缺失槽位", () => {
      const res = SlotExtractor.extract(
        "把 ORD-ADIDAS-8899 改到北京市海淀区中关村南大街1号",
      );
      expect(res.intentType).toBe(AgentIntentType.ORDER_MODIFY_ADDRESS);
      expect(res.slots.orderId).toBe("ORD-ADIDAS-8899");
      expect(res.slots.newAddress).toContain("北京市海淀区");
      expect(res.missingSlots.length).toBe(0);
    });

    test("精确查物流/查订单应提取订单号", () => {
      const res = SlotExtractor.extract("查下 ORD-NIKE-7722 的物流");
      expect(res.intentType).toBe(AgentIntentType.ORDER_QUERY);
      expect(res.slots.orderId).toBe("ORD-NIKE-7722");
      expect(res.missingSlots.length).toBe(0);
    });
  });

  describe("2. Multi-Tenant Brand Awareness & Order Query in Adidas Store", () => {
    test("在 Adidas 店铺下提问'我的订单'应正常响应 Adidas 品牌且输出订单卡片", async () => {
      const threadId = `test_thread_adidas_${Date.now()}`;
      const userId = "usr_adidas_test_1001";
      const businessId = "adidas";

      await db.createThread(threadId, userId, businessId);

      const result = await runAgent(
        threadId,
        userId,
        "我的订单",
        `job_${Date.now()}`,
        undefined,
        businessId,
      );

      console.log("Adidas Store Result Output:", result.output);

      expect(result).toBeDefined();
      expect(result.output).toBeDefined();
      expect(result.output.length).toBeGreaterThan(0);

      // 验证不会将自己误判为 [ECOMMERCE] 并拒绝服务
      expect(result.output.includes("无法为您提供其他品牌")).toBe(false);
      expect(result.output.includes("[ECOMMERCE]")).toBe(false);

      // 验证生成了订单卡片
      const cards = CardSynthesizer.synthesizeCards({
        taskPlan: result.taskPlan,
      });
      expect(cards.some((c) => c.type === "order_card")).toBe(true);
    }, 30000);
  });
});
