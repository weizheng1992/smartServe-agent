import { describe, expect, test } from "bun:test";
import { KnowledgeEngine } from "../src/rag/knowledgeEngine";

describe("KnowledgeEngine Facade Unit Tests", () => {
  test("Should search relevant docs using KnowledgeEngine facade", async () => {
    const engine = new KnowledgeEngine("nike");
    const results = await engine.search("退货政策与运费", { limit: 2 });

    expect(Array.isArray(results)).toBe(true);
    if (results.length > 0) {
      expect(results[0].businessId).toBe("nike");
      expect(typeof results[0].similarity).toBe("number");
    }
  });

  test("Should upsert and delete single chunk via KnowledgeEngine", async () => {
    const engine = new KnowledgeEngine("nike");
    const chunkId = await engine.upsertChunk({
      sourceUrl: "test_ke_file.md",
      docTitle: "Nike 知识库测试",
      headerPath: "测试 > 门面",
      chunkText: "这是通过 KnowledgeEngine 写入的测试切片。",
      category: "store_info",
    });

    expect(typeof chunkId).toBe("string");
    expect(chunkId.length).toBeGreaterThan(0);

    const deleted = await engine.deleteSource("test_ke_file.md");
    expect(deleted).toBeGreaterThanOrEqual(0);
  });
});
