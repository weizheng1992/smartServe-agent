# 04: SQL 动态拼接与安全执行机制（data agent）

Type: research
Status: resolved

## Question

无论主路线如何（01 号票），只要存在 SQL 的动态拼装或生成，就需要一条安全与工程机制链。调研并给出推荐清单：

- **参数化模板拼装**：现有 metric_registry sqlTemplate 的参数面设计与 `order_domain.py` 手写聚合的拼装模式，如何扩展维度/过滤/排序而不失守；
- **LLM 生成 SQL 的校验链**（web 调研业界实践）：SQLGlot（或等价库）解析 + AST 白名单校验（只允许 SELECT/聚合、禁 DML/DDL）、EXPLAIN 预算/超时、强制 LIMIT、business_id 租户过滤强制注入（不可被用户输入覆盖）、只读 DB 角色/独立连接池；
- **失败兜底与诚实呈现**：非法/超预算 SQL 的用户侧反馈（诚实报错不开幻觉数据——本项目数据诚实铁律同样适用于 data agent）；
- 参照 v2 `NLMetricQueryEngine` 规格中的参数化编译与多租户边界设计（`docs/specs/production-resiliency-and-multi-tenant-safety.md`）。

产出：推荐校验链的分层清单（DB 层/解析层/编译层/呈现层各挡什么）与 Python 生态落地选型事实。不拍板。

## Answer

### 1. 本仓现状事实（已精读核实）

- `metric_registry.py::render_sql` 的六个槽位 `{dimensions}/{formula}/{filters}/{groupBy}/{direction}/{limit}` 全是 `str.replace` 裸拼接：`filters` 是整段 SQL 字符串、`direction` 自由字符串、`limit` 类型 `int | str`（str 原样透传）——任一槽位将来接 LLM 输出即成注入面。但每指标已有 `availableDimensions` 白名单与 `permissionTag`，可直接作维度校验依据；`sqlTemplate` 目前无租户过滤槽位（products 路径无 business_id 谓词），是与 v2 规格的差距点。
- `order_domain.py::query_product_ranking` 是本仓已验证的安全拼装样板：**结构片段全部由代码侧闭集枚举**（metric_expr 按 registry key if/elif 选定、`category_clause`/`having_clause` 为固定字符串、direction 取自 registry 而非用户），**用户值全部 bindparams**（`:lim`/`:cat`）；子查询先按 spu_id 预聚合防笛卡尔放大；`WHERE o.status NOT IN ('REFUNDED','CANCELLED')` 保口径诚实。
- 隐患事实：`_merchant_reader_engine()` 同一引擎既读又写（`_update_merchant_order` 用它 `.begin()` 跑 UPDATE）——"只读连接池"落地前必须先拆读写引擎。
- v2 规格（`docs/specs/production-resiliency-and-multi-tenant-safety.md`）已定：`CompiledSQL {text, values}` 位置参数（租户 ID/manager ID/过滤值/limit 均为 `$n`）；`executeReadOnlyAnalyticsQuery` 内 `SET TRANSACTION READ ONLY` + `SET LOCAL statement_timeout='3000ms'` + 50 行绝对上限；对抗样例 `' OR 1=1; DROP TABLE products; --` 必须安全留在 values 数组里。

### 2. 扩展维度/过滤/排序而不失守的核心原则

LLM 只产出"结构意图键"，不产出 SQL 片段：维度、指标、排序方向、过滤字段名全部映射到注册表闭集键（键→fragment 枚举），过滤值/limit 走绑定参数。即 query_product_ranking 模式的推广——**fragment 闭集白名单 + 值参数化，二者缺一不可**。

### 3. 推荐校验链分层清单（不拍板，供 08 号票取舍）

**解析层**（挡：语法错误、多语句、DML/DDL、幻觉表列、危险函数）
- `sqlglot.parse_one(sql, read="postgres")` 捕 `ParseError` 拒；用 `sqlglot.parse()` 取完整 list，长度≠1 → 多语句拒。
- 根节点 AST 白名单：仅 `exp.Select`/`exp.Union`（含 `exp.With` 时 CTE body 也须 SELECT）；遍历拒绝 Insert/Update/Delete/Merge/Create/Drop/Alter/Truncate/Grant/Copy 等一切写节点。
- `sqlglot.optimizer.qualify(expr, schema)` 展开 `SELECT *` 并按 schema 解析全部表/列 → 对照语义白名单（schema 知识来自 02 号票）；未知表/列即拒（顺带挡幻觉表列）。
- 函数白名单：SUM/COUNT/MIN/MAX/AVG/COALESCE/NULLIF/CASE；黑名单兜底 pg_sleep/dblink/pg_read_file/lo_import。

**编译层**（挡：SQL 注入、租户越权、无界查询）
- 输出 v2 的 `CompiledSQL {text, values}`：所有用户/LLM 值位置参数化；维度/方向/limit 由闭集解析，limit 强制 clamp 1–50。
- business_id/manager_id 谓词由服务端从会话上下文（`get_thread_session_context` 同源）注入，用户与 LLM 均不可触达该槽位；编译后可用 sqlglot 断言 AST 确含租户谓词——注入不可被覆盖且可验证。
- 强制 LIMIT：外层包装最稳（outer SELECT + LIMIT），`sqlglot.optimizer.limit` 可向子查询传播，防内层无界扫描。

**DB 层**（挡：写、超时、资源耗尽——上层全部失守的最后防线）
- 独立只读角色：`CREATE ROLE ... default_transaction_read_only=on` + 仅 GRANT SELECT 白名单表；事务内再 `SET TRANSACTION READ ONLY` 双保险（v2 规格）。
- 独立连接池（须与现 `_merchant_reader_engine` 写穿路径拆分），小 pool_size + max_overflow=0 + pool_pre_ping，与业务事务池物理隔离。
- `statement_timeout=3000ms`（SET LOCAL / asyncpg `server_settings` / role 级任一）；执行前 `EXPLAIN (FORMAT JSON)` 取 Total Cost 做预算门（cost 单位是估值非毫秒，阈值按负载经验标定）；行数 50 上限双保险（LIMIT + fetch 截断）。

**呈现层**（挡：幻觉数据、误导呈现——数据诚实铁律落点）
- 解析/白名单失败 → 分类诚实报错（"仅支持查询类问题"/"维度不存在，可选维度为…"），严禁 LLM 编造结果集。
- 超预算/超时 → 如实"查询过于复杂/超时，请缩小时间范围或维度"，不静默降级为估算或编造（`cost_at_purchase` "漏写即报错可见"、零销量不进榜是同款先例）。
- 错误信息对终端用户脱敏：不回显内部 SQL/表结构/堆栈；细节进审计日志，用户侧只给可行动指引。

### 4. Python 生态落地选型事实

| 库 | 版本/日期 | 许可 | 维护状态 | 适配点 |
|---|---|---|---|---|
| sqlglot | 30.18.0（2026-09-03） | MIT | Toby Mao / TobikoData（SQLMesh 背后）持续高频发版；零依赖；Superset/Dagster/Ibis/dlt 在用；mypyc 编译变体快 3–5x | 解析 + AST 白名单 + qualify 列解析；注意其本质是宽松 transpiler 而非严格 validator，必须配白名单遍历兜底 |
| pglast | 8.4（2026-07-22） | GPL-3.0-or-later | Lele Gaifax 持续维护，包 libpg_query（真实 PG 语法），Python 3.10–3.14 预编译轮子 | 可选的严格二次解析校验；GPL 许可商用需法务过目（SaaS 服务端不分发通常可接受） |
| sqlparse | 长期 0.5.x | BSD | 维护稀疏，README 自述 non-validating parser | 仅格式化/分词，不得作为安全边界 |
| Guardrails AI Hub（exclude_sql_predicates 等 validator） | — | — | 社区活跃 | 依赖 sqlglot 的现成 SQL validator，可作参考实现 |

执行侧现有组合即够：SQLAlchemy `text().bindparams` + asyncpg——带绑定参数走扩展协议天然单语句；**注意 asyncpg 无参 `execute()` 走 simple 协议允许分号分隔多语句**，全链路必须保持带参执行。

### Sources

- [sqlglot PyPI](https://pypi.org/project/sqlglot/) / [GitHub tobymao/sqlglot](https://github.com/tobymao/sqlglot)
- [pglast PyPI](https://pypi.org/project/pglast/)
- [From Regex to Deterministic Control: Building a SQL Gateway with sqlglot](https://medium.com/@balajibal/from-regex-to-deterministic-control-building-a-sql-gateway-with-sqlglot-8f0aee90d7e0)
- [SQL Parsing and Validation for LLMs (Towards AI)](https://pub.towardsai.net/sql-parsing-and-validation-for-llms-a-comprehensive-guide-4e33aef586cc)
- [Guardrails AI — Exclude SQL Predicates Validator](https://guardrailsai.com/hub/validator/guardrails/exclude_sql_predicates)
- [Build Analytics SQL Agent: Safe, Cost-Aware SQL (Towards AI)](https://pub.towardsai.net/build-analytics-sql-agent-natural-language-safe-cost-aware-sql-7d52fb373994)
