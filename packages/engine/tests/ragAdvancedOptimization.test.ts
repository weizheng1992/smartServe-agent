import { describe, expect, test } from 'bun:test';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import {
  KnowledgeEngine,
  MarkdownChunker,
  buildContextualSummaryPrompt,
  generateContextualSummary,
  mapConcurrent,
  syncKnowledgeDocument,
} from '../src/rag';

describe('Advanced RAG Optimization & Large Document Pipeline Suite', () => {
  test('【大纲提取与结构保护】MarkdownChunker 提取目录大纲与保护表格代码块', () => {
    const markdown = `# 商户知识库总纲
## 1. 营业与服务
本门店支持全天候服务。

| 区域 | 营业时间 | 电话 |
| :--- | :--- | :--- |
| 华东区 | 09:00 - 22:00 | 400-888-0001 |
| 华南区 | 10:00 - 23:00 | 400-888-0002 |

## 2. 系统接入代码
\`\`\`typescript
const client = new ApiClient({ apiKey: 'sk-123456' });
await client.orders.sync();
\`\`\`
`;

    const outline = MarkdownChunker.extractOutline(markdown);
    expect(outline).toContain('- 商户知识库总纲');
    expect(outline).toContain('- 1. 营业与服务');
    expect(outline).toContain('- 2. 系统接入代码');

    const chunks = MarkdownChunker.splitMarkdown(markdown, {
      maxChunkSize: 300,
    });
    expect(chunks.length).toBeGreaterThanOrEqual(2);

    const tableChunk = chunks.find((c) => c.isTable);
    expect(tableChunk).toBeDefined();
    expect(tableChunk?.chunkText).toContain('400-888-0001');

    const codeChunk = chunks.find((c) => c.isCodeBlock);
    expect(codeChunk).toBeDefined();
    expect(codeChunk?.chunkText).toContain('ApiClient');

    // 验证 contentHash 存在且幂等
    expect(chunks[0].contentHash).toBeDefined();
    expect(chunks[0].contentHash.length).toBe(64);
    const recomputedHash = MarkdownChunker.computeHash(chunks[0].headerPath, chunks[0].chunkText);
    expect(chunks[0].contentHash).toBe(recomputedHash);
  });

  test('【超大文档分层 Contextual Retrieval】自适应切换分层大纲提示词', () => {
    // 1. 小文档提示词生成
    const smallPrompt = buildContextualSummaryPrompt({
      fullDocumentText: '这是一个简短的退货政策说明。',
      chunkText: '支持7天无理由退货。',
      businessId: 'nike',
    });
    expect(smallPrompt).toContain('<document>');
    expect(smallPrompt).toContain('<chunk>');

    // 2. 超长文档带大纲提示词生成
    const largeDocText = '很长的文档内容...'.repeat(500); // > 3000 chars
    const largePrompt = buildContextualSummaryPrompt({
      fullDocumentText: largeDocText,
      documentOutline: '- 章节1\n- 章节2',
      sectionContext: '当前处于【退款物流】章节',
      chunkText: '顺丰寄回免运费。',
      businessId: 'nike',
    });
    expect(largePrompt).toContain('<document_outline>');
    expect(largePrompt).toContain('<section_context>');
    expect(largePrompt).toContain('顺丰寄回免运费');
  });

  test('【受控并发控制器】mapConcurrent 限制并发度并保证有序返回', async () => {
    let running = 0;
    let maxRunning = 0;

    const items = [1, 2, 3, 4, 5, 6, 7, 8];
    const results = await mapConcurrent(items, 3, async (num) => {
      running++;
      if (running > maxRunning) maxRunning = running;
      await new Promise((resolve) => setTimeout(resolve, 20));
      running--;
      return num * 2;
    });

    expect(results).toEqual([2, 4, 6, 8, 10, 12, 14, 16]);
    expect(maxRunning).toBeLessThanOrEqual(3);
  });

  test('【增量 Diff 差量同步与复用】syncKnowledgeDocument 正确识别未变切片', async () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rag_sync_test_'));
    const testFile = path.join(tempDir, 'test_diff_doc.md');

    const contentV1 = `---
businessId: test_diff_brand
title: 测试差量同步文档
category: refund_policy
---
# 核心政策
## 退换时效
自购买之日起 15 天内可申请退换货。

## 运费承担
质量问题由商家承担运费。
`;

    fs.writeFileSync(testFile, contentV1, 'utf-8');

    // 首次同步：全部新增
    const res1 = await syncKnowledgeDocument(testFile, 'test_diff_brand');
    expect(res1.totalChunks).toBeGreaterThanOrEqual(2);
    expect(res1.inserted).toBeGreaterThanOrEqual(2);

    // 二次同步（内容无任何修改）：全部复用，0 新增，0 更新
    const res2 = await syncKnowledgeDocument(testFile, 'test_diff_brand');
    expect(res2.unchanged).toBe(res1.totalChunks);
    expect(res2.inserted).toBe(0);
    expect(res2.updated).toBe(0);

    // 修改其中一个章节：仅更新/新增变动切片，复用未修改切片
    const contentV2 = `---
businessId: test_diff_brand
title: 测试差量同步文档
category: refund_policy
---
# 核心政策
## 退换时效
自购买之日起 30 天内可申请退换货。（已升级为30天）

## 运费承担
质量问题由商家承担运费。
`;
    fs.writeFileSync(testFile, contentV2, 'utf-8');

    const res3 = await syncKnowledgeDocument(testFile, 'test_diff_brand');
    expect(res3.unchanged).toBeGreaterThanOrEqual(1); // 运费承担切片未修改，直接复用
    expect(res3.updated + res3.inserted).toBeGreaterThanOrEqual(1); // 退换时效已更新

    // 清理临时文件
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  test('【KnowledgeEngine 高阶接口】支持 syncFile 和 minScore 过滤检索', async () => {
    const engine = new KnowledgeEngine('test_diff_brand');
    const searchRes = await engine.search('退换时效', {
      limit: 3,
      minScore: 0.3,
    });
    expect(Array.isArray(searchRes)).toBe(true);

    // 清理测试商户数据
    await engine.deleteSource('test_diff_doc.md');
  });
});
