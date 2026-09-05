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

### 1.4 指标语义注册表 (`tools_registry/metric_registry.py`)

- **语义消歧**：`MetricSemanticResolver.resolve` 基于同义词词表匹配指标（gmv / volume / gross_profit / margin_rate / stock_risk），最长匹配词优先，泛指模糊提问（"卖得最好"）且未指明具体量度时标记 `hasAmbiguity` 并返回冲突组。
- **SQL 模板渲染**：`render_sql` 以 `str.replace` 填充 dimensions / groupBy / formula / filters / direction / limit 六个占位符；模板与业务规则为冻结词表，与 promptfoo 指标消歧评测（`eval/scorers/metric_disambiguation.py`）联动。

---

## 2. 编码与维护准则

1. **结构化返回**：所有工具执行返回必须符合 `{ success: boolean, data?: any, error?: string, rawCard?: any }` 结构。
2. **零副作用只读默认**：具备写操作属性的工具（如 `processRefund`, `updateShippingAddress`）必须声明 `requiresApproval: true`，由引擎挂起至 HITL 人工审核台。
3. **安全注入校验**：严禁字符串拼接构造 SQL 或 Shell 命令，所有动态入参必须使用参数化绑定。
