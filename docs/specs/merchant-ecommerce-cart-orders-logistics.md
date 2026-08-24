# 规范：极光潮品商户端独立电商全功能体验（购物车、订单中心、地址簿、详情与物流追踪）

## Problem Statement

当前商户独立品牌站（`apps/merchant` - 极光潮品 Aurora Luxe Store）仅具备基础的 SPU/SKU 展示与单商品极简下单弹窗，缺少完整的现代电商消费闭环：

1. **购物车能力缺失**：用户无法将多款不同规格的商品（SKU）合并加购、按需选择并一并结算。
2. **订单管理体验割裂**：用户无法按状态（待付款、待发货、已发货、已完成、已退款）分类筛选历史订单，缺少可视化的订单详细快照与支付结算凭证。
3. **收货地址单一固定**：当前收货地址固定在输入框中，缺乏多地址管理、默认地址设定与下单时快速切换能力。
4. **物流轨迹不可视**：订单发货后无法直观查看承运商、快递单号与节点动态时间线（从揽收到签收）。
5. **客服协同链路不完整**：在订单与物流界面中无法一键唤起智能客服直达上下文，降低了售后改单和退换货的闭环体验。

## Solution

在 `apps/merchant` 中构建一套端到端完整的独立品牌电商体验系统：

1. **轻量级响应式购物车 (Shopping Cart Drawer)**：提供常驻悬浮购物车图标与角标计数，支持右侧滑出抽屉，具备多 SKU 勾选、数量增减、库存与价格校验、一键合并结算功能。
2. **模块化多地址管理簿 (Address Book Modal)**：支持顾客维护多条收货地址，标记默认地址，在购物车结算或订单下单时一键切换与新增。
3. **全生命周期订单中心 (Orders Management Center)**：提供多状态 Tab 过滤（全部、待付款、处理中、已发货、已完成/已退款）、订单号与商品搜索、直观状态 Badge 与快捷动作。
4. **富信息订单详情视图 (Order Details Drawer/Modal)**：提供商品快照清单、实付费用明细、收货人信息、变更审计记录与履约动作。
5. **沉浸式物流轨迹追踪器 (Logistics Timeline Tracker)**：以垂直时间轴呈现承运商信息、运单号复制、当前最新状态以及途经各转运节点的时空动态。
6. **无缝联动智能客服 (AI Customer Service Seamless Handoff)**：在订单列表与详情页中提供【咨询专属客服】入口，点击即刻打开 AI 客服弹窗并携带当前订单上下文，支持直接触发查单、改地址、极速退款等 AI 技能。

## User Stories

1. As a 消费者, I want to 在浏览商品 SPU 与选中具体 SKU 规格后点击【加入购物车】, so that 我可以将多个感兴趣的商品暂存起来集中购买。
2. As a 消费者, I want to 在页面任意位置看到悬浮的购物车图标与实时商品件数角标, so that 我能随时感知当前加购状态并快速打开购物车。
3. As a 消费者, I want to 在购物车抽屉中调整商品数量或删除不需要的商品, so that 我能灵活管理我的购买清单。
4. As a 消费者, I want to 在购物车中看到总金额实时计算并勾选部分或全部商品, so that 我可以按预算选择性合并结算。
5. As a 消费者, I want to 在结算前从我的地址簿中选择已有收货地址或快速新增地址, so that 订单能准确送达我的指定地点。
6. As a 消费者, I want to 将常用地址设为默认地址, so that 后续加购下单无需重复填写。
7. As a 消费者, I want to 一键提交购物车合并订单并生成独立订单编号, so that 多个商品可以合并在一笔支付与订单中履约。
8. As a 消费者, I want to 在订单中心通过顶部状态标签（全部、待付款、处理中、已发货、已完成/已退款）快速筛选我的订单, so that 我能一目了然跟踪不同生命周期的订单。
9. As a 消费者, I want to 在订单列表中查看每笔订单包含的商品图片、规格说明、实付金额与创建时间, so that 我能快速定位目标订单。
10. As a 消费者, I want to 点击【查看详情】打开订单详情弹窗, so that 我可以查看完整的商品明细快照、收货信息、运费和优惠抵扣。
11. As a 消费者, I want to 对已发货的订单点击【查看物流】打开物流轨迹抽屉, so that 我能实时查看快递承运商、运单号及全流程时间线。
12. As a 消费者, I want to 一键复制物流单号, so that 我可以在快递官网或第三方平台进一步查询。
13. As a 消费者, I want to 在订单详情或物流弹窗中点击【联系客服】直接唤起极光智能客服, so that 我无需手动复制订单号即可针对该订单咨询修改地址或退货。
14. As a 商户运营人员, I want to 在商户后台标记发货并填入承运商和快递单号时，前台订单即时同步更新为已发货且生成初始物流节点, so that 消费者端能即时获得最新履约状态。
15. As a 系统架构师, I want to 保证所有购物车结算、地址维护与订单操作均在商户物理独立数据库内完成, so that 维持严格的商户数据隔离与 SPI 开放一致性。

## Implementation Decisions

### 1. 架构与模块分层

- **前端交互层 (`apps/merchant/app`)**：
  - `page.tsx`：重构商城主界面，集成导航栏购物车入口、悬浮购物车气泡、地址切换器、状态筛选订单列表。
  - `components/cart/CartDrawer.tsx`：购物车滑出抽屉组件，支持规格变更、数量管理、批量勾选与结算。
  - `components/orders/OrdersListModal.tsx`：分类 Tab 订单浏览器，支持搜索、状态过滤与订单卡片。
  - `components/orders/OrderDetailModal.tsx`：订单详情抽屉，展示商品快照、价格明细、收件信息与操作审计。
  - `components/orders/LogisticsModal.tsx`：物流时间线弹窗，展示快递公司、运单号、当前状态与节点列表。
  - `components/address/AddressModal.tsx`：地址簿管理与新增/编辑弹窗。
- **Storefront API 路由层 (`apps/merchant/app/api/store`)**：
  - `GET /api/store/addresses` & `POST /api/store/addresses`：地址簿查询与新增/更新/设默认。
  - `GET /api/store/orders` & `POST /api/store/orders`：支持单品直购与购物车多 SKU 批量结算下单。
  - `GET /api/store/orders/[orderId]`：单笔订单全量详情与物流轨迹时间线检索。
- **商户领域服务层 (`apps/merchant/src/services/merchantDomainService.ts`)**：
  - 扩展 `createOrderFromCart`：批量扣减 SKU 库存、生成订单与明细行、关联收货地址。
  - 扩展 `updateCustomerAddresses`：安全维护 `merchant_customers.addresses` JSONB 数组。
  - 完善 `getOrderDetail`：聚合完整物流轨迹时间线节点与商户审计流水。

### 2. 状态机与数据结构契约

#### 购物车条目状态契约：

```typescript
export interface CartItem {
  id: string; // SKU 编码作为唯一 key
  spuId: string;
  skuCode: string;
  title: string;
  skuTitle: string;
  imageUrl: string;
  price: number;
  originalPrice?: number;
  quantity: number;
  stock: number;
  specAttributes: Record<string, string>;
  selected: boolean;
}
```

#### 地址簿实体契约：

```typescript
export interface CustomerAddress {
  id: string;
  recipientName: string;
  phone: string;
  province: string;
  city: string;
  district: string;
  detailAddress: string;
  fullAddress: string;
  isDefault?: boolean;
}
```

#### 物流动态时间线契约：

```typescript
export interface TrackingNode {
  time: string;
  status: string; // 如 "已揽收" | "运输中" | "派送中" | "已签收"
  location: string;
  description: string;
}
```

## Testing Decisions

- **自动化集成测试规范 (`apps/merchant/tests/merchantEcomFlow.test.ts`)**：
  1. **购物车多品类结算测试**：验证添加 2 个以上不同 SKU 到购物车，批量提交下单后库存正确扣减，生成正确的 `merchant_orders` 及多个 `merchant_order_items`。
  2. **地址簿 CRUD 与默认设值测试**：验证调用地址 API 新增多条地址，设置默认地址后，拉取用户信息时默认地址置顶生效。
  3. **订单分类与详情查询测试**：验证按 `PENDING` / `SHIPPED` 等状态过滤订单列表，以及根据 `orderId` 拉取详情时返回完整商品快照与费用计算。
  4. **物流轨迹生成与流转测试**：验证后台发货后，订单详情中的 `tracking_info.timeline` 节点完整返回且按时间正序排列。
- **Playwright E2E 规范 (`apps/merchant/e2e/merchantCommerce.e2e.ts`)**：
  - 验证从商城首页加购 ➔ 打开购物车抽屉 ➔ 切换地址 ➔ 点击结算 ➔ 跳转/弹出订单详情 ➔ 查看物流时间线 ➔ 点击【咨询客服】唤起 AI 对话的完整视觉交互链路。

## Out of Scope

1. 真实的微信支付 / 支付宝三方支付 SDK 物理拉起（采用模拟确认支付状态机）。
2. 真实第三方快递 API（如快递100/菜鸟网络）实时 HTTP Webhook 对接（采用商户发货时自动生成的真实结构模拟轨迹）。

## Further Notes

- 商户端与 Agent 平台核心服务（`apps/server` / `packages/engine`）保持解耦，所有交互通过标准的 SPI 与 Storefront API 协议通信。
- 界面风格统一继承 `@agent-all/ui` 的 Tailwind 设计语言与 Emerald 极简机能风主题。
