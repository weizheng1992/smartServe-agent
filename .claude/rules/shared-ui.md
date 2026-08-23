---
description: 共享 UI 组件库、富交互卡片家族、HITL 审批组件与 SVG 图标库开发规范
paths: ["packages/ui/**/*"]
---

# 共享 UI 组件库规范 (Shared UI)

本工作区负责提供零外部重度依赖、跨应用（`apps/web` 与 `apps/admin`）复用的纯声明式展示组件、富交互卡片体系与 SVG 图标库。

## 1. 核心架构与组件划分

### 1.1 富交互卡片家族 (`src/components/chat/`)

- **`RichCardRenderer`**：卡片统一渲染入口，根据卡片类型（`cardType`）自适应分发。
- **`OrderCard`**：订单编号、总金额、状态标签与操作按钮。
- **`TrackingTimeline`**：快递物流多节点时间轴、派送员信息与当前状态。
- **`RefundConfirmationCard`**：退款审核状态、赔付金额与凭证展示。
- **`DamageAssessmentCard`**：AI 视觉多模态成色定责评级（瑕疵等级、定责结论与图片标注展示）。
- **`ProductCard` / `SkuSelector`**：商品缩略图、规格选择与加购/咨询操作。
- **`QuickReplies`**：操作胶囊与意图快速确认选项。

### 1.2 HITL 审批与上下文抽屉组件 (`src/components/approval/`)

- **`PendingApprovalCard`**：支持差异化渲染退款、地址变更与敏感操作审核卡片。
- **`ApprovalContextDrawer`**：多 Tab 抽屉式检查器，承载对话回放、用户画像与历史订单轨迹。

### 1.3 基础设计系统与图标库

- **`src/components/icons.tsx`**：轻量级内联 SVG 图标，支持 `className`、`size` 与颜色继承。
- **`src/components/ui/`**：通用的 Modal 弹窗、Drawer 抽屉、Badge 徽章、Button 按钮与 Tabs 切换组件。

---

## 2. 编码与设计准则

1. **绝对解耦**：
   - 严禁在 `@agent-all/ui` 中直接引入数据库驱动（如 `drizzle-orm`、`pg`）或 Node.js 后端专属模块。
   - 所有数据通信均通过 TypeScript 明确声明的 `interface` 或 `type` 入参注入。
2. **多端自适应与优雅降级**：
   - 组件必须使用 Tailwind CSS v4 编写，天然支持移动端与桌面端自适应。
   - 当可选字段（如图片 URL、物流派送员电话、省市区明细）缺失时，必须具备优雅的回退展示，杜绝白屏或布局崩塌。
3. **公共导出规范**：
   - 所有对外可见的组件、Hook 和工具函数必须在 `packages/ui/src/index.ts` 集中统一导出。
