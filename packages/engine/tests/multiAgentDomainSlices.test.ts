import { describe, expect, it } from "bun:test";
import {
  CartManageSkill,
  OrderAddressModificationSkill,
  OrderRefundSkill,
  ShoppingGuideSkill,
  SkillRegistry,
} from "../src/skills";

describe("Multi-Agent Domain Slices & Cross-Agent Handoff Test Suite", () => {
  it("Shopping Guide Agent: should clarify vague preferences and return structured recommendations with guideContext", async () => {
    const guideSkill = new ShoppingGuideSkill();

    // 1. 模糊意图多轮澄清
    const vagueRes = await guideSkill.execute({
      threadId: "thread_guide_1",
      tenantId: "ecommerce",
      userId: "user_test_1",
      input: "买鞋",
      slots: { activeIntent: "shopping_guide" },
    });

    expect(vagueRes.success).toBe(true);
    expect(vagueRes.output).toContain("专属选品顾问");
    expect(vagueRes.extra?.guideContext).toBeDefined();
    expect(vagueRes.extra?.guideContext?.clarificationRound).toBe(1);

    // 2. 具体需求搜索推荐并生成候选商品集
    const searchRes = await guideSkill.execute({
      threadId: "thread_guide_1",
      tenantId: "ecommerce",
      userId: "user_test_1",
      input: "推荐一款男士透气缓震跑步鞋，预算800以内",
      slots: { activeIntent: "shopping_guide" },
      extra: {
        guideContext: vagueRes.extra?.guideContext,
      },
    });

    expect(searchRes.success).toBe(true);
    expect(searchRes.cards?.length).toBeGreaterThan(0);
    expect(searchRes.cards?.[0].type).toBe("product_recommendation");
    expect(
      searchRes.extra?.guideContext?.candidateProductIds?.length,
    ).toBeGreaterThan(0);
  });

  it("Cart & Checkout Agent: should support cross-agent coreference resolution using candidateProductIds", async () => {
    const cartSkill = new CartManageSkill();

    // 导购 Agent 遗留给状态总线的候选商品 ID
    const mockGuideContext = {
      candidateProductIds: [
        "prod_nike_air_pegasus_41",
        "prod_nike_invincible_3",
        "prod_nike_vaporfly_3",
      ],
      extractedPreferences: { gender: "男款", feature: "透气" },
    };

    // 用户跨 Agent 指代消解："把第2件加入购物车"
    const addRes = await cartSkill.execute({
      threadId: "thread_cart_1",
      tenantId: "ecommerce",
      userId: "user_test_2",
      input: "把第2件加入购物车，买2件",
      slots: { activeIntent: "cart_manage" },
      extra: {
        guideContext: mockGuideContext,
      },
    });

    expect(addRes.success).toBe(true);
    expect(addRes.output).toContain("prod_nike_invincible_3");
    expect(addRes.cards?.length).toBe(1);
    expect(addRes.cards?.[0].type).toBe("order_status");
    expect(addRes.extra?.cartContext?.lastModifiedItemId).toBe(
      "prod_nike_invincible_3",
    );

    // 查看购物车与结算
    const summaryRes = await cartSkill.execute({
      threadId: "thread_cart_1",
      tenantId: "ecommerce",
      userId: "user_test_2",
      input: "看下购物车总价",
      slots: { activeIntent: "cart_manage" },
      extra: {
        cartContext: addRes.extra?.cartContext,
      },
    });

    expect(summaryRes.success).toBe(true);
    expect(summaryRes.output).toContain("购物车目前共有");
    expect(summaryRes.output).toContain("实付预估");
  });

  it("Order & Service Agent: should maintain orderContext and trigger HITL when refund exceeds threshold", async () => {
    const refundSkill = new OrderRefundSkill();

    const refundRes = await refundSkill.execute({
      threadId: "thread_order_1",
      tenantId: "ecommerce",
      userId: "user_test_3",
      input: "订单 ORD-98712 申请退款",
      slots: {
        activeIntent: "refund",
        orderId: "ORD-98712",
        refundAmount: 899,
      },
    });

    expect(refundRes.success).toBe(true);
    expect(refundRes.nextAction).toBe("require_approval");
    expect(refundRes.extra?.orderContext?.targetOrderId).toBe("ORD-98712");
    expect(refundRes.extra?.orderContext?.actionType).toBe("refund");
  });
});
