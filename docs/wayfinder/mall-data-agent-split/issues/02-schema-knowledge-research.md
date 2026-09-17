# 02: schema 知识获取方案（data agent）

Type: research
Status: resolved

## Question

data agent 如何获取并持有「数据库结构」这份知识，供口径解析与 SQL 生成使用？涉及两个物理库：engine 本地库（SQLAlchemy models 36 表，`services/engine-py/src/engine_py/db/models.py`）与商户物理库 agent_merchant（DDL 在 `services/gateway-py/src/gateway_py/merchant_db.py`：merchant_spus / merchant_skus / merchant_customers / merchant_orders / merchant_order_items / merchant_product_reviews / merchant_audit_logs）。

对比三方案：

- **A 运行时 introspection**：information_schema / SQLAlchemy inspect，查询时实时取结构；
- **B 代码静态事实源**：SQLAlchemy models + merchant_db DDL 即 schema 快照，随代码版本走，编译期生成结构描述喂给解析层/LLM；
- **C DDL 文档化入 RAG**：把表结构/口径文档作为知识文件进 `rag_documents` 通道，检索式供给（参照现有 KnowledgeEngine 混合检索）。

评估维度：时效性（商户库 schema 演化后的漂移检测与同步）、token/延迟成本、多租户差异（商户库 DDL 是否随商户不同）、与 metric_registry 口径定义的耦合方式。产出事实对比与初步倾向（供 08 号拍板引用），并指出「schema 演化同步机制」应作为后续票还是本方案内含。不拍板。

## Answer

### 1. 两库 schema 定义方式（代码事实）

- **engine 本地库**：SQLAlchemy declarative models，36 表（`services/engine-py/src/engine_py/db/models.py`，635 行），且有真迁移链 alembic（`services/engine-py/alembic/versions/` 0001_baseline…0010 共 10 版，`target_metadata = Base.metadata`）。schema 事实源 = models.py 代码，演进走迁移脚本，PR 可 diff、可 review。
- **商户库 agent_merchant**：无 ORM、无 alembic。全部结构是一个幂等 DDL 字符串 `_MERCHANT_DDL`（`services/gateway-py/src/gateway_py/merchant_db.py` L16-122，7 表 + 2 条 `ALTER … ADD COLUMN IF NOT EXISTS` + product_reviews 增表）。gateway 侧 `ensure_merchant_tables()` 在启动/domain 调用时重放该脚本（simple-query 协议、缺库自愈 CREATE DATABASE）。演进方式 = 直接改字符串；历史靠内嵌注释（ADR-0003、2026-09-13），`IF NOT EXISTS` 语义只能增不能删改——代码与已部署库可能漂移（删列/改型不生效）。
- **多租户事实：当前不存在 per-商户 schema 差异**。merchant 7 表均无 business_id/租户列；一个部署只有一个 `agent_merchant`（`MERCHANT_DATABASE_URL` 单值），gateway 全局单 engine 与 engine 侧 `_merchant_reader_engine()`（lru_cache maxsize=1，`order_domain.py` L45）指向同一物理库。「每商户一套 DDL」是假想场景，未在代码中留任何钩子。对照：RAG 知识倒是按 business_id 物理隔离（rag_documents + docs/knowledge frontmatter）。
- **口径耦合现状（关键）**：`metric_registry.py` 的 METRIC_SEMANTIC_REGISTRY 里，label/synonyms/description/businessRules/direction/unit 是 DB 无关元数据，但 `sourceTables/expression/sqlTemplate` 硬编码的是 **engine 本地表** products/order_items/orders 及列 `oi.price_at_purchase / oi.cost_at_purchase / p.cost_price`。而实际排行查询 `queryProductRanking`（order_domain.py ~L1000-1108）**完全不用 sqlTemplate**，手写 SQL 打商户库（merchant_spus/skus/order_items/orders），口径修正（排除 REFUNDED/CANCELLED、明细预聚合防笛卡尔）都发生在手写 SQL 里。即：口径已是「registry 元数据复用 + SQL 按库手写」的双轨制——schema 知识方案必须与这个现状对齐，而不是假设 sqlTemplate 是活路径。
- **沙箱约束（直接影响方案 A）**：gateway 分析沙箱 `sandbox.py` 用 sqlglot AST 只放行单条 SELECT/WITH，并**显式阻断 information_schema / pg_catalog / pg_ 前缀**（L28），执行面是 engine 本地库。→ LLM 生成「查 information_schema」的 SQL 被现有安全策略直接禁止；运行时 introspection 只能做成显式代码层工具（SQLAlchemy `inspect`），不能走 NL2SQL 通道。

### 2. 三方案事实对比

| 维度 | A 运行时 introspection | B 代码静态事实源 | C DDL 文档化入 RAG |
|---|---|---|---|
| 时效性 | 永远反映物理库真身（含手工漂移）；但本项目事实源是代码 DDL，库是代码的产物，「真身」可能把未评审的手工改动合法化 | 部署即同步（gateway 启动重放 DDL；engine 走 alembic），一致性由部署机制保证；漂移检测转为一次性/启动期断言而非供给路径 | 文档与代码成为**双份事实源**，人手同步必滞后；与本仓库自己修过的坑同构（knowledge_files「不回退内联写死内容，否则与种子漂移成两套知识」） |
| token/延迟 | 每次查询多一轮目录访问（几十 ms）+ 结果裁剪逻辑；全量 36+7 表 dump 必须裁剪，裁剪本身是复杂度 | 编译期从 models.py + `_MERCHANT_DDL` 生成紧凑「schema 卡片」：商户库 7 表全量 ≈1.5k token；engine 侧按分析面白名单裁剪（orders/products/order_items/product_skus/product_reviews 等 5-8 张）≈1-2k token。确定、可测、零运行时开销 | 按需检索最省 token；但 schema 是 SQL 生成的**必要前提**，top-k 漏检一张关联表 = 直接错 SQL，确定性不足 |
| 多租户差异 | 天然支持每库各自 introspect（未来每商户一库时才需要） | 当前单 schema 零成本；未来分库也必然先改代码路由，届时快照随路由一起分版本 | KnowledgeEngine 按租户隔离（business_id），全局性的 schema 要么每商户复制播种要么开全局通道，别扭 |
| 与 metric_registry 耦合 | 无一致性保证：registry 硬编码列名与 introspect 结果各说各话 | 同仓同版本；可做**编译期校验**——registry expression 引用的列必须在 schema 卡片中存在（防「registry 说 cost_at_purchase 而快照没有」） | 检索命中与否决定口径元数据是否到场，口径解析路径变得概率性 |
| 与现有 RAG 基建契合度 | — | — | MarkdownChunker 按标题/空行 500 字符贪心切块，会把 CREATE TABLE 拦腰切断；headerPath 语义不适配 DDL，需新切块器 |

### 3. 业界实践（少量 web 调研）

- Pinterest 生产级 Text-to-SQL：prompt 中放**经列裁剪后选定的表 schema**，pruning 是流水线独立阶段，而非全量 dump 或检索。
- 学术/工业共识：schema linking / pruning 先行（两阶段），全量 DDL 直塞 prompt 只对小 schema 可行——本项目恰好是小 schema（商户 7 表、本地分析面 <10 表）。
- Vanna.ai 的 DDL 入 RAG 模式面向几百上千表的场景（training plan = information_schema 切块），对 7 表库属于过度设计，且牺牲确定性。
- 结论印证：小 schema 用「裁剪后的静态 DDL 进 prompt」是主流；introspection 的合理位置是**漂移检测/元数据刷新**，不是每次查询的供给路径。

### 4. 初步倾向（不拍板，供 08 引用）

**B 为主体，A 缩限为漂移检测断言，C 让位给口径文档而非 schema**：

1. schema 知识 = 编译期生成的两份「schema 卡片」（商户库从 `_MERCHANT_DDL` 解析；本地库从 models.py 选分析面子集生成，含表/列/类型/注释/FK），随代码版本走，喂给口径解析与 SQL 生成。
2. 运行时 introspection 不进供给路径（且被 sandbox 策略排除），只做**启动期/CI 漂移断言**：`inspect` 结果 vs 代码事实源 diff，不一致即报警——这同时覆盖了「手工改库」与「IF NOT EXISTS 无法删改列」两类漂移。
3. metric_registry 重构时（08 的邻接决策）：expression/sqlTemplate 与 schema 卡片做编译期列名一致性校验；DB 无关元数据与 DB 相关 SQL 表达分层。
4. RAG 通道保留给**口径/业务规则白话文档**（metric description、businessRules、字段业务含义），那是会增长、需要语义检索的部分；schema 是有界、必须确定性在场的事实，不走检索。

### 5. schema 演化同步机制：后续票，不内含

理由：①它是横切关注点（商户库要不要上 alembic / 启动期 diff 断言 / 删列语义），独立于「schema 怎么供给 LLM」可并行推进；②02 的产出（卡片生成器）不依赖其最终形态，只需把「事实源接口」抽象成可从代码或断言结果读取；③若内含会把 research 票拖成 implementation 票。建议 08 拍板后立刻开「schema 漂移检测与商户库迁移机制」票，阻塞关系：卡片生成器不阻塞，断言接入阻塞于该票。

### Sources

- [Pinterest Engineering: How we built Text-to-SQL](https://medium.com/pinterest-engineering/how-we-built-text-to-sql-at-pinterest-30bad30dabff)
- [Schema Pruning for Text-to-SQL (deterministic, FK-graph)](https://www.nirmalya.net/posts/2026/02/text-to-sql-schema-pruning/)
- [Vanna.AI: How to Train (DDL training plan)](https://try.vanna.ai/docs/train/)
- [Google Cloud: Techniques for improving text-to-SQL](https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql)
- [OpenReview: Enhancing Text-to-SQL with Open-source LLMs (schema linking)](https://openreview.net/pdf?id=jkYV7OGNoI)
