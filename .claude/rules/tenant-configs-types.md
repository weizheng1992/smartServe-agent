---
description: 多租户业务配置注册中心、分层参数合并策略与跨包共享 TypeScript 类型规范
paths: ["packages/business-configs/**/*", "packages/types/**/*"]
---

# 租户配置与跨包共享契约规范 (Configs & Types)

本工作区负责全系统的多租户业务策略注册配置 (`packages/business-configs`) 以及整个 Monorepo 的类型基石 (`packages/types`)。

## 1. 核心体系与实现规范

### 1.1 租户业务配置注册中心 (`tenantRegistryService.ts`)

- **分层配置合并模型**：
  - 系统内置默认策略（`defaultBusinessConfig`）➔ 租户全局重载 ➔ 技能级个性化配置（`TenantSkillOverride`）。
- **核心业务配置项**：
  - 自动退款金额上限 (`maxAutoRefundAmount`)
  - 退款时效窗口 (`maxRefundDays`)
  - HITL 人工审核门禁策略 (`requireApprovalOnAddressChange`, `requireApprovalOnRefund`)
  - 启用的技能清单 (`enabledSkills`) 与技能自定义 SOP 参数

### 1.2 Monorepo 单一真实来源类型系统 (`packages/types`)

- **`skill.ts`**：技能元数据、阶段生命周期、SOP 策略及上下文类型契约。
- **`config.ts`**：多租户配置结构、租户实体模型及覆盖接口。
- **`agent.ts` / `cards.ts`**：智能体执行状态、规划任务项、多模态富交互卡片结构。
- **`approval.ts`**：HITL 审批单、发件箱事件、决策结果类型。
- **`tool.ts`**：工具定义规范、入参校验 Schema 与执行上下文。

---

## 2. 编码与维护准则

1. **强类型安全与单一来源**：跨应用/包交互的数据结构必须从 `packages/types` 统一导入，严禁在业务包内随意重复定义同名接口。
2. **零运行时外部包依赖**：`packages/types` 保持纯 TypeScript 类型定义，避免引入带副作用的运行时重型依赖。
3. **向后兼容性**：新增配置项与类型属性时，需保持可选（Optional）或提供合理默认值，确保系统升级平滑。
