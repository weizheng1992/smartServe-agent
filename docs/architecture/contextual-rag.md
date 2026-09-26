# 📦 SaaS 多租户 Contextual RAG 检索引擎架构文档

本篇文档深度解析了本系统中实现的 **“SaaS 多租户物理隔离（Multi-Tenant Isolation）”** 与 **“Contextual RAG 高增益检索（Contextual Retrieval）”** 架构。

该方案彻底打破了传统单体 RAG 容易出现的“租户政策混淆（Cross-Tenant Leakage）”与“小文本碎片丢失语义（Loss of Global Context）”两大行业通病，是金融/电商领域标准的 SaaS 级 AI 知识库最佳实践。

---

## 一、 核心痛点与攻克方案

在工业级多商户（如 Nike、Adidas、电商主站）托管客服场景下，传统的 RAG 架构有三大致命缺陷：

1. **多租户政策幻觉混淆**：若没有对检索数据进行物理/逻辑隔离，大模型在回答 Adidas 会员提问时，极易检索出 Nike 的“30天超长退换货”政策，导致重大的商誉及赔付风险。
2. **切片语义丢失（Loss of Context）**：传统 RAG 将整篇 SOP 文档切分为 100-300 字的 chunks 并进行向量化。当模型单独检索出某一 chunk（如：_“退款时必须保留防伪扣”_），由于丢失了上下文，模型根本无法得知这是属于 Adidas 的特殊运动鞋政策，还是属于主站的普通服饰 policy。
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

- **多租户绝对隔离**：查询 RAG 切片时，SQLAlchemy 条件子句强行限定 `WHERE business_id = :tenantId`，并在应用层做**二次租户校验**（行级 `row.business_id != self.business_id` 直接跳过，双锁防注入式越权）。Nike 用户的检索结果绝无可能混入 Adidas 数据库记录，从物理源头上阻断跨租户数据泄露。

> 实现位置：`services/engine-py/src/engine_py/rag/contextual_rag.py`（`search_relevant_docs`）。

---

## 三、 Anthropic Contextual Retrieval 架构实现

本系统完美物理实践了 Anthropic 推出的 **Contextual Retrieval（高增益上下文检索）** 规范：

### 1. 数据模型与结合方式

每一条 `rag_documents` 记录在入库前，都会先合成一段**全局语义前置汇总 (`contextual_summary`)**。Python 实现取**确定性模板**形态（零 LLM 调用，`knowledge_files.py`）：`本段切片出自商户 [{business_id}] 的文档《{doc_title}》中「{header_path}」章节。`——以文档结构锚点达成同等的全局语境消歧效果，且入库成本与口径漂移双双归零（TS 时代「高阶模型预分析写摘要」的做法未随迁）。

```python
# engine_py/rag/knowledge_files.py — 切片入库时即完成「上下文前置汇总 + 切片文本」联合向量化
def embedding_input(self) -> str:
    return f"[Context] {self.contextual_summary()}\n\n[Content] {self.chunk_text}"

# contextual_rag.py 入库路径
embedding = await get_embedding_model().aembed_query(chunk.embedding_input())
```

检索侧则把 `docTitle / headerPath / contextual_summary / chunk_text` 一起分词参与 BM25 通道，向量通道查预先算好的切片向量——**查询向量全轮只算一次**（`run_agent` 预计算 `precomputed_embedding` 后三路复用，见 §四.2）。

### 2. 精准提示词接地 (Grounded Prompting)

在 **Planner（步骤规划）** 和 **Finish（回复生成）** 阶段，高增益的 Contextual RAG 切片以如下结构被强行打入 Prompt 的全局 Context Wallet 中，以此校正模型的心智约束（两处真实段头：`graph/nodes/planner.py` 用 `[RELEVANT BUSINESS POLICIES & KNOWLEDGE BASE]`，`graph/nodes/finish.py` 用 `[RELEVANT STORE POLICIES & KNOWLEDGE BASE]`）：

```
[RELEVANT STORE POLICIES & KNOWLEDGE BASE]:
[Store Policy Rule 1] (Context Summary: 这段切片详细说明了 Nike 会员尊享的 30 天无损无理由退货、已拆吊牌退货政策以及顺丰寄回服务): "Nike 会员专属福利：支持自订单购买之日起 30 天超长无理由退换货。即使已经拆除吊牌或进行过试穿，只要鞋底无明显磨损，均可享受免费原路退款。退款通过顺丰速运免费寄回。"
```

- **Planner 约束**：planner 节点根据 Nike 的 30天政策，能精准规划出 _“30天试穿内退货，无需回退到 planner 说明不符”_ 的步骤；
- **Finish 零幻觉兜底**：finish 节点依托切片，向消费者作出 100% 严谨、有据可查、零政策幻觉的规范解答。

---

## 四、 极客细节：数据自愈、三路并行与高保真本地仿真 Fallback

平台在工程完备度上做了多层次的极限拉满：

### 1. 数据自愈（Self-Healing Seed）

当 RAG 引擎发现物理数据库中的 `rag_documents` 相对知识文件缺失时，`_ensure_seed_data` **在运行时读 `docs/knowledge/*.md`（知识不写死在代码里），逐文档切片、合成 `contextual_summary` 并调用 Embedding 模型向量化后永久注入 PostgreSQL**；同文档以 `MD5(string_agg(chunk_text))` 比对内容指纹，只增量补写缺失来源。用户和开发团队不需要进行任何手动的 SQL Seed 操作，开箱即用；知识文件不可读或 DB 不可达时静默跳过（print 不炸会话）。

### 2. 三路高并发异步检索 + 单次嵌入注入

在 `run_agent` 入口处，通过 `asyncio.gather(..., return_exceptions=True)` **并行跑通三套核心记忆与知识系统**，将 RAG 响应对整体延迟的影响降到最低；查询向量只在入口处计算一次（`precomputed_embedding`），三路检索共享复用：

```python
precomputed_embedding = await get_embedding_model().aembed_query(input_message)

facts_res, events_res, rag_res = await asyncio.gather(
    long_memory.search_relevant_facts(input_message, precomputed_embedding),
    episodic_memory.retrieve_events(input_message, 3, precomputed_embedding),
    contextual_rag.search_relevant_docs(input_message, 2, precomputed_embedding),
    return_exceptions=True,
)
# 任一路失败诚实空(Exception → []),不炸会话
```

### 3. 混合检索与诚实空（FakePool 已退役）

检索本体是**向量余弦 + BM25 关键词双通道**：双通道各自排序后经 Reciprocal Rank Fusion（k=60）融合，最终 `hybrid_score = cosine × 0.8 + normalized_bm25 × 0.2`，低于 `min_score`（默认 0.40）的切片一律截断。TS 时代的 `FakePool` 静态仿真与「Local Fake RAG 假相似度兜底」已于 2026-09-12 退役——**DB 失败时检索终点只有真实结果或诚实空**，与 real-data-only 纪律（01 号决议）对齐：

```python
# contextual_rag.py — 库失败诚实空(演示切片兜底已拆除)
except Exception as db_err:
    print(f"[RAG] PostgreSQL query failed, returning honest empty: {db_err}")
    return []
```

---

## 五、 工具级政策红线守卫（Tool-Level SOP Policy Guardrail）

除了在 Planner 阶段依靠 RAG 知识库校正模型大脑规划，平台还部署了高防卫的物理工具级 SOP 安全拦截门闸：

### 1. 二次校签物理流程

- 执行器即将调用物理工具时，自动携带当前 `threadId` 上下文；
- `process_refund`（`tools_registry/order_domain.py` 物理退款）先经 `get_thread_session_context(threadId)` 溯源会话真实归属：
  `SELECT "user_id", "business_id" FROM threads WHERE id = :tid`——后续 `find_order_by_id(orderId, userId, businessId)` 严格按「订单属于该用户 × 该商户」双重归属过滤，查无即诚实报错（`⚠️ 越权阻止或未找到订单`），绝不操作他人订单。

### 2. 物理时效红线校验 (SOP Timeline Check)

- 根据溯源出的商户（Nike / Adidas / Ecommerce），工具经 `get_return_window_days` 物理匹配 SOP 退货时效规定——**租户配置中心的 `maxRefundDays` 优先，降级商户基准**（Nike 30天，Adidas 14天，电商主站 7天）。
- 工具从订单中读取 `estimatedDelivery`（送达时间，时区偏移先归一），并与当前时间进行时间差（`diffDays`）比对。
- 幂等底线前置：已退款订单（任意来源 engine/merchant/third_party）先于时效校验被拦截（`status: "already_refunded"`，2026-09-05 双退款事故收口）。
- **断路降级与拦截**：若 `diffDays > returnWindowDays`（如 Adidas 订单已逾期 20 天），工具会在**执行层直接切断退款流程，绝不修改数据库订单状态**，并在返回数据中注入标准拦截元数据：
  ```json
  {
    "error": "⚠️ 退款政策拦截：根据商户 [ADIDAS] 官方售后 SOP 规范，退货时效为订单送达之日起 14 天内。该订单送达日期为 2026-07-20，当前已逾期 20 天，超出合规退款时效。物理拒绝执行退款！",
    "orderId": "ORD-XXXX",
    "status": "rejected_by_policy",
    "businessId": "adidas",
    "returnWindowDays": 14,
    "elapsedDays": 20
  }
  ```

---

## 🆕 六、 会话反查顾客查单逻辑设计 (Secure listUserOrders)

针对多商户 SaaS 的查单诉求，`list_user_orders`（`tools_registry/order_domain.py`）的安全模型：

- **会话关联反查**: 传统 RAG 在查单时常需要 LLM 从提问中自行提取 userId，这容易通过 Prompt Injection 进行**篡改越权查单**；此处身份一律由 `threadId` 物理反查 `threads` 表得出，不信 LLM 转述。
- **严格归属过滤**: 结果集强制 `WHERE "user_id" = :uid AND "business_id" = :bid`，且**不回退演示账号、不空结果自愈注入虚构订单**（2026-09-05 收口）；商户租户优先查 `agent_merchant.merchant_orders` 真单（与商户门户「我的订单」列表页同源）。
- **诚实降级（TS 断路语义已改）**: 会话反查为尽力而为——threadId 缺失或查无时回落空 `userId` 与平台缺省商户，查询照常执行并诚实返回空/无归属结果，**不再抛 TS 时代的 `Session threadId is strictly required...` 硬断路异常**；越权防线由「严格归属过滤 + 空结果诚实」承担，而非异常熔断。
- **发货状态过滤**（ADR-0001 Q2）: `UNSHIPPED/SHIPPED/DELIVERED` 非法值诚实报错，严禁静默全量；商户真单与 engine 本地表共用同一纯函数过滤器（`_apply_shipping_filter`），双路永不漂移。

---

_文档编写日期：2026-07-27；2026-09-26 随 Python 移植校正（检索栈 = GLM chat + 本地 bge-small-zh embedding，SQLAlchemy async，FakePool 已退役）_
