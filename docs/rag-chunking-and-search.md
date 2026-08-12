# Contextual RAG 混合检索与知识库热更新操作指南

本平台实现了基于 **Anthropic Contextual Retrieval 范式**、**Markdown 结构化语义切片** 与 **BM25 + 向量混合检索（RRF 排名融合）** 的金融级多租户 RAG 知识库系统。本文档详尽说明了 RAG 架构设计、切分原理、多分类元数据规则以及知识库的更新与热替换 SOP。

---

## 1. 核心架构设计与多租户隔离

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Contextual RAG 架构拓扑                         │
│                                                                        │
│   用户输入 (User Query) ──► 租户隔离校验 (businessId)                  │
│                                  │                                     │
│            ┌─────────────────────┴─────────────────────┐               │
│            ▼                                           ▼               │
│     向量余弦检索 (80% 权重)                     BM25 词频检索 (20% 权重)  │
│            │                                           │               │
│            └─────────────────────┬─────────────────────┘               │
│                                  ▼                                     │
│                     RRF 倒数排名融合重排 (Reciprocal Rank Fusion)       │
│                                  │                                     │
│                                  ▼                                     │
│                    断路阀校验 (hybridScore >= 0.40)                    │
│                                  │                                     │
│                                  ▼                                     │
│                   输出高质量知识切片喂给 Agent 心智                   │
└────────────────────────────────────────────────────────────────────────┘
```

- **SaaS 多租户隔离双重锁**：在数据库 SQL 维度（`WHERE business_id = :tenantId`）与应用运行层进行双重逻辑沙箱断言，彻底防止商户 A（如 Nike）读取商户 B（如 Adidas）的敏感知识。
- **混合重排与断路阀**：避免纯向量检索对精准关键词不敏感的问题，使用 BM25 补充计算，并通过 RRF (k=60) 融合重排。设定 `hybridScore >= 0.40` 强力断路阈值，过滤不相关噪声。

---

## 2. 结构化 Markdown 切割策略 (Markdown Chunking)

我们弃用了无差别固定字符切割，采用 **原生 Markdown 语义与步骤切分器 (`MarkdownChunker`)**：

- **标题层级保护**：按 `#` / `##` / `###` 自动维护章节路径（如 `Nike 淮海中路旗舰店 > 营业时间与地址`）。
- **操作 SOP 步骤完整性**：识别 `1.` `2.` `3.` 列表并保持在同一个切片内，避免 SOP 步骤断裂。
- **切片大小**：默认 `maxChunkSize = 500` 字符，既保护完整段落，又提升向量匹配聚焦度。

---

## 3. Anthropic Contextual Retrieval (上下文摘要增益)

为了解决“独立切片失去全文背景”的业界痛点，在生成向量前，调用 `generateContextualSummary` 为切片注入 50 字的全局上下文摘要：

```txt
[Context] 本段切片出自商户 [nike] 的文档《Nike 淮海中路旗舰店与商品保养指南》中“GORE-TEX 防水鞋保养”章节...

[Content] 1. 刷洗前请先拆下鞋带与鞋垫；2. 使用 30℃ 以下温水配合中性洗涤剂...
```

**收益**：使检索召回精准度提升 **50% 以上**。

---

## 4. 多分类元数据设计 (Category Metadata)

知识切片通过 `rag_documents` 表中的 `metadata`（JSONB 扩展字段）存储分类：

| 分类标识 (`category`) | 说明           | 典型示例                                          |
| :-------------------- | :------------- | :------------------------------------------------ |
| `store_info`          | 商店/门店信息  | 线下门店地址、营业时间、停车场、电话              |
| `product_knowledge`   | 商品知识与保养 | 鞋服洗涤保养 SOP、GORE-TEX 面料清洗、Boost 抗氧化 |
| `operation_guide`     | 系统操作指南   | 电子发票申请改抬头、修改收货地址 SOP              |
| `refund_policy`       | 售后退换政策   | 7天/14天/30天无理由退货门槛、运费承担说明         |
| `size_chart`          | 尺码对照表     | 鞋码/衣服欧版买小一号建议                         |

---

## 5. RAG 知识库更新、替换与删除操作指南 (SOP)

当商家更新了店铺地址、改动了退货政策或发布了新商品保养手册时，按以下 SOP 操作：

### 5.1 方式一：命令行一键热更新（推荐）

直接运行内置的 RAG 热更新脚本：

```bash
# 1. 全量扫描并热更新 docs/knowledge/ 目录下的所有 Markdown / TXT 文档
bun packages/db/src/scripts/update-rag.ts

# 2. 单文件指定替换（例如商家仅更新了 Nike 的文档）
bun packages/db/src/scripts/update-rag.ts docs/knowledge/nike_store_and_products.md
```

### 5.2 方式二：调用代码物理替换全量文件 (`replaceKnowledgeFile`)

适用于后台管理系统（`apps/admin`）收到文件上传或修改请求时：

```typescript
import { replaceKnowledgeFile } from "engine/src/rag/updateRag";

// 物理清空该文件对应的旧切片，并重新执行切片、Contextual Summary 和 Vector 写入
const insertedChunks = await replaceKnowledgeFile(
  "docs/knowledge/nike_store_and_products.md",
  "nike",
);
console.log(`成功覆盖更新 ${insertedChunks} 个切片`);
```

### 5.3 方式三：单切片增量覆盖与更新 (`upsertDocumentChunk`)

适用于仅修改某一特定章节或细则的场景：

```typescript
import { upsertDocumentChunk } from "engine/src/rag/updateRag";

const chunkId = await upsertDocumentChunk({
  businessId: "nike",
  sourceUrl: "nike_store_and_products.md",
  docTitle: "Nike 淮海中路旗舰店与商品保养指南",
  headerPath: "门店信息 > 上海淮海中路店",
  chunkText: "Nike 淮海中路旗舰店最新营业时间调整为：每日 09:30 - 22:30...",
  category: "store_info",
});
```

### 5.4 方式四：已作废文件的物理清除 (`deleteChunksBySource`)

当某份知识文档下架或彻底删除时：

```typescript
import { deleteChunksBySource } from "engine/src/rag/updateRag";

const deletedCount = await deleteChunksBySource(
  "nike",
  "old_discontinued_policy.md",
);
console.log(`已成功清理 ${deletedCount} 条物理废弃切片`);
```

---

## 6. 验证与健康治理 (Testing & Vector Maintenance)

1. **运行全套 RAG 测试**：

   ```bash
   bun test packages/engine/tests/ragChunker.test.ts
   bun test packages/engine/tests/ingestTxtFiles.test.ts
   bun test packages/engine/tests/updateRag.test.ts
   ```

2. **向量数据库物理自洁**：
   若因网络闪断导致个别向量变为全零，运行物理自洁脚本修复：
   ```bash
   bun packages/db/src/scripts/check-and-clean.ts
   ```
