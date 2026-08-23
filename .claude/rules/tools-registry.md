---
description: 工具注册中心、领域服务层、NL2SQL 安全沙箱、动态 OpenAPI 与 PII 隐私脱敏规范
paths: ["packages/tools/**/*"]
---

# 工具注册中心与领域服务规范 (Tools & Domain Services)

本工作区负责定义 Agent 执行器可调用的外部工具、领域业务服务中台、动态工具安全沙箱以及数据脱敏中间件。

## 1. 核心架构与工具体系

### 1.1 工具注册与生命周期 (`registry.ts`)

- **标准化契约**：每个工具必须使用 Zod 声明入参 Schema（`ToolDefinition`），并在全局 `registerTool()` 中登记。
- **自动注册机制**：工具实例化时自动注入租户上下文与凭证上下文。

### 1.2 领域业务服务中台 (Domain Services)

- **`orderDomainService.ts`**：集中封装订单查询、状态流转、退款核验以及与 `userAddresses` 规范化收货地址的关联组装。
- **`mallDomainService.ts`**：封装多商户商城商品、SKU 库存、物流轨迹流转与售后工单领域逻辑。
- **服务分层要求**：工具层和 API 路由层必须通过领域服务操作数据，严禁在工具内部直接编写裸 SQL 或破坏业务边界。

### 1.3 参数化 NL2SQL 安全沙箱 (`nlQuery/` & `metricRegistry.ts`)

- **AST 只读语法审查**：严格校验 SQL 语法树，物理拦截所有 DDL（`DROP`、`ALTER`、`CREATE`）、DML（`INSERT`、`UPDATE`、`DELETE`）及系统函数（如 `pg_sleep`、`copy`）。
- **参数化编译 (`CompiledSQL`)**：动态指标查询统一编译为带占位符的参数化语句（`{ text: string, values: unknown[] }`），彻底杜绝字符串拼接式 SQL 注入。
- **安全沙箱环境**：
  - 强制开启只读事务：`SET TRANSACTION READ ONLY`
  - 强制执行耗时熔断：`SET LOCAL statement_timeout = '3000ms'`
  - 强制行数封顶保护：强制注入 `LIMIT`（最大限制 50~100 行）
  - 强制多租户约束：强制注入 `WHERE business_id = $1`。

### 1.4 动态 OpenAPI 工具与 SSRF 安全网关 (`openapi/`)

- **动态工具工厂 (`dynamicToolFactory.ts`)**：支持解析商户导入的 OpenAPI 3.0 / Swagger 文档并动态注册为 Agent 工具。
- **SSRF 拦截网关 (`ssrfGuard.ts`)**：
  - 严格拦截请求本地回环地址（`127.0.0.1`、`localhost`）。
  - 严格拦截 RFC 1918 私有内网网段（`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`）。
  - 严格拦截公有云元数据服务（如 AWS/GCP `169.254.169.254`）。
- **KMS 凭证解密 (`crypto/secrets.ts`)**：动态工具的 Authorization Headers 通过 KMS 安全解密，防止明文凭证入库。

### 1.5 PII 隐私脱敏中间件 (`scrubber.ts`)

- **脱敏范围**：中国居民身份证、手机号、电子邮箱、银行卡号、Bearer/Token 凭证。
- **处理要求**：在任何工具入参/出参被写入审计日志、遥测指标或 SSE 事件流前，必须执行 `scrubPii()` 进行物理掩码。

### 1.6 多级工具缓存体系 (`cache.ts`)

- **双模降级缓存**：1 分钟 TTL，优先使用 Redis 缓存；当 Redis 离线时自动无缝降级为内存 `Map` 存储。
- **缓存一致性原则**：任何写操作或状态变更工具（如 `processRefund`）在执行成功后，必须立即触发对应 `orderId` 的缓存失效。

### 1.7 物理截图工具 (`screenshot.tools.ts`)

- 基于 Puppeteer 无头浏览器抓取指定 URL 并生成物理 PNG。
- 图片物理保存于 `apps/web/public/screenshots/`，向状态机返回相对静态路径，禁止在内存或工作流状态中回传大体积 Base64。

---

## 2. 编码与安全准则

1. **统一领域服务复用**：严禁在工具内重复编写跨表 SQL 逻辑，统一调用 `orderDomainService` 或 `mallDomainService`。
2. **只读保护与租户绑定**：所有自然语言 BI 分析工具必须绑定 `CompiledSQL` 模式与只读沙箱。
3. **资源显式释放**：Puppeteer 浏览器实例与外部 HTTP Client 必须在 `finally` 代码块中确保释放，杜绝句柄泄漏。
