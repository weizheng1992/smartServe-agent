import { describe, expect, test } from 'bun:test';
import * as path from 'node:path';
import { getDrizzle, ragDocuments } from 'db';
import { sql } from 'drizzle-orm';
import { cleanDatabase } from '../../../packages/db/src/scripts/check-and-clean';
import { ingestTxtDirectory } from '../src/rag/ingestTxtFiles';
import { upsertDocumentChunk } from '../src/rag/updateRag';

describe('RAG Document Deduplication & Idempotence Tests', () => {
  test('Should deduplicate and clean any existing duplicate rows via cleanDatabase', async () => {
    const drizzle = getDrizzle();
    if (!drizzle) return;

    // Run cleanDatabase
    const result = await cleanDatabase();
    expect(result).toBeDefined();

    // Verify in database that no duplicate (business_id, chunk_text) exists
    const duplicates = await drizzle.execute(sql`
      SELECT business_id, chunk_text, count(*) as cnt
      FROM rag_documents
      GROUP BY business_id, chunk_text
      HAVING count(*) > 1
    `);

    expect(duplicates.rows.length).toBe(0);
  });

  test('Should remain idempotent and produce 0 duplicates when ingesting directory repeatedly', async () => {
    const drizzle = getDrizzle();
    if (!drizzle) return;

    const knowledgeDir = path.resolve(__dirname, '../../../docs/knowledge');

    // Ingest first time
    const res1 = await ingestTxtDirectory(knowledgeDir);
    expect(Array.isArray(res1)).toBe(true);

    const countAfterFirst = await drizzle.select({ count: sql`count(*)` }).from(ragDocuments);
    const count1 = Number(countAfterFirst[0].count);

    // Ingest second time
    const res2 = await ingestTxtDirectory(knowledgeDir);
    expect(Array.isArray(res2)).toBe(true);

    const countAfterSecond = await drizzle.select({ count: sql`count(*)` }).from(ragDocuments);
    const count2 = Number(countAfterSecond[0].count);

    // Row count must NOT increase on repeated ingestion
    expect(count2).toBe(count1);

    // Verify 0 duplicate groups
    const duplicates = await drizzle.execute(sql`
      SELECT business_id, chunk_text, count(*) as cnt
      FROM rag_documents
      GROUP BY business_id, chunk_text
      HAVING count(*) > 1
    `);

    expect(duplicates.rows.length).toBe(0);
  }, 30000);

  test('Should update rather than duplicate when upserting same chunk text', async () => {
    const drizzle = getDrizzle();
    if (!drizzle) return;

    const testChunk = {
      businessId: 'nike',
      sourceUrl: 'test_idempotence.md',
      docTitle: 'Nike 幂等性测试',
      headerPath: '测试 > 幂等',
      chunkText: '这是一条用于验证 RAG 幂等更新的专用测试切片文本。',
      category: 'product_knowledge' as const,
    };

    const id1 = await upsertDocumentChunk(testChunk);
    expect(typeof id1).toBe('string');

    // Upsert again with updated title
    const id2 = await upsertDocumentChunk({
      ...testChunk,
      docTitle: 'Nike 幂等性测试 (更新版)',
    });

    expect(id2).toBe(id1);

    // Clean up test chunk
    await drizzle.delete(ragDocuments).where(sql`id = ${id1}::uuid`);
  });
});
