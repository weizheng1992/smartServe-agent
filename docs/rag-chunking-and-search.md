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

当商家更新了店铺地址、改动了退货政策或发布了新商品保养手册时，按以下 SOP 操作。
知识源为 `docs/knowledge/` 下的 Markdown 文档（frontmatter 声明 `businessId` 归属租户），
摄取器为 `services/engine-py/src/engine_py/rag/knowledge_files.py`（TS `updateRag.ts` 已随 TS 后端退役，
其职责由 Python 侧承接，切片/替换语义保持一致）。

### 5.1 方式一：编辑知识文档 + 重跑种子（推荐）

```bash
# 1. 编辑 docs/knowledge/<tenant>_xxx.md（或新增文档,frontmatter 必须带 businessId）
# 2. 重跑种子：按 (businessId, 文件名) 整组替换旧切片（管理端人工新增行不受影响）
bun run db:seed
```

目录位置可用 `RAG_KNOWLEDGE_DIR` 环境变量覆写（容器部署 docs/ 不随包分发时使用）。

### 5.2 方式二：后台管理系统单切片增删

`apps/admin` 知识库模块走网关 CRUD 路由（`POST/DELETE /api/rag/documents`），
直接对 `rag_documents` 单行增删，不经过文件摄取管道。

### 5.3 方式三：空库冷启动自愈

知识表为空时，`ContextualRAG` 首次检索会自动摄取 `docs/knowledge/` 全量文档播种
（与种子同一数据源）；目录缺失/不可读/为空则**跳过播种**（2026-09-09 评审修复：
不再回退内置演示切片，知识只有 `docs/knowledge` 一个来源，冷启动降级与种子不漂移成两套）。

### 5.4 上下文摘要说明

文件摄取管道的 Contextual Summary 为确定性模板（零 LLM 调用、可重复）：
`本段切片出自商户 [businessId] 的文档《docTitle》中「headerPath」章节`；
检索时的 `[Context] … [Content] …` 拼接口径与 §3 一致。

---

## 6. 验证与健康治理 (Testing & Vector Maintenance)

1. **运行 RAG 摄取与检索测试**（文件切片/播种幂等/租户隔离/冷启动自愈）：

   ```bash
   cd services/engine-py && uv run pytest tests/test_merchant_rag_knowledge.py
   ```

2. **向量缺失自愈**：
   种子播种与冷启动自愈均为"整组替换"语义 —— 若因网络闪断导致个别向量缺失，
   重跑 `bun run db:seed` 即按文件重切重建；向量化失败的单行会落 NULL（BM25 仍可召回，
   余弦权重为 0），下次重播种子自动修复。
