import { describe, expect, test } from "bun:test";
import { MarkdownChunker } from "../src/rag/chunker";
import { ContextualRAG } from "../src/rag/contextualRag";

describe("MarkdownChunker & RAG Unit Tests", () => {
  test("Should split Markdown by headers and detect step counts", () => {
    const md = `# Nike 官方门店
## 营业时间与地点
营业时间为 10:00 - 22:00。地址为淮海中路816号。

## 电子发票申请 SOP
1. 登录个人中心
2. 点击发票申请
3. 输入企业抬头开票`;

    const chunks = MarkdownChunker.splitMarkdown(md, {
      category: "store_info",
    });

    expect(chunks.length).toBeGreaterThanOrEqual(2);
    expect(chunks[0].headerPath).toContain("Nike 官方门店");
    expect(chunks[1].stepCount).toBe(3);
  });

  test("ContextualRAG search should filter docs safely", async () => {
    const rag = new ContextualRAG("ecommerce");
    const docs = await rag.searchRelevantDocs("退货运费", 2);
    expect(Array.isArray(docs)).toBe(true);
  });
});
