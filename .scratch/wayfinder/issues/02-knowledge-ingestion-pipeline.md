# TICKET-02: 知识库多格式文档切片与 Contextual Retrieval 异步摄入流水线

**Label:** `wayfinder:research` (AFK)  
**Parent Map:** [Wayfinder Map](../map.md)  
**Assignee:** Subagent (Completed)  
**Status:** Closed

---

## Question

商户上传多格式业务文档（Markdown, PDF, DOCX, TXT）后，如何设计高效稳定的后台解析与 Contextual RAG 摄入流水线？

---

## Resolution Findings

1. **轻量与高兼容解析库选型 (Bun/Node)**:
   - **PDF**: 选用 `unpdf`（现代 ESM/TypeScript 原生，零 C++ 底层依赖）或 `pdf-parse`。
   - **DOCX**: 选用 `mammoth`（纯 JS 文本提取，精准保留层级）。
   - **Markdown / TXT**: 选用 `marked` / 原生正则解析。

2. **分块策略 (Recursive Boundary Chunking)**:
   - 优先按 `\n\n`（段落）、`\n`、句号问号等标点分块，目标大小 **~600 tokens**，重叠 **100 tokens**。

3. **Contextual Summary 提示词 (Anthropic 标准)**:
   - 提取全文 `<document>` 与 `<chunk>`，通过 LLM 异步生成 50-80 词情境摘要，注入 `contextual_summary` 字段。

4. **Temporal 工作流编排**:
   - `IngestDocumentWorkflow` -> `ParseFileActivity` -> `ChunkTextActivity` -> `GenerateContextualSummariesActivity` -> `GenerateEmbeddingsActivity` -> `BulkInsertWithVectorValidationActivity`。
