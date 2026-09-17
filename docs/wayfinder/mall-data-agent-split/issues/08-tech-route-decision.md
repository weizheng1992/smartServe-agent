# 08: data agent 技术路线拍板

Type: grilling
Status: resolved
Blocked by: 01, 02, 03, 04

## Question

HITL 拍板会话：定死 data agent 的技术路线全案——

- 主路线：A 语义层 / B LLM 动态生成 / C 混合，以及各自边界；
- schema 获取方案（引用 01 号路线对比与 02 号 schema 研究的事实）；
- 口语→领域概念映射的分层（引用 03）；
- SQL 校验链采纳清单（引用 04）；
- 子决议：查询/SQL 的存储策略——语义缓存（相似问句复用）、好查询进 few-shot exemplar 库（复用 intent_exemplars 机制？）、是否入 RAG、口径变更后的失效方向。

产出：决议写入 Answer，明确「首版采纳什么 / 明确不做什么 / 留给实现期的自由度」。

## Answer

决议日期 2026-09-17，用户全盘采纳推荐（Q1–Q5）。

### 公共前提（先于五项决议，同为决议）

- **P1 废除静默兜底**：`MetricSemanticResolver.resolve` 未命中与 `query_product_ranking` 未知指标键的「静默落 gmv」均改为响亮失败 / 澄清反问（数据诚实铁律）。
- **P2 指标定义收敛单一事实源**：3 份漂移副本（metric_registry 全量 / order_domain.METRIC_REGISTRY 简化版 / v2 规格口径描述）收敛回 metric_registry；sqlTemplate 与真实数据源（商户镜像库）对齐，order_domain 私有注册表退役。

### D1 主路线 = C 收敛变体：「A 为唯一执行通道，LLM 只做语义解析、永不写 SQL」

- 执行面 100% 指标模板：fragment 闭集 + bindparams（`query_product_ranking` 已验证模式的推广）+ v2 §3 沙箱（位置参数 / READ ONLY / 3s 超时 / 50 行上限）。
- LLM 的位置在映射层（L3 兜底）：问句 → 结构化查询意图（metric key / 维度 / 方向 / 实体 / 时间窗），不产出 SQL 文本。
- 未建模问题：响亮失败 + 反问（conflictGroup 天然是反问选项集）。
- **不做** text-to-SQL 兜底（首版）；spec 留二期演化缝——若长尾需求真实出现再评估降级通道，且必须标注「非核验口径」（Vanna Function RAG 先例）。
- 时间窗解析为必补缺口（用户感知最强），归 slot/时间解析层，以参数化形态进模板 filters 槽。

### D2 schema 获取 = B（代码静态事实源）为主体

- 编译期生成两份 schema 卡片：商户库 7 表全量（≈1.5k token，从 `_MERCHANT_DDL` 解析）+ engine 分析面白名单 5–8 表（从 models.py 生成）；确定性地进解析上下文，不走检索。
- 运行时 introspection 只做启动期 / CI 漂移断言（不进供给路径；gateway sandbox 本就禁 information_schema）。
- RAG 通道留给口径白话文档；schema 不入 RAG。
- 衍生后续票：「schema 漂移检测与商户库迁移机制」（fog 毕业）。

### D3 口语映射 = L0–L3 四层 + 四关键项

- **L0 同义词归一**（确定性）：metric_registry 改为运行时消费者；补反向词族（最差/垫底→direction=ASC）；废除静默兜底；收编 `PROFIT_RANKING_RE` 散正则；实体/品类词面不重建（mall_domain 已管）。
- **L1 指标口径**：registry 为单一真源；口径文档由 registry **单向生成**入 RAG（category=metric_glossary），禁手写反向编辑。
- **L2 查询示例 few-shot**：**新建 query_exemplars 表**（不扩 intent_exemplars 列，避免污染意图分类语义）；双池 = 全局共享 + 租户；检索照抄 exemplar_service 模式；阈值从 0.05 收紧。
- **L3 LLM 兜底**：低置信反问。
- 新指标（差评/退货率等）登记先后序与 10 号首版清单联动。

### D4 SQL 校验链 = 四层全采纳

- **解析层**：sqlglot 30.x（MIT）——parse_one 捕 ParseError、`parse()` 多语句拒、AST 白名单（仅 SELECT / WITH-SELECT / UNION）、qualify 按卡片解析幻觉表列、函数白名单 + 危险函数黑名单。
- **编译层**：CompiledSQL 位置参数；business_id 谓词服务端注入不可覆盖（编译后 AST 断言确含租户谓词）；LIMIT clamp 1–50 外层包装。
- **DB 层**：只读角色（default_transaction_read_only=on + 白名单表 GRANT SELECT）+ 独立连接池 + SET LOCAL statement_timeout 3000ms + EXPLAIN 成本预算门 + 50 行双保险。
- **呈现层**：分类诚实报错、错误信息对终端用户脱敏（不回显内部 SQL/表结构/堆栈）、细节进审计日志。
- **选型否决**：pglast（GPL-3.0 法务负担，收益边际）；sqlparse（non-validating，不可作安全边界）。
- asyncpg 纪律：全程带参执行（无参 execute 走 simple 协议允许多语句）。
- **前置工程项入 spec**：先拆 `_merchant_reader_engine` 读写共用引擎（UPDATE 与读同引擎），再落只读池。

### D5 查询/SQL 存储 = 「SQL 不入 RAG」三件套

- **语义缓存**：缓存对象是「问句 → 已验证的结构化查询意图（含 SQL 计划指纹）」，非裸 SQL 文本；先做每租户阈值校准（零训练），bge 微调缓行（衔接 05 号结论）。
- **回流**：命中且执行成功的解析结果回流 query_exemplars（few-shot 语义，非 RAG 语义）。
- **失效方向**：registry 口径指纹变更 → 缓存与示例标 stale；时间敏感问句（「上个月」）按时间窗指纹区分或不缓存（细则留实现期）。

### 明确不做（首版）

text-to-SQL 兜底通道、schema 入 RAG、pglast、intent_exemplars 扩列、口径文档手写双向编辑、异步全量 DDL introspection 供给。
