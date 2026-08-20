import { getDrizzle, ragDocuments } from "db";
import {
  buildContextualSummaryPrompt,
  chunkDocumentText,
  parseDocumentText,
  prepareRagDocumentRecords,
} from "engine";
import { type NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const {
      businessId,
      content,
      filename = "document.md",
      mimeType = "text/markdown",
      sourceUrl,
      category = "store_policy",
    } = body;

    if (!businessId || !content) {
      return NextResponse.json(
        { success: false, error: "businessId and content are required" },
        { status: 400 },
      );
    }

    // 1. 解析文档
    const parsed = await parseDocumentText({ content, filename, mimeType });

    // 2. 递归边界感知分块
    const chunks = chunkDocumentText({
      text: parsed.rawText,
      targetChunkSize: 600,
      overlap: 100,
    });

    if (chunks.length === 0) {
      return NextResponse.json(
        { success: false, error: "Document text produced 0 valid chunks." },
        { status: 400 },
      );
    }

    // 3. 生成基础情境摘要（Anthropic Contextual Summary）
    const summaries = chunks.map((chunk) => {
      return `[${businessId.toUpperCase()} Policy Chunk ${chunk.chunkIndex + 1}/${chunks.length}]: Document '${parsed.title}' covering ${category}.`;
    });

    // 4. 组装 RAG 数据记录
    const records = prepareRagDocumentRecords({
      businessId,
      sourceUrl: sourceUrl || `https://${businessId}.store/docs/${filename}`,
      chunks,
      contextualSummaries: summaries,
      metadata: { category, filename, title: parsed.title },
    });

    // 5. 批量写入 PostgreSQL rag_documents 表
    const db = getDrizzle();
    const inserted = await db
      .insert(ragDocuments)
      .values(
        records.map((r) => ({
          businessId: r.businessId,
          sourceUrl: r.sourceUrl,
          chunkText: r.chunkText,
          contextualSummary: r.contextualSummary,
          metadata: r.metadata,
        })),
      )
      .returning();

    return NextResponse.json({
      success: true,
      documentTitle: parsed.title,
      totalChunks: inserted.length,
      chunks: inserted.map((doc) => ({
        id: doc.id,
        contextualSummary: doc.contextualSummary,
        preview: doc.chunkText.substring(0, 80) + "...",
      })),
    });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error("Error uploading and ingesting knowledge document:", error);
    return NextResponse.json(
      { success: false, error: errMsg },
      { status: 500 },
    );
  }
}
