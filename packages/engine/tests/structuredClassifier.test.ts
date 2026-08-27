import { describe, expect, test } from "bun:test";
import {
  StructuredClassifier,
  StructuredTriageOutputSchema,
} from "../src/graph/nodes/triage/structuredClassifier";

describe("StructuredClassifier 结构化约束解码与联合槽位提取测试", () => {
  test("应该能正确校验合法符合 Schema 的结构化意图对象", () => {
    const sample = {
      executionMode: "parallel",
      intents: [
        {
          intent: "order_status",
          confidence: 0.95,
          type: "primary",
          entities: { orderId: "ORD-98712" },
          slots: { orderId: "ORD-98712" },
        },
      ],
      isOutOfScope: false,
    };

    const parsed = StructuredTriageOutputSchema.parse(sample);
    expect(parsed.executionMode).toBe("parallel");
    expect(parsed.intents[0].intent).toBe("order_status");
    expect(parsed.intents[0].entities?.orderId).toBe("ORD-98712");
  });

  test("应该能正确解析条件意图与条件谓词 (Conditional Execution)", () => {
    const sample = {
      executionMode: "conditional",
      intents: [
        {
          intent: "order_modify_address",
          confidence: 0.92,
          type: "primary",
          condition: {
            field: "shipping_status",
            operator: "equals",
            expectedValue: "pending",
          },
          entities: { orderId: "ORD-98712", newAddress: "北京市海淀区科技园" },
        },
      ],
      isOutOfScope: false,
    };

    const parsed = StructuredTriageOutputSchema.parse(sample);
    expect(parsed.executionMode).toBe("conditional");
    expect(parsed.intents[0].condition?.field).toBe("shipping_status");
    expect(parsed.intents[0].condition?.operator).toBe("equals");
  });

  test("应该能捕获缺失槽位并带有追问话术", () => {
    const sample = {
      executionMode: "parallel",
      intents: [
        {
          intent: "order_modify_address",
          confidence: 0.9,
          type: "primary",
          entities: { orderId: "ORD-12345" },
          missingSlots: ["newAddress"],
        },
      ],
      clarificationMessage: "请问您需要将订单 ORD-12345 修改至什么新地址？",
      isOutOfScope: false,
    };

    const parsed = StructuredTriageOutputSchema.parse(sample);
    expect(parsed.intents[0].missingSlots).toContain("newAddress");
    expect(parsed.clarificationMessage).toBeDefined();
  });
});
