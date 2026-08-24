---
description: NestJS 多租户 API 网关、实时会话与人工协同接入、Skills 配置管理接口规范
paths: ["apps/server/**/*"]
---

# 服务端多租户网关与实时协同规范 (Server Gateway)

本应用是整个平台的服务端 API 网关，基于 NestJS 框架构建，负责多租户路由转发、实时人工客服协同接管 (Live Takeover)、Skills 技能与工具配置同步、会话流式推送与审计追踪。

## 1. 核心模块与架构规范

### 1.1 模块职责划分

1. **`AppModule`**：主入口模块，统一装配路由、全局异常过滤器、日志中间件与 CORS 配置。
2. **`ConversationsModule`**：
   - 会话历史列表查询与详情检索（多租户过滤）。
   - 人工坐席实时接入接管（`takeover` / `release`），同步修改会话 `is_takeover` 标记与坐席 ID。
   - 人工消息发送接口，即时推送至客户端并沉淀至 `messages` 物理表。
3. **`SkillsModule`**：
   - 技能注册中心同步与能力发现（元数据、依赖工具、SOP 策略）。
   - 租户级技能参数覆盖配置读取与更新（`GET/PUT /api/skills/config`）。
4. **`ApprovalsModule`**：
   - HITL 挂起审批单拉取与审核处理（Approve / Reject）。
   - 触发事务发件箱与工作流幂等恢复任务。

### 1.2 多租户鉴权与上下文传递

- **租户识别中间件/Guard**：通过 Request Header（如 `x-tenant-id`, `x-business-id`）或 Bearer Token 解析租户上下文。
- **请求生命周期隔离**：所有 Controller 和 Service 注入方法必须显式接收并传递 `tenantId`，严禁使用全局静态变量承载租户状态。

### 1.3 统一响应与异常处理规范

- **统一 JSON 响应格式**：`{ success: boolean, data?: any, error?: string, message?: string }`。
- **业务异常与 HTTP 状态码**：非法租户返回 403 Forbidden，资源未找到返回 404 Not Found，参数校验失败返回 400 Bad Request。

---

## 2. 编码与维护准则

1. **强依赖注入与模块化**：遵循 NestJS 依赖注入设计，跨模块调用通过 Module 显式导出和导入 Service。
2. **DTO 严格校验**：所有接收客户端输入的主体对象必须使用 `class-validator` 或 TypeScript 类型接口定义清晰的 DTO。
3. **测试覆盖**：新增 Controller 或 Service 时，必须配套编写单元测试（`*.test.ts` 或 `*.spec.ts`），覆盖多租户参数和异常分支。
