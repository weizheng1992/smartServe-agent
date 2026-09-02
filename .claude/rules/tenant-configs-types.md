---
description: 多租户业务配置注册中心、分层参数合并策略与前端契约类型规范
paths: ["packages/types/**/*", "services/engine-py/src/engine_py/tenant_config.py", "services/engine-py/src/engine_py/tenant.py"]
---

# 租户配置与前端契约类型规范 (Configs & Types)

本模块负责多租户业务策略注册配置（`services/engine-py/src/engine_py/tenant_config.py`，原 `packages/business-configs` 移植）以及前端共享契约类型（`packages/types`，冻结保留）。

## 1. 核心体系与实现规范

### 1.1 租户业务配置注册中心

- **分层配置合并模型**：
  - 系统内置默认策略（`defaultBusinessConfig`）➔ 租户全局重载（DB `tenants.skills_config`）➔ 技能级个性化配置（`TenantSkillOverride`）。
- **核心业务配置项**：
  - 自动退款金额上限 (`maxAutoRefundAmount`)
  - 退款时效窗口 (`maxRefundDays`)
  - HITL 人工审核门禁策略 (`requireApprovalOnAddressChange`, `requireApprovalOnRefund`)
  - 启用的技能清单 (`enabledSkills`) 与技能自定义 SOP 参数
- **冷启动容错**：DB 加载失败时降级至内置默认配置并 print 告警，不得阻断状态机。

### 1.2 前端契约类型系统 (`packages/types`)

- 后端 Python 化后，本包定位变更为**冻结的前端共享契约**（web / admin / merchant 三个 TS 应用统一导入），不再随后端演进自由扩展。
- **`skill.ts`**：技能元数据、阶段生命周期、SOP 策略及上下文类型契约。
- **`config.ts`**：多租户配置结构、租户实体模型及覆盖接口。
- **`agent.ts` / `cards.ts`**：智能体执行状态、规划任务项、多模态富交互卡片结构。
- **`approval.ts`**：HITL 审批单、发件箱事件、决策结果类型。
- **`tool.ts`**：工具定义规范、入参校验 Schema 与执行上下文。

---

## 2. 编码与维护准则

1. **强类型安全与单一来源**：前端跨应用交互的数据结构必须从 `packages/types` 统一导入，严禁在业务包内随意重复定义同名接口；契约变更必须同步 pytest 契约测试（`services/gateway-py/tests/`）。
2. **零运行时外部包依赖**：`packages/types` 仅依赖 zod，保持纯类型 + 校验 schema 定义，避免引入带副作用的运行时重型依赖。
3. **向后兼容性**：新增配置项与类型属性时，需保持可选（Optional）或提供合理默认值，确保系统升级平滑。
