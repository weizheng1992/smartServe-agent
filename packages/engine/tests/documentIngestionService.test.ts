import { describe, expect, it } from 'bun:test';
import {
  buildContextualSummaryPrompt,
  chunkDocumentText,
  parseDocumentText,
  prepareRagDocumentRecords,
} from '../src/rag/documentIngestionService';

describe('Phase 2: Knowledge Document Ingestion & Contextual Chunking (TDD)', () => {
  const samplePolicyMarkdown = `
# Nike Official Store Return and Refund Policy

## 1. Return Window
Customers can return any unworn, unwashed items within 30 days of delivery.
Original packaging, tags, and receipt are strictly required.

## 2. Shipping Fees and Exceptions
Returns due to merchant quality defects or incorrect shipment are 100% free with pre-paid return labels.
For change-of-mind returns, a flat $5.99 return shipping fee is deducted from the refund total.

## 3. High-Value and Limited Edition Products
Customized Nike By You sneakers and SNKRS limited-edition drops cannot be returned unless damaged upon arrival.
All returns require human auditor approval before funds are credited.
  `.trim();

  it('should parse text and markdown documents cleanly', async () => {
    const parsed = await parseDocumentText({
      content: samplePolicyMarkdown,
      filename: 'nike-return-policy.md',
      mimeType: 'text/markdown',
    });

    expect(parsed).toBeDefined();
    expect(parsed.title).toBe('Nike Official Store Return and Refund Policy');
    expect(parsed.rawText).toContain('30 days of delivery');
    expect(parsed.lineCount).toBeGreaterThan(5);
  });

  it('should split document into boundary-aware chunks with overlap', () => {
    const chunks = chunkDocumentText({
      text: samplePolicyMarkdown,
      targetChunkSize: 100, // Small chunk size for test precision
      overlap: 20,
    });

    expect(chunks.length).toBeGreaterThanOrEqual(2);
    expect(chunks[0].chunkText).toContain('Nike');
    expect(chunks[0].chunkIndex).toBe(0);
    expect(chunks[1].chunkText.length).toBeGreaterThan(0);
  });

  it('should formulate Anthropic standard Contextual Summary prompt', () => {
    const chunkText = 'Customized Nike By You sneakers cannot be returned.';
    const prompt = buildContextualSummaryPrompt({
      fullDocumentText: samplePolicyMarkdown,
      chunkText,
      businessId: 'nike',
      brandName: 'Nike',
    });

    expect(prompt).toContain('<document>');
    expect(prompt).toContain('<chunk>');
    expect(prompt).toContain(chunkText);
    expect(prompt).toContain('Nike');
    expect(prompt).toContain('50-80');
  });

  it('should assemble RAG document records ready for Drizzle bulk insert', () => {
    const chunks = [
      { chunkIndex: 0, chunkText: 'Chunk 1: 30-day return policy.' },
      { chunkIndex: 1, chunkText: 'Chunk 2: $5.99 return shipping fee.' },
    ];
    const summaries = [
      'This chunk describes the standard 30-day return window for Nike retail purchases.',
      'This chunk outlines shipping deduction fees for non-defective returns at Nike.',
    ];

    const records = prepareRagDocumentRecords({
      businessId: 'nike',
      sourceUrl: 'https://nike.com/policies/returns.md',
      chunks,
      contextualSummaries: summaries,
      metadata: { category: 'return_policy', author: 'Nike Ops' },
    });

    expect(records).toHaveLength(2);
    expect(records[0].businessId).toBe('nike');
    expect(records[0].sourceUrl).toBe('https://nike.com/policies/returns.md');
    expect(records[0].chunkText).toBe(chunks[0].chunkText);
    expect(records[0].contextualSummary).toBe(summaries[0]);
    expect(records[0].metadata?.category).toBe('return_policy');
  });
});
