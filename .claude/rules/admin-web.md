---
description: Vite 6 SPA 管理后台控制台、11 大路由 CRUD 模块、统一组件套件与 HITL 人工审核台规范
paths: ["apps/admin/**/*"]
---

# 管理控制台应用规范 (Admin Control Plane)

本应用是企业级 SaaS 运营与决策中枢，采用 Vite 6 + React 19 SPA 架构，负责 11 大业务模块的统一 CRUD 管理、实时人工审核与干预、会话接管以及多租户穿透运营。

## 1. 核心架构与模块规范

### 1.1 11 大路由级业务模块(与 `App.tsx` 路由表/Sidebar 一一对应,2026-10-01 校对)

- `/dashboard`：全局指标大盘,六卡库内真算(活跃租户/Autopilot 率/HITL 待审批/LLM 24h),30s 轮询,严禁编造宣传数字。
- `/tenants`：SaaS 多租户管理与商户接入配置(内置域删除保护、SPI/技能/引导配置编辑)。
- `/conversations`：全景会话回放浏览器,支持 Live Desk 人工实时接管、消息发送与结单归档。
- `/audits`：审批与风控审计,HITL 人工审批工作台(状态档位含 `resolved_by_human` 已接管完结)。
- `/personas`：人物画像事实素描,双层画像(scope global/tenant)记忆查询与铸造闸管理。
- `/rag-studio`：知识库与检索演练,Contextual RAG 切片管理 + 在线检索演练台。
- `/skills-tools`：技能与 MCP 工具市场,配置 SOP 门禁、阈值覆盖(退款上限、有效天数等)与开关。
- `/evals`：评测与 Prompt 实验,promptfoo 批次历史与逐用例下钻(真实评测通道,无随机生成)。
- `/billing`：计量计费与配额,Token 用量与月度配额管理。
- `/guardrails`：安全合规与围栏,护栏规则 CRUD。
- `/system-logs`：系统与 LLM 日志,session_metrics/intent_logs 遥测消费,无数据处真实 0。

### 1.2 统一 CRUD 核心组件套件 (`src/components/common/`)

- **`DataTable`**：统一封装加载态、空状态、分页与排序表格。
- **`FilterBar`**：标准多条件搜索、状态筛选与操作按钮栏。
- **`DetailDrawer`**：标准化侧边详情抽屉，支持多 Tab 内容呈现。
- **`FormModal`**：弹窗式数据编辑与创建表单。
- **`ConfirmDialog`**：高危动作二次确认弹窗。
- **`useAdminCrud` Hook**：统一封装列表获取、分页、筛选、创建、更新、删除等状态流。

### 1.3 全局租户穿透与状态治理

- **租户穿透切换器 (`TenantSwitcher`)**：全局 Header 提供租户快速切换，变更时同步更新全局 `tenantId` 状态并自动重刷当前页面数据。
- **只读与操作权限隔离**：所有管理动作在向 API 网关发起请求时必须注入选中的 `tenantId`。

---

## 2. 编码与维护准则

1. **零外部重型 UI 库依赖**：严格使用 `@agent-all/ui` 提供的原子组件与原生 Tailwind CSS 样式，严禁引入未经评审的重型三方组件库。
2. **纯客户端 SPA 架构**：路由采用 `react-router` 客户端路由，数据请求统一使用封装的 API 客户端。
3. **中文界面规范**：所有按钮文案、表格表头、表单提示与状态文案必须使用自然、清晰的中文。
