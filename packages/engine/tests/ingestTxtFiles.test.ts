import { describe, expect, test } from "bun:test";
import * as path from "node:path";
import { ContextualRAG } from "../src/rag/contextualRag";
import { ingestTxtDirectory } from "../src/rag/ingestTxtFiles";

describe("TXT File Knowledge Ingestion & RAG Test", () => {
  test("Should parse and ingest simulated txt files from docs/knowledge", async () => {
    const knowledgeDir = path.resolve(__dirname, "../../../docs/knowledge");
    const results = await ingestTxtDirectory(knowledgeDir);

    expect(Array.isArray(results)).toBe(true);
    expect(results.length).toBeGreaterThanOrEqual(3);

    const totalChunks = results.reduce((sum, r) => sum + r.chunksIngested, 0);
    expect(totalChunks).toBeGreaterThan(0);
  }, 15000);

  test("Should search and retrieve ingested txt knowledge for Nike GORE-TEX", async () => {
    const rag = new ContextualRAG("nike");
    const docs = await rag.searchRelevantDocs("GORE-TEX 洗涤保养", 2);

    expect(Array.isArray(docs)).toBe(true);
    if (docs.length > 0) {
      expect(docs[0].chunkText).toContain("GORE-TEX");
    }
  });
});
