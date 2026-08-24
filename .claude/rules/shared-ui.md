---
description: 零外部依赖共享原子 UI 组件库、交互式富卡片族谱与 SVG 图标体系规范
paths: ["packages/ui/**/*"]
---

# 共享 UI 与富交互卡片规范 (Shared UI & Cards)

本工作区是整个 Monorepo 的共享 UI 资产库，为客户端对话应用 (`apps/web`) 和管理后台 (`apps/admin`) 提供一致、高质感、零外部依赖的基础组件与多模态富交互卡片。

## 1. 核心设计哲学与规范

### 1.1 零外部依赖原子设计 (Zero External Dependency)

- **无三方重量级 UI 库绑定**：所有组件（Button, Badge, Input, Modal, Drawer, Table, Tabs 等）均基于原生 React + Tailwind CSS 纯手工打造，杜绝臃肿的外部库依赖。
- **高可定制与模块化**：严格遵循 props 驱动与受控/非受控模式标准，提供精准的 TypeScript 类型定义。

### 1.2 多模态富交互卡片族谱 (Interactive Card Family)

- **标准卡片结构**：
  1. `CardHeader`：包含操作类型标题、图标与状态徽章（`status: 'pending' | 'success' | 'warning' | 'error'`）。
  2. `CardBody`：关键核心信息网格（如订单号、金额、收货人、创建时间）。
  3. `CardActions`：操作区（主按钮、次按钮、取消或回退触发器）。
- **主要卡片类型**：
  - `OrderSummaryCard`：订单详情与履约状态卡片。
  - `RefundProgressCard`：退款进度追踪与风控审核卡片。
  - `AddressConfirmationCard`：新旧收货地址核对与授权卡片。
  - `ActionApprovalCard`：HITL 人工审核卡片（支持单步决策与批量放行）。

### 1.3 SVG 图标系统与无障碍支持

- **自研轻量 SVG 图标**：内置统一尺寸（16x16, 20x20, 24x24）与线宽风格的 SVG 图标组件，严禁随机引入不同设计风格的外链图标。
- **A11y 基础无障碍**：关键按钮与交互元素需提供 `aria-label` 与合规的键盘可聚焦（Focus Ring）样式。

---

## 2. 编码与维护准则

1. **绝对隔离业务数据**：`packages/ui` 严禁直接导入业务数据库实例、API 请求逻辑或服务端环境变量。
2. **样式一致性**：遵循系统定义的调色板（Primary Indigo/Blue, Success Emerald, Warning Amber, Danger Rose）。
