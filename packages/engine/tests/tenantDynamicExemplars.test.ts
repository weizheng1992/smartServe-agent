import { describe, expect, test } from "bun:test";
import { ExemplarService } from "../src/graph/nodes/triage/exemplarService";

describe("租户级动态 Exemplar 样本路由测试 (Tenant-Isolated Dynamic Exemplar Routing)", () => {
  const tenantNike = "nike_test_" + Date.now();
  const tenantAdidas = "adidas_test_" + Date.now();

  test("应该能成功添加租户专属意图样本并计算 Embedding", async () => {
    const id = await ExemplarService.addExemplar(
      tenantNike,
      "sneaker_authenticity_check",
      "帮我查一下这双球鞋的防伪码是不是官方正品",
    );
    expect(id).toBeDefined();
  });

  test("应该能按租户隔离精确召回样本 (Nike vs Adidas 物理隔离)", async () => {
    // 为 Adidas 添加一条不同样本
    await ExemplarService.addExemplar(
      tenantAdidas,
      "boost_sole_maintenance",
      "我的椰子鞋底发黄了怎么清洗保养",
    );

    // 查询 Nike
    const nikeResults = await ExemplarService.searchRelevantExemplars(
      tenantNike,
      "防伪码验证球鞋真伪",
    );
    expect(nikeResults.length).toBeGreaterThan(0);
    expect(nikeResults[0].intentName).toBe("sneaker_authenticity_check");
    expect(nikeResults[0].businessId).toBe(tenantNike);

    // 查询 Adidas 不应该出现 Nike 的防伪意图
    const adidasResults = await ExemplarService.searchRelevantExemplars(
      tenantAdidas,
      "鞋底发黄清洗保养",
    );
    expect(adidasResults.length).toBeGreaterThan(0);
    expect(adidasResults[0].intentName).toBe("boost_sole_maintenance");
    expect(adidasResults[0].businessId).toBe(tenantAdidas);

    // 交叉验证：Nike 绝对查不到 Adidas 的专属意图
    const nikeCrossResults = await ExemplarService.searchRelevantExemplars(
      tenantNike,
      "椰子鞋底保养",
    );
    const hasAdidasIntent = nikeCrossResults.some(
      (r) => r.intentName === "boost_sole_maintenance",
    );
    expect(hasAdidasIntent).toBe(false);
  });

  test("应该能正确格式化 Exemplars 为 Few-Shot Prompt", () => {
    const samples = [
      {
        id: "1",
        businessId: "nike",
        intentName: "custom_embroidery",
        exampleText: "我想在鞋跟上刺绣我的名字",
      },
    ];

    const promptText = ExemplarService.formatExemplarsForPrompt(samples);
    expect(promptText).toContain("custom_embroidery");
    expect(promptText).toContain("我想在鞋跟上刺绣我的名字");
  });

  test("当样本不存在时应平滑返回空数组降级", async () => {
    const emptyResults = await ExemplarService.searchRelevantExemplars(
      "non_existing_tenant",
      "测试语句",
    );
    expect(emptyResults).toEqual([]);
  });
});
