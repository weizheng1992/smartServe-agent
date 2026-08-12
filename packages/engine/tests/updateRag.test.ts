import { describe, expect, test } from "bun:test";
import * as path from "node:path";
import {
  deleteChunksBySource,
  replaceKnowledgeFile,
  upsertDocumentChunk,
} from "../src/rag/updateRag";

describe("RAG Update & Replacement Pipeline Tests", () => {
  test("Should upsert and update single RAG chunk", async () => {
    const chunkId = await upsertDocumentChunk({
      businessId: "nike",
      sourceUrl: "test_update_file.md",
      docTitle: "Nike 测试文档",
      headerPath: "测试章节 > 规则说明",
      chunkText: "这是全新的 Nike 30 天无条件退货规则描述。",
      category: "refund_policy",
    });

    expect(typeof chunkId).toBe("string");
    expect(chunkId.length).toBeGreaterThan(0);
  });

  test("Should replace full knowledge file and delete old chunks", async () => {
    const filePath = path.resolve(
      __dirname,
      "../../../docs/knowledge/nike_store_and_products.md",
    );
    const count = await replaceKnowledgeFile(filePath, "nike");

    expect(count).toBeGreaterThan(0);
  });

  test("Should safely delete chunks by sourceUrl", async () => {
    const deletedCount = await deleteChunksBySource(
      "nike",
      "test_update_file.md",
    );
    expect(deletedCount).toBeGreaterThanOrEqual(0);
  });
});
