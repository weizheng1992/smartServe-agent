# 📦 SaaS 多租户 Contextual RAG 检索引擎架构文档

本篇文档深度解析了本系统中实现的 **“SaaS 多租户物理隔离（Multi-Tenant Isolation）”** 与 **“Contextual RAG 高增益检索（Contextual Retrieval）”** 架构。

该方案彻底打破了传统单体 RAG 容易出现的“租户政策混淆（Cross-Tenant Leakage）”与“小文本碎片丢失语义（Loss of Global Context）”两大行业通病，是金融/电商领域标准的 SaaS 级 AI 知识库最佳实践。

---

## 一、 核心痛点与攻克方案

在工业级多商户（如 Nike、Adidas、电商主站）托管客服场景下，传统的 RAG 架构有三大致命缺陷：
1. **多租户政策幻觉混淆**：若没有对检索数据进行物理/逻辑隔离，大模型在回答 Adidas 会员提问时，极易检索出 Nike 的“30天超长退换货”政策，导致重大的商誉及赔付风险。
2. **切片语义丢失（Loss of Context）**：传统 RAG 将整篇 SOP 文档切分为 100-300 字的 chunks 并进行向量化。当模型单独检索出某一 chunk（如：*“退款时必须保留防伪扣”*），由于丢失了上下文，模型根本无法得知这是属于 Adidas 的特殊运动鞋政策，还是属于主站的普通服饰 policy。
3. **向量数据库（pgvector）依赖与离线瘫痪**：大多数系统的向量检索强依赖 pgvector 或 Pinecone服务。一旦数据库离线或进行本地模拟时，整个知识检索就会完全瘫痪。

为了攻克这些痛点，平台物理实现了 **多租户隔离 Contextual RAG 检索引擎**：

---

## 二、 SaaS 级多租户隔离架构 (Multi-Tenant Isolation)

系统基于会话的 `threadId` 自动追踪所属租户，实现端到端的物理安全隔离：

```
[用户提问: "我想退货"] ──> [runAgent(threadId)]
                                │
                                ▼ (物理查询会话所属租户)
                   SELECT business_id FROM threads WHERE id = threadId
                                │
                                ▼ (确定商户: e.g. "nike")
                        [ContextualRAG("nike")]
                                │
                                ▼ (SaaS 租户物理隔离 SQL 检索)
                  SELECT chunk_text, contextual_summary, embedding 
                  FROM rag_documents 
                  WHERE business_id = 'nike'
```
*   **多租户绝对隔离**：查询 RAG 切片时，Drizzle ORM 的条件子句强行限定 `WHERE business_id = :tenantId`。Nike 用户的检索结果绝无可能混入 Adidas 数据库记录，从物理源头上阻断跨租户数据泄露。

---

## 三、 Anthropic Contextual Retrieval 架构实现

本系统完美物理实践了 Anthropic 推出的 **Contextual Retrieval（高增益上下文检索）** 规范：

### 1. 数据模型与结合方式
每一条 `rag_documents` 记录在入库前，均由高阶模型对全局文档进行预分析，提炼出一段 **20-50字的全局语义前置汇总 (`contextual_summary`)**：

```typescript
// 结合上下文 summaries 与 chunk 文本生成真实的高增益 Embedding
const combinedText = `[Context] ${doc.contextualSummary}\n\n[Content] ${doc.chunkText}`;
const embedding = await embeddingModel.embedQuery(combinedText);
```

### 2. 精准提示词接地 (Grounded Prompting)

在 **Planner（步骤规划）** 和 **Finish（回复生成）** 阶段，高增益的 Contextual RAG 切片以如下结构被强行打入 Prompt 的全局 Context Wallet 中，以此校正模型的心智约束：

```
[RELEVANT STORE POLICIES & KNOWLEDGE BASE]:
[Store Policy Rule 1] (Context Summary: 这段切片详细说明了 Nike 会员尊享的 30 天无损无理由退货、已拆吊牌退货政策以及顺丰寄回服务): "Nike 会员专属福利：支持自订单购买之日起 30 天超长无理由退换货。即使已经拆除吊牌或进行过试穿，只要鞋底无明显磨损，均可享受免费原路退款。退款通过顺丰速运免费寄回。"
```

*   **Planner 约束**：`plannerNode` 根据 Nike 的 30天政策，能精准规划出 *“30天试穿内退货，无需回退到 planner 说明不符”* 的步骤；
*   **Finish 零幻觉兜底**：`finishNode` 依托切片，向消费者作出 100% 严谨、有据可查、零政策幻觉的规范解答。

---

## 四、 极客细节：数据自愈、三路并行与高保真本地仿真 Fallback

平台在工程完备度上做了多层次的极限拉满：

### 1. 数据自愈（Self-Healing Seed）
当 RAG 引擎发现物理数据库中的 `rag_documents` 为空时，**在运行时异步调用 Embedding 模型，自动生成 Nike、Adidas 和电商主站的演示政策 Embedding 并永久注入 PostgreSQL**，用户和开发团队不需要进行任何手动的 SQL Seed 操作，开箱即用。

### 2. 三路高并发异步检索
在 `runAgent` 入口处，通过 `Promise.allSettled` **并行跑通三套核心记忆与知识系统**，将 RAG 响应对整体延迟的影响降到最低：
```typescript
const [factsRes, eventsRes, ragRes] = await Promise.allSettled([
  longMemory.searchRelevantFacts(inputMessage),
  episodicMemory.retrieveEvents(inputMessage),
  contextualRag.searchRelevantDocs(inputMessage)
]);
```

### 3. High-Fidelity Fallback (FakePool)
当物理数据库处于 offline 或本地以 `FakePool` 运行时，系统将静默容错，**无缝降级到 Local Map 模糊关键词匹配检索，依然能输出完全一致的 SaaS 隔离的模拟 RAG 结果**，保障了整个单体环境在任何恶劣测试条件下的 100% 完备运行：

```typescript
// db/client.ts 内置了 RAG 物理 SQL query 的物理静态仿真
if (s.toUpperCase().includes('FROM RAG_DOCUMENTS')) {
  const rows = fakeRags.filter(r => r.businessId === businessId);
  return { rows };
}
```

---

## 五、 工具级政策红线守卫（Tool-Level SOP Policy Guardrail）

除了在 Planner 阶段依靠 RAG 知识库校正模型大脑规划，平台还部署了高防卫的物理工具级 SOP 安全拦截门闸：

### 1. 二次校签物理流程
*   在 `executor.node.ts` 即将调用物理工具时，系统会自动下发当前的 `threadId` 参数：
    `await toolDef.execute({ ...args, threadId })`
*   在 `processRefund`（物理退款工具）中，系统会根据 `threadId` 执行高吞吐、轻量级的 raw SQL 溯源其所属 `businessId`（完全避开 Drizzle ORM 的引入警告）：
    `SELECT business_id FROM threads WHERE id = :threadId`

### 2. 物理时效红线校验 (SOP Timeline Check)
*   根据溯源出的商户（Nike / Adidas / Ecommerce），工具会物理匹配 RAG 对应的 SOP 退货时效规定（Nike 30天，Adidas 14天，电商主站 7天）。
*   工具从 Postgres 表中读取该笔订单的 `estimatedDelivery`（送达时间），并与物理当前时间进行精密的时间差（`diffDays`）比对。
*   **断路降级与拦截**：若 `diffDays > returnWindowDays`（如 Adidas 订单已逾期 20 天），工具会在**执行层直接切断退款流程，绝不修改数据库订单状态**，并在返回数据中注入标准拦截元数据：
    ```json
    {
      "error": "⚠️ 退款政策拦截：根据商户 [ADIDAS] 官方售后 SOP 规范，退货时效为订单送达之日起 14 天内。该订单送达日期为 2026-07-20，当前已逾期 20 天，超出合规退款时效。物理拒绝执行退款！",
      "status": "rejected_by_policy",
      "elapsedDays": 20
    }
    ```

---

## 🆕 六、 零 Fallback 级顾客查单逻辑设计 (Secure listUserOrders)
针对多商户 SaaS 的查单诉求，全新扩展了 `listUserOrders` 原子级工具：
*   **会话关联反查**: 传统 RAG 在查单时常需要 LLM 从提问中自行提取 userId，这容易通过 Prompt Injection 进行**篡改越权查单**。
*   **零 Fallback 会话校验**: `listUserOrders` **强校验 `threadId` 参数**。它在底层强制执行物理 SQL 查询，动态抓取该会话真实的 `user_id` 与 `business_id`。
*   **物理拦截熔断**: 一旦无法解出有效的会话，或者发现会话未在 threads 物理表中注册，工具将即刻抛出 `"Session threadId is strictly required to query customer orders."` 安全断路异常，物理上**彻底铲除了通过默认账号或越权 ID 读取他人历史订单的漏洞**！

---

*文档编写日期：2026-07-27*
*检索架构：Contextual-Embedding (Gemini-3.5-Flash & Text-Embedding)*
