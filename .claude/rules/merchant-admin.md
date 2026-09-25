---
description: 商户独立后台(数据分析 Agent/RBAC/优惠/订单商品客户 CRUD):悬浮助手、page-context 选择上行、ResultCard 同形渲染与诚实降级
paths: ["apps/merchant-admin/**/*"]
---

# 商户独立后台规范 (Merchant Admin)

`apps/merchant-admin` 是 v4 新增的独立商户后台(Vite 6 + React 19,端口 3006,`bun run dev:merchant-admin`;`/api/*` 由 Vite proxy 代理至 gateway-py 4000,`GATEWAY_URL` env 可覆写)。员工/老板工作台:全局悬浮数据分析助手 + RBAC 动态菜单 + 优惠/订单/商品/客户 CRUD。组件强制 workspace 包 `ui` + Tailwind,界面中文。

## 1. 核心架构与页面

### 1.1 路由与动态菜单

- `App.tsx`:未登录整树渲染 `LoginPage`;登录后 `AdminShell`。路由表固定 14 条(`/analytics` `/board` `/reports` `/orders` `/live-desk` `/promotions` `/customers` `/menus` `/roles` `/staff` `/products` `/products/:code` `/skus` `/spi-logs`,`*` 兜底重定向 `/products`;orders/live-desk/spi-logs 三条共用 `OrderWorkbench` 按 scope 分域)。侧边栏导航**不写死** —— 由 `GET /api/admin/analytics/menus` 下发的 `MenuNode` 树(directory/menu/button + `permCode`)驱动,`route` 字段对齐上述路由表;新增页面须同批补服务端种子菜单(`engine_py/analytics/rbac.py`),否则导航不可见。
- **身份 = Bearer JWT**(0013 收口,后端不再信任 `x-user-id` 头);401 统一清会话回登录页(`api.ts` 的 `req`/`fetchJson` 两个收口)。**400 级业务错误走 `fetchJson` 返回 body**,由页面按 `success`/`message` 呈现文案,不吞进 throw。
- 老板身份切换:顶栏 select 仅 `hasBossSession()` 可见;`api.staffSwitch` 以留底的老板凭证(localStorage `merchant-admin.boss`,首次切换时保存)调 `POST /api/admin/analytics/staff/switch`,服务端为目标员工换签 JWT。`x-tenant-id` 硬编码 `'aurora'`(单租户 dev)。

### 1.2 悬浮数据分析助手 (FloatingAgent)

- 任意路由可唤起(挂 `AdminShell` 主区右下角);上下文 = 当前路由 + 列表页勾选。提问经 `POST /api/admin/analytics/ask`:fetch 流式读取 + `createFrameParser` 增量解析 SSE 帧逐帧回调。帧带自增 `id`,渲染层按 id 回写状态(按下标会错位);`start` 帧过滤不渲染。
- `pageContext = {route, selection, selectionLabels, sessionId}`;`sessionId` 浏览器侧稳定(localStorage `merchant-admin.session`),服务端 Redis 会话存储按此键维护多轮上下文。
- localStorage 键位约定:`merchant-admin.token`(JWT)/ `.staff`(当前员工 email)/ `.boss`(老板凭证留底)/ `.agent.history`(对话帧,上限 60)/ `.board`(钉看板 pin,上限 20)/ `.session`(agent 会话 id)。
- 事件面板:`user`/`pending`/`result`/`clarify`/`unsupported`/`error`;result 帧 = `ResultCard` + `summary` 速览 + 导出 CSV(BOM 头防 Excel 中文乱码)+ 📌 钉看板 + 存为报告(`reports/from-result` 服务端持久化,`saved` 标记防重复)。
- 就地唤起:任意页面 `window.dispatchEvent(new CustomEvent('merchant-admin:open-agent', {detail: {question}}))` 开面板并自动提问,不跳页。

### 1.3 page-context 选择上行(T5 契约)

- `lib/page-context.ts` 内存广播:`getSelection`/`setSelectionKind`/`toggleKindId`/`clearSelection`/`subscribe`。`kind ∈ 'order' | 'spu' | 'customer'`,ids 去重截断 ≤100;labels 并行存 `{kind: {id: 人话标签}}` 供图表标题等人话呈现。
- **严禁入 localStorage**:残留勾选曾两次静默污染查询(实弹踩坑),选择是一次性会话上下文,随页面会话生灭;旧键 `merchant-admin.selection` 在模块加载时一次性清除(迁移 2026-09-22)。
- FloatingAgent 订阅广播即时显示「已勾选 N 项」横幅,点击横幅即清除。

### 1.4 结果卡 ResultCard(同形渲染 + 诚实降级)

- 唯一结果渲染缝:悬浮面板 / analytics 全屏问答 / 看板重放 / 报告详情共用同一 `ResultCard` —— 改渲染行为只改这一处,四处自动一致。
- 图形纪律(**诚实降级,绝不画假图**):
  - 折线:值列(行内第 2 列)必须全员 `Number.isFinite` 才画;数据点 <2 或值列非数值(如对比卡第 2 列是「品类」文案)出诚实说明卡 + 表格。实弹:历史持久化帧重放曾把 `Number('潮流T恤')` 画成三条 NaN 网线(2026-09-25 修复)。
  - 条形:`rankingPoints` 需 ≥2 行且末列数值,取前 10;`NO_BAR_METRICS`(`order_overview`/`customer_orders` 逐笔列表)永不画条;`chart='bar'` 用户指令但形状不符 → 诚实说明卡 + 表格。
  - `chart='table'` 尊重用户指令,不画图。
- 「折线仅趋势族」是**服务端**约定(`engine_py/analytics/graph.py` `_effective_chart`);前端数值护栏是历史帧重放/服务端回归时的最后防线,两层都不可拆。

### 1.5 看板页 (board)

- 钉看板 pin 存 localStorage(`.board` 上限 20):`{id, question, route, pinnedAt}`;每 60s(`REFRESH_MS`)对 pin 的问题重放 `api.ask` 刷新。重放走完整 ask 管线,`ResultCard` 渲染与悬浮面板同形。

---

## 2. 编码与维护准则

1. **数据操作收口 `lib/api.ts`**:页面只做编排,一切后端调用经 `api` 域对象(`menus`/`roles`/`staff`/`menuAdmin`/`customers`/`reports`/`products`/`promotions`/`ask`);新增后端接口同批在此加方法与 TS 类型,严禁页面裸 fetch。
2. **SSE 帧解析只经 `lib/sse.ts`**(`parseSseFrames` 全量 / `createFrameParser` 增量),与网关 `_sse()` 帧格式一一对应;坏 JSON 跳帧不中断流。
3. **RBAC 前端只做可见性**:菜单树由服务端下发,权限判定真源在服务端 `permCode`;严禁在前端复制权限表。
4. **测试**:`cd apps/merchant-admin && bun run test`(vitest,92 例/22 文件,与被测文件同目录就近放置;`src/test/live-api.ts` 可起 live 网关做集成);Playwright E2E `e2e/merchant-admin.config.ts`(testDir `apps/merchant-admin/e2e`,复用运行中的 3006 前端 + 4000 网关;dev 种子账号 `test@example.com` 老板 / `ops@aurora` 运营 / `wh@aurora` 仓储,密码统一 `agent-all-dev`)。
5. **中文界面 + workspace 包 `ui` 原子组件 + Tailwind**:与 web/admin 同一零依赖 UI 不变量,严禁引入重型外部组件框架。
