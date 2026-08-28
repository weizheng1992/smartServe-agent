import { describe, expect, test } from "bun:test";
import { CardSynthesizer } from "../src/cards/cardSynthesizer";
import type { TaskPlan } from "types";

describe("CardSynthesizer & Streaming Hydration Unit Tests", () => {
  test("Should synthesize skeleton cards for streaming initial phase", () => {
    const taskPlan: TaskPlan = {
      goal: "Query order status and refund process",
      currentStepIndex: 0,
      subtasks: [
        {
          id: "step_order_query",
          description: "Get order status",
          status: "pending",
        },
        {
          id: "step_refund_flow",
          description: "Initiate refund step",
          status: "pending",
        },
      ],
    };

    const skeletons = CardSynthesizer.synthesizeSkeletonCards({ taskPlan });
    expect(skeletons.length).toBeGreaterThanOrEqual(2);
    expect(skeletons[0].hydrationState).toBe("skeleton");
    expect(skeletons[0].type).toBe("order_card");
    expect(skeletons[1].type).toBe("step_progress");
  });

  test("Should synthesize StepProgressCard when subtask produces stepProgress data", () => {
    const taskPlan: TaskPlan = {
      goal: "Track return shipment and inspection",
      currentStepIndex: 1,
      subtasks: [
        {
          id: "step_return_tracking",
          description: "Track return shipment",
          status: "completed",
          result: {
            orderId: "ORD-ECO-9988",
            stepProgress: {
              ticketId: "TICK-RET-1001",
              orderId: "ORD-ECO-9988",
              title: "售后退货换货多步流转",
              currentStep: 1,
              totalSteps: 4,
              steps: [
                {
                  stepIndex: 0,
                  title: "申请退货",
                  description: "买家发起退货换货申请",
                  status: "completed",
                },
                {
                  stepIndex: 1,
                  title: "填写寄件单号",
                  description: "请将商品寄回指定仓库并填写快递单号",
                  status: "current",
                  actionRequired: {
                    actionType: "input_text",
                    placeholder: "请输入顺丰或圆通等寄回单号...",
                    submitAction: "submit_return_tracking",
                    buttonLabel: "提交单号",
                  },
                },
                {
                  stepIndex: 2,
                  title: "仓库质检验货",
                  description: "仓库签收后进行品质成色核验",
                  status: "upcoming",
                },
                {
                  stepIndex: 3,
                  title: "退款到账",
                  description: "原路返还原支付账户",
                  status: "upcoming",
                },
              ],
            },
          },
        },
      ],
    };

    const cards = CardSynthesizer.synthesizeCards({ taskPlan });
    const stepCard = cards.find((c) => c.type === "step_progress");
    expect(stepCard).toBeDefined();
    if (stepCard && stepCard.type === "step_progress") {
      expect(stepCard.data.ticketId).toBe("TICK-RET-1001");
      expect(stepCard.data.currentStep).toBe(1);
      expect(stepCard.data.steps.length).toBe(4);
      expect(stepCard.data.steps[1].actionRequired?.actionType).toBe(
        "input_text",
      );
    }
  });

  test("Should synthesize InteractiveProductCard with multi-sku choices", () => {
    const taskPlan: TaskPlan = {
      goal: "Recommend sports shoes with specs",
      currentStepIndex: 0,
      subtasks: [
        {
          id: "step_recommend_shoe",
          description: "Recommend shoes",
          status: "completed",
          result: {
            interactiveProduct: {
              productId: "PROD-SHOE-001",
              title: "Ultra Boost 跑步鞋 2026 旗舰款",
              subtitle: "全掌减震马牌大底，轻盈透气舒适脚感",
              imageUrl: "https://example.com/shoe.png",
              basePrice: 899,
              skus: [
                {
                  skuId: "SKU-BLK-42",
                  title: "曜石黑 / 42 码",
                  color: "曜石黑",
                  size: "42",
                  price: 899,
                  stock: 12,
                },
                {
                  skuId: "SKU-WHT-42",
                  title: "珍珠白 / 42 码",
                  color: "珍珠白",
                  size: "42",
                  price: 899,
                  stock: 3,
                },
              ],
            },
          },
        },
      ],
    };

    const cards = CardSynthesizer.synthesizeCards({ taskPlan });
    const productCard = cards.find((c) => c.type === "interactive_product");
    expect(productCard).toBeDefined();
    if (productCard && productCard.type === "interactive_product") {
      expect(productCard.data.productId).toBe("PROD-SHOE-001");
      expect(productCard.data.skus.length).toBe(2);
      expect(productCard.data.basePrice).toBe(899);
    }
  });
});
