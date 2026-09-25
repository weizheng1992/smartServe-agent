---
description: 工具注册中心、标准 SPI/MCP 连接器、AST NL2SQL 安全沙箱与指标语义注册表规范
paths: ["services/engine-py/src/engine_py/tools_registry/**/*", "services/gateway-py/src/gateway_py/routers/spi.py", "services/gateway-py/src/gateway_py/sandbox.py", "services/gateway-py/src/gateway_py/hmac_signer.py"]
---

# 工具生态与安全沙箱规范 (Tools & Sandboxes)

本模块负责智能体外部工具注册中心（`services/engine-py/src/engine_py/tools_registry/`）、标准 SPI 开放连接器（`services/gateway-py/src/gateway_py/`）、只读 AST NL2SQL 分析沙箱及指标语义注册表。

## 1. 核心架构与工具分类

### 1.1 工具注册中心架构

- **标准工具契约**：所有工具必须实现统一契约，包含 `name`、`description`、`parameters` (JSON Schema) 和 `execute(params, context)` 协程方法。
- **租户上下文传递**：执行环境通过 `ToolExecutionContext` 强制注入 `business_id`、`user_id`、`thread_id`，确保工具执行天然具备多租户约束。
- **域服务分层**：`order_domain.py` / `mall_domain.py` 承载订单与商城领域查询；`ecommerce_tools.py` 组装为可执行工具；`cache.py` 提供工具级缓存。
- **商品检索降级链（2026-09-11 L3/L2，2026-09-12 L4，症状「推荐背包热销」给了 Nike 跑鞋）**：`search_products` / `compare_products` / SPI `search_products` 统一走 **商户真货架（词元 ILIKE → 语义余弦补位 → L4 词表锚定改写重试）→ engine 本地 `products` 表 → 诚实空** 链路；单商户现实下全租户统一路由（含 ecommerce，商户表无租户列）。**search 路径严禁 mock 目录兜底**（`MOCK_PRODUCTS` 假目录与 `compare_products` 硬编码拼接已拆除——假货不得冒充推荐，库可达但查无必须诚实空，不得跨目录补货）。词元提取经 `_extract_query_terms` 剥导购 wrapper 词（修饰词族一律短语形，「比较」裸词会残留「好」拉入无关商品）+ `_expand_stem_aliases` 词干别名展开（2026-09-12：口语统称「裤子/鞋子」→ 追加货架词素「裤/鞋」OR 词元——货架命名「工装裤/慢跑裤/老爹鞋」四列不含「裤子/鞋子」子串，ILIKE 永远擦肩；显式小词表而非通用剥「子」，电子/种子类词剥后语义漂移）；SPU 展示价 = MIN(sku.price)、库存 = SUM(sku.stock)，无 SKU 的 SPU 经 `HAVING MIN IS NOT NULL` 排除。**L2 语义补位（2026-09-11）**：词元查空且原始 NL 非空时，对硬过滤候选池做 bge 余弦 top-k（`AI_MALL_SEMANTIC_ENABLED` 默认开、`AI_MALL_SEMANTIC_MIN_SIMILARITY` 默认 0.55——真 bge-small-zh 实测定标：正例 0.56-0.58 / 无关 0.36-0.45），命中按相似度 DESC；SPU 嵌入进程内缓存按文案 sha256 失效（商户改文案下轮自动重嵌）；嵌入异常/不可用降级诚实空，绝不阻断检索；纯浏览形输入不走语义。**L4 词表锚定改写重试（2026-09-12，症状「卖的好的背心」词元+语义双空）**：双空后 `_rewrite_query_terms` 以 `get_shelf_overview()` 品类词表为锚调一次 LLM（`_invoke_rewrite_llm` 独立静态方法=测试桩点），把口语措辞映射成货架检索词元（只允许产出词表品类词或常见叫法，防跨目录自由发挥）再 `_fetch_merchant_catalog` 重试一次；`AI_MALL_QUERY_REWRITE_ENABLED` 默认开、`AI_MALL_QUERY_REWRITE_TIMEOUT_SECONDS` 默认 2.0，超时/异常/脏输出降级空表，检索链终点始终是诚实空；重试词元同样经 `_expand_stem_aliases` 展开；纯浏览形输入不进 L4。**诚实空品类盘点（2026-09-12）**：`get_shelf_overview()` 在售 SPU 按品类聚合计数（OFF_SALE 不计数，库不可达返回空），`ShoppingGuideSkill` / `ProductInquirySkill` 空分支把「调整关键词」升级为「目前店内热卖品类：背包收纳(2款)…」——剩余诚实空从冷场变成可点选的真实方向，盘点描述商户店内、严禁跨目录拼数。热销排序**不做**（merchant 库无销量列，全仓亦无 sales_volume），词元/浏览路径排序 min_price ASC 系已文档化限制，严禁合成假热度。行为由 `tests/test_merchant_catalog_reach.py`（密封商户库 + 桩嵌入 + 密封改写 LLM）与 `tests/test_mall_search_terms.py`（词元单测 + engine 降级分支）钉死。

### 1.2 开放集成与标准 SPI/MCP 连接器

- **分层调用管道**：遵循 `Planner ➔ Skill ➔ SPI/MCP Connector ➔ Remote Service/DB` 分层，业务逻辑下沉至 Skill（`skills/spi_client.py` 负责连接与协议适配），工具只负责连接。
- **安全防护与 HMAC 签名**（`gateway_py/hmac_signer.py`）：
  - 外部服务调用必须校验 HMAC-SHA256 签名与时间戳（防重放攻击，窗口 ≤ 300 秒）。
  - 内置 SSRF 白名单防护网关，阻断私有内网 IP（`10.0.0.0/8`, `127.0.0.0/8`, `192.168.0.0/16`）的非法穿透。

### 1.3 AST 参数化只读 NL2SQL 沙箱 (`gateway_py/sandbox.py`)

- **AST 语法树只读审计**：通过 SQL Parser（sqlglot）将 LLM 生成的 SQL 解析为抽象语法树（AST）。
- **硬性安全防护**：
  - 严禁包含 `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT` 等写语句。
  - 强制注入只读保护：`LIMIT 50`。
  - 阻断系统表穿透（`information_schema`, `pg_catalog` 等，限定名 catalog/db/name 逐段比对）。
- **租户边界注入：未实现（2026-09-05 盘点）**：沙箱当前**不注入** `AND business_id = :tenantId`（TS 基线亦无此行为，属文档先行于实现）。沙箱零调用方；NL2SQL 真正接入时必须先补齐——需按表内省 `business_id` 列后改写 WHERE,届时调用方以参数化绑定传租户值，严禁字符串拼接。在此之前任何调用方必须自行携带租户过滤条件。

### 1.4 指标语义注册表 (`tools_registry/metric_registry.py` + `metrics.yaml`,2026-09-25 校对)

- **闭集事实源 = `metrics.yaml`**：**37 指标 × 8 域**（sales 13 / customer 7 / promotion 5 / inventory 3 / review 3 / refund 2 / profit 2 / session 2），每条带 label/description/expression/sqlTemplate/businessRules/unit/aliases/synonyms/`permissionTag`/sampleQueries。`metric_registry.py` 只做**加载与校验**（缺必填键/空表/key 与条目名不一致一律 raise 响亮失败，不静默跳过），导出 `METRIC_SEMANTIC_REGISTRY`。
- **消费方**：Data Agent 分析管线经 `analytics/tools_registry_bridge.py`（防 tools_registry ↔ analytics 循环导入的桥）读取；意图解析在 `analytics/engine.py::MetricQueryEngine.resolve`（L0 词表 → 缝②小模型 → L2 范例 → L3 LLM 分层，详见 agent-engine.md §1.9）；SQL 由闭集模板编译渲染（dimensions/groupBy/formula/filters/direction/limit 占位符），经 `analytics/sql_guard.py` AST 审计后执行。
- **评测联动**：与 promptfoo 指标消歧评测（`eval/scorers/metric_disambiguation.py`）共用同一词表。

---

## 2. 编码与维护准则

1. **结构化返回**：所有工具执行返回必须符合 `{ success: boolean, data?: any, error?: string, rawCard?: any }` 结构。
2. **零副作用只读默认**：具备写操作属性的工具（如 `processRefund`, `updateShippingAddress`）必须声明 `requiresApproval: true`，由引擎挂起至 HITL 人工审核台。豁免口径（2026-09-13）：资金/订单操作（退款、改单地址）走 HITL；顾客自有资产操作（地址簿管理 `saveUserAddress`、购物车结算 `checkoutCart`）与商城前台同权免审 —— 二者执行面均有确定性快路径与库级对账测试钉死，checkoutCart 为 all-or-nothing 条件扣减（防超卖）。
3. **安全注入校验**：严禁字符串拼接构造 SQL 或 Shell 命令，所有动态入参必须使用参数化绑定。
