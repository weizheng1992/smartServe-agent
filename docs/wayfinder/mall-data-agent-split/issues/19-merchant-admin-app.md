# 19: merchant-admin 独立后台应用

Type: grilling
Status: resolved

## Question

要不要把 apps/merchant 的 /admin（MerchantAdminPage 六 tab）拆成独立后台应用 apps/merchant-admin？若拆：菜单信息架构规范化、agent 是否能根据菜单/页面选中数据进行分析、技术栈与组件库约束（必须用 packages/ui）。

## Answer

决议日期 2026-09-17，用户认可拆分并追加约束。

### D1 拆分决议

- 新建 `apps/merchant-admin`（Turborepo 应用），现有六 tab（orders / approvals / live_desk / spus / skus / spi_logs）**平移不重写**；storefront 删除 `/admin` 路由；新应用代理到同一 gateway；data agent 的 analytics 模块直接落新家。
- 与图谱期「先逻辑后物理」不冲突：该决议管后端服务部署拓扑；monorepo 内拆前端应用同仓同 CI，且有真实触发因素（重资产隔离 / 鉴权域对齐 / 发布节奏）。

### D2 技术栈与组件库约束（用户强制）

- 与 apps/merchant 同栈：Bun + Vite 6 + React 19 + TypeScript；路由、SSE 事件流约定跟随现有 apps。
- **组件库强制 `packages/ui`**：新应用不得本地新造重复组件、不引入第二套组件库；packages/ui 覆盖不了的组件先进 packages/ui 再用（图表除外）。
- 图表 = ECharts（echarts-for-react，10-D2 决议）；样式沿用仓库 Tailwind v4 + shadcn 约定。

### D3 页面上下文驱动分析（用户点名能力，采纳进 v1 架构）

- **PageContext 契约**：前端随每条分析消息上行 `{ route/tab, selection: 实体 id 列表, activeFilters }`；用户在订单页选中 3 笔退款单问「这些单的平均金额」，agent 拿到的是结构化上下文而非截图。
- **落点**：PageContext 是 `MetricQueryEngine.resolve(question, session_ctx)` 中 session_ctx 的一部分（09-D5 接口不变，扩上下文）；选中实体作为查询意图的**实体过滤参数**——模板侧以闭集 fragment + IN 绑定参数列表承接（值仍不进 SQL 文本，business_id 服务端重校验，id 列表长度设上限）。
- **边界**：v1 限定单一上下文源（当前页面）；自由计算（任意 Python 式整理）不进 v1，归二期沙箱演化缝（15 号票定边界）。

### D4 菜单信息架构规范化

- 方向：分组一级导航——**数据**（数据分析）/ **运营**（订单履约、售后审批）/ **客服**（工作台）/ **配置**（商品、接口日志、设置）；设置内预留角色权限入口（13 号票落点）。
- 定稿交 16 号产品原型（该票已扩题），死按钮禁令适用于菜单每一项。

### D5 对既有决议的影响

- 16 号原型以新应用为宿主并扩题（菜单 IA + PageContext 交互原型）；12 号 spec 第①部分新增前端边界章节；其余决议（08/09/10）不受影响。

## Comments

- 2026-09-18 用户重画修订：**D4 菜单 IA 作废重定**——按模块分：商品、分类、订单、用户、权限管理、运营管理（优惠活动）+ 数据分析/我的报告，每模块自带子菜单与路由（定稿仍经 16 号原型）。**新增全局悬浮 agent 入口**：后台任意路由右下角悬浮（参照 storefront FloatingChatWidget 模式），上下文=当前路由+选中数据（PageContext 契约不变），数据分析页保留为全屏对话形态。D1/D2/D3 不受影响。
