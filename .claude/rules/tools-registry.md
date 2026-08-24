---
description: 工具注册中心、标准 SPI/MCP 连接器、AST NL2SQL 安全沙箱与 Puppeteer 工具规范
paths: ["packages/tools/**/*"]
---

# 工具生态与安全沙箱规范 (Tools & Sandboxes)

本工作区负责智能体外部工具注册中心、动态 OpenAPI 生成工具、标准 SPI/MCP 开放连接器、只读 AST NL2SQL 分析沙箱及浏览器自动化工具。

## 1. 核心架构与工具分类

### 1.1 工具注册中心架构 (`registry.ts`)

- **标准工具契约**：所有工具必须实现 `ToolDefinition` 接口，包含 `name`、`description`、`parameters` (JSON Schema) 和 `execute(params, context)` 方法。
- **租户上下文传递**：执行环境通过 `ToolExecutionContext` 强制注入 `businessId`、`userId`、`threadId`，确保工具执行天然具备多租户约束。

### 1.2 开放集成与标准 SPI/MCP 连接器

- **分层调用管道**：遵循 `Planner ➔ Skill ➔ MCP/SPI Connector ➔ Remote Service/DB` 分层，业务逻辑下沉至 Skill，工具只负责连接与协议适配。
- **安全防护与 HMAC 签名**：
  - 外部服务调用必须校验 HMAC-SHA256 签名与时间戳（防重放攻击，窗口 $\le 300$ 秒）。
  - 内置 SSRF 白名单防护网关，阻断私有内网 IP（`10.0.0.0/8`, `127.0.0.0/8`, `192.168.0.0/16`）的非法穿透。

### 1.3 AST 参数化只读 NL2SQL 沙箱 (`nl2sql.ts`)

- **AST 语法树只读审计**：通过 SQL Parser 将 LLM 生成的 SQL 解析为抽象语法树（AST）。
- **硬性安全防护**：
  - 严禁包含 `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT` 等写语句。
  - 强制注入多租户隔离条件：`AND business_id = :tenantId`。
  - 强制注入只读保护：`LIMIT 50`。
  - 阻断系统表穿透（`information_schema`, `pg_catalog` 等）。

### 1.4 声明式 OpenAPI 动态工具生成

- 支持解析三方 OpenAPI 3.0 / Swagger JSON 规范，自动编译成具备完整类型校验的 LangGraph 外部执行工具。
- 敏感认证配置与 API Key 均需通过 KMS 加密落盘与解密使用。

### 1.5 浏览器自动化工具 (Puppeteer)

- 截图与渲染工具必须运行在无头沙箱隔离模式（`--no-sandbox`, `--disable-setuid-sandbox`）。
- 严格限制单次渲染超时时间（5000ms），避免卡死 Agent 主执行流水线。

---

## 2. 编码与维护准则

1. **结构化返回**：所有工具执行返回必须符合 `{ success: boolean, data?: any, error?: string, rawCard?: any }` 结构。
2. **零副作用只读默认**：具备写操作属性的工具（如 `processRefund`, `updateShippingAddress`）必须声明 `requiresApproval: true`，由引擎挂起至 HITL 人工审核台。
3. **安全注入校验**：严禁字符串拼接构造 SQL 或 Shell 命令，所有动态入参必须使用参数化绑定。
