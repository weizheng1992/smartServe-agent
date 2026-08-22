import { describe, expect, test } from "bun:test";
import { db } from "db";
import { AgentIntentType } from "types";
import { CardSynthesizer } from "../src/cards/cardSynthesizer";
import { runAgent } from "../src/graph/buildGraph";
import { plannerNode } from "../src/graph/nodes/planner.node";
import { triageNode } from "../src/graph/nodes/triage.node";
import { SlotExtractor } from "../src/graph/nodes/triage/slotExtractor";
import type { AgentStateAnnotation } from "../src/graph/state";

describe("全场景全方位电商客服意图与业务闭环测试矩阵 (Comprehensive Matrix)", () => {
  describe("1. 槽位提取与意图识别全覆盖 (Slot Extraction & Disambiguation)", () => {
    test("【查订单/泛查单】不应索要订单号，直接走 listUserOrders", () => {
      const inputs = [
        "我的订单",
        "看看我买了啥",
        "我有哪些订单",
        "订单列表",
        "历史购买记录",
        "查下我买的东西",
      ];
      for (const input of inputs) {
        const res = SlotExtractor.extract(input);
        expect(res.intentType).not.toBe(AgentIntentType.ORDER_QUERY);
        expect(res.missingSlots.length).toBe(0);
      }
    });

    test("【物流查询】包含单号时精准提取 orderId，无单号时追问", () => {
      // 包含单号
      const withId = SlotExtractor.extract("查下 ORD-NIKE-7722 的物流到哪了");
      expect(withId.intentType).toBe(AgentIntentType.ORDER_QUERY);
      expect(withId.slots.orderId).toBe("ORD-NIKE-7722");
      expect(withId.missingSlots.length).toBe(0);

      // 无单号
      const withoutId = SlotExtractor.extract("我的快递到哪了？发货了吗");
      expect(withoutId.intentType).toBe(AgentIntentType.ORDER_QUERY);
      expect(withoutId.missingSlots).toContain("orderId");
      expect(withoutId.clarificationMessage).toContain("订单");
    });

    test("【修改地址】全缺槽位 / 部分缺失 / 完整指令三级状态机", () => {
      // 1. 全缺槽位
      const allMissing = SlotExtractor.extract("我要修改收货地址");
      expect(allMissing.intentType).toBe(AgentIntentType.ORDER_MODIFY_ADDRESS);
      expect(allMissing.missingSlots).toContain("orderId");
      expect(allMissing.missingSlots).toContain("newAddress");

      // 2. 缺新地址
      const missingAddr = SlotExtractor.extract(
        "把订单 ORD-998877 改一下收货地址",
      );
      expect(missingAddr.intentType).toBe(AgentIntentType.ORDER_MODIFY_ADDRESS);
      expect(missingAddr.slots.orderId).toBe("ORD-998877");
      expect(missingAddr.missingSlots).toContain("newAddress");

      // 3. 完整指令（多种动词连接词：改到/改成/送至/送往/改派）
      const patterns = [
        "把 ORD-ADIDAS-8899 改到北京市海淀区中关村南大街1号",
        "订单 ORD-ADIDAS-8899 改成上海市浦东新区张江高科技园区",
        "把单子 ORD-ADIDAS-8899 送至广州市天河区珠江新城冼村路",
        "请将 ORD-ADIDAS-8899 改派到深圳市南山区科技园南区",
      ];
      for (const p of patterns) {
        const full = SlotExtractor.extract(p);
        expect(full.intentType).toBe(AgentIntentType.ORDER_MODIFY_ADDRESS);
        expect(full.slots.orderId).toBe("ORD-ADIDAS-8899");
        expect(full.slots.newAddress).toBeDefined();
        expect(full.slots.newAddress!.length).toBeGreaterThan(3);
        expect(full.missingSlots.length).toBe(0);
      }
    });

    test("【退货与退款】有单号直接流转，无单号精准追问", () => {
      // 缺单号
      const noId = SlotExtractor.extract("我想申请退货退款");
      expect(noId.intentType).toBe(AgentIntentType.ORDER_RETURN);
      expect(noId.missingSlots).toContain("orderId");

      // 有单号
      const hasId = SlotExtractor.extract(
        "订单 ORD-889901 我不想要了，帮我退款",
      );
      expect(hasId.intentType).toBe(AgentIntentType.ORDER_RETURN);
      expect(hasId.slots.orderId).toBe("ORD-889901");
      expect(hasId.missingSlots.length).toBe(0);
    });

    test("【取消订单】待发货取消意图与单号解析", () => {
      const cancelWithId = SlotExtractor.extract(
        "帮我取消订单 ORD-ECOM-889901",
      );
      expect(cancelWithId.intentType).toBe(AgentIntentType.ORDER_CANCEL);
      expect(cancelWithId.slots.orderId).toBe("ORD-ECOM-889901");
      expect(cancelWithId.missingSlots.length).toBe(0);

      const cancelNoId = SlotExtractor.extract("我不想要了，帮我取消订单");
      expect(cancelNoId.intentType).toBe(AgentIntentType.ORDER_CANCEL);
      expect(cancelNoId.missingSlots).toContain("orderId");
    });
  });

  describe("2. 多意图与复合指令 DAG 规划 (Multi-Intent Composite Planning)", () => {
    test("查物流 + 申请退款 双意图应生成对应两个子任务", async () => {
      const threadId = `test_thread_multi_${Date.now()}`;
      const state = {
        threadId,
        input:
          "我想看看我买的跑鞋 ORD-98712 到了没，顺便我想把上一笔订单申请退款了",
        intents: [
          { intent: "order_status", confidence: 1.0 },
          { intent: "refund", confidence: 1.0 },
        ],
        slots: { orderId: "ORD-98712" },
        globalTransitionsCount: 0,
        toolErrorsCount: 0,
      } as unknown as typeof AgentStateAnnotation.State;

      const planRes = await plannerNode(state);
      expect(planRes.taskPlan).toBeDefined();
      expect(planRes.taskPlan?.subtasks?.length).toBe(2);

      const toolDescriptions =
        planRes.taskPlan?.subtasks?.map((s) => s.description.toLowerCase()) ||
        [];
      expect(
        toolDescriptions.some(
          (d) => d.includes("getorderstatus") || d.includes("status"),
        ),
      ).toBe(true);
      expect(
        toolDescriptions.some(
          (d) => d.includes("processrefund") || d.includes("refund"),
        ),
      ).toBe(true);
    });
  });

  describe("3. 多租户品牌隔离与自识别问单 (Multi-Tenant Isolation Matrix)", () => {
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
    }, 300000);

    test("在 Nike 官方专营店提问'我的订单'应正确展示专属客服身份", async () => {
      const threadId = `test_thread_nike_${Date.now()}`;
      const userId = "usr_nike_test_1002";
      const businessId = "nike";

      await db.createThread(threadId, userId, businessId);

      const result = await runAgent(
        threadId,
        userId,
        "我的订单",
        `job_${Date.now()}`,
        undefined,
        businessId,
      );

      expect(result).toBeDefined();
      expect(result.output).toBeDefined();
      expect(result.output.includes("[ECOMMERCE]")).toBe(false);
      expect(result.output.includes("无法为您提供其他品牌")).toBe(false);
    }, 300000);
  });
});
